"""Pro 모드 이미지 캔버스.

- 휠 확대/축소, 드래그 이동(Pan), 창 크기 맞춤(Fit)
- 이미지 보정(Adjust) 실시간 적용 — 원본(_base)은 보존
- 주석 도구: 텍스트(T), 화살표(↗). 좌표는 원본 이미지 픽셀 좌표계
- render_to_bgr(): 보정 + 주석을 원본 해상도로 합성 (보정본 저장/인쇄용)
- link(other): 2장 비교 시 확대·스크롤 동기화
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QInputDialog,
)

from app.capture.frame_utils import bgr_to_qimage
from app.capture.image_process import Adjust, apply_adjust

_ANN_COLOR = QColor("#facc15")   # 노란 주석 (검은 외곽선과 함께 어떤 배경에서도 잘 보임)


def qimage_to_bgr(qimg: QImage) -> np.ndarray:
    qimg = qimg.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = qimg.width(), qimg.height(), qimg.bytesPerLine()
    buf = np.frombuffer(qimg.constBits(), dtype=np.uint8, count=bpl * h)
    rgb = buf.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)
    return rgb[..., ::-1].copy()


class ImageCanvas(QGraphicsView):
    zoomed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._pix)
        self._base: np.ndarray | None = None
        self._adj = Adjust()
        self._tool = "pan"
        self._ann: list = []
        self._drag_start: QPointF | None = None
        self._temp_line = None
        self._auto_fit = True
        self._caption = ""
        self._placeholder = "영상 없음"

        self.setBackgroundBrush(QColor("#000000"))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumSize(320, 240)

    # ---- 이미지 ----
    def set_image(self, frame: np.ndarray | None, keep_view: bool = False,
                  keep_annotations: bool = False) -> None:
        first = self._base is None
        self._base = frame
        if not keep_annotations:
            self.clear_annotations()
        self._refresh()
        if frame is not None and (not keep_view or first):
            self._auto_fit = True
            self.fit()

    def image(self) -> np.ndarray | None:
        return self._base

    def set_adjust(self, adj: Adjust) -> None:
        self._adj = adj
        self._refresh()

    def _refresh(self) -> None:
        if self._base is None:
            self._pix.setPixmap(QPixmap())
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
        else:
            img = apply_adjust(self._base, self._adj)
            self._pix.setPixmap(QPixmap.fromImage(bgr_to_qimage(img)))
            self._scene.setSceneRect(self._pix.boundingRect())
        self.viewport().update()

    def fit(self) -> None:
        if self._base is not None:
            self.fitInView(self._pix, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._base is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self._auto_fit = False
        self.scale(factor, factor)
        self.zoomed.emit(factor)

    def apply_zoom(self, factor: float) -> None:
        self._auto_fit = False
        self.scale(factor, factor)

    def zoom_by(self, factor: float) -> None:
        self.apply_zoom(factor)
        self.zoomed.emit(factor)

    def reset_view(self) -> None:
        self._auto_fit = True
        self.resetTransform()
        self.fit()

    def link(self, other: "ImageCanvas") -> None:
        """두 캔버스의 확대·스크롤 동기화 (2장 비교)."""
        self.zoomed.connect(other.apply_zoom)
        other.zoomed.connect(self.apply_zoom)
        self.horizontalScrollBar().valueChanged.connect(other.horizontalScrollBar().setValue)
        other.horizontalScrollBar().valueChanged.connect(self.horizontalScrollBar().setValue)
        self.verticalScrollBar().valueChanged.connect(other.verticalScrollBar().setValue)
        other.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)

    # ---- 캡션 (좌상단 오버레이) ----
    def set_caption(self, text: str) -> None:
        self._caption = text
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect) -> None:  # noqa: N802
        painter.save()
        painter.resetTransform()
        if self._base is None:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
        elif self._caption:
            f = QFont(self.font())
            f.setPointSize(10)
            painter.setFont(f)
            fm = painter.fontMetrics()
            w = fm.horizontalAdvance(self._caption) + 16
            painter.fillRect(8, 8, w, fm.height() + 8, QColor(0, 0, 0, 160))
            painter.setPen(QColor("#e2e8f0"))
            painter.drawText(16, 8 + 4 + fm.ascent(), self._caption)
        painter.restore()

    # ---- 주석 ----
    def set_tool(self, tool: str) -> None:
        self._tool = tool
        if tool == "pan":
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def _ann_scale(self) -> float:
        if self._base is None:
            return 1.0
        return max(1.0, max(self._base.shape[:2]) / 900.0)

    def _ann_pen(self) -> QPen:
        pen = QPen(_ANN_COLOR)
        pen.setWidthF(3.0 * self._ann_scale())
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def add_text(self, x: float, y: float, text: str) -> None:
        item = QGraphicsSimpleTextItem(text)
        f = QFont()
        f.setPixelSize(int(26 * self._ann_scale()))
        f.setBold(True)
        item.setFont(f)
        item.setBrush(QBrush(_ANN_COLOR))
        outline = QPen(QColor("#000000"))
        outline.setWidthF(1.2 * self._ann_scale())
        item.setPen(outline)
        item.setPos(x, y)
        self._scene.addItem(item)
        self._ann.append(("text", item, text))

    def add_arrow(self, p1: QPointF, p2: QPointF) -> None:
        pen = self._ann_pen()
        line = self._scene.addLine(QLineF(p1, p2), pen)
        ang = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        size = 18 * self._ann_scale()
        a1 = QPointF(p2.x() - size * math.cos(ang - math.pi / 7), p2.y() - size * math.sin(ang - math.pi / 7))
        a2 = QPointF(p2.x() - size * math.cos(ang + math.pi / 7), p2.y() - size * math.sin(ang + math.pi / 7))
        head = self._scene.addPolygon(QPolygonF([p2, a1, a2]), pen, QBrush(_ANN_COLOR))
        self._ann.append(("arrow", line, head))

    def clear_annotations(self) -> None:
        for entry in self._ann:
            for obj in entry[1:]:
                if hasattr(obj, "scene") and obj.scene() is not None:
                    self._scene.removeItem(obj)
        self._ann = []

    def annotation_kinds(self) -> list:
        return [e[0] for e in self._ann]

    def has_annotations(self) -> bool:
        return bool(self._ann)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._base is not None and event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            if self._tool == "text":
                text, ok = QInputDialog.getText(self, "텍스트 주석", "내용:")
                if ok and text.strip():
                    self.add_text(pos.x(), pos.y(), text.strip())
                return
            if self._tool == "arrow":
                self._drag_start = pos
                self._temp_line = self._scene.addLine(QLineF(pos, pos), self._ann_pen())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._tool == "arrow" and self._drag_start is not None and self._temp_line is not None:
            self._temp_line.setLine(QLineF(self._drag_start, self.mapToScene(event.position().toPoint())))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._tool == "arrow" and self._drag_start is not None:
            end = self.mapToScene(event.position().toPoint())
            if self._temp_line is not None:
                self._scene.removeItem(self._temp_line)
                self._temp_line = None
            if QLineF(self._drag_start, end).length() > 4:
                self.add_arrow(self._drag_start, end)
            self._drag_start = None
            return
        super().mouseReleaseEvent(event)

    # ---- 합성 렌더 ----
    def render_to_bgr(self) -> np.ndarray | None:
        """보정 + 주석을 원본 해상도 BGR로 합성."""
        if self._base is None:
            return None
        h, w = self._base.shape[:2]
        qimg = QImage(w, h, QImage.Format.Format_RGB888)
        qimg.fill(QColor("#000000"))
        p = QPainter(qimg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._scene.render(p, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
        p.end()
        return qimage_to_bgr(qimg)
