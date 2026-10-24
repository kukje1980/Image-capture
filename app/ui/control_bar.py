"""하단 촬영 도크: OD/OS/OU 안구 스위치 + 4분할/일시정지 + 정지영상·셔터(사진 캡처)·녹화 + 상태."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT, ICON_RECORD

_EYE_CODES = ["NA", "OD", "OS", "OU"]
_EYE_BUTTONS = [("OD", "OD", "우안"), ("OS", "OS", "좌안"), ("OU", "OU", "양안"), ("NA", "—", "미지정")]


class ControlBar(QFrame):
    pauseToggled = Signal(bool)
    captureClicked = Signal()
    recordToggled = Signal(bool)
    freezeClicked = Signal()
    quadToggled = Signal(bool)
    saveQuadClicked = Signal()
    clearQuadClicked = Signal()
    eyeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Dock")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(6)

        # 안구 선택: 세그먼트 버튼 (eye_combo 는 기존 API 호환용으로 숨겨 둔다)
        self.eye_combo = QComboBox()
        self.eye_combo.addItems(["미지정", "OD(우안)", "OS(좌안)", "OU(양안)"])
        self.eye_combo.setVisible(False)
        seg = QFrame()
        seg.setObjectName("EyeSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.eye_group = QButtonGroup(self)
        self.eye_buttons = {}
        for code, text, ko in _EYE_BUTTONS:
            b = QPushButton(text)
            b.setObjectName("EyeBtn")
            b.setProperty("eye", code)
            b.setCheckable(True)
            b.setToolTip(ko)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.eye_group.addButton(b)
            self.eye_buttons[code] = b
            sl.addWidget(b)
            b.clicked.connect(lambda _=False, c=code: self.set_eye(c))
        self.eye_buttons["NA"].setChecked(True)
        lay.addWidget(seg)
        lay.addWidget(self._sep())

        self.btn_quad = self._button("4분할", "quad", "Pause", checkable=True,
                                     tip="한 화면 4분할 정지영상")
        self.btn_pause = self._button("일시정지", "pause", "Pause", checkable=True, tip="일시정지")
        self.btn_freeze = self._button("정지영상", "freeze", "Freeze", color=ICON_ACCENT,
                                       tip="현재 프레임 정지 (4분할에서는 칸 채우기)")
        self.btn_capture = self._button("사진 캡처", "camera", "Shutter", color=ICON_ON_ACCENT, tip="사진 캡처")
        self.btn_capture.setIconSize(QSize(20, 20))
        self.btn_capture.setMinimumWidth(132)
        self.btn_record = self._button("녹화 시작", "rec", "Record", checkable=True, color=ICON_RECORD,
                                       tip="녹화 시작/중지")
        self.btn_save_quad = self._button("4분할 저장", "save", "Primary", color=ICON_ON_ACCENT)
        self.btn_clear_quad = self._button("비우기", "eraser", "ToolBtn")

        lay.addWidget(self.btn_quad)
        lay.addWidget(self.btn_pause)
        lay.addSpacing(8)
        lay.addWidget(self.btn_freeze)
        lay.addWidget(self.btn_capture)
        lay.addWidget(self.btn_record)
        lay.addWidget(self.btn_save_quad)
        lay.addWidget(self.btn_clear_quad)
        lay.addStretch(1)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setStyleSheet("background:#3ccf7a;border-radius:4px;")
        self.status = QLabel("준비")
        self.status.setObjectName("StatusLabel")
        lay.addWidget(self.status_dot)
        lay.addWidget(self.status)

        self.btn_quad.toggled.connect(self._on_quad)
        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_freeze.clicked.connect(self.freezeClicked.emit)
        self.btn_capture.clicked.connect(self.captureClicked.emit)
        self.btn_record.toggled.connect(self._on_record)
        self.btn_save_quad.clicked.connect(self.saveQuadClicked.emit)
        self.btn_clear_quad.clicked.connect(self.clearQuadClicked.emit)
        self.eye_combo.currentIndexChanged.connect(self._sync_eye_buttons)

        self.set_capture_enabled(False)
        self.set_quad_mode(False)

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("DockSep")
        f.setFixedSize(1, 28)
        return f

    @staticmethod
    def _button(text, icon_name, obj, checkable=False, color=ICON, tip="") -> QPushButton:
        b = QPushButton(icons.gap(text))
        b.setObjectName(obj)
        b.setCheckable(checkable)
        b.setIcon(icons.icon(icon_name, color, 18))
        b.setIconSize(QSize(16, 16))
        b.setMinimumHeight(40)
        if tip:
            b.setToolTip(tip)
        return b

    def _on_quad(self, checked: bool) -> None:
        self.set_quad_mode(checked)
        self.quadToggled.emit(checked)

    def _on_pause(self, checked: bool) -> None:
        self.btn_pause.setText(icons.gap("재개" if checked else "일시정지"))
        self.btn_pause.setIcon(icons.icon("play" if checked else "pause", ICON_ACCENT if checked else ICON, 18))
        self.pauseToggled.emit(checked)

    def _on_record(self, checked: bool) -> None:
        self.btn_record.setText(icons.gap("녹화 중지" if checked else "녹화 시작"))
        self.btn_record.setIcon(icons.icon("rec", "#ffffff" if checked else ICON_RECORD, 18))
        self.recordToggled.emit(checked)

    def set_freeze_state(self, frozen: bool) -> None:
        """단일 모드 정지영상 상태에 맞춰 버튼 표시 (정지영상 ↔ 라이브)."""
        self.btn_freeze.setText(icons.gap("라이브" if frozen else "정지영상"))
        self.btn_freeze.setIcon(icons.icon("play" if frozen else "freeze", ICON_ACCENT, 18))

    def current_eye(self) -> str:
        return _EYE_CODES[self.eye_combo.currentIndex()]

    def set_eye(self, code: str) -> None:
        if code in _EYE_CODES:
            self.eye_combo.setCurrentIndex(_EYE_CODES.index(code))
            self._sync_eye_buttons()

    def _sync_eye_buttons(self, *_):
        code = self.current_eye()
        self.eye_buttons[code].setChecked(True)
        self.eyeChanged.emit(code)

    def set_capture_enabled(self, on: bool) -> None:
        self.btn_capture.setEnabled(on)
        self.btn_record.setEnabled(on)
        self.btn_freeze.setEnabled(on)
        self.btn_save_quad.setEnabled(on)

    def set_quad_mode(self, on: bool) -> None:
        # 4분할 모드에서만 보이는 버튼 / 단일 모드에서만 의미있는 버튼 토글
        self.btn_save_quad.setVisible(on)
        self.btn_clear_quad.setVisible(on)
        self.btn_pause.setVisible(not on)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        bad = text.startswith("오류")
        rec = text.startswith("녹화 중")
        self.status_dot.setStyleSheet(
            f"background:{'#f0524f' if (bad or rec) else '#3ccf7a'};border-radius:4px;")

    def reset_record_button(self) -> None:
        self.btn_record.blockSignals(True)
        self.btn_record.setChecked(False)
        self.btn_record.setText(icons.gap("녹화 시작"))
        self.btn_record.setIcon(icons.icon("rec", ICON_RECORD, 18))
        self.btn_record.blockSignals(False)
