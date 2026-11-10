"""부드러운 움직임 (motion.py): flicks that settle, a wheel zoom that glides, eased view changes —
in the 2D view and on the 3D eye — and the same end state with the motion switched off."""
import math
import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def live(app):
    """Motion on, with the clock in the test's hands: ``live(seconds)`` lets that much time pass."""
    from fundusview.ui import motion

    t = motion.ticker()
    was, t.manual = motion.enabled(), True
    motion.set_enabled(True)

    def run(seconds: float, dt: float = 1 / 120) -> None:
        for _ in range(int(round(seconds / dt))):
            t.advance(dt)

    yield run
    t.finish_all()
    t.manual = False
    motion.set_enabled(was)


def test_decay_is_a_flick_that_settles(live):
    from fundusview.ui import motion

    moved = []
    d = motion.Decay(lambda dx, dy: moved.append((dx, dy)), tau=0.3, stop_speed=5.0)
    assert d.start(1000.0, -500.0) and d.running()
    live(0.05)
    first = len(moved)
    live(4.0)
    assert not d.running() and len(moved) > first
    xs = [m[0] for m in moved]
    assert all(a >= b > 0 for a, b in zip(xs, xs[1:]))                  # ever slower, never back
    assert sum(xs) == pytest.approx(1000.0 * 0.3, rel=0.02)            # distance = speed × tau
    assert sum(m[1] for m in moved) == pytest.approx(-500.0 * 0.3, rel=0.02)
    assert not d.start(10.0, 0.0) and not d.running()                    # too slow to be a flick
    motion.set_enabled(False)
    assert not d.start(1000.0, 0.0)                                      # off: nothing keeps moving


def test_chase_hands_out_exactly_what_went_in(live):
    from fundusview.ui import motion

    parts = []
    c = motion.Chase(parts.append, half_life=0.05)
    c.add(3.0)
    assert parts == [] and c.running()                                   # nothing jumps
    live(0.05)
    assert sum(parts) == pytest.approx(1.5, rel=0.02)                    # half of it after a half-life
    c.add(1.0)                                                           # more notches while gliding
    live(2.0)
    assert not c.running() and sum(parts) == pytest.approx(4.0, abs=1e-9)
    c.add(2.0)
    c.finish()                                                           # be there now
    assert sum(parts) == pytest.approx(6.0, abs=1e-9) and not c.running()
    motion.set_enabled(False)
    c.add(5.0)
    assert parts[-1] == 5.0 and not c.running()                          # off: at once


def test_tween_eases_and_reports_the_end_once(live):
    from fundusview.ui import motion

    seen, done = [], []
    t = motion.Tween(seen.append, 0.3, done=lambda: done.append(1))
    t.start()
    live(0.15)
    assert t.running() and 0.5 < seen[-1] < 1.0 and seen == sorted(seen)   # fast start, soft landing
    live(0.3)
    assert not t.running() and seen[-1] == 1.0 and done == [1]
    t.finish()
    assert done == [1]
    t.start()
    live(0.05)
    t.finish()
    assert seen[-1] == 1.0 and done == [1, 1]
    motion.set_enabled(False)
    seen.clear()
    t.start()
    assert seen == [1.0] and done == [1, 1, 1]


def test_velocity_of_the_last_moments():
    from fundusview.ui.motion import Velocity

    v = Velocity()
    for i in range(10):
        v.add(i * 10.0, -i * 5.0, t=i * 0.01)                           # 1000 px/s right, 500 up
    vx, vy = v.get(now=0.09)
    assert vx == pytest.approx(1000.0, rel=0.01) and vy == pytest.approx(-500.0, rel=0.01)
    assert v.get(now=0.09 + 0.2) == (0.0, 0.0)                           # rested before letting go
    v.reset()
    assert v.get(now=0.0) == (0.0, 0.0)


def _view(app):
    from fundusview.demo import synth_fundus
    from fundusview.ui.image_view import ImageView

    v = ImageView()
    v.resize(640, 480)
    v.show()
    v.set_rgb(synth_fundus(size=(800, 800)))
    app.processEvents()
    return v


def _wheel(app, widget, pos, notches):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    p = QPointF(pos)
    app.sendEvent(widget, QWheelEvent(p, QPointF(widget.mapToGlobal(pos)), QPoint(0, 0),
                                      QPoint(0, int(120 * notches)), Qt.MouseButton.NoButton,
                                      Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))


def test_2d_wheel_zoom_glides_to_where_a_jump_would_land(app, live):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from fundusview.ui import motion

    v = _view(app)
    try:
        z0 = v.zoom
        at = QPoint(400, 200)
        under = v.mapToScene(at)
        _wheel(app, v.viewport(), at, 3)
        assert v.zoom == z0                                              # nothing jumps
        live(0.05)
        assert z0 < v.zoom < z0 * 1.15 ** 3
        live(1.5)
        assert v.zoom == pytest.approx(z0 * 1.15 ** 3, rel=1e-6)        # the same end as before
        now = v.mapToScene(at)
        assert abs(now.x() - under.x()) < 2 and abs(now.y() - under.y()) < 2   # the cursor's spot stayed
        # a press stops a glide where it is
        _wheel(app, v.viewport(), at, 4)
        live(0.03)
        mid = v.zoom
        QTest.mousePress(v.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, at)
        QTest.mouseRelease(v.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, at)
        live(0.5)
        assert v.zoom == mid
        # 맞춤 eases back to the whole photo
        v.fit(animate=True)
        assert v.zoom == mid
        live(0.1)
        assert z0 < v.zoom < mid
        live(0.5)
        assert v.zoom == pytest.approx(v._fit_zoom()) and v._fit
        # off: the wheel jumps as it always did
        motion.set_enabled(False)
        _wheel(app, v.viewport(), at, 1)
        assert v.zoom == pytest.approx(v._fit_zoom() * 1.15)
    finally:
        v.close()


def test_2d_flick_keeps_sliding_and_stops_at_the_edge(app, live):
    v = _view(app)
    try:
        v._zoom_at(3.0, v.viewport().rect().center())
        h = v.horizontalScrollBar()
        h.setValue((h.minimum() + h.maximum()) // 2)
        start = h.value()
        v._fling_rest = [0.0, 0.0]
        assert v._fling.start(-900.0, 0.0)                               # dragged left and let go
        live(0.1)
        early = h.value()
        assert early > start                                             # the photo keeps going left
        live(3.0)
        assert not v._fling.running() and early < h.value() <= h.maximum()
        assert h.value() - start == pytest.approx(900.0 * v._fling.tau, rel=0.06)
        h.setValue(h.maximum())
        assert v._fling.start(-3000.0, 0.0)
        live(0.05)
        assert not v._fling.running()                                    # the edge: nothing to slide
    finally:
        v.close()


def _eye(app, monkeypatch, detail="detailed"):
    from fundusview.ui.eye3d import EyeView

    e = EyeView()
    e.resize(640, 420)
    e.set_mapping(fov_deg=135.0, fov_type="internal", projection="equidistant")
    e.set_disc("OD", None, None)
    e.detail = detail
    monkeypatch.setattr(e, "isVisible", lambda: True)                    # no OpenGL needed for the motion
    return e


def test_3d_flick_wheel_and_view_glides(app, live, monkeypatch):
    e = _eye(app, monkeypatch)
    yaw0 = e.yaw
    e._drag_kind = "rotate"
    assert e._fling.start(500.0, 0.0)
    live(0.1)
    y1 = e.yaw
    live(3.0)
    turned = (yaw0 - e.yaw) % 360.0
    assert not e.moving() and 0 < (yaw0 - y1) % 360 < turned
    assert turned == pytest.approx(500.0 * 0.4 * e._fling.tau, rel=0.05)   # 0.4° per pixel, as when dragging
    # the wheel: the same distance as three jumps, reached in a glide
    d0 = e.dist
    e._zoom_pos = None
    e._zoom_glide.add(3.0)
    assert e.dist == d0
    live(0.04)
    assert d0 * 0.88 ** 3 < e.dist < d0
    live(1.0)
    assert e.dist == pytest.approx(d0 * 0.88 ** 3, rel=1e-6)
    # a view change takes the short way round and lands exactly
    e.yaw, e.pitch = 350.0, 0.0
    e.glide_to({"yaw": 10.0, "pitch": 5.0, "dist": 2.0, "target": (0.1, 0.0, 0.0)}, duration=0.4)
    live(0.2)
    assert e.yaw > 350.0 or e.yaw < 10.0                                 # through 0°, not back through 180°
    live(0.4)
    assert (e.yaw, e.pitch, e.dist) == (pytest.approx(10.0), pytest.approx(5.0), pytest.approx(2.0))
    assert np.allclose(e.target, (0.1, 0.0, 0.0))
    e.reset_view(animate=True)                                           # 더블클릭 / 0
    live(0.2)
    assert e.moving()
    live(0.6)
    assert (e.yaw, e.pitch, e.dist) == (pytest.approx(38.0), pytest.approx(18.0), pytest.approx(e.DIST0))


def test_3d_enters_through_the_pupil_and_back(app, live, monkeypatch):
    from fundusview.ui import motion

    e = _eye(app, monkeypatch)
    e.cut = 0.25
    e.enter("inside")
    assert e.mode == "outside" and e.moving()
    live(0.5)
    assert e.mode == "outside" and e.cut > 0.9 and e.dark == 0.0        # the eye closes, seen from the front
    live(0.55)
    assert e.mode == "outside" and e.dark > 0.5 and e.dist < 1.6        # diving at the pupil, into the dark
    live(0.3)
    assert e.mode == "inside" and e.in_fov < e.FOV0 and e.dark < 1.0    # inside, opening up
    live(1.0)
    assert not e.moving()
    assert (e.mode, e.dark, e.cut, e.in_fov) == ("inside", 0.0, 0.25, pytest.approx(e.FOV0))
    # back out — and a touch on the way ends it at once, at the goal
    e.enter("outside")
    live(0.3)
    assert e.moving()
    e.stop_motion()
    assert not e.moving()
    assert (e.mode, e.dark, e.cut) == ("outside", 0.0, 0.25)
    assert (e.yaw, e.pitch, e.dist) == (38.0, 18.0, e.DIST0)
    # the simple model has no pupil to fly through: a fade through black
    s = _eye(app, monkeypatch, detail="simple")
    s.enter("inside")
    live(0.15)
    assert s.mode == "outside" and 0.0 < s.dark < 1.0
    live(0.6)
    assert (s.mode, s.dark) == ("inside", 0.0) and not s.moving()
    # off: just there
    motion.set_enabled(False)
    s.enter("outside")
    assert (s.mode, s.dark) == ("outside", 0.0) and not s.moving()


def test_3d_auto_rotate_waits_for_idle_hands(app, live, monkeypatch):
    import time

    e = _eye(app, monkeypatch)
    e.set_auto_rotate(12.0)
    yaw0 = e.yaw
    live(0.5)
    assert e.yaw == yaw0                                                 # just touched: not yet
    e._touched = time.perf_counter() - 10.0                              # left alone for a while
    live(1.0)
    turned = (e.yaw - yaw0) % 360.0
    assert turned == pytest.approx(12.0, rel=0.05)
    e._drag = object()                                                   # a finger on it: it holds still
    held = e.yaw
    live(0.5)
    assert e.yaw == held
    e._drag = None
    e.set_auto_rotate(0.0)
    e._touched = time.perf_counter() - 10.0
    live(0.5)
    assert e.yaw == held and not e._spin.running()


def test_3d_draws_smaller_only_while_moving_on_a_slow_computer(app, monkeypatch):
    e = _eye(app, monkeypatch)
    e._render_ms = 8.0                                                   # a fast frame: always full size
    e._drag = object()
    assert e._pick_scale() == 1.0
    e._render_ms = 60.0                                                  # slow, and moving
    assert e._pick_scale() == 0.5
    e._render_ms = 30.0
    assert e._pick_scale() == 0.65
    e._force_full = True                                                 # a saved picture is sharp
    assert e._pick_scale() == 1.0
    e._drag, e._paint_end = None, 0.0                                    # at rest
    assert e._pick_scale() == 1.0
    e.adaptive = False
    e._drag = object()
    assert e._pick_scale() == 1.0
    e._note_render(10.0, 0.5)                                            # a half-size frame of 10 ms ≈ 40 ms full
    assert math.isclose(e._render_ms, 0.6 * 30.0 + 0.4 * 40.0)


def test_smooth_wheel_scrolls_a_list_in_a_glide(app, live):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QAbstractItemView, QListWidget

    from fundusview.ui import motion

    lw = QListWidget()
    lw.addItems([f"item {i}" for i in range(200)])
    lw.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    lw.resize(200, 300)
    lw.show()
    app.processEvents()
    sw = motion.SmoothWheel(lw, step=100.0)
    bar = lw.verticalScrollBar()
    try:
        _wheel(app, lw.viewport(), QPoint(50, 50), -2)                   # two notches down
        assert bar.value() == 0
        live(0.06)
        assert 0 < bar.value() < 200
        live(1.5)
        assert bar.value() == pytest.approx(200, abs=1)
        _wheel(app, lw.viewport(), QPoint(50, 50), 50)                   # far past the top: stops there
        live(1.5)
        assert bar.value() == 0 and not sw._chase.running()
    finally:
        lw.close()
