"""미리 보기 — the photo of the photo list under the mouse, large over the photos.

A pane that floats over the views while the mouse rests on a photo of the list: the photo as
large as the room allows, its eye · date · kind in the line above it, and what a click does
(선택 / 빼기). The photos underneath stay as they are — nothing is laid out again — and the pane
lets the mouse through (it is only looked at). The main window shows and hides it
(``MainWindow._apply_peek``).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import theme
from .image_view import ImageView

MARGIN = 14                     # around the pane: the views under it show at its edges
PEEK_COLOR = "#facc15"          # its frame (the colour of a picked photo in the list)


class PeekPane(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("peekPane")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(f"QFrame#peekPane {{ background:#000000; border:3px solid {PEEK_COLOR}; "
                           "border-radius:6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(0)
        self.label = QLabel()
        self.label.setStyleSheet(f"background:{theme.CARD}; color:{theme.TEXT}; padding:6px 10px; font-size:13px")
        self.view = ImageView()
        self.view.set_navigator(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.label)
        lay.addWidget(self.view, 1)
        self.image_id: int | None = None
        self.hide()

    def place(self) -> None:
        """Over the whole parent, a margin left around it."""
        r = self.parentWidget().rect()
        self.setGeometry(QRect(r).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN))

    def show_photo(self, image_id: int, label: str, rgb) -> None:
        self.image_id = image_id
        self.label.setText(label)
        self.place()
        self.show()
        self.raise_()
        self.layout().activate()               # the photo is fitted to the room it has now
        self.view.set_rgb(rgb)
        self.view.fit()

    def clear(self) -> None:
        self.image_id = None
        self.hide()
        self.view.set_rgb(None)
