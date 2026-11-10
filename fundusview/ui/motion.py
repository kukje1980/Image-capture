"""Motion like a phone's: nothing jumps, everything a finger lets go of keeps moving and settles.

* :class:`Decay`  — a flick: the speed at release dies away exponentially (rotation, panning).
* :class:`Chase`  — a value that follows its target smoothly (wheel zoom: every notch moves the
  target, the view glides after it; nothing overshoots).
* :class:`Tween`  — an eased transition of a fixed length (view changes, cross-fades).
* :class:`Velocity` — the speed of the last moments of a drag, to start a :class:`Decay` with.

All of them step on one shared timer (:func:`ticker`) with the real time between frames, so a slow
frame moves further instead of slowing the motion down. ``set_enabled(False)`` (보기 → 부드러운
움직임, or ``FUNDUSVIEW_NO_MOTION=1``) makes every animation finish at once: the same end state,
without the motion — for remote desktops and for tests.
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer

FRAME_MS = 8                       # the timer asks for 120 Hz; the screen shows what it can
_enabled = os.environ.get("FUNDUSVIEW_NO_MOTION", "") not in ("1", "true", "yes")


def enabled() -> bool:
    return _enabled


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)
    if not _enabled:
        ticker().finish_all()


def ease_out(t: float) -> float:
    """Fast start, soft landing (cubic)."""
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


class Ticker(QObject):
    """One timer for every running animation; stops by itself when nothing moves."""

    def __init__(self):
        super().__init__()
        self.manual = False            # tests: no timer, ``advance(dt)`` is called by hand
        self._anims: list = []
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._last = 0.0

    def add(self, anim) -> None:
        if anim not in self._anims:
            self._anims.append(anim)
        if not self._timer.isActive() and not self.manual:
            self._last = time.perf_counter()
            self._timer.start()

    def remove(self, anim) -> None:
        if anim in self._anims:
            self._anims.remove(anim)
        if not self._anims:
            self._timer.stop()

    def active(self) -> int:
        return len(self._anims)

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.25, max(1e-4, now - self._last))     # real time, so slow frames skip ahead — but no leaps
        self._last = now
        self.advance(dt)

    def advance(self, dt: float) -> None:
        """Step every animation by ``dt`` seconds (the timer does this; tests call it directly)."""
        for a in list(self._anims):
            if a in self._anims:
                try:
                    alive = a.step(dt)
                except RuntimeError:                    # its widget is gone
                    alive = False
                if not alive:
                    self.remove(a)

    def finish_all(self) -> None:
        for a in list(self._anims):
            try:
                a.finish()
            except RuntimeError:
                pass
            self.remove(a)


_ticker: Ticker | None = None


def ticker() -> Ticker:
    global _ticker
    if _ticker is None:
        _ticker = Ticker()
    return _ticker


class _Anim:
    def running(self) -> bool:
        return self in ticker()._anims

    def stop(self) -> None:
        """Stop where it is."""
        ticker().remove(self)

    def finish(self) -> None:        # pragma: no cover - overridden
        self.stop()

    def step(self, dt: float) -> bool:   # pragma: no cover - overridden
        return False


class Decay(_Anim):
    """A flick. ``move(dx, dy)`` is called with the distance of each frame until the speed has died
    away; ``tau`` is the time (s) in which the speed falls to 37 % (a phone's scrolling: ≈ 0.33)."""

    def __init__(self, move, tau: float = 0.30, stop_speed: float = 6.0, done=None):
        self._move, self.tau, self.stop_speed, self._done = move, tau, stop_speed, done
        self.vx = self.vy = 0.0

    def start(self, vx: float, vy: float) -> bool:
        """Start with the speed (units / s). False (and nothing moves) when it is too slow or motion is off."""
        self.stop()
        if not enabled() or math.hypot(vx, vy) < self.stop_speed * 4:
            return False
        self.vx, self.vy = float(vx), float(vy)
        ticker().add(self)
        return True

    def step(self, dt: float) -> bool:
        k = math.exp(-dt / self.tau)
        # the distance covered while the speed fell from v to v·k
        d = self.tau * (1.0 - k)
        self._move(self.vx * d, self.vy * d)
        self.vx *= k
        self.vy *= k
        if math.hypot(self.vx, self.vy) < self.stop_speed:
            if self._done:
                self._done()
            return False
        return True

    def finish(self) -> None:
        self.stop()


class Chase(_Anim):
    """An amount to hand out smoothly: ``add(x)`` puts ``x`` in the pot, each frame ``apply(part)``
    receives a share of what is left (half of it every ``half_life`` seconds). Wheel zoom: the
    notches go in, the view receives them as a glide; more notches while it glides just add up."""

    def __init__(self, apply, half_life: float = 0.055, eps: float = 1e-3, done=None):
        self._apply, self.half_life, self.eps, self._done = apply, half_life, eps, done
        self.left = 0.0

    def add(self, amount: float) -> None:
        if not enabled():
            self._apply(float(amount))
            return
        self.left += float(amount)
        ticker().add(self)

    def step(self, dt: float) -> bool:
        part = self.left * (1.0 - 0.5 ** (dt / self.half_life))
        if abs(self.left - part) < self.eps:
            part = self.left
        self.left -= part
        self._apply(part)
        if self.left == 0.0:
            if self._done:
                self._done()
            return False
        return True

    def stop(self) -> None:
        self.left = 0.0
        super().stop()

    def finish(self) -> None:
        left, self.left = self.left, 0.0
        super().stop()
        if left:
            self._apply(left)


class Tween(_Anim):
    """``update(k)`` with ``k`` easing from 0 to 1 over ``duration`` seconds, then ``done()``."""

    def __init__(self, update, duration: float = 0.3, easing=ease_out, done=None):
        self._update, self.duration, self._easing, self._done = update, duration, easing, done
        self._t = 0.0
        self._live = False

    def start(self, duration: float | None = None) -> None:
        self.stop()
        if duration is not None:
            self.duration = duration
        self._t, self._live = 0.0, True
        if not enabled() or self.duration <= 0.0:
            self.finish()
            return
        self._update(0.0)
        ticker().add(self)

    def running(self) -> bool:
        return self._live

    def step(self, dt: float) -> bool:
        self._t += dt
        t = self._t / self.duration
        if t >= 1.0:
            self.finish()
            return False
        self._update(self._easing(t))
        return True

    def stop(self) -> None:
        self._live = False
        super().stop()

    def finish(self) -> None:
        """Jump to the end (the goal is reached, ``done`` is told)."""
        if not self._live:
            return
        self._live = False
        ticker().remove(self)
        self._update(1.0)
        if self._done:
            self._done()


class Velocity:
    """Speed of the last moments of a drag (positions fed with ``add``), in units / s."""

    WINDOW = 0.09          # seconds looked back
    STALE = 0.06           # a finger that rested this long before letting go has no speed

    def __init__(self):
        self._pts: list[tuple[float, float, float]] = []

    def reset(self) -> None:
        self._pts.clear()

    def add(self, x: float, y: float, t: float | None = None) -> None:
        t = time.perf_counter() if t is None else t
        self._pts.append((t, float(x), float(y)))
        while len(self._pts) > 2 and t - self._pts[0][0] > self.WINDOW:
            self._pts.pop(0)

    def get(self, now: float | None = None) -> tuple[float, float]:
        now = time.perf_counter() if now is None else now
        if len(self._pts) < 2 or now - self._pts[-1][0] > self.STALE:
            return 0.0, 0.0
        (t0, x0, y0), (t1, x1, y1) = self._pts[0], self._pts[-1]
        dt = t1 - t0
        if dt < 1e-3:
            return 0.0, 0.0
        return (x1 - x0) / dt, (y1 - y0) / dt


class SmoothWheel(QObject):
    """The wheel scrolls a list or the photo strip in a glide instead of jumps."""

    def __init__(self, area, step: float = 96.0):
        super().__init__(area)
        self.area, self.step = area, step
        self._bar = None
        self._rest = 0.0
        self._chase = Chase(self._move, half_life=0.06, eps=0.4)
        area.viewport().installEventFilter(self)

    def eventFilter(self, obj, e) -> bool:
        if e.type() != QEvent.Type.Wheel or not enabled():
            return False
        v, h = self.area.verticalScrollBar(), self.area.horizontalScrollBar()
        bar = v if v.maximum() > v.minimum() else h
        if bar.maximum() <= bar.minimum():
            return False
        d = e.angleDelta()
        notches = (d.y() if d.y() else d.x()) / 120.0
        if bar is not self._bar:
            self._chase.stop()
            self._bar, self._rest = bar, 0.0
        self._chase.add(-notches * self.step)
        return True

    def _move(self, d: float) -> None:
        if self._bar is None:
            return
        self._rest += d
        whole = int(self._rest)
        self._rest -= whole
        if whole:
            before = self._bar.value()
            self._bar.setValue(before + whole)
            if self._bar.value() == before:          # the end of the list
                self._chase.stop()
                self._rest = 0.0
