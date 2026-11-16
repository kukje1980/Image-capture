"""Multi-image view (VK-2 "Multiple Images": 1 / 2 / 4 / 6 / 9 / 16 on screen) — the page of both
Simple and Multi.

Simple: two cells, the patient's newest OD (left) and OS (right) photo — a click on the photo
list puts a photo in its eye's place, and ◀ ▶ at the sides of a cell (``EdgeNav``; ← / →) step
through that eye's photos. Multi: the cells show the photos picked in the photo list (plain
click, in pick order) and the layout follows the number picked — or, with nothing picked,
consecutive photos of the current patient starting at the shown one (down-scaled for speed).
Click a cell to select it: the info panel, the other views and the image-processing toolbar
follow, and the processing applies to that photo only. Double-click opens it large (Detail).
Each cell can be zoomed (wheel) and panned (drag) on its own.

``compact=True`` (a small pane, no longer shown): no layout row, always 4 photos (2 × 2).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .edge_nav import EdgeNav
from .image_view import ImageView

LAYOUTS = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 16: (4, 4)}


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
        self.nav = EdgeNav(self.view)       # ◀ ▶ at its sides (Simple; nowhere to go until told)
        lay.addWidget(self.label)
        lay.addWidget(self.view, 1)
        self.image_id: int | None = None
        self.select(False)

    def select(self, on: bool) -> None:
        self.selected = on
        self.setStyleSheet("QFrame { border: 2px solid %s; }" % (theme.ACCENT if on else theme.CARD))


class MultiView(QWidget):
    selected = Signal(int)
    opened = Signal(int)
    layoutChanged = Signal(int)
    stepped = Signal(int, int)          # (the photo of a cell, -1 / +1): ◀ ▶ at its sides · ← / →

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.topbar = QWidget()
        top = QHBoxLayout(self.topbar)
        top.setContentsMargins(4, 4, 4, 0)
        top.addWidget(QLabel("화면 분할"))
        self.combo = QComboBox()
        for n in LAYOUTS:
            self.combo.addItem(f"{n}장", n)
        self.combo.setCurrentIndex(2)
        self.combo.currentIndexChanged.connect(lambda _: self.layoutChanged.emit(self.count))
        top.addWidget(self.combo)
        self.mode_text = ""                  # '고른 사진 3장' — shown in the combo's tooltip
        self._tip()
        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        # nothing picked any more: what to do, where the cells were
        self.empty = QLabel("")
        self.empty.setObjectName("multiEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color:{theme.TEXT3}; font-size:15px; padding:24px")
        self.empty.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.topbar)
        lay.addLayout(self.grid, 1)
        lay.addWidget(self.empty, 1)
        if compact:
            self.grid.setSpacing(2)
            self.topbar.hide()
        self.cells: list[_Cell] = []

    @property
    def count(self) -> int:
        return int(self.combo.currentData())

    def set_count(self, n: int, quiet: bool = False) -> None:
        """``quiet``: no ``layoutChanged`` (the caller fills the cells itself)."""
        i = self.combo.findData(n)
        if i < 0:
            return
        was = self.combo.blockSignals(quiet or self.combo.signalsBlocked())
        try:
            self.combo.setCurrentIndex(i)
        finally:
            self.combo.blockSignals(was)

    @staticmethod
    def fit(n: int) -> int:
        """The smallest layout that holds ``n`` photos (3 → 4 · 5 → 6 · 7 → 9 …, at most 16)."""
        return next((k for k in LAYOUTS if k >= n), max(LAYOUTS))

    def populate(self, items, current_id: int | None, empty: str = "") -> None:
        """``items`` = list of ``(image_id, label, rgb)`` (already processed). With no items and
        an ``empty`` text, that text is shown instead of the cells."""
        hint = not items and bool(empty)
        self.empty.setText(empty if hint else "")
        self.empty.setVisible(hint)
        rows, cols = LAYOUTS[self.count]
        while len(self.cells) < rows * cols:
            cell = _Cell()
            cell.view.clicked.connect(lambda c=cell: self._select(c))
            cell.view.activated.connect(lambda c=cell: c.image_id is not None and self.opened.emit(c.image_id))
            cell.nav.stepped.connect(lambda d, c=cell: c.image_id is not None and self.stepped.emit(c.image_id, d))
            self.cells.append(cell)
        for cell in self.cells:
            self.grid.removeWidget(cell)
            cell.hide()
        for i in range(rows * cols):
            cell = self.cells[i]
            self.grid.addWidget(cell, i // cols, i % cols)
            cell.setVisible(not hint)
            if i < len(items):
                iid, label, rgb = items[i]
                # the same photo in the same cell (another cell changed): its zoom and place stay
                same = (cell.image_id == iid and cell.view._rgb is not None
                        and cell.view._rgb.shape == rgb.shape)
                cell.image_id = iid
                cell.label.setText(label)
                cell.view.set_rgb(rgb, keep_view=same)
                cell.select(iid == current_id)
            else:
                cell.image_id = None
                cell.label.setText("")
                cell.view.set_rgb(None)
                cell.select(False)
                cell.nav.set_available(False, False)
        for r in range(4):
            self.grid.setRowStretch(r, 1 if r < rows else 0)
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def take_topbar(self) -> QWidget:
        """The 화면 분할 row, out of this view — the main window shows it in its own top row,
        next to the 3D · Montage · Glaucoma buttons."""
        self.layout().removeWidget(self.topbar)
        self.topbar.layout().setContentsMargins(0, 0, 0, 0)
        return self.topbar

    def set_mode_text(self, text: str) -> None:
        """'고른 사진 3장' (picked photos) or '' (consecutive photos from the shown one)."""
        self.mode_text = text
        self._tip()

    def _tip(self) -> None:
        tip = "화면 분할 — 휠: 확대·축소 · 드래그: 이동 · 클릭: 선택 · 더블클릭: 크게 보기"
        self.combo.setToolTip(f"{self.mode_text}\n{tip}" if self.mode_text else tip)

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
