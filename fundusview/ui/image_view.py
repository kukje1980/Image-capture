"""2D image viewer: zoom (wheel, anchored at the cursor), pan (drag), fit
(double-click), overlays for the detected image circle and optic disc, and a
context menu to place the disc by hand."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QMenu


def to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb[..., :3], dtype=np.uint8)
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return img.copy()  # own the buffer


class ImageView(QGraphicsView):
    discPicked = Signal(float, float)
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#111316")))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._pix)
        self._circle = QGraphicsEllipseItem()
        self._circle.setPen(QPen(QColor(80, 200, 255, 160), 0, Qt.PenStyle.DashLine))
        self._circle.setVisible(False)
        self.scene().addItem(self._circle)
        self._disc = QGraphicsEllipseItem()
        self._disc.setPen(QPen(QColor(255, 220, 60, 220), 0))
        self._disc.setVisible(False)
        self.scene().addItem(self._disc)
        self._fit = True
        self.show_overlays = False
        self._circle_px = None
        self._disc_px = None

    def has_image(self) -> bool:
        return not self._pix.pixmap().isNull()

    def set_rgb(self, rgb: np.ndarray | None, *, keep_view: bool = False) -> None:
        if rgb is None:
            self._pix.setPixmap(QPixmap())
            self._circle.setVisible(False)
            self._disc.setVisible(False)
            return
        self._pix.setPixmap(QPixmap.fromImage(to_qimage(rgb)))
        self.scene().setSceneRect(QRectF(self._pix.pixmap().rect()))
        if not keep_view:
            self.fit()

    def set_overlays(self, circle, disc) -> None:
        self._circle_px, self._disc_px = circle, disc
        self._update_overlays()

    def _update_overlays(self) -> None:
        if self._circle_px:
            cx, cy, r = self._circle_px
            self._circle.setRect(cx - r, cy - r, 2 * r, 2 * r)
        if self._disc_px:
            x, y = self._disc_px[:2]
            r = (self._circle_px[2] if self._circle_px else 500) * 0.06
            self._disc.setRect(x - r, y - r, 2 * r, 2 * r)
        self._circle.setVisible(self.show_overlays and bool(self._circle_px))
        self._disc.setVisible(self.show_overlays and bool(self._disc_px))

    def toggle_overlays(self, on: bool) -> None:
        self.show_overlays = on
        self._update_overlays()

    def fit(self) -> None:
        if self.has_image():
            self.fitInView(self._pix, Qt.AspectRatioMode.KeepAspectRatio)
            self._fit = True
            self.zoomChanged.emit(self.transform().m11())

    def zoom_to(self, factor: float) -> None:
        self.setTransform(QTransform.fromScale(factor, factor))
        self._fit = False
        self.zoomChanged.emit(factor)

    def wheelEvent(self, e):
        if not self.has_image():
            return
        f = 1.15 ** (e.angleDelta().y() / 120.0)
        cur = self.transform().m11()
        if 0.02 < cur * f < 40:
            self.scale(f, f)
            self._fit = False
            self.zoomChanged.emit(self.transform().m11())

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()

    def contextMenuEvent(self, e):
        if not self.has_image():
            return
        pos = self.mapToScene(e.pos())
        menu = QMenu(self)
        act_disc = QAction("여기를 시신경 유두로 지정 (3D 시신경 위치)", menu)
        act_disc.triggered.connect(lambda: self.discPicked.emit(pos.x(), pos.y()))
        menu.addAction(act_disc)
        act_fit = QAction("화면에 맞춤", menu)
        act_fit.triggered.connect(self.fit)
        menu.addAction(act_fit)
        act_100 = QAction("100% 크기", menu)
        act_100.triggered.connect(lambda: self.zoom_to(1.0))
        menu.addAction(act_100)
        menu.exec(e.globalPos())

    def scene_pos(self, p: QPointF) -> QPointF:
        return self.mapToScene(p.toPoint())
