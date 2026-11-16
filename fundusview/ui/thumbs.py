"""The photo list under the views: what is painted on a photo, the rows by eye and their names.

VK-2 lists the photos newest first and shows which eye each one is. Here the photo fills its cell
(no lines of caption under it: the height goes to the photos above) and what is said about it lies
on the photo — the exam date at its top left, and, as options (보기 → 사진 목록 표시), the kind of
photo (컬러 · 몽타주 …) at its bottom left. A photo shown above gets a yellow frame — on Multi with
its pick number —, the second picked photo ②.

``ThumbStrip`` lays the photos out by eye: OD photos in the top row, OS photos in the row under
it, and anything else (OU) in a third row only when there is any; the rows scroll sideways
together. The eye is said once per row, at the right end of the rows (``EyeRail``), not on every
photo. Or all photos in one line — then each has its eye badge (OD blue · OS orange · OU purple ·
미상 grey). (The main window leaves 미상 photos out of the list.)
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPixmapCache
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

    def photo_rect(self, option, index) -> QRect:
        """Where the photo is painted: as large as fits the cell, centred."""
        area = option.rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        size = icon.actualSize(area.size()) if isinstance(icon, QIcon) and not icon.isNull() else QSize()
        if size.isEmpty():
            return QRect(area)
        photo = QRect(0, 0, size.width(), size.height())
        photo.moveCenter(area.center())
        return photo

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
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        opt.icon, opt.text = QIcon(), ""    # the style paints the cell only (hover · selected)
        opt.features &= ~(QStyleOptionViewItem.ViewItemFeature.HasDecoration
                          | QStyleOptionViewItem.ViewItemFeature.HasDisplay)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        photo = self.photo_rect(option, index)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, photo)
        rank = int(index.data(PICK_ROLE) or 0)
        if rank:                             # shown above: framed; on Multi with its pick number
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(PICK_COLOR), 3))
            painter.drawRect(QRectF(photo).adjusted(1.5, 1.5, -1.5, -1.5))
        f = QFont(opt.font)
        f.setBold(True)
        f.setPixelSize(10)
        painter.setFont(f)
        date, kind = index.data(DATE_ROLE) or "", index.data(KIND_ROLE) or ""
        if self.show_date and date:
            self._chip(painter, date, photo.left() + 2, photo.top() + 2)
        x = photo.left() + 2.0
        if self.show_eye:
            text, bg, fg = eye_badge(index.data(EYE_ROLE))
            x = self._chip(painter, text, x, photo.bottom() - 1, bottom=True, bg=QColor(bg), fg=QColor(fg)).right() + 2
        if self.show_kind and kind:
            self._chip(painter, kind, x, photo.bottom() - 1, bottom=True)
        f.setPixelSize(12)
        painter.setFont(f)
        d = painter.fontMetrics().height() + 3
        x = photo.right() - 2.0
        for mark, bg, fg in ((str(rank) if rank > 0 else "", PICK_COLOR, "#111827"),
                             ("②" if index.data(SECOND_ROLE) else "", SECOND_COLOR, "#ffffff")):
            if not mark:
                continue
            dot = QRectF(x - d, photo.bottom() - d - 1.0, d, d)
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
    to its eye's row (``setPositionForIndex`` needs a non-static movement; dragging stays off).
    """
    stepped = Signal(int)                    # ← (-1) / → (+1): the photo before / after (the window steps)
    rowsChanged = Signal()                   # the rows were laid out again (``EyeRail`` names them)

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

    def doItemsLayout(self) -> None:
        if self._by_eye:
            self._slots, self._shape = self._eye_slots()
        super().doItemsLayout()
        self.rowsChanged.emit()
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


class EyeRail(QWidget):
    """The eye of each row of the strip, said once at the right end of the rows — OD at the top
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
