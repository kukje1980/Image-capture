"""2D image viewer with VK-2 style tools.

Mouse
  * wheel — zoom at the cursor; **right-drag up/down — zoom** (anchored where
    the drag started; a right click without dragging opens the menu);
    middle-drag — pan; double-click — fit.
  * left button depends on the active tool: 이동 (pan), 확대/축소 (drag up/down
    to zoom, click ×2, Shift+click ×½), 돋보기 (hold for a loupe; wheel while
    holding changes its power), 길이 / 각도 / C/D 비 (길이·면적) measurements,
    글자 / 화살표+글자 annotations, 회색조 분석 (hold: grey-level profile of the
    row under the cursor).

Zooming in shows a mini-map (미니맵) in the top-right corner: the whole photo
with the visible part framed; click or drag in it to move there. Keys: + / −
zoom at the cursor, 0 fit, 1 100%. ``zoom_to_rect`` zooms onto a region
(e.g. the posterior pole or one periphery of an ultra-wide-field photo).

Lengths are shown in pixels and — through the image's eye geometry
(``measure.Geometry``) — in retinal degrees and millimetres. Flips and
rotation are view transforms, so measurements and annotations stay attached
to the image; labels are counter-rotated to stay readable.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction, QBrush, QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem, QGraphicsPixmapItem,
    QGraphicsPolygonItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QInputDialog, QLabel, QMenu,
    QWidget,
)

from .. import measure

TOOLS = {
    "pan": "이동", "zoom": "확대/축소", "loupe": "돋보기", "length": "길이 측정", "angle": "각도 측정",
    "cd_length": "C/D 비 (길이)", "cd_area": "C/D 비 (면적)", "text": "글자 입력", "arrow": "화살표+글자",
    "profile": "회색조 분석",
}
TOOL_HINTS = {
    "pan": "드래그: 이동 · 휠/오른쪽 드래그: 확대·축소 · 더블클릭: 화면 맞춤",
    "zoom": "위로 드래그: 확대 · 아래로 드래그: 축소 · 클릭: 2배 · Shift+클릭: ½",
    "loupe": "누르고 있는 동안 돋보기 · 누른 채 휠: 배율",
    "length": "드래그해서 길이 측정 (px · 망막 각도 · mm)",
    "angle": "세 점 클릭 (가운데 점이 꼭짓점)",
    "cd_length": "① 시신경 함몰(cup) 지름을 드래그 → ② 유두(disc) 지름을 드래그",
    "cd_area": "① cup 둘레를 클릭(최대 12점, 더블클릭/Enter로 닫기) → ② disc 둘레",
    "text": "클릭한 곳에 글자 입력",
    "arrow": "드래그해서 화살표 → 글자 입력",
    "profile": "누르고 있는 동안 그 가로줄의 밝기 그래프",
}
YELLOW, CYAN = QColor(255, 214, 64), QColor(110, 215, 255)
CAPTION = QColor(0, 255, 0)   # VK-2 text colour


def to_qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb[..., :3], dtype=np.uint8)
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return img.copy()  # own the buffer


def from_qimage(img: QImage) -> np.ndarray:
    """``uint8`` RGB array of a QImage (any format)."""
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, :w * 3]
    return np.ascontiguousarray(arr.reshape(h, w, 3))


class _Navigator(QWidget):
    """Mini-map: the whole photo (as oriented on screen) with the visible part framed.

    Click or drag in it to centre the view there. Shown only while zoomed in.
    """

    BORDER = 3

    def __init__(self, view: "ImageView"):
        super().__init__(view.viewport())
        self.view = view
        self._thumb = QPixmap()
        self._key = None
        self._k = 1.0
        self._br = QRectF()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("미니맵: 전체 사진에서 지금 보는 곳 · 클릭·드래그: 그곳으로 이동")
        self.hide()

    def rebuild(self, side: int) -> None:
        """New thumbnail when the photo, its orientation or the mini-map size changed."""
        v = self.view
        pm = v._pix.pixmap()
        key = (pm.cacheKey(), v._rot, v._fh, v._fv, side)
        if key == self._key:
            return
        self._key = key
        t = v._orient()
        self._br = t.mapRect(QRectF(pm.rect()))
        self._k = side / max(self._br.width(), self._br.height(), 1.0)
        small = pm.scaled(max(1, round(pm.width() * self._k)), max(1, round(pm.height() * self._k)),
                          Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._thumb = small.transformed(t)
        self.resize(self._thumb.width() + 2 * self.BORDER, self._thumb.height() + 2 * self.BORDER)

    def to_nav(self, sp: QPointF) -> QPointF:
        q = self.view._orient().map(sp) - self._br.topLeft()
        return QPointF(q.x() * self._k + self.BORDER, q.y() * self._k + self.BORDER)

    def from_nav(self, pos: QPointF) -> QPointF:
        q = QPointF((pos.x() - self.BORDER) / self._k, (pos.y() - self.BORDER) / self._k) + self._br.topLeft()
        return self.view._orient().inverted()[0].map(q)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        p.setBrush(QColor(10, 12, 14, 200))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.setOpacity(0.75)
        p.drawPixmap(self.BORDER, self.BORDER, self._thumb)
        p.setOpacity(1.0)
        vis = self.view.mapToScene(self.view.viewport().rect())
        poly = QPolygonF([self.to_nav(vis.at(i)) for i in range(vis.count())])
        p.setPen(QPen(QColor(255, 214, 10), 1.6))
        p.setBrush(QColor(255, 214, 10, 40))
        p.drawPolygon(poly)
        p.end()

    def mousePressEvent(self, e):
        self.view.centerOn(self.from_nav(e.position()))

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.view.centerOn(self.from_nav(e.position()))

    def wheelEvent(self, e):
        e.ignore()          # the viewport zooms (with the position mapped to it)


class ImageView(QGraphicsView):
    discPicked = Signal(float, float)
    zoomChanged = Signal(float)
    measured = Signal(str)       # result of a measurement
    hovered = Signal(str)        # pixel / retinal position under the cursor
    clicked = Signal()           # any left press (multi-view selection, slideshow stop)
    activated = Signal()         # double click

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setBackgroundBrush(QBrush(QColor("#111316")))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMouseTracking(True)
        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._pix)
        self._circle = QGraphicsEllipseItem()
        self._circle.setPen(QPen(QColor(80, 200, 255, 160), 0, Qt.PenStyle.DashLine))
        self._circle.setVisible(False)
        self._circle.setZValue(5)
        self.scene().addItem(self._circle)
        self._disc = QGraphicsEllipseItem()
        self._disc.setPen(QPen(QColor(255, 220, 60, 220), 0))
        self._disc.setVisible(False)
        self._disc.setZValue(5)
        self.scene().addItem(self._disc)
        self.show_overlays = False
        self.show_captions = False
        self._captions = ("", "", "", "")
        self._circle_px = None
        self._disc_px = None
        self._rgb: np.ndarray | None = None
        self.geometry: measure.Geometry | None = None
        # view state
        self._zoom, self._rot, self._fh, self._fv, self._fit = 1.0, 0, False, False, True
        # tools
        self.tool = "pan"
        self._drag: dict | None = None
        self._annots: list[list[QGraphicsItem]] = []   # one entry per finished annotation
        self._labels: list[QGraphicsSimpleTextItem] = []
        self._work: list[QGraphicsItem] = []           # in-progress items
        self._pts: list[QPointF] = []
        self._cd: dict = {}
        self._rubber: QGraphicsLineItem | None = None
        self._profile: list[QGraphicsItem] = []
        self._loupe = QLabel(self.viewport())
        self._loupe.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._loupe.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._loupe.setStyleSheet("background: transparent; border: none;")
        self._loupe.hide()
        self.loupe_mag, self.loupe_size = 3.0, 260
        self.show_navigator = True
        self._nav = _Navigator(self)

    # =====================================================================
    # image
    # =====================================================================
    def has_image(self) -> bool:
        return not self._pix.pixmap().isNull()

    def set_rgb(self, rgb: np.ndarray | None, *, keep_view: bool = False) -> None:
        if not keep_view:
            self.clear_annotations()
            self._rot, self._fh, self._fv = 0, False, False
        self._rgb = rgb
        if rgb is None:
            self._pix.setPixmap(QPixmap())
            self._circle.setVisible(False)
            self._disc.setVisible(False)
            self._update_navigator()
            return
        self._pix.setPixmap(QPixmap.fromImage(to_qimage(rgb)))
        self.scene().setSceneRect(QRectF(self._pix.pixmap().rect()))
        if not keep_view:
            self.fit()
        self._update_navigator()

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

    # -- VK-2 style on-screen captions (green text in the corners) ------------
    def set_captions(self, top_left: str = "", top_right: str = "", bottom_left: str = "",
                     bottom_right: str = "") -> None:
        self._captions = (top_left, top_right, bottom_left, bottom_right)
        self.viewport().update()

    def toggle_captions(self, on: bool) -> None:
        self.show_captions = on
        self.viewport().update()
        self._update_navigator()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not (self.show_captions and any(self._captions) and self.has_image()):
            return
        p = QPainter(self.viewport())
        f = QFont(self.font())
        f.setPixelSize(max(13, min(22, self.viewport().height() // 32)))
        f.setBold(True)
        p.setFont(f)
        r = self.viewport().rect().adjusted(10, 6, -10, -6)
        flags = (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        for text, flag in zip(self._captions, flags):
            if not text:
                continue
            p.setPen(QColor(0, 0, 0, 200))       # shadow keeps it legible on bright retina
            p.drawText(r.translated(1, 1), int(flag), text)
            p.setPen(CAPTION)
            p.drawText(r, int(flag), text)
        p.end()

    @property
    def _side(self) -> float:
        pm = self._pix.pixmap()
        return float(max(pm.width(), pm.height(), 1))

    # =====================================================================
    # view transform: zoom · flips · rotation
    # =====================================================================
    def _orient(self) -> QTransform:
        t = QTransform()
        t.scale(-1 if self._fh else 1, -1 if self._fv else 1)  # screen-space flips ...
        t.rotate(self._rot)                                    # ... after the rotation
        return t

    def _apply(self) -> None:
        t = QTransform()
        t.scale(self._zoom * (-1 if self._fh else 1), self._zoom * (-1 if self._fv else 1))
        t.rotate(self._rot)
        self.setTransform(t)
        inv = self._orient().inverted()[0]
        for lab in self._labels:  # keep text upright and unmirrored
            lab.setTransform(inv)
        self._update_navigator()

    # -- mini-map -------------------------------------------------------------------
    def zoomed_in(self) -> bool:
        """True while part of the photo is outside the view."""
        if not self.has_image():
            return False
        vis = self.mapToScene(self.viewport().rect()).boundingRect().adjusted(-1, -1, 1, 1)
        return not vis.contains(QRectF(self._pix.pixmap().rect()))

    def set_navigator(self, on: bool) -> None:
        self.show_navigator = on
        self._update_navigator()

    def _update_navigator(self) -> None:
        nav = getattr(self, "_nav", None)         # scrolling can start before __init__ ends
        if nav is None:
            return
        vw, vh = self.viewport().width(), self.viewport().height()
        side = int(min(170, 0.3 * min(vw, vh)))
        if not (self.show_navigator and side >= 60 and self.zoomed_in()):
            nav.hide()
            return
        nav.rebuild(side)
        top = 44 if self.show_captions else 10            # below the top-right caption
        nav.move(vw - nav.width() - 10, top)
        nav.show()
        nav.update()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._update_navigator()

    def zoom_to_rect(self, rect: QRectF) -> None:
        """Zoom so ``rect`` (image pixels) fills the view, centred on it."""
        if not self.has_image() or rect.width() <= 0 or rect.height() <= 0:
            return
        br = self._orient().mapRect(rect)
        vw, vh = max(self.viewport().width(), 1), max(self.viewport().height(), 1)
        self._zoom, self._fit = max(0.02, min(40.0, min(vw / br.width(), vh / br.height()) * 0.97)), False
        self._apply()
        self.centerOn(rect.center())
        self.zoomChanged.emit(self._zoom)

    @property
    def zoom(self) -> float:
        return self._zoom

    def fit(self) -> None:
        if not self.has_image():
            return
        br = self._orient().mapRect(QRectF(self._pix.pixmap().rect()))
        vw, vh = max(self.viewport().width(), 1), max(self.viewport().height(), 1)
        self._zoom = max(1e-3, min(vw / br.width(), vh / br.height()) * 0.98)
        self._apply()
        self.centerOn(self._pix)
        self._fit = True
        self.zoomChanged.emit(self._zoom)

    def zoom_to(self, factor: float, vpos: QPoint | None = None) -> None:
        self._zoom_at(factor, vpos if vpos is not None else self.viewport().rect().center())

    def _zoom_at(self, z: float, vpos: QPoint) -> None:
        if not self.has_image():
            return
        z = max(0.02, min(40.0, z))
        sp = self.mapToScene(vpos)
        self._zoom, self._fit = z, False
        self._apply()
        d = self.mapFromScene(sp) - vpos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + d.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + d.y())
        self.zoomChanged.emit(z)

    def rotate90(self, clockwise: bool = True) -> None:
        self._rot = (self._rot + (90 if clockwise else -90)) % 360
        self.fit() if self._fit else self._apply()

    def flip(self, horizontal: bool) -> None:
        if horizontal:
            self._fh = not self._fh
        else:
            self._fv = not self._fv
        self.fit() if self._fit else self._apply()

    def reset_orientation(self) -> None:
        self._rot, self._fh, self._fv = 0, False, False
        self.fit()

    def sync_from(self, other: "ImageView") -> None:
        """Copy zoom / orientation / scroll from ``other`` (compare views)."""
        self._zoom, self._rot, self._fh, self._fv, self._fit = (other._zoom, other._rot, other._fh,
                                                                 other._fv, other._fit)
        self._apply()
        self.horizontalScrollBar().setValue(other.horizontalScrollBar().value())
        self.verticalScrollBar().setValue(other.verticalScrollBar().value())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()
        self._update_navigator()

    # =====================================================================
    # tools
    # =====================================================================
    def set_tool(self, tool: str) -> None:
        self._cancel_work()
        self.tool = tool if tool in TOOLS else "pan"
        self._restore_cursor()

    def _restore_cursor(self) -> None:
        cursors = {"pan": Qt.CursorShape.OpenHandCursor, "zoom": Qt.CursorShape.SizeVerCursor,
                   "loupe": Qt.CursorShape.CrossCursor, "text": Qt.CursorShape.IBeamCursor}
        self.viewport().setCursor(cursors.get(self.tool, Qt.CursorShape.CrossCursor))

    def _pen(self, color: QColor = YELLOW) -> QPen:
        pen = QPen(color, max(2.0, self._side / 700))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def _label(self, text: str, pos: QPointF, color: QColor = YELLOW) -> QGraphicsSimpleTextItem:
        lab = QGraphicsSimpleTextItem(text)
        f = QFont()
        f.setPixelSize(int(max(14, min(140, self._side / 55))))
        f.setBold(True)
        lab.setFont(f)
        lab.setBrush(QBrush(color))
        outline = QPen(QColor(0, 0, 0, 220), max(1.0, f.pixelSize() / 14))
        lab.setPen(outline)
        lab.setPos(pos)
        lab.setZValue(20)
        lab.setTransform(self._orient().inverted()[0])
        self.scene().addItem(lab)
        self._labels.append(lab)
        return lab

    def _add(self, item: QGraphicsItem) -> QGraphicsItem:
        item.setZValue(15)
        self.scene().addItem(item)
        return item

    def _finish(self, items: list[QGraphicsItem], text: str | None = None) -> None:
        self._annots.append(items)
        self._work = []
        if text:
            self.measured.emit(text)

    def _cancel_work(self) -> None:
        for it in self._work + ([self._rubber] if self._rubber else []):
            if it.scene():
                self.scene().removeItem(it)
            if it in self._labels:
                self._labels.remove(it)
        self._work, self._pts, self._cd, self._rubber = [], [], {}, None

    def undo_annotation(self) -> None:
        if self._work:
            self._cancel_work()
            return
        if self._annots:
            for it in self._annots.pop():
                if it.scene():
                    self.scene().removeItem(it)
                if it in self._labels:
                    self._labels.remove(it)

    def clear_annotations(self) -> None:
        self._cancel_work()
        while self._annots:
            self.undo_annotation()

    @property
    def annotation_count(self) -> int:
        return len(self._annots)

    def _length_text(self, a: QPointF, b: QPointF) -> str:
        return measure.describe_length((a.x(), a.y()), (b.x(), b.y()), self.geometry)

    def _arrow_head(self, a: QPointF, b: QPointF, color: QColor) -> QGraphicsPolygonItem:
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = max(10.0, self._side / 90)
        p1 = QPointF(b.x() - size * math.cos(ang - 0.45), b.y() - size * math.sin(ang - 0.45))
        p2 = QPointF(b.x() - size * math.cos(ang + 0.45), b.y() - size * math.sin(ang + 0.45))
        head = QGraphicsPolygonItem(QPolygonF([b, p1, p2]))
        head.setBrush(QBrush(color))
        head.setPen(self._pen(color))
        return self._add(head)

    def _ask_text(self, title: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, "글자:")
        return text.strip() if ok and text.strip() else None

    # -- loupe / profile -------------------------------------------------------------
    def _show_loupe(self, vpos: QPoint) -> None:
        size, mag = self.loupe_size, self.loupe_mag
        sp = self.mapToScene(vpos)
        half = size / 2.0 / (self._zoom * mag)
        src = QRectF(sp.x() - half, sp.y() - half, 2 * half, 2 * half)
        pm = self._pix.pixmap()
        piece = QPixmap(max(1, int(src.width())), max(1, int(src.height())))
        piece.fill(QColor("#111316"))
        p = QPainter(piece)
        p.drawPixmap(QRectF(0, 0, src.width(), src.height()), pm, src)
        p.end()
        piece = piece.transformed(self._orient(), Qt.TransformationMode.SmoothTransformation)
        piece = piece.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(1, 1, size - 2, size - 2)
        p.setClipPath(path)
        p.drawPixmap(0, 0, piece)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 200), 2))
        p.drawEllipse(1, 1, size - 2, size - 2)
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        c = size / 2
        p.drawLine(QPointF(c - 8, c), QPointF(c + 8, c))
        p.drawLine(QPointF(c, c - 8), QPointF(c, c + 8))
        p.end()
        self._loupe.setPixmap(out)
        self._loupe.resize(size, size)
        self._loupe.move(vpos.x() - size // 2, vpos.y() - size // 2)
        self._loupe.show()

    def _show_profile(self, sp: QPointF) -> None:
        for it in self._profile:
            self.scene().removeItem(it)
        self._profile = []
        if self._rgb is None:
            return
        h, w = self._rgb.shape[:2]
        y = int(min(max(sp.y(), 0), h - 1))
        row = self._rgb[y].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
        step = max(1, w // 1500)
        amp = h * 0.22
        path = QPainterPath(QPointF(0, y - row[0] / 255 * amp))
        for x in range(step, w, step):
            path.lineTo(QPointF(x, y - row[x] / 255 * amp))
        base = QGraphicsLineItem(QLineF(0, y, w, y))
        pen = QPen(QColor(110, 215, 255, 180), 0)
        base.setPen(pen)
        curve = QGraphicsPathItem(path)
        cpen = QPen(YELLOW, 0)
        curve.setPen(cpen)
        for it in (base, curve):
            it.setZValue(25)
            self.scene().addItem(it)
        self._profile = [base, curve]
        x = int(min(max(sp.x(), 0), w - 1))
        self.measured.emit(f"회색조: 줄 y={y} · x={x} 밝기 {row[x]:.0f} / 255 (줄 평균 {row.mean():.0f})")

    # =====================================================================
    # mouse
    # =====================================================================
    def wheelEvent(self, e):
        if not self.has_image():
            return
        steps = e.angleDelta().y() / 120.0
        if self._drag and self._drag.get("kind") == "loupe":
            self.loupe_mag = max(1.5, min(10.0, self.loupe_mag * (1.15 ** steps)))
            self._show_loupe(e.position().toPoint())
            return
        self._zoom_at(self._zoom * (1.15 ** steps), e.position().toPoint())

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        btn = e.button()
        if btn == Qt.MouseButton.RightButton:
            self._drag = {"kind": "rzoom", "start": pos, "z0": self._zoom, "moved": False}
            return
        if btn == Qt.MouseButton.MiddleButton:
            self._drag = {"kind": "pan", "last": pos}
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if btn != Qt.MouseButton.LeftButton or not self.has_image():
            return super().mousePressEvent(e)
        self.clicked.emit()
        sp = self.mapToScene(pos)
        t = self.tool
        if t == "pan":
            self._drag = {"kind": "pan", "last": pos}
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        elif t == "zoom":
            self._drag = {"kind": "zoom", "start": pos, "z0": self._zoom, "moved": False,
                          "shift": bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)}
        elif t == "loupe":
            self._drag = {"kind": "loupe"}
            self._show_loupe(pos)
        elif t == "profile":
            self._drag = {"kind": "profile"}
            self._show_profile(sp)
        elif t in ("length", "arrow", "cd_length"):
            color = CYAN if (t == "cd_length" and not self._cd.get("cup")) else YELLOW
            line = QGraphicsLineItem(QLineF(sp, sp))
            line.setPen(self._pen(color))
            self._add(line)
            self._work.append(line)
            self._drag = {"kind": "line", "a": sp, "item": line, "color": color}
        elif t == "angle":
            self._angle_click(sp)
        elif t == "cd_area":
            self._poly_click(sp)
        elif t == "text":
            text = self._ask_text("글자 입력")
            if text:
                self._finish([self._label(text, sp)])

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        sp = self.mapToScene(pos)
        d = self._drag
        if d is None:
            self._hover(sp)
            if self._rubber is not None and self._pts:
                self._rubber.setLine(QLineF(self._pts[-1], sp))
            return super().mouseMoveEvent(e)
        kind = d["kind"]
        if kind in ("rzoom", "zoom"):
            dy = pos.y() - d["start"].y()
            if abs(dy) > 3:
                d["moved"] = True
            if d["moved"]:
                self._zoom_at(d["z0"] * math.exp(-dy / 150.0), d["start"])
        elif kind == "pan":
            delta = pos - d["last"]
            d["last"] = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        elif kind == "loupe":
            self._show_loupe(pos)
        elif kind == "profile":
            self._show_profile(sp)
        elif kind == "line":
            d["item"].setLine(QLineF(d["a"], sp))
            if self.tool == "length":
                self.measured.emit(self._length_text(d["a"], sp))

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        pos = e.position().toPoint()
        if d and d["kind"] == "pan":
            self._restore_cursor()
        if d is None:
            return super().mouseReleaseEvent(e)
        kind = d["kind"]
        sp = self.mapToScene(pos)
        if kind == "rzoom" and not d["moved"]:
            self._context_menu(e.globalPosition().toPoint(), sp)
        elif kind == "zoom" and not d["moved"]:
            self._zoom_at(self._zoom * (0.5 if d["shift"] else 2.0), d["start"])
        elif kind == "loupe":
            self._loupe.hide()
        elif kind == "profile":
            for it in self._profile:
                self.scene().removeItem(it)
            self._profile = []
        elif kind == "line":
            self._line_done(d["a"], sp, d["item"], d["color"])
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if self.tool == "cd_area" and len(self._pts) >= 3:
            self._close_polygon()
            return
        if self.tool in ("angle", "cd_area", "length", "arrow", "cd_length", "text"):
            return
        self.fit()
        self.activated.emit()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._cancel_work()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tool == "cd_area" and len(self._pts) >= 3:
            self._close_polygon()
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.undo_annotation()
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            at = self.viewport().mapFromGlobal(QCursor.pos())
            if not self.viewport().rect().contains(at):
                at = self.viewport().rect().center()
            self._zoom_at(self._zoom * (1.25 if k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) else 0.8), at)
        elif k == Qt.Key.Key_0:
            self.fit()
        elif k == Qt.Key.Key_1:
            self.zoom_to(1.0)
        else:
            super().keyPressEvent(e)

    def _hover(self, sp: QPointF) -> None:
        if self._rgb is None:
            return
        h, w = self._rgb.shape[:2]
        x, y = int(sp.x()), int(sp.y())
        if not (0 <= x < w and 0 <= y < h):
            return
        r, g, b = (int(v) for v in self._rgb[y, x][:3])
        txt = f"x {x}, y {y} · RGB {r},{g},{b}"
        if self.geometry is not None:
            p = self.geometry.to_sphere(sp.x(), sp.y())
            if p is not None:
                txt += f" · 후극에서 {math.degrees(math.acos(max(-1.0, min(1.0, -p[2])))):.1f}°"
        self.hovered.emit(txt)

    # -- measurement completion ------------------------------------------------------
    def _line_done(self, a: QPointF, b: QPointF, item: QGraphicsLineItem, color: QColor) -> None:
        if QLineF(a, b).length() * self._zoom < 4:  # a click, not a drag
            self._work.remove(item)
            self.scene().removeItem(item)
            return
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        if self.tool == "length":
            text = self._length_text(a, b)
            self._finish([item, self._label(text, mid)], f"길이: {text}")
        elif self.tool == "arrow":
            head = self._arrow_head(a, b, color)
            text = self._ask_text("화살표 글자")
            items = [item, head] + ([self._label(text, a)] if text else [])
            self._finish(items)
        elif self.tool == "cd_length":
            if "cup" not in self._cd:
                self._cd["cup"] = (QLineF(a, b).length(), item)
                self.measured.emit("cup 지름 표시됨 — 이제 disc 지름을 드래그하세요")
                return
            cup_len, cup_item = self._cd.pop("cup")
            ratio = cup_len / max(QLineF(a, b).length(), 1e-6)
            text = f"C/D (길이) = {ratio:.2f}"
            self._finish([cup_item, item, self._label(text, b)], text)

    def _angle_click(self, sp: QPointF) -> None:
        self._pts.append(sp)
        dot = QGraphicsEllipseItem(sp.x() - 3, sp.y() - 3, 6, 6)
        dot.setPen(self._pen())
        self._work.append(self._add(dot))
        if len(self._pts) >= 2:
            seg = QGraphicsLineItem(QLineF(self._pts[-2], self._pts[-1]))
            seg.setPen(self._pen())
            self._work.append(self._add(seg))
        if self._rubber is None:
            self._rubber = QGraphicsLineItem()
            pen = self._pen()
            pen.setStyle(Qt.PenStyle.DashLine)
            self._rubber.setPen(pen)
            self._add(self._rubber)
        if len(self._pts) == 3:
            a, v, c = self._pts
            deg = measure.angle_deg((a.x(), a.y()), (v.x(), v.y()), (c.x(), c.y()))
            text = f"각도 {deg:.1f}°"
            items = self._work + [self._label(text, v)]
            self.scene().removeItem(self._rubber)
            self._rubber, self._pts = None, []
            self._finish(items, text)

    def _poly_click(self, sp: QPointF) -> None:
        stage = "disc" if "cup" in self._cd else "cup"
        color = CYAN if stage == "cup" else YELLOW
        self._pts.append(sp)
        tmp = self._cd.setdefault("tmp", [])
        dot = QGraphicsEllipseItem(sp.x() - 3, sp.y() - 3, 6, 6)
        dot.setPen(self._pen(color))
        tmp.append(self._add(dot))
        if len(self._pts) >= 2:
            seg = QGraphicsLineItem(QLineF(self._pts[-2], self._pts[-1]))
            seg.setPen(self._pen(color))
            tmp.append(self._add(seg))
        self._work = [it for it in self._work if it not in tmp] + tmp
        if self._rubber is None:
            self._rubber = QGraphicsLineItem()
            pen = self._pen(color)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._rubber.setPen(pen)
            self._add(self._rubber)
        if len(self._pts) >= 12:
            self._close_polygon()

    def _close_polygon(self) -> None:
        stage = "disc" if "cup" in self._cd else "cup"
        color = CYAN if stage == "cup" else YELLOW
        pts = [(p.x(), p.y()) for p in self._pts]
        for it in self._cd.pop("tmp", []):  # this polygon's vertex dots / edges
            self.scene().removeItem(it)
            if it in self._work:
                self._work.remove(it)
        if self._rubber is not None:
            self.scene().removeItem(self._rubber)
        poly = QGraphicsPolygonItem(QPolygonF(self._pts))
        poly.setPen(self._pen(color))
        fill = QColor(color)
        fill.setAlpha(40)
        poly.setBrush(QBrush(fill))
        self._add(poly)
        self._pts, self._rubber = [], None
        area = measure.polygon_area(pts)
        if stage == "cup":
            self._cd["cup"] = (area, poly)
            self.measured.emit(f"cup 면적 {area:.0f} px² — 이제 disc 둘레를 클릭하세요")
            self._work.append(poly)
            return
        cup_area, cup_poly = self._cd.pop("cup")
        ratio = cup_area / max(area, 1e-6)
        text = f"C/D (면적) = {ratio:.2f}  (지름 환산 {math.sqrt(ratio):.2f})"
        top = min(pts, key=lambda p: p[1])
        self._finish([cup_poly, poly, self._label(text, QPointF(*top))], text)

    # -- menu ----------------------------------------------------------------------------
    def _context_menu(self, gpos: QPoint, sp: QPointF) -> None:
        if not self.has_image():
            return
        menu = QMenu(self)
        act = QAction("여기를 시신경 유두로 지정 (3D 시신경 위치)", menu)
        act.triggered.connect(lambda: self.discPicked.emit(sp.x(), sp.y()))
        menu.addAction(act)
        menu.addSeparator()
        for label, fn in (("화면에 맞춤", self.fit), ("100% 크기", lambda: self.zoom_to(1.0)),
                          ("마지막 측정 지우기", self.undo_annotation), ("측정·글자 모두 지우기", self.clear_annotations)):
            a = QAction(label, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        nav = QAction("미니맵 표시 (확대했을 때)", menu, checkable=True)
        nav.setChecked(self.show_navigator)
        nav.triggered.connect(self.set_navigator)
        menu.addAction(nav)
        sub = menu.addMenu("돋보기 배율")
        for m in (2, 3, 4, 6, 8):
            a = QAction(f"{m}배", sub, checkable=True)
            a.setChecked(abs(self.loupe_mag - m) < 0.01)
            a.triggered.connect(lambda _=False, m=m: setattr(self, "loupe_mag", float(m)))
            sub.addAction(a)
        menu.exec(gpos)

    # =====================================================================
    # export
    # =====================================================================
    def render_image(self) -> QImage:
        """The displayed (adjusted, oriented) image with its annotations, at full resolution."""
        pm = self._pix.pixmap()
        rect = QRectF(pm.rect())
        o = self._orient()
        br = o.mapRect(rect)
        img = QImage(int(round(br.width())), int(round(br.height())), QImage.Format.Format_RGB888)
        img.fill(QColor(0, 0, 0))
        p = QPainter(img)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.setTransform(o * QTransform.fromTranslate(-br.left(), -br.top()))
        self.scene().render(p, rect, rect)
        p.end()
        return img
