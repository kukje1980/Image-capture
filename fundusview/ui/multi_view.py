"""Multi-image view (VK-2 "Multiple Images": 1 / 2 / 4 / 6 / 9 / 16 on screen).

Cells show the photos picked in the thumbnail strip (plain click, in pick order) — or, with
nothing picked, the current patient's photos a screen at a time (16 when a patient is picked in
the patient list), down-scaled for speed; ◀ ▶ go to the next / previous screen. A click on a cell
opens that photo large (``opened``: 모두 보기 — [다중 보기] comes back to the same screen); the
press already selects it (``selected``: the info panel, the other tabs and the image-processing
toolbar follow, and with picked photos the processing applies to that photo only). Each cell can
be zoomed (drag up/down, wheel) and panned on its own — a drag never opens the photo.

``compact=True`` (모두 보기의 작은 화면): no layout row, always 4 photos (2 × 2).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from . import theme
from .image_view import ImageView

LAYOUTS = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 16: (4, 4)}
DEFAULT = 16                    # a patient's photos: 16 to a screen


class _Cell(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.label = QLabel()
        self.label.setStyleSheet(f"background:{theme.CARD}; color:{theme.TEXT2}; padding:3px 6px; font-size:11px")
        self.view = ImageView()
        lay.addWidget(self.label)
        lay.addWidget(self.view, 1)
        self.image_id: int | None = None
        self.select(False)

    def select(self, on: bool) -> None:
        self.setStyleSheet("QFrame { border: 2px solid %s; }" % (theme.ACCENT if on else theme.CARD))


class MultiView(QWidget):
    selected = Signal(int)          # a cell pressed: its photo is the shown one
    opened = Signal(int)            # a cell clicked (not dragged): its photo large
    layoutChanged = Signal(int)
    pageRequested = Signal(int)     # ◀ −1 / ▶ +1: the previous / next screen of photos

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.topbar = QWidget()
        top = QHBoxLayout(self.topbar)
        top.setContentsMargins(4, 4, 4, 0)
        top.addWidget(QLabel("화면 분할"))
        self.combo = QComboBox()
        for n in LAYOUTS:
            self.combo.addItem(f"{n}장", n)
        self.combo.setCurrentIndex(self.combo.findData(DEFAULT))
        self.combo.currentIndexChanged.connect(lambda _: self.layoutChanged.emit(self.count))
        top.addWidget(self.combo)
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet(f"color:{theme.YELLOW}; font-weight:600; padding-left:6px")
        top.addWidget(self.mode_label)
        hint = QLabel("사진을 누르면 크게 보기 ([다중 보기]로 돌아옴) · 위/아래 드래그: 확대·축소")
        hint.setStyleSheet(f"color:{theme.TEXT3}")
        top.addWidget(hint, 1)
        self.btn_prev = QToolButton()
        self.btn_prev.setText("◀")
        self.btn_prev.setToolTip("앞 화면의 사진")
        self.btn_prev.clicked.connect(lambda: self.pageRequested.emit(-1))
        self.lbl_page = QLabel("")
        self.lbl_page.setStyleSheet(f"color:{theme.TEXT2}; padding: 0 4px")
        self.btn_next = QToolButton()
        self.btn_next.setText("▶")
        self.btn_next.setToolTip("다음 화면의 사진")
        self.btn_next.clicked.connect(lambda: self.pageRequested.emit(1))
        for w in (self.btn_prev, self.lbl_page, self.btn_next):
            top.addWidget(w)
            w.hide()
        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.topbar)
        lay.addLayout(self.grid, 1)
        if compact:
            self.grid.setSpacing(2)
            self.topbar.hide()
            self.set_count(4)                       # always 2 × 2
        self.cells: list[_Cell] = []

    @property
    def count(self) -> int:
        return int(self.combo.currentData())

    def set_count(self, n: int) -> None:
        i = self.combo.findData(n)
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def populate(self, items, current_id: int | None) -> None:
        """``items`` = list of ``(image_id, label, rgb)`` (already processed)."""
        rows, cols = LAYOUTS[self.count]
        while len(self.cells) < rows * cols:
            cell = _Cell()
            cell.view.clicked.connect(lambda c=cell: self._select(c))
            cell.view.tapped.connect(lambda c=cell: c.image_id is not None and self.opened.emit(c.image_id))
            cell.view.activated.connect(lambda c=cell: c.image_id is not None and self.opened.emit(c.image_id))
            self.cells.append(cell)
        for cell in self.cells:
            self.grid.removeWidget(cell)
            cell.hide()
        for i in range(rows * cols):
            cell = self.cells[i]
            self.grid.addWidget(cell, i // cols, i % cols)
            cell.show()
            if i < len(items):
                iid, label, rgb = items[i]
                cell.image_id = iid
                cell.label.setText(label)
                cell.view.set_rgb(rgb)
                cell.select(iid == current_id)
            else:
                cell.image_id = None
                cell.label.setText("")
                cell.view.set_rgb(None)
                cell.select(False)
        for r in range(4):
            self.grid.setRowStretch(r, 1 if r < rows else 0)
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def set_page(self, start: int, n: int, total: int) -> None:
        """Where the cells are in the patient's photos: "1–16 / 40장" and ◀ ▶ (only with more photos
        than cells; ``total`` 0 = the picked photos, no pages)."""
        many = total > n
        self.lbl_page.setText(f"{start + 1}–{min(start + n, total)} / {total}장" if many else "")
        for w in (self.btn_prev, self.lbl_page, self.btn_next):
            w.setVisible(many)
        self.btn_prev.setEnabled(start > 0)
        self.btn_next.setEnabled(start + n < total)

    def set_mode_text(self, text: str) -> None:
        """'고른 사진 3장' (picked photos) or '' (consecutive photos from the shown one)."""
        self.mode_label.setText(text)

    def update_cell(self, image_id: int, rgb) -> bool:
        """Show new pixels for one photo, keeping that cell's zoom and position."""
        for cell in self.cells:
            if cell.image_id == image_id and cell.isVisible():
                cell.view.set_rgb(rgb, keep_view=True)
                return True
        return False

    def mark_selected(self, image_id: int | None) -> None:
        for c in self.cells:
            c.select(c.image_id is not None and c.image_id == image_id)

    def _select(self, cell: _Cell) -> None:
        if cell.image_id is None:
            return
        for c in self.cells:
            c.select(c is cell)
        self.selected.emit(cell.image_id)
