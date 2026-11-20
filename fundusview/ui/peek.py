"""미리 보기 — the photo of the photo list under the mouse grows where it is, like the Dock of a Mac.

The photo of the list the mouse rests on grows to ``scale`` times its size in the list (보기 → 미리
보기 배율: 1.5 … 3 times) and the photos after it in its row move to the right to make room
(``ThumbStrip.set_grown``). This pane is that grown photo: it lies on the cell of the photo, its left
edge on the cell's, its bottom on the bottom of the row, and grows to the right — into the room
made — and upwards. Only its eye (OD / OS) is on it, at the top left. It lets the mouse through
(it is only looked at; the list under it takes the click). The main window shows, grows and hides
it (``MainWindow._apply_peek``).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .image_view import ImageView

SCALE = 2.0                     # the photo under the mouse: this many times its size in the list …
# … or as chosen in 보기 → 미리 보기 배율 (Settings.preview_scale)
SCALES = (1.5, 2.0, 2.5, 3.0)
BORDER = 2
PEEK_COLOR = "#facc15"          # its frame (the colour of a picked photo in the list)


def scale_name(scale: float) -> str:
    return f"{scale:g}배"


class PeekPane(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("peekPane")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(f"QFrame#peekPane {{ background:#000000; border:{BORDER}px solid {PEEK_COLOR}; "
                           "border-radius:4px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(BORDER, BORDER, BORDER, BORDER)
        lay.setSpacing(0)
        self.view = ImageView()
        self.view.set_navigator(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.view, 1)
        self.label = QLabel(self)               # the eye (OD / OS), on the photo: top left
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setStyleSheet("background:transparent; font-size:12px")
        self.label.move(BORDER + 4, BORDER + 4)
        self.image_id: int | None = None
        self.scale = SCALE                      # how large the photo gets (보기 → 미리 보기 배율)
        self.hide()

    def place(self, cell: QRect, factor: float) -> None:
        """Over ``cell`` — the photo's cell of the list, in the parent —, ``factor`` times its size:
        the left edge and the bottom stay, it grows to the right and upwards (kept inside the parent)."""
        r = self.parentWidget().rect()
        w = min(r.width(), max(cell.width(), round(cell.width() * factor)))
        h = min(r.height(), max(cell.height(), round(cell.height() * factor)))
        x = max(0, min(cell.left(), r.width() - w))
        y = max(0, cell.bottom() + 1 - h)
        self.setGeometry(QRect(x, y, w, h))
        self.layout().activate()               # the photo is fitted to the room it has now
        self.view.fit()

    def show_photo(self, image_id: int, label: str, rgb, cell: QRect, factor: float = 1.0) -> None:
        self.image_id = image_id
        self.label.setText(label)
        self.label.adjustSize()
        self.setGeometry(cell)
        self.show()
        self.raise_()
        self.label.raise_()
        self.view.set_rgb(rgb)
        self.place(cell, factor)

    def clear(self) -> None:
        self.image_id = None
        self.hide()
        self.view.set_rgb(None)
