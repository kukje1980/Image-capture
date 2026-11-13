"""The photo of the 3D tab's 사진 card: the fundus photo small, its image circle, the optic disc (yellow
ring, 유두) and the macula (light blue ring, 황반) where they were found or marked — and, while
황반 지정 / 유두 지정 is on, a click on the photo marks the place (``picked``).

The web page draws the same (``web3d/app.js``, ``PhotoCanvas``).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import imaging

DISC_COLOR = QColor("#ffd60a")
FOVEA_COLOR = QColor("#64d2ff")
CIRCLE_COLOR = QColor(80, 200, 255, 166)
PICK_COLOR = QColor("#0a84ff")


class LandmarkPhoto(QWidget):
    """The photo with its image circle, disc and macula; clicks mark a place while ``picking``."""

    picked = Signal(float, float)        # photo pixels
    MAX_SIDE = 900                       # the photo is kept this small: it is drawn about 280 px wide

    def __init__(self, parent=None):
        super().__init__(parent)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumHeight(150)
        self._pix: QPixmap | None = None
        self._scale = 1.0                # photo pixels → pixmap pixels
        self.circle = None
        self.disc = None
        self.fovea = None
        self.picking: str | None = None  # "fovea" / "disc" while marking

    # -- size: 4 : 3, as wide as the card ------------------------------------------------------
    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return max(150, round(w * 0.75))

    def sizeHint(self) -> QSize:
        return QSize(276, 207)

    # -- what is shown ----------------------------------------------------------------------------
    def set_photo(self, rgb: np.ndarray | None, alpha: np.ndarray | None = None) -> None:
        """The photo; with ``alpha`` (imaging.fundus_alpha) black outside the image circle, so the name or
        ID a device burns into a corner is not shown."""
        if rgb is None:
            self._pix = None
            self.update()
            return
        h, w = rgb.shape[:2]
        s = min(1.0, self.MAX_SIDE / max(h, w))
        small = imaging.shrink(np.ascontiguousarray(rgb[..., :3]), s) if s < 1.0 else np.ascontiguousarray(rgb[..., :3])
        if alpha is not None:
            mask = imaging.shrink(np.ascontiguousarray(alpha), s, like=small) if s < 1.0 else alpha
            small = (small.astype(np.uint16) * mask.astype(np.uint16)[..., None] // 255).astype(np.uint8)
        data = np.ascontiguousarray(small, np.uint8)
        img = QImage(data.data, data.shape[1], data.shape[0], 3 * data.shape[1], QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(img)
        self._scale = data.shape[1] / float(w)
        self.update()

    def set_marks(self, circle, disc, fovea) -> None:
        self.circle, self.disc, self.fovea = circle, disc, fovea
        self.update()

    def set_picking(self, what: str | None) -> None:
        self.picking = what
        self.setCursor(Qt.CursorShape.CrossCursor if what else Qt.CursorShape.ArrowCursor)
        self.update()

    # -- geometry -----------------------------------------------------------------------------------
    def image_rect(self) -> QRectF:
        """Where the photo is drawn (fitted, centred)."""
        if self._pix is None:
            return QRectF()
        k = min(self.width() / self._pix.width(), self.height() / self._pix.height())
        w, h = self._pix.width() * k, self._pix.height() * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def to_widget(self, x: float, y: float) -> QPointF:
        r = self.image_rect()
        k = r.width() / max(1, self._pix.width()) * self._scale if self._pix is not None else 1.0
        return QPointF(r.left() + x * k, r.top() + y * k)

    def to_photo(self, p: QPointF) -> tuple[float, float] | None:
        if self._pix is None:
            return None
        r = self.image_rect()
        k = r.width() / max(1, self._pix.width()) * self._scale
        if k <= 0 or not r.contains(p):
            return None
        return (p.x() - r.left()) / k, (p.y() - r.top()) / k

    def _k(self) -> float:
        r = self.image_rect()
        return r.width() / max(1, self._pix.width()) * self._scale if self._pix is not None else 1.0

    # -- drawing ------------------------------------------------------------------------------------
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        p.fillPath(path, QColor(0, 0, 0))
        if self._pix is None:
            p.setPen(QColor(142, 142, 147))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "사진 없음")
            p.end()
            return
        p.save()
        p.setClipPath(path)
        p.drawPixmap(self.image_rect(), self._pix, QRectF(self._pix.rect()))
        p.restore()
        k = self._k()
        if self.circle is not None and self.circle[2]:
            pen = QPen(CIRCLE_COLOR, 1.0, Qt.PenStyle.DashLine)
            pen.setDashPattern([5, 4])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            c = self.to_widget(self.circle[0], self.circle[1])
            p.drawEllipse(c, self.circle[2] * k, self.circle[2] * k)
        rr = (self.circle[2] * k) if self.circle is not None and self.circle[2] else self.image_rect().width() / 2
        left = self.disc is not None and self.fovea is not None and self.fovea[0] < self.disc[0]
        self._ring(p, self.disc, max(6.0, rr * 0.07), DISC_COLOR, "유두")
        self._ring(p, self.fovea, max(4.0, rr * 0.03), FOVEA_COLOR, "황반", left)
        if self.picking:
            p.setPen(QPen(PICK_COLOR, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        p.end()

    def _ring(self, p: QPainter, at, r: float, color: QColor, label: str, left: bool = False) -> None:
        if at is None:
            return
        c = self.to_widget(at[0], at[1])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 153), 2.0))
        p.drawEllipse(c, r + 1, r + 1)
        p.setPen(QPen(color, 1.6))
        p.drawEllipse(c, r, r)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        text = QPainterPath()
        text.addText(0, 0, font, label)
        b = text.boundingRect()
        x = c.x() - r - 4 - b.width() if left else c.x() + r + 4
        text.translate(x - b.left(), c.y() - b.center().y())
        p.strokePath(text, QPen(QColor(0, 0, 0, 178), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
        p.fillPath(text, color)

    # -- marking --------------------------------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        if not self.picking or e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        at = self.to_photo(e.position())
        if at is None:
            return
        self.picked.emit(float(at[0]), float(at[1]))
