"""깊이 막대: a vertical bar over the right edge of the 3D eye that sets how deep the eye is cut open.

It is the settings panel's 깊이 slider (``안구 열기``) drawn where the eye is, made to be found at a glance:
its own dark panel with the title 깊이 and the depth in figures, a thick track whose cut-away part is filled
in the accent colour, a large round handle, ticks every quarter and the two ends named (닫힘 at the top,
깊게 — or 절반 for 세로 단면 — at the bottom). Drag the handle (or press anywhere on the bar) up and down,
or turn the wheel over it; up closes the eye, down cuts deeper. The slider stays the one value: the bar
reads it and sets it, follows its range, and is shown only while the slider is enabled (outside the eye).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSlider, QWidget

from . import theme

WIDTH = 64
MARGIN = 14              # from the eye's right edge
TOP = 82                 # the track's top, below the title, the figure and 닫힘
BOTTOM = 30              # the track's bottom from the bar's
HANDLE_R = 11.0
TRACK_W = 8.0
WHEEL_STEP = 4           # slider units per wheel notch (as the wheel over the eye in 깊이)


class DepthBar(QWidget):
    TIP = ("깊이 막대 — 위아래로 끌어 안구를 자르는 깊이를 정합니다 (맨 위 = 닫힌 안구, 아래로 갈수록 깊게) · "
           "막대 위에서 휠로도 조절")

    def __init__(self, slider: QSlider, eye: QWidget):
        super().__init__(eye)
        self.slider = slider
        self.bottom_text = "깊게"
        self._drag = False
        self._hover = False
        self._wheel = 0.0
        self.setObjectName("depthBar3d")
        self.setToolTip(self.TIP)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)    # the arrow keys stay the eye's
        self.setMouseTracking(True)
        slider.valueChanged.connect(lambda _: self.update())
        slider.rangeChanged.connect(lambda *_: self.update())
        slider.installEventFilter(self)                # enabled ↔ shown
        eye.installEventFilter(self)                   # resized → placed again
        self._place()
        self.setVisible(slider.isEnabled())

    # -- the value ---------------------------------------------------------------------------------
    def fraction(self) -> float:
        """0 at the top (닫힘, the slider's maximum) … 1 at the bottom (the deepest cut, its minimum)."""
        lo, hi = self.slider.minimum(), self.slider.maximum()
        return 0.0 if hi <= lo else (hi - self.slider.value()) / (hi - lo)

    def text(self) -> str:
        return "닫힘" if self.slider.value() >= self.slider.maximum() else f"{round(100 * self.fraction())}%"

    def set_bottom(self, text: str) -> None:
        """What the bottom end is called: 깊게 (앞쪽 절개) or 절반 (세로 단면)."""
        self.bottom_text = text
        self.update()

    def _track(self) -> tuple[float, float]:
        return float(TOP), float(max(TOP + 40, self.height() - BOTTOM))

    def handle_y(self) -> float:
        y0, y1 = self._track()
        return y0 + self.fraction() * (y1 - y0)

    def _set_from_y(self, y: float) -> None:
        y0, y1 = self._track()
        f = min(1.0, max(0.0, (y - y0) / (y1 - y0)))
        lo, hi = self.slider.minimum(), self.slider.maximum()
        self.slider.setValue(round(hi - f * (hi - lo)))

    # -- where it sits ----------------------------------------------------------------------------------
    def _place(self) -> None:
        eye = self.parentWidget()
        h = int(min(440, max(240, eye.height() * 0.6)))
        h = max(160, min(h, eye.height() - 24))
        self.setGeometry(max(0, eye.width() - WIDTH - MARGIN), max(0, (eye.height() - h) // 2), WIDTH, h)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self.slider and ev.type() == QEvent.Type.EnabledChange:
            self.setVisible(self.slider.isEnabled())
            if self.isVisible():
                self.raise_()
        elif obj is self.parentWidget() and ev.type() == QEvent.Type.Resize:
            self._place()
        return False

    # -- the mouse --------------------------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._set_from_y(ev.position().y())
            self.update()
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag:
            self._set_from_y(ev.position().y())
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        self._drag = False
        self.update()
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        ev.accept()                                    # (not the eye's: its double click resets the view)

    def wheelEvent(self, ev) -> None:
        """Up: toward the closed eye (the handle goes up); down: deeper."""
        self._wheel += ev.angleDelta().y() / 120.0 * WHEEL_STEP
        n = int(self._wheel)
        if n:
            self._wheel -= n
            s = self.slider
            v = max(s.minimum(), min(s.maximum(), s.value() + n))
            if v == s.value():
                self._wheel = 0.0
            s.setValue(v)
        ev.accept()

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

    # -- the picture -------------------------------------------------------------------------------------
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        accent, accent_hi = QColor(theme.ACCENT), QColor(theme.ACCENT_HI)
        active = self._drag or self._hover

        # the panel
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 12.0, 12.0)
        p.fillPath(panel, QColor(28, 28, 30, 225))
        p.setPen(QPen(accent if active else QColor(255, 255, 255, 46), 1.2))
        p.drawPath(panel)

        def label(y: float, height: float, text: str, px: int, bold: bool, color: QColor) -> None:
            f = QFont(self.font())
            f.setPixelSize(px)
            f.setBold(bold)
            p.setFont(f)
            p.setPen(color)
            p.drawText(QRectF(0.0, y, w, height), Qt.AlignmentFlag.AlignCenter, text)

        label(8.0, 18.0, "깊이", 13, True, QColor(theme.TEXT))
        label(28.0, 22.0, self.text(), 15, True, accent_hi)
        label(56.0, 16.0, "닫힘", 11, False, QColor(theme.TEXT3))
        label(h - 24.0, 16.0, self.bottom_text, 11, False, QColor(theme.TEXT3))

        # the track: quarter ticks, the groove, the part cut away in the accent colour
        cx = w / 2.0
        y0, y1 = self._track()
        p.setPen(QPen(QColor(theme.TEXT4), 1.4))
        for k in range(5):
            y = y0 + (y1 - y0) * k / 4.0
            p.drawLine(QPointF(cx - TRACK_W / 2 - 9, y), QPointF(cx - TRACK_W / 2 - 3, y))
            p.drawLine(QPointF(cx + TRACK_W / 2 + 3, y), QPointF(cx + TRACK_W / 2 + 9, y))
        groove = QRectF(cx - TRACK_W / 2, y0, TRACK_W, y1 - y0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.FILL))
        p.drawRoundedRect(groove, TRACK_W / 2, TRACK_W / 2)
        hy = self.handle_y()
        if hy > y0:
            p.setBrush(accent_hi if active else accent)
            p.drawRoundedRect(QRectF(groove.left(), y0, TRACK_W, hy - y0), TRACK_W / 2, TRACK_W / 2)

        # the handle: white with an accent ring, a glow while held
        if self._drag:
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 70))
            p.drawEllipse(QPointF(cx, hy), HANDLE_R + 6, HANDLE_R + 6)
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(accent_hi if active else accent, 3.0))
        p.drawEllipse(QPointF(cx, hy), HANDLE_R, HANDLE_R)
        p.setPen(QPen(QColor(theme.TEXT4), 1.6))
        for dy in (-2.5, 2.5):                         # grip: it moves up and down
            p.drawLine(QPointF(cx - 4.5, hy + dy), QPointF(cx + 4.5, hy + dy))
        p.end()
