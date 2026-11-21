"""◀ ▶ at the sides of a photo: the photo before / after it, without leaving the photo.

The mouse near the left or the right edge of a view brings up a round arrow there; a click on it
asks for the photo before (◀) or after (▶) — Detail: of the photo list; Simple: of the same eye,
in its place. The ← / → keys ask for the same while the view has the keyboard
(``ImageView.step_keys``). An arrow is there only where there is a photo to go to
(``set_available``). The rest of the view is the photo's as before: drag = move, wheel = zoom.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolButton

from .icons import icon
from .image_view import ImageView

SIZE = 46                                    # the arrow: a circle of this many pixels
MARGIN = 12                                  # … this far from the view's edge


class EdgeNav(QObject):
    stepped = Signal(int)                    # -1: the photo before · +1: the photo after

    def __init__(self, view: ImageView):
        super().__init__(view)
        self.view = view
        self._can = {-1: False, 1: False}
        self.buttons: dict[int, QToolButton] = {}
        port = self._port = view.viewport()
        for d, name, tip in ((-1, "prev", "이전 사진 (←)"), (1, "next", "다음 사진 (→)")):
            b = QToolButton(view)                 # (over the viewport, not in it: a scrolled photo takes
                                                  # the viewport's own children along)
            b.setObjectName("edgeNav")
            b.setIcon(icon(name, plain=True))
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(SIZE, SIZE)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)        # the keys stay with the photo
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, d=d: self.stepped.emit(d))
            b.installEventFilter(self)
            b.hide()
            self.buttons[d] = b
        port.installEventFilter(self)
        view.step_keys = True
        view.stepped.connect(self.stepped)

    def set_available(self, before: bool, after: bool) -> None:
        """Is there a photo before / after this one? (No arrow where there is none.)"""
        can = {-1: bool(before), 1: bool(after)}
        if can != self._can:
            self._can = can
            self._refresh()

    def available(self) -> tuple[bool, bool]:
        return self._can[-1], self._can[1]

    def zone(self) -> int:
        """Width of the strip at either side in which the mouse brings the arrow up (0: the view
        is too narrow for arrows)."""
        w = self.view.viewport().width()
        return 0 if w < 4 * SIZE else max(SIZE + 2 * MARGIN, min(150, round(0.16 * w)))

    def _refresh(self, pos: QPoint | None = None) -> None:
        """Show the arrow of the side the mouse is at (``pos``: where a mouse event says it is,
        else where the cursor is)."""
        port = self._port
        if pos is None:
            pos = port.mapFromGlobal(QCursor.pos())
        zone = self.zone()
        inside = port.rect().contains(pos) and port.isVisible() and zone > 0
        origin = port.geometry().topLeft()                  # the viewport within the view
        y = origin.y() + (port.height() - SIZE) // 2
        for d, b in self.buttons.items():
            at_side = pos.x() < zone if d < 0 else pos.x() >= port.width() - zone
            on = inside and at_side and self._can[d] and self.view.has_image()
            if on:
                b.move(origin.x() + (MARGIN if d < 0 else port.width() - SIZE - MARGIN), y)
                b.raise_()
            b.setVisible(on)

    def eventFilter(self, obj, e) -> bool:
        # (events still arrive while the view is being taken down: nothing of the view is touched
        # here but through ``_settle``, which the event loop no longer calls once this is gone)
        t = e.type()
        if obj is self._port:
            if t == QEvent.Type.MouseMove:
                self._refresh(e.position().toPoint())
            elif t in (QEvent.Type.Leave, QEvent.Type.Resize, QEvent.Type.Hide):
                QTimer.singleShot(0, self, self._settle)    # (onto the arrow itself: it stays)
        elif t == QEvent.Type.Leave:                        # off an arrow
            QTimer.singleShot(0, self, self._settle)
        return False

    def _settle(self) -> None:
        try:
            self._refresh()
        except RuntimeError:                                # the view is gone
            pass
