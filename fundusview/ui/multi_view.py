"""Multi-image view (VK-2 "Multiple Images": 자동, or 1 / 2 / 4 / 6 / 9 / 16 on screen).

화면 분할 "자동" (the default): as many cells as there are picked photos — every click on a
thumbnail adds a cell, a second click takes it away (one photo when nothing is picked).

Cells show the photos picked in the thumbnail strip (plain click, in pick order) — or, with
nothing picked, consecutive photos of the current patient starting at the shown one
(down-scaled for speed). Click a cell to select it: the info panel, the other tabs and the
image-processing toolbar follow, and with picked photos the processing applies to that photo
only. Double-click opens it in the 2D tab. Each cell can be zoomed (drag up/down, wheel) and
panned on its own.

``compact=True`` (모두 보기의 작은 화면): no layout row, always 4 photos (2 × 2).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .image_view import ImageView

LAYOUTS = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 16: (4, 4)}
AUTO = 0                                     # 화면 분할 "자동": the cells follow the picked photos
MAX_CELLS = 16


def grid_for(n: int) -> tuple[int, int]:
    """(rows, columns) for ``n`` photos, wide rather than tall (the photo area is a wide one)."""
    n = max(1, min(int(n), MAX_CELLS))
    if n <= 3:
        return 1, n
    if n <= 8:
        return 2, -(-n // 2)
    if n <= 12:
        return 3, 3 if n == 9 else 4
    return 4, 4


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
    selected = Signal(int)
    opened = Signal(int)
    layoutChanged = Signal(int)

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.topbar = QWidget()
        top = QHBoxLayout(self.topbar)
        top.setContentsMargins(4, 4, 4, 0)
        top.addWidget(QLabel("화면 분할"))
        self.combo = QComboBox()
        self.combo.addItem("자동", AUTO)
        self.combo.setItemData(0, "고른 사진 수만큼 — 사진을 클릭할 때마다 한 칸씩 늘어납니다", Qt.ItemDataRole.ToolTipRole)
        for n in LAYOUTS:
            self.combo.addItem(f"{n}장", n)
        self._auto_n = 1                         # cells shown with "자동" (see set_auto_count)
        self.combo.setCurrentIndex(self.combo.findData(4 if compact else AUTO))
        self.combo.currentIndexChanged.connect(lambda _: self.layoutChanged.emit(self.count))
        top.addWidget(self.combo)
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet(f"color:{theme.YELLOW}; font-weight:600; padding-left:6px")
        top.addWidget(self.mode_label)
        hint = QLabel("위/아래 드래그: 확대·축소 · 클릭: 선택 · 더블클릭: 2D로 열기")
        hint.setStyleSheet(f"color:{theme.TEXT3}")
        top.addWidget(hint, 1)
        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.topbar)
        lay.addLayout(self.grid, 1)
        if compact:
            self.grid.setSpacing(2)
            self.topbar.hide()
        self.cells: list[_Cell] = []

    @property
    def auto(self) -> bool:
        return int(self.combo.currentData()) == AUTO

    @property
    def count(self) -> int:
        """Photos on screen: the chosen number, or with "자동" the number of picked photos."""
        return self._auto_n if self.auto else int(self.combo.currentData())

    def set_auto_count(self, n: int) -> None:
        self._auto_n = max(1, min(int(n), MAX_CELLS))

    def set_count(self, n: int) -> None:
        """``n`` photos on screen (one of LAYOUTS), or ``AUTO``."""
        i = self.combo.findData(n)
        if i >= 0:
            self.combo.setCurrentIndex(i)

    def populate(self, items, current_id: int | None) -> None:
        """``items`` = list of ``(image_id, label, rgb)`` (already processed)."""
        auto = self.auto
        rows, cols = grid_for(self.count) if auto else LAYOUTS[self.count]
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
            cell.setVisible(not auto or i < max(1, len(items)))   # 자동: no empty frames after the last photo
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
