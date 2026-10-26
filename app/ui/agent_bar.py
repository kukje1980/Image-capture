"""AI 에이전트 도구줄 — 장면 표시 · 자동 촬영 · 프로토콜 체크리스트 · 추천 프레임 · 데이터 메뉴."""
from __future__ import annotations

from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.agent.protocol import PROTOCOLS, Checklist
from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT

THUMB = QSize(96, 54)


def _thumb_icon(frame: np.ndarray) -> QIcon:
    h, w = frame.shape[:2]
    scale = THUMB.width() / max(1, w)
    small = cv2.resize(frame, (THUMB.width(), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).copy()
    img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
    return QIcon(QPixmap.fromImage(img))


class AgentBar(QFrame):
    enabledToggled = Signal(bool)
    autoCaptureToggled = Signal(bool)
    protocolChanged = Signal(str)
    loggingToggled = Signal(bool)
    candidateChosen = Signal(int)
    candidatesDismissed = Signal()
    resetChecklist = Signal()
    exportDataset = Signal()
    openLogs = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Dock")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 12, 6)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_on = QPushButton(icons.gap("에이전트"))
        self.btn_on.setObjectName("ToolBtn")
        self.btn_on.setCheckable(True)
        self.btn_on.setIcon(icons.icon("bot", ICON_ACCENT, 18))
        self.btn_on.setToolTip("AI 에이전트: 장면 인식 · 자동 촬영 · 전후 클립 · 추천 프레임")
        self.btn_on.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(self.btn_on)

        self.scene = QLabel("장면 --")
        self.scene.setObjectName("SmartMeter")
        self.scene.setMinimumWidth(190)
        self.scene.setToolTip("지금 화면의 조명·부위 (확신 %)")
        row.addWidget(self.scene)
        row.addWidget(self._sep())

        self.chk_auto = QCheckBox("자동 촬영")
        self.chk_auto.setToolTip("장면이 1초 이상 안정되고 초점이 맞으면\n"
                                 "눈·장면당 한 장을 자동 저장")
        self.chk_auto.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(self.chk_auto)

        self.protocol = QComboBox()
        for key, p in PROTOCOLS.items():
            self.protocol.addItem(p["name"], key)
        self.protocol.setToolTip("검사 프로토콜 — 있어야 하는 샷 목록")
        self.protocol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(self.protocol)

        self.checks = QWidget()
        self.checks_lay = QHBoxLayout(self.checks)
        self.checks_lay.setContentsMargins(0, 0, 0, 0)
        self.checks_lay.setSpacing(4)
        row.addWidget(self.checks)
        row.addStretch(1)

        self.hint = QLabel("")
        self.hint.setObjectName("SmartHint")
        self.hint.setMinimumWidth(160)
        row.addWidget(self.hint)

        self.btn_menu = QToolButton()
        self.btn_menu.setIcon(icons.icon("list", ICON, 16))
        self.btn_menu.setToolTip("에이전트 메뉴")
        self.btn_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        menu = QMenu(self.btn_menu)
        self.act_reset = menu.addAction("체크리스트 초기화 (같은 환자 다시 촬영)")
        self.act_logging = menu.addAction("사용 기록 수집 (익명)")
        self.act_logging.setCheckable(True)
        menu.addSeparator()
        self.act_export = menu.addAction("학습 데이터 내보내기…")
        self.act_logs = menu.addAction("이벤트 로그 폴더 열기")
        self.btn_menu.setMenu(menu)
        row.addWidget(self.btn_menu)
        outer.addLayout(row)

        # 추천 프레임 줄 (후보가 있을 때만)
        self.strip = QWidget()
        sl = QHBoxLayout(self.strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        lb = QLabel("추천 프레임 (촬영 전후 중 선명한 순)")
        lb.setObjectName("SmartHint")
        sl.addWidget(lb)
        self.cands: List[QToolButton] = []
        for i in range(6):
            b = QToolButton()
            b.setIconSize(THUMB)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip("클릭하면 이 프레임을 사진으로 저장")
            b.clicked.connect(lambda _=False, k=i: self.candidateChosen.emit(k))
            b.hide()
            sl.addWidget(b)
            self.cands.append(b)
        sl.addStretch(1)
        self.btn_dismiss = QPushButton("닫기")
        self.btn_dismiss.setObjectName("ToolBtn")
        self.btn_dismiss.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_dismiss.clicked.connect(self.candidatesDismissed.emit)
        sl.addWidget(self.btn_dismiss)
        self.strip.hide()
        outer.addWidget(self.strip)

        self.btn_on.toggled.connect(self._on_toggled)
        self.chk_auto.toggled.connect(self.autoCaptureToggled.emit)
        self.protocol.currentIndexChanged.connect(
            lambda _i: self.protocolChanged.emit(self.protocol.currentData()))
        self.act_reset.triggered.connect(self.resetChecklist.emit)
        self.act_logging.toggled.connect(self.loggingToggled.emit)
        self.act_export.triggered.connect(self.exportDataset.emit)
        self.act_logs.triggered.connect(self.openLogs.emit)
        self._on_toggled(False)

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("DockSep")
        f.setFixedSize(1, 18)
        return f

    def _on_toggled(self, on: bool) -> None:
        for w in (self.scene, self.chk_auto, self.protocol, self.checks, self.hint):
            w.setEnabled(on)
        if not on:
            self.scene.setText("장면 --")
            self.hint.setText("")
            self.clear_candidates()
        self.enabledToggled.emit(on)

    # ---- 상태 ----
    def set_state(self, enabled: bool, auto: bool, protocol: str, logging_on: bool) -> None:
        for w in (self.btn_on, self.chk_auto, self.protocol, self.act_logging):
            w.blockSignals(True)
        self.btn_on.setChecked(enabled)
        self.chk_auto.setChecked(auto)
        i = self.protocol.findData(protocol)
        self.protocol.setCurrentIndex(i if i >= 0 else 0)
        self.act_logging.setChecked(logging_on)
        for w in (self.btn_on, self.chk_auto, self.protocol, self.act_logging):
            w.blockSignals(False)
        for w in (self.scene, self.chk_auto, self.protocol, self.checks, self.hint):
            w.setEnabled(enabled)

    def is_enabled(self) -> bool:
        return self.btn_on.isChecked()

    def set_scene(self, r) -> None:
        if r is None:
            self.scene.setText("장면 --")
            return
        extra = f" · 슬릿 {r.slit_width_px:.0f}px" if r.label == "slit" and r.slit_width_px else ""
        self.scene.setText(f"{r.label_ko} {r.confidence * 100:.0f}%{extra}")
        detail = ", ".join(f"{k} {v:.2f}" for k, v in r.scores.items())
        self.scene.setToolTip(f"출처: {r.source} · {detail}")

    def set_hint(self, text: str) -> None:
        self.hint.setText(text or "")

    def set_checklist(self, cl: Optional[Checklist]) -> None:
        while self.checks_lay.count():
            item = self.checks_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if cl is None:
            return
        for it in cl.items:
            lb = QLabel(("✓ " if it.done else "○ ") + it.text)
            lb.setObjectName("SmartMeter")
            lb.setProperty("done", it.done)
            lb.setStyleSheet("color: #3ccf7a;" if it.done else "")
            self.checks_lay.addWidget(lb)

    # ---- 추천 프레임 ----
    def show_candidates(self, cands) -> None:
        self.clear_candidates()
        for b, c in zip(self.cands, cands, strict=False):
            b.setIcon(_thumb_icon(c.frame))
            b.setText(f"초점 {c.score:.0f}")
            b.show()
        self.strip.setVisible(bool(cands))

    def mark_candidate_saved(self, idx: int) -> None:
        if 0 <= idx < len(self.cands):
            self.cands[idx].setText(self.cands[idx].text() + " ✓")
            self.cands[idx].setEnabled(False)

    def clear_candidates(self) -> None:
        for b in self.cands:
            b.hide()
            b.setEnabled(True)
        self.strip.hide()
