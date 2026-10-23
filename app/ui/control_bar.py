"""하단 컨트롤 바: 안구 선택 + 4분할/정지영상/일시정지/캡처/녹화 + 상태."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

_EYE_CODES = ["NA", "OD", "OS", "OU"]


class ControlBar(QWidget):
    pauseToggled = Signal(bool)
    captureClicked = Signal()
    recordToggled = Signal(bool)
    freezeClicked = Signal()
    quadToggled = Signal(bool)
    saveQuadClicked = Signal()
    clearQuadClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(8)

        eye_label = QLabel("안구:")
        eye_label.setObjectName("Muted")
        lay.addWidget(eye_label)
        self.eye_combo = QComboBox()
        self.eye_combo.addItems(["미지정", "OD(우안)", "OS(좌안)", "OU(양안)"])
        self.eye_combo.setMinimumWidth(110)
        lay.addWidget(self.eye_combo)

        self.btn_quad = QPushButton("⊞  4분할")
        self.btn_quad.setObjectName("Pause")
        self.btn_quad.setCheckable(True)
        self.btn_pause = QPushButton("⏸  일시정지")
        self.btn_pause.setObjectName("Pause")
        self.btn_pause.setCheckable(True)
        self.btn_freeze = QPushButton("❄  정지영상")
        self.btn_freeze.setObjectName("Freeze")
        self.btn_capture = QPushButton("📷  사진 캡처")
        self.btn_capture.setObjectName("Primary")
        self.btn_capture.setMinimumWidth(120)
        self.btn_record = QPushButton("●  녹화 시작")
        self.btn_record.setObjectName("Record")
        self.btn_record.setCheckable(True)
        self.btn_save_quad = QPushButton("💾  4분할 저장")
        self.btn_save_quad.setObjectName("Primary")
        self.btn_clear_quad = QPushButton("비우기")
        for b in (self.btn_quad, self.btn_pause, self.btn_freeze, self.btn_capture,
                  self.btn_record, self.btn_save_quad, self.btn_clear_quad):
            b.setMinimumHeight(38)

        lay.addWidget(self.btn_quad)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_freeze)
        lay.addWidget(self.btn_capture)
        lay.addWidget(self.btn_record)
        lay.addWidget(self.btn_save_quad)
        lay.addWidget(self.btn_clear_quad)
        lay.addStretch(1)
        self.status = QLabel("준비")
        self.status.setObjectName("StatusLabel")
        lay.addWidget(self.status)

        self.btn_quad.toggled.connect(self._on_quad)
        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_freeze.clicked.connect(self.freezeClicked.emit)
        self.btn_capture.clicked.connect(self.captureClicked.emit)
        self.btn_record.toggled.connect(self._on_record)
        self.btn_save_quad.clicked.connect(self.saveQuadClicked.emit)
        self.btn_clear_quad.clicked.connect(self.clearQuadClicked.emit)

        self.set_capture_enabled(False)
        self.set_quad_mode(False)

    def _on_quad(self, checked: bool) -> None:
        self.set_quad_mode(checked)
        self.quadToggled.emit(checked)

    def _on_pause(self, checked: bool) -> None:
        self.btn_pause.setText("▶  재개" if checked else "⏸  일시정지")
        self.pauseToggled.emit(checked)

    def _on_record(self, checked: bool) -> None:
        self.btn_record.setText("■  녹화 중지" if checked else "●  녹화 시작")
        self.recordToggled.emit(checked)

    def current_eye(self) -> str:
        return _EYE_CODES[self.eye_combo.currentIndex()]

    def set_eye(self, code: str) -> None:
        if code in _EYE_CODES:
            self.eye_combo.setCurrentIndex(_EYE_CODES.index(code))

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

    def reset_record_button(self) -> None:
        self.btn_record.blockSignals(True)
        self.btn_record.setChecked(False)
        self.btn_record.setText("●  녹화 시작")
        self.btn_record.blockSignals(False)
