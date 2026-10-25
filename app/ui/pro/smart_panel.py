"""Pro 사이드 패널 — '스마트 캡처' 탭과 '분석' 탭 (위젯만; 동작은 ProWorkspace 가 연결).

스마트 캡처  자동 촬영 모드 · 관심 영역 · Best Shot · 포커스 피킹 · 실시간 화질 점검(초점/노출/안정/반사)
분석         조명 모드 태그 · 형광 염색 면적 · 충혈 지수 · 경과 비교(고스트 겹치기 · 정렬 · 깜빡임 전환)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.capture.smart_capture import AUTO_MODES

PEAKING_COLORS = {"red": ("빨강", (255, 59, 48)), "green": ("초록", (52, 211, 153)), "cyan": ("시안", (34, 211, 238))}
_QUALITY_ROWS = [("focus", "초점"), ("exposure", "노출"), ("stability", "안정"), ("reflection", "반사")]


def _sub(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("PanelHeader")
    return lbl


def _muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


class SmartTab(QWidget):
    settingsChanged = Signal()
    bestShotClicked = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setObjectName("ProTabPage")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(6)

        lay.addWidget(_sub("자동 촬영"))
        form = QFormLayout()
        form.setSpacing(5)
        self.c_auto = QComboBox()
        self.c_auto.addItems(["끄기", "Smart Freeze (자동 정지)", "Auto Save (자동 저장)"])
        self.c_auto.setToolTip("초점이 흐렸다가 최고점 근처에서 안정되면 자동으로 정지(또는 저장)합니다.\n"
                               "깜빡임·반사광 과다·흔들림 중에는 찍지 않습니다.")
        self.c_auto.setCurrentIndex(max(0, AUTO_MODES.index(config.smart_auto_mode))
                                    if config.smart_auto_mode in AUTO_MODES else 0)
        form.addRow("모드", self.c_auto)
        roi_row = QHBoxLayout()
        self.s_roi = QSlider(Qt.Orientation.Horizontal)
        self.s_roi.setRange(20, 100)
        self.s_roi.setValue(int(round((config.smart_roi_frac or 0.5) * 100)))
        self.s_roi.setToolTip("초점을 판정할 화면 중앙 영역 크기 (점선 테두리)")
        self.lbl_roi = _muted()
        self.lbl_roi.setFixedWidth(34)
        roi_row.addWidget(self.s_roi, 1)
        roi_row.addWidget(self.lbl_roi)
        form.addRow("관심 영역", roi_row)
        lay.addLayout(form)
        self.chk_best = QCheckBox("Best Shot (최근 1초 중 가장 선명한 프레임)")
        self.chk_best.setChecked(bool(config.smart_best_shot))
        self.chk_best.setToolTip("누르는 순간의 흔들림·셔터 지연을 피합니다 (풋스위치에도 적용)")
        lay.addWidget(self.chk_best)
        self.b_best = QPushButton("지금 Best Shot 정지")
        self.b_best.setObjectName("ProBtn")
        self.b_best.setToolTip("최근 1초 중 가장 선명한 프레임으로 정지")
        lay.addWidget(self.b_best)

        lay.addWidget(_sub("포커스 피킹"))
        form2 = QFormLayout()
        form2.setSpacing(5)
        self.chk_peak = QCheckBox("초점이 맞은 경계를 색으로 표시")
        self.chk_peak.setChecked(bool(config.smart_peaking))
        form2.addRow("", self.chk_peak)
        self.c_sens = QComboBox()
        self.c_sens.addItems(["적게", "보통", "많이"])
        self.c_sens.setCurrentIndex(min(2, max(0, int(config.smart_peaking_sensitivity) - 1)))
        form2.addRow("민감도", self.c_sens)
        self.c_color = QComboBox()
        for key, (name, _rgb) in PEAKING_COLORS.items():
            self.c_color.addItem(name, key)
        idx = self.c_color.findData(config.smart_peaking_color)
        self.c_color.setCurrentIndex(idx if idx >= 0 else 0)
        form2.addRow("색상", self.c_color)
        lay.addLayout(form2)

        lay.addWidget(_sub("실시간 화질 점검"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.bars = {}
        for i, (key, name) in enumerate(_QUALITY_ROWS):
            grid.addWidget(_muted(name), i, 0)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setFormat("%v")
            bar.setFixedHeight(16)
            grid.addWidget(bar, i, 1)
            self.bars[key] = bar
        lay.addLayout(grid)
        self.lbl_advice = _muted("LIVE 화면에서 영상이 들어오면 점검을 시작합니다.")
        lay.addWidget(self.lbl_advice)
        self.lbl_log = _muted("")
        lay.addWidget(self.lbl_log)
        note = _muted("점수는 같은 조명·배율 안에서 비교하는 상대값이며 진단 정보가 아닙니다.")
        lay.addWidget(note)
        lay.addStretch(1)

        self.s_roi.valueChanged.connect(lambda v: self.lbl_roi.setText(f"{v}%"))
        self.lbl_roi.setText(f"{self.s_roi.value()}%")
        for w in (self.c_auto.currentIndexChanged, self.s_roi.valueChanged, self.chk_best.toggled,
                  self.chk_peak.toggled, self.c_sens.currentIndexChanged, self.c_color.currentIndexChanged):
            w.connect(lambda *_: self.settingsChanged.emit())
        self.b_best.clicked.connect(self.bestShotClicked.emit)

    # ---- 값 ----
    def auto_mode(self) -> str:
        return AUTO_MODES[self.c_auto.currentIndex()]

    def roi_frac(self) -> float:
        return self.s_roi.value() / 100.0

    def best_shot(self) -> bool:
        return self.chk_best.isChecked()

    def peaking(self) -> bool:
        return self.chk_peak.isChecked()

    def sensitivity(self) -> int:
        return self.c_sens.currentIndex() + 1

    def color_key(self) -> str:
        return self.c_color.currentData() or "red"

    def apply_to_config(self, config) -> None:
        config.smart_auto_mode = self.auto_mode()
        config.smart_roi_frac = self.roi_frac()
        config.smart_best_shot = self.best_shot()
        config.smart_peaking = self.peaking()
        config.smart_peaking_sensitivity = self.sensitivity()
        config.smart_peaking_color = self.color_key()

    def show_quality(self, q: dict | None) -> None:
        if not q:
            for bar in self.bars.values():
                bar.setValue(0)
            self.lbl_advice.setText("LIVE 화면에서 영상이 들어오면 점검을 시작합니다.")
            return
        for key, bar in self.bars.items():
            v = int(q.get(key, 0))
            bar.setValue(v)
            col = "#3ccf7a" if v >= 70 else ("#ffd08a" if v >= 40 else "#f0524f")
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {col}; border-radius: 3px; }}")
        issues = q.get("issues") or []
        self.lbl_advice.setText("촬영 조건 좋음 ✓" if not issues else " · ".join(issues))

    def log(self, text: str) -> None:
        self.lbl_log.setText(text)


class AnalysisTab(QWidget):
    tagClicked = Signal()
    fluoClicked = Signal()
    rednessClicked = Signal()
    addNoteClicked = Signal()
    clearClicked = Signal()
    ghostChanged = Signal(int)           # 0~100 (0 = 끄기)
    alignClicked = Signal()
    blinkToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProTabPage")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(6)

        lay.addWidget(_sub("조명 모드 태그"))
        self.lbl_tag = _muted("1화면에서 영상을 열면 자동으로 추정합니다.")
        lay.addWidget(self.lbl_tag)

        lay.addWidget(_sub("측정 (1화면 · '원' 주석 = 측정 영역)"))
        g = QGridLayout()
        g.setSpacing(4)
        self.b_fluo = QPushButton("형광 염색 면적")
        self.b_fluo.setToolTip("코발트블루 + 플루오레세인 영상에서 녹색 형광 화소의 면적·비율 (눈금 보정 시 mm²)")
        self.b_red = QPushButton("충혈 지수")
        self.b_red.setToolTip("측정 영역의 붉은 기·혈관 화소 비율 — 같은 조건의 경과 영상끼리 비교하는 상대값")
        self.b_note = QPushButton("코멘트에 기록")
        self.b_note.setToolTip("마지막 측정 결과를 이 영상의 코멘트에 추가")
        self.b_clear = QPushButton("표시 지우기")
        for b in (self.b_fluo, self.b_red, self.b_note, self.b_clear):
            b.setObjectName("ProBtn")
            b.setMinimumHeight(32)
        g.addWidget(self.b_fluo, 0, 0)
        g.addWidget(self.b_red, 0, 1)
        g.addWidget(self.b_note, 1, 0)
        g.addWidget(self.b_clear, 1, 1)
        lay.addLayout(g)
        self.lbl_result = _muted("-")
        lay.addWidget(self.lbl_result)

        lay.addWidget(_sub("경과 비교 (비교 화면)"))
        row = QHBoxLayout()
        row.addWidget(_muted("고스트"))
        self.s_ghost = QSlider(Qt.Orientation.Horizontal)
        self.s_ghost.setRange(0, 100)
        self.s_ghost.setValue(0)
        self.s_ghost.setToolTip("왼쪽(이전) 영상을 오른쪽(현재) 영상 위에 반투명으로 겹칩니다 (0 = 끄기)")
        self.lbl_ghost = _muted("끄기")
        self.lbl_ghost.setFixedWidth(34)
        row.addWidget(self.s_ghost, 1)
        row.addWidget(self.lbl_ghost)
        lay.addLayout(row)
        g2 = QGridLayout()
        g2.setSpacing(4)
        self.b_align = QPushButton("위치 정렬")
        self.b_align.setToolTip("이전 영상을 현재 영상에 맞춰 이동·회전 (촬영 위치 차이 보정)")
        self.b_blink = QPushButton("깜빡임 전환")
        self.b_blink.setCheckable(True)
        self.b_blink.setToolTip("두 영상을 0.5초마다 번갈아 표시 — 변화한 부위가 눈에 띕니다")
        for b in (self.b_align, self.b_blink):
            b.setObjectName("ProBtn")
            b.setMinimumHeight(32)
        g2.addWidget(self.b_align, 0, 0)
        g2.addWidget(self.b_blink, 0, 1)
        lay.addLayout(g2)
        self.lbl_cmp = _muted("")
        lay.addWidget(self.lbl_cmp)
        lay.addWidget(_muted("측정값은 기록 보조용이며 질환 판정(진단)을 하지 않습니다. "
                             "조명·배율·각도가 다른 영상의 차이는 병변 변화로 해석하지 마세요."))
        lay.addStretch(1)

        self.b_fluo.clicked.connect(self.fluoClicked.emit)
        self.b_red.clicked.connect(self.rednessClicked.emit)
        self.b_note.clicked.connect(self.addNoteClicked.emit)
        self.b_clear.clicked.connect(self.clearClicked.emit)
        self.s_ghost.valueChanged.connect(self._on_ghost)
        self.b_align.clicked.connect(self.alignClicked.emit)
        self.b_blink.toggled.connect(self.blinkToggled.emit)

    def _on_ghost(self, v: int) -> None:
        self.lbl_ghost.setText("끄기" if v == 0 else f"{v}%")
        self.ghostChanged.emit(v)

    def set_enabled_for(self, mode: str) -> None:
        single = mode == "single"
        cmp = mode == "compare"
        for b in (self.b_fluo, self.b_red, self.b_note, self.b_clear):
            b.setEnabled(single)
        for w in (self.s_ghost, self.b_align, self.b_blink):
            w.setEnabled(cmp)
        if not cmp and self.b_blink.isChecked():
            self.b_blink.setChecked(False)
