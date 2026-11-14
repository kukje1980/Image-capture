"""Controls in the manner of a phone's settings: a switch that slides, a segmented control whose
selection glides to the next segment, and grouped cards of labelled rows.

They keep the plain Qt interfaces — ``Switch`` is a ``QCheckBox`` (``isChecked`` / ``setChecked`` /
``toggled``), the segments are ordinary checkable buttons — so code and tests use them like the
widgets they replace.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from . import motion, theme


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


class Switch(QCheckBox):
    """An on/off switch whose knob slides. ``trailing``: the label on the left and the switch at the
    right edge (a row of settings); otherwise the switch first, then the label."""

    TRACK_W, TRACK_H = 38, 22

    def __init__(self, text: str = "", parent=None, trailing: bool = True):
        super().__init__(text, parent)
        self.trailing = trailing
        self._t = 0.0
        self._ends = (0.0, 0.0)
        self._anim = motion.Tween(self._slide, 0.18, motion.ease_out)
        self.toggled.connect(self._on_toggled)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding if trailing else QSizePolicy.Policy.Minimum,
                           QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = self.TRACK_W + (fm.horizontalAdvance(self.text()) + 10 if self.text() else 0)
        return QSize(w, max(self.TRACK_H + 6, fm.height() + 10))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def _on_toggled(self, on: bool) -> None:
        self._ends = (self._t, 1.0 if on else 0.0)
        self._anim.start()

    def _slide(self, k: float) -> None:
        a, b = self._ends
        self._t = a + (b - a) * k
        self.update()

    def track_rect(self) -> QRectF:
        y = (self.height() - self.TRACK_H) / 2.0
        x = self.width() - self.TRACK_W if self.trailing else 0.0
        return QRectF(x, y, self.TRACK_W, self.TRACK_H)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isEnabled()
        r = self.track_rect()
        track = _mix(QColor("#39393d"), QColor(theme.GREEN), self._t)
        if not on:
            track.setAlphaF(0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4.0
        x = r.left() + 2.0 + self._t * (r.width() - d - 4.0)
        p.setBrush(QColor(0, 0, 0, 50))                       # the knob's soft shadow
        p.drawEllipse(QRectF(x, r.top() + 3.0, d, d))
        p.setBrush(QColor("#ffffff") if on else QColor("#aeaeb2"))
        p.drawEllipse(QRectF(x, r.top() + 2.0, d, d))
        if self.text():
            p.setPen(QColor(theme.TEXT if on else theme.TEXT4))
            if self.trailing:
                box = QRectF(0, 0, r.left() - 8, self.height())
            else:
                box = QRectF(r.right() + 8, 0, self.width() - r.right() - 8, self.height())
            p.drawText(box, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        p.end()


class Segmented(QFrame):
    """One choice out of a few, side by side on a track; the selected segment lies on a lighter
    thumb that glides to the next. The segments are the given checkable buttons (made exclusive)."""

    def __init__(self, buttons: list[QAbstractButton], parent=None, on_card: bool = True):
        super().__init__(parent)
        self.on_card = on_card
        self.buttons = list(buttons)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        for b in self.buttons:
            b.setCheckable(True)
            b.setObjectName("segment")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.group.addButton(b)
            lay.addWidget(b, 1)
            b.toggled.connect(self._on_toggled)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._thumb = QRectF()
        self._ends = (QRectF(), QRectF())
        self._anim = motion.Tween(self._glide, 0.22, motion.ease_out)
        self.setStyleSheet(
            "QPushButton#segment { background: transparent; border: 0; border-radius: 6px; padding: 4px 10px;"
            f" color: {theme.TEXT2}; font-weight: 400; }}"
            f"QPushButton#segment:hover:!checked {{ color: {theme.TEXT}; }}"
            "QPushButton#segment:checked { background: transparent; color: #ffffff; font-weight: 600; }"
            f"QPushButton#segment:disabled {{ color: {theme.TEXT4}; background: transparent; }}")

    def _target(self) -> QRectF:
        b = self.group.checkedButton()
        return QRectF(b.geometry()) if b is not None else QRectF()

    def _on_toggled(self, on: bool) -> None:
        if not on:
            return
        self._ends = (QRectF(self._thumb), self._target())
        if self._ends[0].isEmpty() or not self.isVisible():
            self._thumb = self._ends[1]
            self.update()
            return
        self._anim.start()

    def _glide(self, k: float) -> None:
        a, b = self._ends
        self._thumb = QRectF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k,
                             a.width() + (b.width() - a.width()) * k, a.height() + (b.height() - a.height()) * k)
        self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._anim.stop()
        self._thumb = self._target()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._thumb = self._target()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1c1c1e" if self.on_card else theme.CARD))
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        if not self._thumb.isEmpty():
            t = self._thumb
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawRoundedRect(t.translated(0, 1), 6, 6)
            p.setBrush(QColor(theme.FILL3 if self.isEnabled() else theme.FILL))
            p.drawRoundedRect(t, 6, 6)
        p.end()


def segment(text: str, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(True)
    if tip:
        b.setToolTip(tip)
    return b


class FlowLayout(QLayout):
    """A row of controls that wraps onto the next line when the window is too narrow for it —
    a bar laid out with this never forces the window wider than its widest control."""

    def __init__(self, parent=None, margins=(10, 6, 10, 6), spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._lines = 1
        self.setContentsMargins(*margins)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._place(rect, True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def rows(self) -> int:
        """Lines the controls take at the current width (tests, screenshots)."""
        return self._lines

    def _place(self, rect: QRect, move: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        gap = self.spacing()
        x, y, line_h, lines = area.x(), area.y(), 0, 1
        line: list = []

        def flush() -> None:                      # centre the line's controls on its height
            for item, ix in line:
                h = item.sizeHint().height()
                item.setGeometry(QRect(QPoint(ix, y + (line_h - h) // 2), item.sizeHint()))

        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_h > 0:
                if move:
                    flush()
                line = []
                x, y, line_h, lines = area.x(), y + line_h + gap, 0, lines + 1
            line.append((item, x))
            x += hint.width() + gap
            line_h = max(line_h, hint.height())
        if move:
            flush()
            self._lines = lines
        return y + line_h - rect.y() + m.bottom()


def vline(height: int = 20) -> QFrame:
    """A short vertical hairline between groups of a bar."""
    f = QFrame()
    f.setObjectName("vline")
    f.setFixedSize(1, height)
    return f


def hairline() -> QFrame:
    f = QFrame()
    f.setObjectName("hairline")
    f.setFixedHeight(1)
    return f


def row(label: str, widget: QWidget, tip: str = "") -> QWidget:
    """A settings row: the name on the left, its control on the right."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lab = QLabel(label)
    lab.setObjectName("rowLabel")
    lay.addWidget(lab)
    lay.addStretch(1)
    lay.addWidget(widget)
    if tip:
        w.setToolTip(tip)
    w.label = lab
    return w


def card(title: str, *rows: QWidget, lines: bool = True) -> QWidget:
    """A titled group of rows on a rounded card (hairlines between the rows)."""
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(4)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        outer.addWidget(t)
    frame = QFrame()
    frame.setObjectName("card")
    inner = QVBoxLayout(frame)
    inner.setContentsMargins(12, 8, 12, 8)
    inner.setSpacing(6)
    for i, r in enumerate(rows):
        if i and lines:
            inner.addWidget(hairline())
        inner.addWidget(r)
    outer.addWidget(frame)
    box.frame = frame
    return box


def knob_center(sw: Switch) -> QPointF:
    """Where the switch's knob is drawn (tests)."""
    r = sw.track_rect()
    d = r.height() - 4.0
    return QPointF(r.left() + 2.0 + sw._t * (r.width() - d - 4.0) + d / 2, r.center().y())
