"""Multi-image view (VK-2 "Multiple Images": 1 / 2 / 4 / 6 / 9 / 16 on screen).

Cells show the photos picked in the thumbnail strip (plain click, in pick order) — or, with
nothing picked, consecutive photos of the current patient starting at the shown one
(down-scaled for speed). Click a cell to select it: the info panel, the other tabs and the
image-processing toolbar follow, and with picked photos the processing applies to that photo
only. Double-click opens it in the 2D tab. Each cell can be zoomed (drag up/down, wheel) and
panned on its own.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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
        self.label.setStyleSheet("background:#20262c; color:#e6ebef; padding:2px 4px; font-size:11px")
        self.view = ImageView()
        lay.addWidget(self.label)
        lay.addWidget(self.view, 1)
        self.image_id: int | None = None
        self.select(False)

    def select(self, on: bool) -> None:
        self.setStyleSheet("QFrame { border: 2px solid %s; }" % ("#2f9be0" if on else "#20262c"))


class MultiView(QWidget):
    selected = Signal(int)
    opened = Signal(int)
    layoutChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        top = QHBoxLayout()
        top.setContentsMargins(4, 4, 4, 0)
        top.addWidget(QLabel("화면 분할"))
        self.combo = QComboBox()
        for n in LAYOUTS:
            self.combo.addItem(f"{n}장", n)
        self.combo.setCurrentIndex(2)
        self.combo.currentIndexChanged.connect(lambda _: self.layoutChanged.emit(self.count))
        top.addWidget(self.combo)
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("color:#facc15; font-weight:600; padding-left:6px")
        top.addWidget(self.mode_label)
        hint = QLabel("위/아래 드래그: 확대·축소 · 클릭: 선택 · 더블클릭: 2D로 열기")
        hint.setStyleSheet("color:#889")
        top.addWidget(hint, 1)
        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addLayout(self.grid, 1)
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
