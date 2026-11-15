"""Thumbnail strip painting: the eye (OD / OS) on every photo and the multi-view picks.

VK-2 lists the photos newest first and shows which eye each one is. Here every thumbnail gets
a coloured eye badge in its top-left corner (OD blue · OS orange · OU purple · 미상 grey), and
the photos picked for the multi view (plain click) get a yellow frame with their pick number.

``ThumbStrip`` lays the photos out by eye: OD photos in the top row, OS photos in the row under
it, and anything else (OU) in a third row only when there is any; the rows scroll sideways
together. Or all of them in one line. (The main window leaves 미상 photos out of the list.)
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPixmapCache
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListWidget, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

EYE_ROLE = Qt.ItemDataRole.UserRole + 2     # laterality of the photo ("OD" / "OS" / "OU" / "")
PICK_ROLE = Qt.ItemDataRole.UserRole + 3    # pick order for the multi view (0 = not picked)

PICK_COLOR = "#facc15"
_EYES = {"OD": ("OD", "#5aa9ff", "#04192f"), "OS": ("OS", "#f5a524", "#2a1700"),
         "OU": ("OU", "#b18cff", "#1b0f3a")}


def eye_row(laterality: str | None) -> int:
    """The row of a photo in the strip by eye: OD 0 (top), OS 1 (under it), OU / 미상 2."""
    return {"OD": 0, "OS": 1}.get(laterality or "", 2)


def eye_badge(laterality: str | None) -> tuple[str, str, str]:
    """(text, background, text colour) of the eye badge; unknown eye = grey 미상."""
    return _EYES.get(laterality or "", ("미상", "#4b5563", "#e5e7eb"))


def thumb_pixmap(path: str | None, side: int = 0) -> QPixmap:
    """The stored thumbnail of a photo (``images.thumb_path``), scaled to fit ``side`` pixels when
    given — read once and kept (the patient list and the 검토 timeline show the same photos)."""
    if not path:
        return QPixmap()
    key = f"fundusthumb:{side}:{path}"
    pm = QPixmap()
    if QPixmapCache.find(key, pm):
        return pm
    pm = QPixmap(path)
    if side and not pm.isNull():
        pm = pm.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not pm.isNull():
        QPixmapCache.insert(key, pm)
    return pm


def paint_eye_badge(painter: QPainter, laterality: str | None, x: float, y: float, px: int = 11) -> QRectF:
    """The coloured eye badge (OD / OS / OU / 미상) with its top-left corner at (x, y)."""
    text, bg, fg = eye_badge(laterality)
    f = QFont(painter.font())
    f.setBold(True)
    f.setPixelSize(px)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setFont(f)
    fm = painter.fontMetrics()
    rect = QRectF(x, y, fm.horizontalAdvance(text) + 10, fm.height() + 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(bg))
    painter.drawRoundedRect(rect, 4, 4)
    painter.setPen(QColor(fg))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return rect


def eye_badge_html(laterality: str | None) -> str:
    text, bg, fg = eye_badge(laterality)
    return f"<span style='background:{bg}; color:{fg}; font-weight:700'>&nbsp;{text}&nbsp;</span>"


class ThumbDelegate(QStyledItemDelegate):
    """Default icon + caption, then the eye badge and the pick frame / number on the photo."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        deco = style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, opt, opt.widget)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        size = icon.actualSize(deco.size()) if isinstance(icon, QIcon) and not icon.isNull() else QSize()
        if size.isEmpty():
            photo = QRect(deco)
        else:                                  # the photo itself, centred in the icon cell
            photo = QRect(0, 0, size.width(), size.height())
            photo.moveCenter(deco.center())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(opt.font)
        f.setBold(True)
        f.setPixelSize(13)
        painter.setFont(f)
        fm = painter.fontMetrics()
        text, bg, fg = eye_badge(index.data(EYE_ROLE))
        badge = QRectF(photo.left() + 3, photo.top() + 3, fm.horizontalAdvance(text) + 12, fm.height() + 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor(fg))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        rank = int(index.data(PICK_ROLE) or 0)
        if rank:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(PICK_COLOR), 3))
            painter.drawRect(QRectF(photo).adjusted(1.5, 1.5, -1.5, -1.5))
            d = fm.height() + 6
            dot = QRectF(photo.right() - d - 2, photo.top() + 3, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PICK_COLOR))
            painter.drawEllipse(dot)
            painter.setPen(QColor("#111827"))
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, str(rank))
        painter.restore()


class ThumbStrip(QListWidget):
    """The photo list under the views: by eye (OD row on top, OS row under it, any other in a
    third row when there is one) or all photos in one line.

    One list keeps one order for 이전 / 다음, the n/N on the photo and the multi view: the caller
    adds the photos OD first, then OS, then the rest, so reading the rows left to right, top to
    bottom is that order. Qt lays the items out in one line and ``doItemsLayout`` then moves each
    to its eye's row (``setPositionForIndex`` needs a non-static movement; dragging stays off).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self._by_eye = False
        self._slots: list[tuple[int, int]] = []     # (row, column) of every item, by eye
        self._shape = (1, 0)                         # rows and columns of the by-eye grid

    def set_by_eye(self, on: bool) -> None:
        self._by_eye = bool(on)
        self.setMovement(QListWidget.Movement.Free if on else QListWidget.Movement.Static)
        self.setDragEnabled(False)                   # (setMovement switches dragging on)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.viewport().setAcceptDrops(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.doItemsLayout()

    def grid_shape(self) -> tuple[int, int]:
        """(rows, columns) the photos take: by eye one row per eye present, else one line."""
        return self._eye_slots()[1] if self._by_eye else (1, self.count())

    def _eye_slots(self) -> tuple[list[tuple[int, int]], tuple[int, int]]:
        eyes = [eye_row(self.item(i).data(EYE_ROLE)) for i in range(self.count())]
        line = {e: k for k, e in enumerate(sorted(set(eyes)))}     # no OD photo: OS is the top row
        cols = [0] * max(1, len(line))
        slots = []
        for e in eyes:
            k = line[e]
            slots.append((k, cols[k]))
            cols[k] += 1
        return slots, (max(1, len(line)), max(cols))

    def doItemsLayout(self) -> None:
        if self._by_eye:
            self._slots, self._shape = self._eye_slots()
        super().doItemsLayout()
        if not self._by_eye or not self._slots:
            return
        gw, gh = self.gridSize().width(), self.gridSize().height()
        model = self.model()
        for i, (row, col) in enumerate(self._slots):
            index = model.index(i, 0)
            dx = max(0, (gw - self.rectForIndex(index).width()) // 2)    # centred in its cell, as Qt does
            self.setPositionForIndex(QPoint(col * gw + dx, row * gh), index)
        self.updateGeometries()

    def updateGeometries(self) -> None:
        super().updateGeometries()
        if not self._by_eye or not self.count():
            return
        # Qt still counts the one line it laid out first: the scroll range is that of the eye rows
        rows, cols = self._shape
        vp = self.viewport()
        h = self.horizontalScrollBar()
        h.setPageStep(vp.width())
        h.setRange(0, max(0, cols * self.gridSize().width() - vp.width()))
        self.verticalScrollBar().setRange(0, 0)     # the strip is as high as its rows: the wheel goes sideways
