"""Smart Capture 도구줄: 자동 촬영 모드 · 포커스 피킹 · ROI 지정 · Best Shot + 실시간 영상 품질 표시."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT

_MODES = [("off", "끄기", "자동 촬영 끄기"),
          ("freeze", "자동 정지", "초점이 가장 잘 맞는 순간 화면을 자동으로 정지 — 확인 후 '사진 캡처'로 저장"),
          ("snapshot", "자동 저장", "초점이 맞으면 가장 선명한 프레임을 자동 저장 (쿨다운으로 연속 저장 방지)")]
_MODE_TEXT = {code: text for code, text, _ in _MODES}

# 품질 점수 색 (좋음 / 보통 / 나쁨)
_GOOD, _FAIR, _POOR = "#3ccf7a", "#f5b94a", "#f0524f"


def score_color(v: float) -> str:
    return _GOOD if v >= 80 else _FAIR if v >= 50 else _POOR


class SmartBar(QFrame):
    modeChanged = Signal(str)
    peakingToggled = Signal(bool)
    sensitivityChanged = Signal(int)
    roiSelectToggled = Signal(bool)
    bestShotToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Dock")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 12, 6)
        lay.setSpacing(6)

        title = QLabel()
        title.setPixmap(icons.pixmap("aperture", ICON_ACCENT, 18))
        title.setToolTip("Smart Capture")
        lay.addWidget(title)
        name = QLabel("Smart")
        name.setObjectName("SmartTitle")
        lay.addWidget(name)

        seg = QFrame()
        seg.setObjectName("EyeSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for code, text, tip in _MODES:
            b = QPushButton(text)
            b.setObjectName("SmartBtn")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.mode_group.addButton(b)
            self.mode_buttons[code] = b
            sl.addWidget(b)
            b.clicked.connect(lambda _=False, c=code: self._on_mode(c))
        self.mode_buttons["off"].setChecked(True)
        lay.addWidget(seg)
        lay.addWidget(self._sep())

        self.btn_peaking = self._toggle("피킹", "lens", "포커스 피킹: 초점이 맞은 경계를 색으로 표시")
        self.sens = QSlider(Qt.Orientation.Horizontal)
        self.sens.setRange(0, 100)
        self.sens.setValue(50)
        self.sens.setFixedWidth(84)
        self.sens.setToolTip("피킹 감도")
        self.sens.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_roi = self._toggle("ROI", "crop", "초점을 볼 영역(각막·홍채·수정체 등)을 영상 위에서 끌어 지정 "
                                                   "· 영상을 두 번 클릭하면 중앙으로 초기화")
        self.chk_best = QCheckBox("Best Shot")
        self.chk_best.setToolTip("사진 캡처 시 최근 0.6초 중 가장 선명한 프레임을 저장")
        self.chk_best.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.btn_peaking)
        lay.addWidget(self.sens)
        lay.addWidget(self._sep())
        lay.addWidget(self.btn_roi)
        lay.addWidget(self.chk_best)
        lay.addStretch(1)

        self.meters: dict[str, QLabel] = {}
        for key, text in (("focus", "초점"), ("exposure", "노출"), ("stability", "안정"), ("reflection", "반사")):
            lb = QLabel(f"{text} --")
            lb.setObjectName("SmartMeter")
            lb.setProperty("label", text)
            self.meters[key] = lb
            lay.addWidget(lb)
        self.hint = QLabel("")
        self.hint.setObjectName("SmartHint")
        self.hint.setMinimumWidth(150)
        lay.addWidget(self.hint)

        self.btn_peaking.toggled.connect(self._on_peaking)
        self.sens.valueChanged.connect(self.sensitivityChanged.emit)
        self.btn_roi.toggled.connect(self.roiSelectToggled.emit)
        self.chk_best.toggled.connect(self.bestShotToggled.emit)
        self._on_peaking(False)

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("DockSep")
        f.setFixedSize(1, 24)
        return f

    @staticmethod
    def _toggle(text: str, icon_name: str, tip: str) -> QPushButton:
        b = QPushButton(icons.gap(text))
        b.setObjectName("Pause")              # 체크 시 강조되는 도크 버튼 스타일 재사용
        b.setCheckable(True)
        ic = icons.icon(icon_name, ICON, 16)
        ic.addPixmap(icons.pixmap(icon_name, ICON_ACCENT, 16), ic.Mode.Normal, ic.State.On)
        b.setIcon(ic)
        b.setIconSize(QSize(15, 15))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    # ---- 상태 ----
    def _on_mode(self, code: str) -> None:
        self.mode_buttons[code].setChecked(True)
        self.modeChanged.emit(code)

    def _on_peaking(self, on: bool) -> None:
        self.sens.setEnabled(on)
        self.peakingToggled.emit(on)

    def mode(self) -> str:
        return next((c for c, b in self.mode_buttons.items() if b.isChecked()), "off")

    def set_mode(self, code: str, emit: bool = True) -> None:
        if code not in self.mode_buttons:
            code = "off"
        if emit:
            self._on_mode(code)
        else:
            self.mode_buttons[code].setChecked(True)

    def cycle_mode(self) -> str:
        order = [c for c, _, _ in _MODES]
        nxt = order[(order.index(self.mode()) + 1) % len(order)]
        self._on_mode(nxt)
        return nxt

    def set_state(self, mode: str, peaking: bool, sensitivity: int, best_shot: bool) -> None:
        """설정값으로 초기화 (신호 없이)."""
        for w in (self.btn_peaking, self.sens, self.chk_best):
            w.blockSignals(True)
        self.set_mode(mode, emit=False)
        self.btn_peaking.setChecked(peaking)
        self.sens.setValue(max(0, min(100, int(sensitivity))))
        self.sens.setEnabled(peaking)
        self.chk_best.setChecked(best_shot)
        for w in (self.btn_peaking, self.sens, self.chk_best):
            w.blockSignals(False)

    def set_roi_selecting(self, on: bool) -> None:
        self.btn_roi.blockSignals(True)
        self.btn_roi.setChecked(on)
        self.btn_roi.blockSignals(False)

    def set_quality(self, q) -> None:
        """FrameQuality → 점수 표시. None 이면 비운다."""
        if q is None:
            for lb in self.meters.values():
                lb.setText(f"{lb.property('label')} --")
                lb.setStyleSheet("")
            self.hint.setText("")
            return
        for key, lb in self.meters.items():
            v = float(getattr(q, "focus_pct" if key == "focus" else key))
            lb.setText(f"{lb.property('label')} {v:3.0f}")
            lb.setStyleSheet(f"color:{score_color(v)};")
        self.hint.setText(q.hint)
        self.hint.setStyleSheet(f"color:{_GOOD};" if q.in_focus else "")


def mode_text(code: str) -> str:
    return _MODE_TEXT.get(code, code)
