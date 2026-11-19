"""미리 보기 — the photo of the photo list under the mouse, a good deal larger, right over it.

A small pane that comes up just above the photo of the list the mouse rests on (like a large
tool tip): the photo some five times the size it has in the list (``SIDE``) and nothing but its
eye (OD / OS) on it, at the top left. It covers only a corner of the
views — the photos there stay as they are, nothing is laid out again — and lets the mouse
through (it is only looked at). The main window shows and hides it (``MainWindow._apply_peek``).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .image_view import ImageView

MARGIN = 6                      # between the pane and the edges of the views / the photo list
SIDE = 440                      # the photo in the pane: this many pixels across (the list: 84) …
# … or as chosen in 보기 → 미리 보기 크기 (Settings.preview_size): (pixels across, name)
SIZES = ((300, "작게"), (440, "보통"), (600, "크게"), (800, "아주 크게"))
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
        self.view = ImageView()
        self.view.set_navigator(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.view, 1)
        self.label = QLabel(self)               # the eye (OD / OS), on the photo: top left
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setStyleSheet("background:transparent; font-size:15px")
        self.label.move(3 + 8, 3 + 8)
        self.image_id: int | None = None
        self.side = SIDE                        # the photo: this many pixels across (보기 → 미리 보기 크기)
        self.anchor_x = 0                       # the middle of the photo of the list, in the parent
        self.aspect = 0.75                      # height / width of the photo shown
        self.hide()

    def place(self) -> None:
        """At the bottom of the parent (just above the photo list), centred over ``anchor_x`` — the
        photo of the list it shows — and kept inside the parent: ``side`` pixels across, less where
        the parent has no room for that."""
        r = self.parentWidget().rect()
        head = 0                                # (no line of text over the photo)
        w = min(self.side, r.width() - 2 * MARGIN)
        h = min(int(w * self.aspect), max(120, r.height() - head - 12 - 2 * MARGIN))
        w = min(w, int(h / self.aspect)) if self.aspect > 0 else w
        w, h = max(w, 200) + 12, h + head + 12          # (the frame and its padding)
        x = max(MARGIN, min(self.anchor_x - w // 2, r.width() - w - MARGIN))
        self.setGeometry(QRect(x, r.height() - h - MARGIN, w, h))

    def show_photo(self, image_id: int, label: str, rgb, anchor_x: int = 0) -> None:
        self.image_id = image_id
        self.label.setText(label)
        self.label.adjustSize()
        self.anchor_x = int(anchor_x)
        self.aspect = rgb.shape[0] / max(1, rgb.shape[1])
        self.place()
        self.show()
        self.raise_()
        self.label.raise_()
        self.layout().activate()               # the photo is fitted to the room it has now
        self.view.set_rgb(rgb)
        self.view.fit()

    def clear(self) -> None:
        self.image_id = None
        self.hide()
        self.view.set_rgb(None)
