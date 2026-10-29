"""Histogram chart with black / white level points (VK-2 "Histogram Chart")."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QPushButton, QSlider, QVBoxLayout, QWidget


class _Chart(QWidget):
    def __init__(self, hist: np.ndarray, parent=None):
        super().__init__(parent)
        self.hist = hist.astype(np.float64)
        self.levels = (0, 255)
        self.setMinimumSize(420, 200)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#16191d"))
        w, h = self.width(), self.height()
        top = np.log1p(self.hist).max() or 1.0
        for c, color in enumerate((QColor(235, 80, 70), QColor(90, 200, 100), QColor(80, 140, 240))):
            path = QPainterPath(QPointF(0, h))
            for x in range(256):
                path.lineTo(QPointF(x / 255 * w, h - np.log1p(self.hist[c, x]) / top * (h - 6)))
            path.lineTo(QPointF(w, h))
            fill = QColor(color)
            fill.setAlpha(60)
            p.fillPath(path, fill)
            p.setPen(QPen(color, 1.2))
            p.drawPath(path)
        p.setPen(QPen(QColor(255, 214, 64), 2))
        for v in self.levels:
            x = v / 255 * w
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.end()


class HistogramDialog(QDialog):
    levelsChanged = Signal(int, int)

    def __init__(self, hist: np.ndarray, levels: tuple[int, int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("히스토그램 · 레벨")
        self.chart = _Chart(hist)
        self.lo = QSlider(Qt.Orientation.Horizontal)
        self.hi = QSlider(Qt.Orientation.Horizontal)
        for s in (self.lo, self.hi):
            s.setRange(0, 255)
        self.lo.setValue(levels[0])
        self.hi.setValue(levels[1])
        self.chart.levels = tuple(levels)
        self.lo.valueChanged.connect(self._changed)
        self.hi.valueChanged.connect(self._changed)
        form = QFormLayout()
        form.addRow("검정 기준", self.lo)
        form.addRow("흰색 기준", self.hi)
        reset = QPushButton("초기화")
        reset.clicked.connect(lambda: (self.lo.setValue(0), self.hi.setValue(255)))
        form.addRow(reset)
        lay = QVBoxLayout(self)
        lay.addWidget(self.chart, 1)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def _changed(self, _=None) -> None:
        lo, hi = self.lo.value(), self.hi.value()
        if hi <= lo:  # keep at least one step between the points
            if self.sender() is self.lo:
                self.lo.setValue(hi - 1)
            else:
                self.hi.setValue(lo + 1)
            return
        self.chart.levels = (lo, hi)
        self.chart.update()
        self.levelsChanged.emit(lo, hi)
