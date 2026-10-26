"""겹쳐보기 창 — 다른 날 찍은 두 영상을 겹쳐 병변의 변화(진행)를 본다.

아래 / 위 영상을 고르고 투명도·방식(겹치기 · 차이 강조 · 바둑판 · 좌우 분할)을 바꾼다.
위 영상은 위치 맞춤(dx, dy)으로 옮길 수 있다 — 방향키 1px, Shift+방향키 10px.
'겹친 영상 저장' 은 지금 화면을 새 영상으로 환자 DB 에 저장한다 (코멘트 '겹쳐보기').
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from app.capture import overlay
from app.capture.image_process import Adjust, apply_adjust
from app.ui.pro.image_canvas import ImageCanvas

_CHANNELS = [("rgb", "컬러"), ("green", "Red-free (녹색)"), ("gray", "흑백")]


class OverlayDialog(QDialog):
    def __init__(self, items: list, parent=None, on_save=None):
        """items: [(bgr, caption), ...] 2장 이상. on_save(bgr) → 저장 결과 문자열 (없으면 저장 버튼 숨김)."""
        super().__init__(parent)
        self.setWindowTitle("겹쳐보기 (Overlay)")
        self.resize(1180, 780)
        self._items = items
        self._on_save = on_save

        self.canvas = ImageCanvas()
        side = QWidget()
        side.setFixedWidth(300)
        form = QFormLayout(side)
        self.c_base = QComboBox()
        self.c_top = QComboBox()
        for c in (self.c_base, self.c_top):
            c.addItems([cap for _, cap in items])
        self.c_top.setCurrentIndex(1 if len(items) > 1 else 0)
        self.c_mode = QComboBox()
        for m in overlay.MODES:
            self.c_mode.addItem(overlay.MODE_LABELS[m], m)
        self.s_alpha = QSlider(Qt.Orientation.Horizontal)
        self.s_alpha.setRange(0, 100)
        self.s_alpha.setValue(50)
        self.lbl_alpha = QLabel("50%")
        arow = QHBoxLayout()
        arow.addWidget(self.s_alpha, 1)
        arow.addWidget(self.lbl_alpha)
        self.c_channel = QComboBox()
        for key, label in _CHANNELS:
            self.c_channel.addItem(label, key)
        self.sp_dx = QSpinBox()
        self.sp_dy = QSpinBox()
        for sp in (self.sp_dx, self.sp_dy):
            sp.setRange(-2000, 2000)
            sp.setSuffix(" px")
        b_swap = QPushButton("아래 ↔ 위 바꾸기")
        b_center = QPushButton("위치 초기화")
        b_fit = QPushButton("화면 맞춤")
        self.b_save = QPushButton("겹친 영상 저장")
        self.b_save.setObjectName("Primary")
        self.b_save.setVisible(on_save is not None)
        self.lbl_msg = QLabel("방향키: 위 영상 1px 이동 · Shift+방향키: 10px")
        self.lbl_msg.setObjectName("Muted")
        self.lbl_msg.setWordWrap(True)

        form.addRow("아래 영상", self.c_base)
        form.addRow("위 영상", self.c_top)
        form.addRow("방식", self.c_mode)
        form.addRow("투명도 / 경계", arow)
        form.addRow("채널", self.c_channel)
        form.addRow("가로 이동", self.sp_dx)
        form.addRow("세로 이동", self.sp_dy)
        form.addRow(b_swap)
        form.addRow(b_center)
        form.addRow(b_fit)
        form.addRow(self.b_save)
        form.addRow(self.lbl_msg)

        lay = QHBoxLayout(self)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(side)

        for w in (self.c_base, self.c_top, self.c_mode, self.c_channel):
            w.currentIndexChanged.connect(self._render)
        for w in (self.s_alpha, self.sp_dx, self.sp_dy):
            w.valueChanged.connect(self._render)
        b_swap.clicked.connect(self.swap)
        b_center.clicked.connect(lambda: (self.sp_dx.setValue(0), self.sp_dy.setValue(0)))
        b_fit.clicked.connect(self.canvas.reset_view)
        self.b_save.clicked.connect(self._save)
        self._first = True
        self._render()

    # ---- 합성 ----
    def composed(self):
        base = self._items[self.c_base.currentIndex()][0]
        top = self._items[self.c_top.currentIndex()][0]
        ch = self.c_channel.currentData()
        if ch != "rgb":
            base, top = apply_adjust(base, Adjust(channel=ch)), apply_adjust(top, Adjust(channel=ch))
        return overlay.compose(base, top, self.c_mode.currentData(), self.s_alpha.value() / 100.0,
                               self.sp_dx.value(), self.sp_dy.value())

    def _render(self, *_):
        self.lbl_alpha.setText(f"{self.s_alpha.value()}%")
        self.canvas.set_image(self.composed(), keep_view=not self._first)
        self._first = False
        mode = overlay.MODE_LABELS[self.c_mode.currentData()]
        self.canvas.set_caption(f"{mode}  ·  아래: {self.c_base.currentText()}  ·  위: {self.c_top.currentText()}")

    def swap(self) -> None:
        a, b = self.c_base.currentIndex(), self.c_top.currentIndex()
        for c, v in ((self.c_base, b), (self.c_top, a)):
            c.blockSignals(True)
            c.setCurrentIndex(v)
            c.blockSignals(False)
        self._render()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                 Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
        if e.key() in moves:
            dx, dy = moves[e.key()]
            self.sp_dx.setValue(self.sp_dx.value() + dx)
            self.sp_dy.setValue(self.sp_dy.value() + dy)
            return
        super().keyPressEvent(e)

    def _save(self) -> None:
        if self._on_save is None:
            return
        self.lbl_msg.setText(self._on_save(self.composed()) or "저장했습니다")
