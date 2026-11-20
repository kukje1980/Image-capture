"""The photo list under the views: what is painted on a photo, the rows by eye and their names.

VK-2 lists the photos newest first and shows which eye each one is. Here the photo fills its cell
(no lines of caption under it: the height goes to the photos above) and what is said about it lies
on the photo — the exam date at its top left, and, as options (보기 → 사진 목록 표시), the kind of
photo (컬러 · 몽타주 …) at its bottom left. A photo shown above gets a yellow frame — on Multi with
its pick number —, the second picked photo ②.

``ThumbStrip`` lays the photos out by eye: OD photos in the top row, OS photos in the row under
it, and anything else (OU) in a third row only when there is any; the rows scroll sideways
together. The eye is said once per row, at the left of the rows (``EyeRail``), not on every
photo. Or all photos in one line — then each has its eye badge (OD blue · OS orange · OU purple ·
미상 grey). (The main window leaves 미상 photos out of the list.)

미리 보기 (the Dock of a Mac): the photos of the row under the mouse grow toward the mouse — the one
under it most, those beside it less and less — and move apart for it (``ThumbStrip.set_dock``). The
row is then painted by ``DockOverlay``, which lies over the strip and the room above it (the photos
grow upwards from the bottom of their row), not by the list.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPixmapCache
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListWidget, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QWidget)

EYE_ROLE = Qt.ItemDataRole.UserRole + 2     # laterality of the photo ("OD" / "OS" / "OU" / "")
PICK_ROLE = Qt.ItemDataRole.UserRole + 3    # shown above: its pick number on Multi (1 …), SHOWN on Simple; 0 = not
DATE_ROLE = Qt.ItemDataRole.UserRole + 4    # the exam date, as written on the photo
KIND_ROLE = Qt.ItemDataRole.UserRole + 5    # the kind of photo (컬러 · 몽타주 …)
SECOND_ROLE = Qt.ItemDataRole.UserRole + 6  # True: the second picked photo (②)

SHOWN = -1                                  # PICK_ROLE of a photo of Simple: framed, no number
PICK_COLOR = "#facc15"
SECOND_COLOR = "#a8681c"                    # the second picked photo (②)
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
    """The photo as large as its cell, and on it: the date (top left), the kind of photo (bottom
    left), the frame of a photo shown above with its pick number, ② of the second photo (bottom
    right) — and the eye badge (bottom left, before the kind) where the strip is one line."""

    PAD = 3                                 # around the photo: the cell's own colour (selected: the accent)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show_date = True               # 보기 → 사진 목록 표시 → 날짜
        self.show_kind = False              # … → 종류 (컬러 · 몽타주 …)
        self.show_eye = False               # one line: the eye on every photo (by eye the row says it)
        self.docking = False                # True while the DockOverlay paints a grown photo with this

    def photo_rect(self, option, index) -> QRect:
        """Where the photo is painted: as large as fits the cell, centred."""
        area = option.rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        size = self._photo_size(icon)
        if size.isEmpty():
            return QRect(area)
        size = size.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)   # (a grown cell: larger than stored)
        photo = QRect(0, 0, size.width(), size.height())
        photo.moveCenter(area.center())
        return photo

    CORNER = 0.16                           # the photo's corners: round by this much of its shorter side

    @classmethod
    def corner(cls, photo: QRect) -> float:
        return cls.CORNER * min(photo.width(), photo.height())

    @staticmethod
    def _photo_size(icon) -> QSize:
        """The size of the stored photo of an item (empty: none)."""
        if not isinstance(icon, QIcon) or icon.isNull():
            return QSize()
        sizes = icon.availableSizes()
        return sizes[0] if sizes else QSize()

    @staticmethod
    def _chip(painter: QPainter, text: str, x: float, y: float, *, bottom: bool = False,
              bg: QColor | None = None, fg: QColor | None = None) -> QRectF:
        """A few letters on a dark, see-through chip with its left top (``bottom``: left bottom)
        corner at (x, y) — legible on any photo."""
        fm = painter.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 6, fm.height() + 1
        rect = QRectF(x, y - h if bottom else y, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg or QColor(0, 0, 0, 165))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(fg or QColor("#f2f2f7"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        return rect

    def paint(self, painter: QPainter, option, index) -> None:
        strip = option.widget
        if not self.docking and isinstance(strip, ThumbStrip) and strip.docked(index.row()):
            return                           # 미리 보기: its row is painted by the DockOverlay, grown
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        opt.icon, opt.text = QIcon(), ""    # the style paints the cell only (hover · selected)
        opt.features &= ~(QStyleOptionViewItem.ViewItemFeature.HasDecoration
                          | QStyleOptionViewItem.ViewItemFeature.HasDisplay)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        opt.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)   # (round, below)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        photo = self.photo_rect(option, index)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if selected or hover:                # the cell's colour around the photo, round as the photo
            glow = QColor(opt.palette.color(opt.palette.ColorRole.Highlight))
            glow.setAlpha(255 if selected else 90)
            r = self.corner(photo) + self.PAD
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(QRectF(photo).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD), r, r)
        rr = self.corner(photo)              # the photo's corners are round (as the icons of the Dock)
        if isinstance(icon, QIcon) and not icon.isNull():
            shape = QPainterPath()
            shape.addRoundedRect(QRectF(photo), rr, rr)
            painter.setClipPath(shape, Qt.ClipOperation.IntersectClip)
            size = self._photo_size(icon)
            if size.width() >= photo.width():
                icon.paint(painter, photo)
            else:                            # grown past the stored photo: stretched to its place
                painter.drawPixmap(photo, icon.pixmap(size))
            painter.restore()
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rank = int(index.data(PICK_ROLE) or 0)
        if rank:                             # shown above: framed; on Multi with its pick number
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(PICK_COLOR), 3))
            painter.drawRoundedRect(QRectF(photo).adjusted(1.5, 1.5, -1.5, -1.5), rr - 1.5, rr - 1.5)
        inset = 2.0 + rr * 0.3               # what is written on the photo keeps off its round corners
        f = QFont(opt.font)
        f.setBold(True)
        f.setPixelSize(10)
        painter.setFont(f)
        date, kind = index.data(DATE_ROLE) or "", index.data(KIND_ROLE) or ""
        if self.show_date and date:
            self._chip(painter, date, photo.left() + inset, photo.top() + inset)
        x = photo.left() + inset
        if self.show_eye:
            text, bg, fg = eye_badge(index.data(EYE_ROLE))
            x = self._chip(painter, text, x, photo.bottom() + 1 - inset, bottom=True, bg=QColor(bg),
                           fg=QColor(fg)).right() + 2
        if self.show_kind and kind:
            self._chip(painter, kind, x, photo.bottom() + 1 - inset, bottom=True)
        f.setPixelSize(12)
        painter.setFont(f)
        d = painter.fontMetrics().height() + 3
        x = photo.right() + 1 - inset
        for mark, bg, fg in ((str(rank) if rank > 0 else "", PICK_COLOR, "#111827"),
                             ("②" if index.data(SECOND_ROLE) else "", SECOND_COLOR, "#ffffff")):
            if not mark:
                continue
            dot = QRectF(x - d, photo.bottom() + 1 - inset - d, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawEllipse(dot)
            painter.setPen(QColor(fg))
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, mark)
            x -= d + 2
        painter.restore()


class ThumbStrip(QListWidget):
    """The photo list under the views: by eye (OD row on top, OS row under it, any other in a
    third row when there is one) or all photos in one line.

    One list keeps one order for 이전 / 다음, the n/N on the photo and the multi view: the caller
    adds the photos OD first, then OS, then the rest, so reading the rows left to right, top to
    bottom is that order. Qt lays the items out in one line and ``doItemsLayout`` then moves each
    to its place (``setPositionForIndex`` needs a non-static movement; dragging stays off).
    """
    stepped = Signal(int)                    # ← (-1) / → (+1): the photo before / after (the window steps)
    rowsChanged = Signal()                   # the rows were laid out again (``EyeRail`` names them)
    dockChanged = Signal()                   # 미리 보기: the grown row changed (``DockOverlay`` paints it)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self._by_eye = False
        self._slots: list[tuple[int, int]] = []     # (row, column) of every item
        self._shape = (1, 0)                         # rows and columns of the grid
        self._dock: tuple[int, float, float] | None = None   # 미리 보기: (row, the mouse's x, how much more)
        self._dock_rects: list | None = None
        self._free_movement()

    def _free_movement(self) -> None:
        self.setMovement(QListWidget.Movement.Free)  # (the items are placed here: doItemsLayout)
        self.setDragEnabled(False)                   # (setMovement switches dragging on)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.viewport().setAcceptDrops(False)

    def set_by_eye(self, on: bool) -> None:
        self._by_eye = bool(on)
        self._free_movement()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.doItemsLayout()

    def grid_shape(self) -> tuple[int, int]:
        """(rows, columns) the photos take: by eye one row per eye present, else one line."""
        return self._eye_slots()[1] if self._by_eye else (1, self.count())

    def row_eyes(self) -> list[str]:
        """The eye of each row, top to bottom, by eye ("OD", "OS", "OU" or "" — 미상); [] in one line."""
        if not self._by_eye:
            return []
        rows: dict[int, str] = {}
        for i in range(self.count()):
            eye = self.item(i).data(EYE_ROLE) or ""
            rows.setdefault(eye_row(eye), eye)
        return [rows[k] for k in sorted(rows)]

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            self.stepped.emit(-1 if e.key() == Qt.Key.Key_Left else 1)
            return
        super().keyPressEvent(e)

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

    # -- 미리 보기: the row under the mouse grows toward the mouse, like the Dock of a Mac -------
    DOCK_REACH = 2.2                         # the photos grow within this many cells of the mouse

    def set_dock(self, row: int | None, x: float = 0.0, grow: float = 0.0) -> None:
        """The photos of ``row`` grow toward ``x`` (viewport): the one there ``1 + grow`` times its
        size, those within ``DOCK_REACH`` cells of it less and less. None: every photo as it is."""
        dock = (int(row), float(x), max(0.0, float(grow))) if row is not None and self.count() else None
        if dock == self._dock:
            return
        self._dock = dock
        self._dock_rects = None
        self.viewport().update()
        self.dockChanged.emit()

    def cell_rect(self, i: int) -> QRect:
        """The cell of item ``i`` in the viewport, as the list lays it out (not grown)."""
        if not 0 <= i < len(self._slots):
            return QRect()
        row, col = self._slots[i]
        gw, gh = self.gridSize().width(), self.gridSize().height()
        return QRect(col * gw - self.horizontalOffset(), row * gh - self.verticalOffset(), gw, gh)

    def dock_row(self) -> int | None:
        return self._dock[0] if self._dock is not None else None

    def docked(self, i: int) -> bool:
        """Item ``i`` is in the row that is grown now (the ``DockOverlay`` paints it)."""
        return self._dock is not None and 0 <= i < len(self._slots) and self._slots[i][0] == self._dock[0]

    def row_at(self, y: int) -> int | None:
        """The row of photos at ``y`` of the viewport (None: none there)."""
        row = (y + self.verticalOffset()) // max(1, self.gridSize().height())
        return int(row) if y >= 0 and 0 <= row < self._shape[0] and self.count() else None

    def dock_rects(self) -> list[tuple[int, QRectF]]:
        """(item, where it is painted in the viewport) of every photo of the grown row, left to right.
        The place under the mouse stays under the mouse — the photos before it move left, those
        after it right — but the row never starts left of where it starts ungrown: near its start
        the photos only move right."""
        if self._dock is None:
            return []
        if self._dock_rects is not None:
            return self._dock_rects
        row, x, grow = self._dock
        gw, gh = float(self.gridSize().width()), float(self.gridSize().height())
        items = sorted((col, i) for i, (r, col) in enumerate(self._slots) if r == row)
        n = len(items)
        m = x + self.horizontalOffset()                 # the mouse, in the row's own coordinates
        reach = self.DOCK_REACH * gw

        def widths(u: float) -> list[float]:
            out = []
            for k in range(n):
                d = abs((k + 0.5) * gw - u)
                out.append(gw * (1.0 + (grow * math.cos(math.pi * d / (2 * reach)) ** 2 if d < reach else 0.0)))
            return out

        def spot(u: float, ws: list[float]) -> float:
            """Where the place ``u`` of the ungrown row lies in the grown one (the row starting at 0)."""
            if u <= 0:
                return u
            k = min(n - 1, int(u // gw))
            return sum(ws[:k]) + (u - k * gw) / gw * ws[k] if u < n * gw else sum(ws) + u - n * gw

        ws = widths(m)
        start = m - spot(m, ws)                         # the place under the mouse stays there
        if start < 0:                                   # … unless the row would start left of its start:
            lo, hi = 0.0, max(0.0, m)                   # then it starts there, and the photo the mouse is
            for _ in range(30):                         # on is the one that lies under it
                u = (lo + hi) / 2
                if spot(u, widths(u)) < m:
                    lo = u
                else:
                    hi = u
            ws, start = widths((lo + hi) / 2), 0.0
        out, left = [], start - self.horizontalOffset()
        bottom = (row + 1) * gh - self.verticalOffset()
        for (_col, i), w in zip(items, ws):
            h = gh * w / gw
            out.append((i, QRectF(left, bottom - h, w, h)))
            left += w
        self._dock_rects = out
        return out

    def itemAt(self, *at):
        pos = at[0] if len(at) == 1 else QPoint(*at)
        if self._dock is not None and self.row_at(pos.y()) == self._dock[0]:
            return next((self.item(i) for i, r in self.dock_rects() if r.left() <= pos.x() < r.right()), None)
        return super().itemAt(pos)

    def _place_items(self) -> None:
        if not self._slots:
            return
        gw, gh = self.gridSize().width(), self.gridSize().height()
        model = self.model()
        for i, (row, col) in enumerate(self._slots):
            index = model.index(i, 0)
            dx = max(0, (gw - self.rectForIndex(index).width()) // 2)    # centred in its cell, as Qt does
            self.setPositionForIndex(QPoint(col * gw + dx, row * gh), index)
        self.updateGeometries()

    def doItemsLayout(self) -> None:
        n = self.count()
        self._slots, self._shape = self._eye_slots() if self._by_eye else ([(0, i) for i in range(n)], (1, n))
        if self._dock is not None and self._dock[0] >= self._shape[0]:
            self._dock = None
        self._dock_rects = None
        super().doItemsLayout()
        self.rowsChanged.emit()
        self._place_items()

    def updateGeometries(self) -> None:
        super().updateGeometries()
        if not self.count():
            return
        # Qt counts where the items were ever put: the scroll range is that of the rows themselves
        rows, cols = self._shape
        vp = self.viewport()
        h = self.horizontalScrollBar()
        h.setPageStep(vp.width())
        h.setRange(0, max(0, cols * self.gridSize().width() - vp.width()))
        self.verticalScrollBar().setRange(0, 0)     # the strip is as high as its rows: the wheel goes sideways


class DockOverlay(QWidget):
    """미리 보기: the grown row of the strip (``ThumbStrip.set_dock``), painted over the strip and the
    room above it — the photos grow upwards from the bottom of their row, like the icons of the Dock
    of a Mac. It lets the mouse through: the strip under it takes the mouse."""

    def __init__(self, strip: ThumbStrip, parent: QWidget):
        super().__init__(parent)
        self.strip = strip
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        strip.dockChanged.connect(self.follow)
        strip.horizontalScrollBar().valueChanged.connect(lambda _v: self.follow())
        strip.model().dataChanged.connect(lambda *_a: self.update())      # (picked, the second photo …)
        self.hide()

    def rects(self) -> list[tuple[int, QRect]]:
        """(item, where it is painted here) of the grown row."""
        vp = self.strip.viewport()
        off = vp.mapTo(self.parentWidget(), QPoint(0, 0)) - self.pos()
        return [(i, r.toRect().translated(off)) for i, r in self.strip.dock_rects()]

    def follow(self) -> None:
        """Over the strip, as wide as it, from as high as the grown photos reach to its bottom."""
        rects = self.strip.dock_rects()
        if not rects:
            self.hide()
            return
        vp = self.strip.viewport()
        at = vp.mapTo(self.parentWidget(), QPoint(0, 0))
        top = min(0, math.floor(min(r.top() for _i, r in rects)))
        self.setGeometry(at.x(), max(0, at.y() + top), vp.width(), vp.height() + at.y() - max(0, at.y() + top))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, e) -> None:
        strip, paint = self.strip, self.strip.itemDelegate()
        p = QPainter(self)
        under = strip.itemAt(strip.viewport().mapFromGlobal(self.cursor().pos()))
        paint.docking = True
        try:
            for i, rect in self.rects():
                opt = QStyleOptionViewItem()
                opt.initFrom(strip)
                opt.rect = rect
                opt.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Active
                if strip.item(i) is strip.currentItem():
                    opt.state |= QStyle.StateFlag.State_Selected
                if strip.item(i) is under:
                    opt.state |= QStyle.StateFlag.State_MouseOver
                paint.paint(p, opt, strip.model().index(i, 0))
        finally:
            paint.docking = False
        p.end()


class EyeRail(QWidget):
    """The eye of each row of the strip, said once at the left of the rows — OD at the top
    row, OS at the one under it — rather than on every photo. (One line: nothing; each photo has
    its badge.)"""

    WIDTH = 40

    def __init__(self, strip: ThumbStrip, parent=None):
        super().__init__(parent)
        self.strip = strip
        self.setObjectName("eyeRail")
        self.setFixedWidth(self.WIDTH)
        self.setToolTip("이 줄의 눈 — 위 줄 OD(우안) · 아래 줄 OS(좌안)")
        strip.rowsChanged.connect(self.update)

    def badge_rects(self) -> list[tuple[str, QRectF]]:
        """(eye, where its badge is painted) for every row of the strip."""
        fm = self.fontMetrics()
        gh = self.strip.gridSize().height()
        top = self.strip.viewport().mapTo(self.strip, QPoint(0, 0)).y() + self.strip.y() - self.y()
        out = []
        for k, eye in enumerate(self.strip.row_eyes()):
            w, h = max(30, fm.horizontalAdvance(eye_badge(eye)[0]) + 12), 20
            out.append((eye, QRectF((self.width() - w) / 2, top + k * gh + (gh - h) / 2, w, h)))
        return out

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        for eye, rect in self.badge_rects():
            text, bg, fg = eye_badge(eye)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(bg))
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(fg))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
