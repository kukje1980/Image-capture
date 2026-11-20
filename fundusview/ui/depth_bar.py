"""깊이 막대 · 배율 막대: bars floating over the 3D eye that set how deep the eye is cut open and how
much it is magnified.

Each is a slider of the 3D tab (깊이 of ``안구 열기``, the 확대 바) drawn where the eye is, made to be found
at a glance: its own see-through dark panel with its title and the value in figures, a thick track filled
in the accent colour, a large round handle, ticks every quarter and the two ends named. The slider stays
the one value: the bar reads it and sets it, follows its range, and is shown only while the slider is
enabled (the depth: outside the eye).

* drag the handle (or press anywhere on the track), or turn the wheel over the bar;
* **double click**: the bar lies down (가로) or stands up (세로), as a toolbar;
* drag it by anything but the track: it moves over the eye and stays there (``state()``);
* ☑ 휠 (``checkable``): the bar whose box is checked is what the wheel over the eye itself does.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSlider, QWidget

from . import theme

WIDTH = 64               # standing (세로): its width; lying (가로): LYING_H high
LYING_H = 58
MARGIN = 14              # from the eye's edge
TOP = 82                 # standing: the track's top, below the title, the figure and the top end's name
CHECK_H = 22             # … and ☑ 휠, where there is one
BOTTOM = 30              # the track's bottom from the bar's
HANDLE_R = 11.0
TRACK_W = 8.0
WHEEL_STEP = 4           # slider units per wheel notch (as the wheel over the eye in 깊이)


class FloatBar(QWidget):
    """A slider as a bar floating over ``eye``. Standing, the slider's maximum is at the top; lying, at
    the right."""
    TITLE = ""
    TIP = ""
    ORIENT = "v"             # as it is at first: "v" standing, "h" lying
    FILL_FROM_MAX = False    # the accent fill runs from the maximum's end to the handle (else from the minimum's)
    STEP = WHEEL_STEP
    MOVABLE = True           # dragged over the eye and laid down / stood up by hand (else it stays as it is)
    TITLE_W = 62.0           # lying: the room of the title and the figure (one above the other)
    ONE_LINE = False         # lying: the title and the figure side by side (a thin bar)

    placed = Signal()            # moved, or laid down / stood up, by hand (``state()`` to remember it)
    checkToggled = Signal(bool)  # ☑ 휠 pressed: what it should become (the owner answers with set_checked)

    def __init__(self, slider: QSlider, eye: QWidget, checkable: bool = False):
        super().__init__(eye)
        self.slider = slider
        self.checkable = checkable
        self.checked = False
        self.orient = self.ORIENT
        self.max_text, self.min_text = "", ""
        self._pos: tuple[float, float] | None = None   # where it was put (fractions of the free room); None: home
        self._drag = False                             # the handle
        self._move: QPoint | None = None               # the bar itself: the press, in the bar
        self._moved = False
        self._before: int | None = None                # the value before the press (a double click puts it back)
        self._hover = False
        self._wheel = 0.0
        self.setToolTip(self.TIP)
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
        """0 at the slider's maximum (standing: the top) … 1 at its minimum (the bottom)."""
        lo, hi = self.slider.minimum(), self.slider.maximum()
        return 0.0 if hi <= lo else (hi - self.slider.value()) / (hi - lo)

    def text(self) -> str:
        return str(self.slider.value())

    def vertical(self) -> bool:
        return self.orient == "v"

    def _track(self) -> tuple[float, float]:
        """The two ends of the track along the bar: standing top, bottom; lying left, right."""
        if self.vertical():
            top = TOP + (CHECK_H if self.checkable else 0)
            return float(top), float(max(top + 40, self.height() - BOTTOM))
        x0 = 10.0 + (36.0 if self.checkable else 0.0) + self.TITLE_W + 42.0 + HANDLE_R
        return x0, max(x0 + 40.0, self.width() - 10.0 - 42.0 - HANDLE_R)

    def handle_pos(self) -> float:
        a, b = self._track()
        return a + self.fraction() * (b - a) if self.vertical() else b - self.fraction() * (b - a)

    def handle_y(self) -> float:
        return self.handle_pos()

    def _set_from_pos(self, t: float) -> None:
        a, b = self._track()
        f = min(1.0, max(0.0, (t - a) / (b - a)))
        lo, hi = self.slider.minimum(), self.slider.maximum()
        self.slider.setValue(round(hi - f * (hi - lo)) if self.vertical() else round(lo + f * (hi - lo)))

    def _set_from_y(self, y: float) -> None:
        self._set_from_pos(y)

    def _along(self, pos) -> float:
        return pos.y() if self.vertical() else pos.x()

    def _on_track(self, pos) -> bool:
        a, b = self._track()
        return a - HANDLE_R - 4 <= self._along(pos) <= b + HANDLE_R + 4

    # -- ☑ 휠 --------------------------------------------------------------------------------------------
    def _check_rect(self) -> QRectF | None:
        """Where ☑ 휠 is pressed (the box and its word)."""
        if not self.checkable:
            return None
        return QRectF(6.0, 52.0, self.width() - 12.0, 22.0) if self.vertical() else QRectF(8.0, 6.0, 36.0, self.height() - 12.0)

    def set_checked(self, on: bool) -> None:
        if self.checked != bool(on):
            self.checked = bool(on)
            self.update()

    # -- where it sits ----------------------------------------------------------------------------------
    def _size(self) -> tuple[int, int]:
        eye = self.parentWidget()
        if self.vertical():
            h = int(min(440, max(240, eye.height() * 0.6))) + (CHECK_H if self.checkable else 0)
            return WIDTH, max(160, min(h, eye.height() - 24))
        w = int(min(460, max(300, eye.width() * 0.42)))
        return max(220, min(w, eye.width() - 24)), LYING_H

    def _home(self, w: int, h: int) -> tuple[int, int]:
        """Where it is until it is moved: the middle of the eye's right edge."""
        eye = self.parentWidget()
        return eye.width() - w - MARGIN, (eye.height() - h) // 2

    def _place(self) -> None:
        eye = self.parentWidget()
        w, h = self._size()
        if self._pos is None:
            x, y = self._home(w, h)
        else:
            x, y = round(self._pos[0] * (eye.width() - w)), round(self._pos[1] * (eye.height() - h))
        self.setGeometry(max(0, min(x, eye.width() - w)), max(0, min(y, eye.height() - h)), w, h)

    def _remember(self) -> None:
        eye = self.parentWidget()
        fw, fh = max(1, eye.width() - self.width()), max(1, eye.height() - self.height())
        self._pos = (min(1.0, max(0.0, self.x() / fw)), min(1.0, max(0.0, self.y() / fh)))

    def set_orientation(self, orient: str) -> None:
        """Lie down ("h") or stand up ("v"), around where the bar is."""
        orient = "h" if orient == "h" else "v"
        if orient == self.orient:
            return
        eye, c = self.parentWidget(), self.geometry().center()
        self.orient = orient
        w, h = self._size()
        self.setGeometry(max(0, min(c.x() - w // 2, eye.width() - w)), max(0, min(c.y() - h // 2, eye.height() - h)), w, h)
        self._remember()
        self.update()

    def state(self) -> str:
        """Orientation and place, to remember: ``""`` as at first, else ``"h"`` or ``"v:0.250:0.900"``."""
        if self._pos is None:
            return "" if self.orient == self.ORIENT else self.orient
        return f"{self.orient}:{self._pos[0]:.3f}:{self._pos[1]:.3f}"

    def set_state(self, state: str) -> None:
        parts = str(state or "").split(":")
        self.orient = parts[0] if parts[0] in ("v", "h") else self.ORIENT
        try:
            self._pos = (min(1.0, max(0.0, float(parts[1]))), min(1.0, max(0.0, float(parts[2]))))
        except (IndexError, ValueError):
            self._pos = None
        self._place()
        self.update()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self.slider and ev.type() == QEvent.Type.EnabledChange:
            self.setVisible(self.slider.isEnabled())
            if self.isVisible():
                self.raise_()
        elif obj is self.parentWidget() and ev.type() == QEvent.Type.Resize:
            self._place()
        return False

    # -- the mouse --------------------------------------------------------------------------------------
    def _cursor(self, pos) -> None:
        check = self._check_rect()
        if check is not None and check.contains(QPointF(pos)):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._on_track(pos):
            self.setCursor(Qt.CursorShape.SizeVerCursor if self.vertical() else Qt.CursorShape.SizeHorCursor)
        elif self.MOVABLE:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position()
            check = self._check_rect()
            self._before = None
            if check is not None and check.contains(pos):
                self.checkToggled.emit(not self.checked)
            elif self._on_track(pos):
                self._drag = True
                self._before = self.slider.value()
                self._set_from_pos(self._along(pos))
            elif self.MOVABLE:
                self._move, self._moved = pos.toPoint(), False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        if self._drag:
            self._set_from_pos(self._along(pos))
        elif self._move is not None:
            eye = self.parentWidget()
            to = self.mapToParent(pos.toPoint()) - self._move
            if self._moved or (to - self.pos()).manhattanLength() >= 4:
                self._moved = True
                self.move(max(0, min(to.x(), eye.width() - self.width())), max(0, min(to.y(), eye.height() - self.height())))
        else:
            self._cursor(pos)
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if self._move is not None and self._moved:
            self._remember()
            self.placed.emit()
        self._drag, self._move, self._moved = False, None, False
        self._cursor(ev.position())
        self.update()
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        """Lie down ↔ stand up (not the eye's double click, which resets the view)."""
        check = self._check_rect()
        if (self.MOVABLE and ev.button() == Qt.MouseButton.LeftButton
                and not (check is not None and check.contains(ev.position()))):
            if self._before is not None:               # (the first press was on the track: as it was)
                self.slider.setValue(self._before)
                self._before = None
            self.set_orientation("h" if self.vertical() else "v")
            self.placed.emit()
        ev.accept()

    def wheelEvent(self, ev) -> None:
        """Up: toward the slider's maximum (the closed eye, larger); down: toward its minimum."""
        self._wheel += ev.angleDelta().y() / 120.0 * self.STEP
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
        active = self._drag or self._hover or self._move is not None
        vert = self.vertical()

        # the panel: see-through over the eye, denser under the mouse
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 12.0, 12.0)
        p.fillPath(panel, QColor(28, 28, 30, 205 if active else 140))
        p.setPen(QPen(accent if active else QColor(255, 255, 255, 46), 1.2))
        p.drawPath(panel)

        def label(rect: QRectF, text: str, px: int, bold: bool, color: QColor) -> None:
            f = QFont(self.font())
            f.setPixelSize(px)
            f.setBold(bold)
            p.setFont(f)
            p.setPen(color)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        def check_box(x: float, y: float) -> None:      # ☑: this bar is what the wheel over the eye does
            box = QRectF(x, y, 14.0, 14.0)
            p.setPen(QPen(accent_hi if self.checked else QColor(theme.TEXT3), 1.4))
            p.setBrush(accent if self.checked else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 3.5, 3.5)
            if self.checked:
                p.setPen(QPen(QColor("#ffffff"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                tick = QPainterPath(QPointF(x + 3.2, y + 7.4))
                tick.lineTo(x + 6.0, y + 10.2)
                tick.lineTo(x + 10.8, y + 4.0)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(tick)

        a, b = self._track()
        text3, wheel_color = QColor(theme.TEXT3), QColor(theme.TEXT if self.checked else theme.TEXT3)
        if vert:
            label(QRectF(0.0, 8.0, w, 18.0), self.TITLE, 13, True, QColor(theme.TEXT))
            label(QRectF(0.0, 28.0, w, 22.0), self.text(), 15, True, accent_hi)
            if self.checkable:
                check_box(w / 2 - 17.0, 56.0)
                label(QRectF(w / 2 - 1.0, 54.0, 20.0, 18.0), "휠", 11, self.checked, wheel_color)
            label(QRectF(0.0, a - 26.0, w, 16.0), self.max_text, 11, False, text3)
            label(QRectF(0.0, h - 24.0, w, 16.0), self.min_text, 11, False, text3)
        else:
            x = 10.0
            if self.checkable:
                check_box(x + 10.0, 12.0)
                label(QRectF(x, 30.0, 34.0, 18.0), "휠", 11, self.checked, wheel_color)
                x += 36.0
            if self.ONE_LINE:
                label(QRectF(x, 0.0, 38.0, h), self.TITLE, 12, True, QColor(theme.TEXT))
                label(QRectF(x + 38.0, 0.0, self.TITLE_W - 38.0, h), self.text(), 13, True, accent_hi)
            else:
                label(QRectF(x, 8.0, 62.0, 18.0), self.TITLE, 13, True, QColor(theme.TEXT))
                label(QRectF(x, 28.0, 62.0, 22.0), self.text(), 15, True, accent_hi)
            label(QRectF(a - HANDLE_R - 42.0, 0.0, 42.0, h), self.min_text, 11, False, text3)
            label(QRectF(b + HANDLE_R, 0.0, 42.0, h), self.max_text, 11, False, text3)

        # the track: quarter ticks, the groove, the filled part in the accent colour
        def pt(t: float, across: float) -> QPointF:     # a point at t along the track, ``across`` off its axis
            return QPointF(w / 2.0 + across, t) if vert else QPointF(t, h / 2.0 + across)

        def bar_rect(t0: float, t1: float) -> QRectF:
            return (QRectF(w / 2.0 - TRACK_W / 2, t0, TRACK_W, t1 - t0) if vert
                    else QRectF(t0, h / 2.0 - TRACK_W / 2, t1 - t0, TRACK_W))

        p.setPen(QPen(QColor(theme.TEXT4), 1.4))
        for k in range(5):
            t = a + (b - a) * k / 4.0
            p.drawLine(pt(t, -TRACK_W / 2 - 9), pt(t, -TRACK_W / 2 - 3))
            p.drawLine(pt(t, TRACK_W / 2 + 3), pt(t, TRACK_W / 2 + 9))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.FILL))
        p.drawRoundedRect(bar_rect(a, b), TRACK_W / 2, TRACK_W / 2)
        ht = self.handle_pos()
        from_start = self.FILL_FROM_MAX == vert         # the maximum is at the track's start when standing
        t0, t1 = (a, ht) if from_start else (ht, b)
        if t1 > t0:
            p.setBrush(accent_hi if active else accent)
            p.drawRoundedRect(bar_rect(t0, t1), TRACK_W / 2, TRACK_W / 2)

        # the handle: white with an accent ring, a glow while held
        if self._drag:
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 70))
            p.drawEllipse(pt(ht, 0.0), HANDLE_R + 6, HANDLE_R + 6)
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(accent_hi if active else accent, 3.0))
        p.drawEllipse(pt(ht, 0.0), HANDLE_R, HANDLE_R)
        p.setPen(QPen(QColor(theme.TEXT4), 1.6))
        for d in (-2.5, 2.5):                           # grip: across the way it moves
            p.drawLine(pt(ht + d, -4.5), pt(ht + d, 4.5))
        p.end()


MOVE_TIP = " · 더블클릭: 가로 ↔ 세로 · 막대의 빈 곳을 끌어 옮기기"
CHECK_TIP = " · ☑ 휠: 체크한 막대가 3D 화면 위 마우스 휠의 기본 동작"


class DepthBar(FloatBar):
    """깊이 막대: how deep the eye is cut open — the maximum's end 닫힘 (the closed eye), the other 깊게
    (or 절반 for 세로 단면). At first standing at the eye's right edge."""
    TITLE = "깊이"
    TIP = ("깊이 막대 — 끌어서 안구를 자르는 깊이를 정합니다 (닫힘 = 닫힌 안구, 반대쪽으로 갈수록 깊게) · "
           "막대 위에서 휠로도 조절" + MOVE_TIP)
    FILL_FROM_MAX = True

    def __init__(self, slider: QSlider, eye: QWidget, checkable: bool = False):
        super().__init__(slider, eye, checkable)
        self.setObjectName("depthBar3d")
        self.max_text, self.min_text = "닫힘", "깊게"
        if checkable:
            self.setToolTip(self.TIP + CHECK_TIP)

    @property
    def bottom_text(self) -> str:
        return self.min_text

    def text(self) -> str:
        return "닫힘" if self.slider.value() >= self.slider.maximum() else f"{round(100 * self.fraction())}%"

    def set_bottom(self, text: str) -> None:
        """What the deep end is called: 깊게 (앞쪽 절개) or 절반 (세로 단면)."""
        self.min_text = text
        self.update()


class TopDepthBar(DepthBar):
    """The 깊이 막대 of all the eyes at once (여러 장 3D with many eyes): lying in a strip above them, in
    its middle, where it stays (not dragged, not stood up)."""
    ORIENT = "h"
    MOVABLE = False
    ONE_LINE = True
    TITLE_W = 84.0
    HEIGHT = 34              # thin: 깊이 and its figure on one line
    TIP = ("깊이 막대 — 끌어서 모든 안구를 자르는 깊이를 한꺼번에 정합니다 (닫힘 = 닫힌 안구, 반대쪽으로 "
           "갈수록 깊게) · 막대 위에서 휠로도 조절")

    def __init__(self, slider: QSlider, strip: QWidget):
        super().__init__(slider, strip)
        self.setObjectName("depthBarAll3d")

    def _size(self) -> tuple[int, int]:
        strip = self.parentWidget()
        return max(220, min(560, strip.width() - 24)), self.HEIGHT

    def _home(self, w: int, h: int) -> tuple[int, int]:
        strip = self.parentWidget()
        return (strip.width() - w) // 2, (strip.height() - h) // 2


class ZoomBar(FloatBar):
    """배율 막대: the magnification of the 3D eye (the slider is 100 · log2 of it). At first lying at the
    eye's top left."""
    TITLE = "배율"
    TIP = ("배율 막대 — 끌어서 확대 · 축소합니다 (화면 가운데를 중심으로) · 막대 위에서 휠로도 조절"
           + MOVE_TIP)
    ORIENT = "h"
    STEP = 12

    def __init__(self, slider: QSlider, eye: QWidget, checkable: bool = False):
        super().__init__(slider, eye, checkable)
        self.setObjectName("zoomBar3d")
        self.max_text = f"×{2.0 ** (slider.maximum() / 100.0):.0f}"
        self.min_text = f"×{2.0 ** (slider.minimum() / 100.0):.1f}"
        if checkable:
            self.setToolTip(self.TIP + CHECK_TIP)

    def text(self) -> str:
        return f"×{2.0 ** (self.slider.value() / 100.0):.1f}"

    def _home(self, w: int, h: int) -> tuple[int, int]:
        return MARGIN, MARGIN
