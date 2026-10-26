"""비교 창 — 2~4장을 나란히 놓고 확대·이동을 함께 움직여 본다.

2장 = 좌우, 3~4장 = 2×2. 휠 확대·드래그 이동은 모든 칸이 같이 움직인다.
채널(컬러 / Red-free / 흑백)과 밝기·대비는 모든 칸에 똑같이 적용된다 (원본은 그대로).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from app.capture.image_process import Adjust
from app.ui.pro.image_canvas import ImageCanvas

MAX_ITEMS = 4
_CHANNELS = [("rgb", "컬러"), ("green", "Red-free"), ("red", "적색"), ("blue", "청색"), ("gray", "흑백")]


class CompareDialog(QDialog):
    def __init__(self, items: list, parent=None, title: str = "영상 비교"):
        """items: [(bgr, caption), ...] — 앞의 4장까지."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1280, 820)
        self._items = items[:MAX_ITEMS]

        bar = QHBoxLayout()
        self.c_channel = QComboBox()
        for key, label in _CHANNELS:
            self.c_channel.addItem(label, key)
        self.s_bright = QSlider(Qt.Orientation.Horizontal)
        self.s_bright.setRange(-100, 100)
        self.s_contrast = QSlider(Qt.Orientation.Horizontal)
        self.s_contrast.setRange(20, 300)
        self.s_contrast.setValue(100)
        for s in (self.s_bright, self.s_contrast):
            s.setFixedWidth(150)
        b_fit = QPushButton("화면 맞춤")
        b_in = QPushButton("확대 +")
        b_out = QPushButton("축소 −")
        b_reset = QPushButton("보정 초기화")
        bar.addWidget(QLabel("채널"))
        bar.addWidget(self.c_channel)
        bar.addSpacing(10)
        bar.addWidget(QLabel("밝기"))
        bar.addWidget(self.s_bright)
        bar.addWidget(QLabel("대비"))
        bar.addWidget(self.s_contrast)
        bar.addWidget(b_reset)
        bar.addStretch(1)
        for b in (b_out, b_in, b_fit):
            bar.addWidget(b)

        grid = QGridLayout()
        grid.setSpacing(4)
        cols = 2
        self.canvases: list[ImageCanvas] = []
        for i, (img, cap) in enumerate(self._items):
            cv = ImageCanvas()
            cv.set_image(img)
            cv.set_caption(cap)
            grid.addWidget(cv, i // cols, i % cols)
            for other in self.canvases:             # 모든 칸끼리 연결 (확대 신호는 한 단계만 전달됨)
                other.link(cv)
            self.canvases.append(cv)

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addLayout(grid, 1)

        self.c_channel.currentIndexChanged.connect(self._apply)
        self.s_bright.valueChanged.connect(self._apply)
        self.s_contrast.valueChanged.connect(self._apply)
        b_reset.clicked.connect(self.reset_adjust)
        b_fit.clicked.connect(lambda: [cv.reset_view() for cv in self.canvases])
        b_in.clicked.connect(lambda: self.canvases and self.canvases[0].zoom_by(1.25))
        b_out.clicked.connect(lambda: self.canvases and self.canvases[0].zoom_by(0.8))

    def adjust(self) -> Adjust:
        return Adjust(channel=self.c_channel.currentData(), brightness=float(self.s_bright.value()),
                      contrast=self.s_contrast.value() / 100.0)

    def _apply(self, *_):
        adj = self.adjust()
        for cv in self.canvases:
            cv.set_adjust(adj)

    def reset_adjust(self) -> None:
        for w, v in ((self.c_channel, 0), (self.s_bright, 0), (self.s_contrast, 100)):
            w.blockSignals(True)
            w.setCurrentIndex(v) if isinstance(w, QComboBox) else w.setValue(v)
            w.blockSignals(False)
        self._apply()
