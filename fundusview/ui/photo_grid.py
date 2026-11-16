"""16장 보기 (VK-2 방식): 한 환자의 사진을 한 화면에 16장(4 × 4)씩, 최신 사진부터.

설정 → 일반 → **환자를 열면** 에서 VK-2 방식을 고르면 환자를 열 때 이 화면이 먼저 나옵니다. 아래 사진
목록과 같은 사진 · 같은 순서이고(날짜 · 눈 · 촬영 종류 고르기도 같음) 고르는 방법도 같습니다:

* 클릭 = Multi로 고르기 (노란 테두리와 번호) · 다시 클릭 = 빼기
* 더블클릭 = 그 사진을 크게 (Detail)
* Ctrl+클릭 = 두 번째 사진(②) · 오른쪽 클릭 = 사진 메뉴

[Multi]를 누르면 고른 사진만 모아 봅니다. 사진이 16장보다 많으면 쪽으로 나뉩니다
(◀ ▶ 단추 · 휠). 지금 보고 있는 사진은 파란 테두리입니다.

The window owns the photos and the picks (``main_window.py``); this widget only paints them and
reports what was clicked. It reads the stored thumbnails (``images.thumb_path``, 320 px), so a
page of 16 is drawn at once even for large photos.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme
from .thumbs import PICK_COLOR, SECOND_COLOR, paint_eye_badge, thumb_pixmap


@dataclass
class GridPhoto:
    image_id: int
    thumb: str | None           # stored thumbnail
    eye: str | None             # "OD" / "OS" / "OU" / None
    caption: str                # "2026-03-10 10:15 · 컬러 45°"


class PhotoGrid(QWidget):
    pressed = Signal(int)               # plain click on a photo (the window picks it)
    activated = Signal(int)             # double click: open it big
    secondPicked = Signal(int)          # Ctrl+click: the second photo (②)
    menuRequested = Signal(int, QPoint)  # right click (global position)
    pageChanged = Signal()

    COLS = ROWS = 4
    PER_PAGE = COLS * ROWS
    GAP = 6
    MARGIN = 6
    CAPTION = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("photoGrid")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._items: list[GridPhoto] = []
        self._picks: dict[int, int] = {}   # image id -> pick number (1 …)
        self._current: int | None = None
        self._second: int | None = None
        self._page = 0
        self._hover = -1                    # cell under the mouse (0 … 15)

    # -- what is shown ---------------------------------------------------------------------------
    def set_items(self, items: list[GridPhoto], current: int | None = None) -> None:
        self._items = list(items)
        self._current = current
        if not self.show_photo(current):
            self._set_page(min(self._page, self.pages() - 1))
        self.update()

    def items(self) -> list[GridPhoto]:
        return list(self._items)

    def set_picks(self, picks: list[int]) -> None:
        self._picks = {iid: k + 1 for k, iid in enumerate(picks)}
        self.update()

    def set_current(self, image_id: int | None) -> None:
        """The photo on screen elsewhere: framed blue, and its page is shown."""
        self._current = image_id
        self.show_photo(image_id)
        self.update()

    def set_second(self, image_id: int | None) -> None:
        self._second = image_id
        self.update()

    # -- pages -----------------------------------------------------------------------------------
    def pages(self) -> int:
        return max(1, -(-len(self._items) // self.PER_PAGE))

    def page(self) -> int:
        return self._page

    def set_page(self, page: int) -> None:
        self._set_page(max(0, min(page, self.pages() - 1)))

    def _set_page(self, page: int) -> None:
        page = max(0, page)
        if page != self._page:
            self._page = page
            self._hover = -1
            self.update()
        self.pageChanged.emit()

    def show_photo(self, image_id: int | None) -> bool:
        """Turn to the page holding ``image_id``; False when it is not in the grid."""
        for i, it in enumerate(self._items):
            if it.image_id == image_id:
                self._set_page(i // self.PER_PAGE)
                return True
        return False

    def visible_ids(self) -> list[int]:
        """The photos of the page on screen, in their order."""
        first = self._page * self.PER_PAGE
        return [it.image_id for it in self._items[first:first + self.PER_PAGE]]

    def page_range(self) -> tuple[int, int]:
        """1-based numbers of the first and the last photo on the page (0, 0 when empty)."""
        ids = self.visible_ids()
        first = self._page * self.PER_PAGE
        return (first + 1, first + len(ids)) if ids else (0, 0)

    # -- geometry --------------------------------------------------------------------------------
    def cell_rect(self, k: int) -> QRect:
        """The k-th cell of the page (0 … 15, row by row)."""
        m, g = self.MARGIN, self.GAP
        w = (self.width() - 2 * m - (self.COLS - 1) * g) / self.COLS
        h = (self.height() - 2 * m - (self.ROWS - 1) * g) / self.ROWS
        r, c = divmod(k, self.COLS)
        x, y = m + c * (w + g), m + r * (h + g)
        return QRect(round(x), round(y), max(1, round(x + w) - round(x)), max(1, round(y + h) - round(y)))

    def photo_rect(self, image_id: int) -> QRect | None:
        """The cell of a photo when it is on the page shown (tests click it here)."""
        ids = self.visible_ids()
        return self.cell_rect(ids.index(image_id)) if image_id in ids else None

    def _cell_at(self, pos) -> int:
        for k in range(self.PER_PAGE):
            if self.cell_rect(k).contains(pos):
                return k
        return -1

    def _id_at(self, pos) -> int | None:
        k = self._cell_at(pos)
        ids = self.visible_ids()
        return ids[k] if 0 <= k < len(ids) else None

    # -- painting --------------------------------------------------------------------------------
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if not self._items:
            p.setPen(QColor(theme.TEXT3))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "사진이 없습니다")
            p.end()
            return
        first = self._page * self.PER_PAGE
        page = self._items[first:first + self.PER_PAGE]
        f = QFont(self.font())
        f.setPixelSize(12)
        for k in range(self.PER_PAGE):
            cell = QRectF(self.cell_rect(k))
            if k >= len(page):               # VK-2: the empty places of the page stay as frames
                p.setPen(QPen(QColor(theme.SEP), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(cell.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
                continue
            it = page[k]
            second = it.image_id == self._second
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.FILL if k == self._hover else theme.CARD))
            p.drawRoundedRect(cell, 6, 6)
            photo_area = cell.adjusted(4, 4, -4, -4 - self.CAPTION)
            photo = QRectF(photo_area)
            pm = thumb_pixmap(it.thumb)
            p.fillRect(photo_area, QColor(theme.BLACK))
            if not pm.isNull() and photo_area.width() > 2 and photo_area.height() > 2:
                s = min(photo_area.width() / pm.width(), photo_area.height() / pm.height())
                photo = QRectF(0, 0, pm.width() * s, pm.height() * s)
                photo.moveCenter(photo_area.center())
                p.drawPixmap(photo, pm, QRectF(pm.rect()))
            paint_eye_badge(p, it.eye, photo.left() + 4, photo.top() + 4, px=13)
            rank = self._picks.get(it.image_id, 0)
            if rank:                         # picked for the multi view: yellow frame and its number
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(PICK_COLOR), 3))
                p.drawRect(photo.adjusted(1.5, 1.5, -1.5, -1.5))
                nf = QFont(f)
                nf.setBold(True)
                nf.setPixelSize(15)
                p.setFont(nf)
                d = p.fontMetrics().height() + 8
                dot = QRectF(photo.right() - d - 4, photo.top() + 4, d, d)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(PICK_COLOR))
                p.drawEllipse(dot)
                p.setPen(QColor("#111827"))
                p.drawText(dot, Qt.AlignmentFlag.AlignCenter, str(rank))
            cap = QRectF(cell.left() + 4, cell.bottom() - 4 - self.CAPTION, cell.width() - 8, self.CAPTION)
            if second:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(SECOND_COLOR))
                p.drawRoundedRect(cap, 4, 4)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT if second or it.image_id == self._current else theme.TEXT2))
            text = ("② " if second else "") + it.caption
            text = p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(cap.width()) - 8)
            p.drawText(cap.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            if it.image_id == self._current:  # the photo shown in Detail / selected
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(theme.ACCENT), 2))
                p.drawRoundedRect(cell.adjusted(1, 1, -1, -1), 6, 6)
        p.end()

    # -- mouse -----------------------------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        iid = self._id_at(e.position().toPoint())
        if e.button() != Qt.MouseButton.LeftButton or iid is None:
            return super().mousePressEvent(e)
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.secondPicked.emit(iid)
        elif not e.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier):
            self.pressed.emit(iid)

    def mouseDoubleClickEvent(self, e) -> None:
        iid = self._id_at(e.position().toPoint())
        if (e.button() == Qt.MouseButton.LeftButton and iid is not None
                and not e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.activated.emit(iid)
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e) -> None:
        iid = self._id_at(e.pos())
        if iid is not None:
            self.menuRequested.emit(iid, e.globalPos())

    def mouseMoveEvent(self, e) -> None:
        k = self._cell_at(e.position().toPoint())
        k = k if k < len(self.visible_ids()) else -1
        if k != self._hover:
            self._hover = k
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e) -> None:
        if self._hover != -1:
            self._hover = -1
            self.update()
        super().leaveEvent(e)

    def wheelEvent(self, e) -> None:
        """The wheel turns the pages (down = the next, older photos) — one page per notch; a
        trackpad's small steps are added up first."""
        if self.pages() <= 1:
            return super().wheelEvent(e)
        self._wheel += e.angleDelta().y()
        if abs(self._wheel) >= 120:
            self.set_page(self._page + (1 if self._wheel < 0 else -1))
            self._wheel = 0
        e.accept()

    _wheel = 0
