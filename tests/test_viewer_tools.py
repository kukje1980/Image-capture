"""VK-2 style viewer tools: drag zoom, measurements, processing stack, multi view."""
import math
import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fundusview import imaging, measure  # noqa: E402
from fundusview.demo import synth_fundus  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(app):
    from fundusview.ui.image_view import ImageView
    v = ImageView()
    v.resize(800, 600)
    v.show()
    rgb = synth_fundus(eye="OD", fov_deg=176, fov_type="internal", projection="radial", size=(800, 600),
                       circle=(400, 300, 290), seed=5)
    v.set_rgb(rgb)
    v.geometry = measure.Geometry(400, 300, 290, 176, "internal", "radial")
    app.processEvents()
    yield v
    # Taken down here, not left on screen for the garbage collector: a view holds itself in reference
    # cycles, so a dropped one stayed shown until some later collection deleted it — at any moment,
    # once while it was being painted (a segmentation fault in a later test's processEvents).
    from PySide6.QtCore import QCoreApplication, QEvent
    v.close()
    v.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _drag(view, button, a, b, steps=6):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    vp = view.viewport()
    QTest.mousePress(vp, button, pos=QPoint(*a))
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, QPoint(int(a[0] + (b[0] - a[0]) * i / steps), int(a[1] + (b[1] - a[1]) * i / steps)))
    QTest.mouseRelease(vp, button, pos=QPoint(*b))


def _click(view, p, button=None):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(view.viewport(), button or Qt.MouseButton.LeftButton, pos=QPoint(*p))


def _wheel(view, pos, notches):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    vp, p = view.viewport(), QPoint(*pos)
    QApplication.sendEvent(vp, QWheelEvent(QPointF(p), QPointF(vp.mapToGlobal(p)), QPoint(0, 0),
                                           QPoint(0, int(120 * notches)), Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))


def test_only_the_wheel_zooms(view):
    """No drag — left or right, up, down or sideways — changes the zoom; the wheel zooms at the cursor."""
    from PySide6.QtCore import QPoint, Qt
    z0 = view.zoom
    for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
        for end in ((400, 150), (400, 450), (550, 300)):
            _drag(view, button, (400, 300), end)
            view.stop_motion()
            assert view.zoom == pytest.approx(z0)
    _click(view, (300, 250))
    assert view.zoom == pytest.approx(z0)
    anchor = view.mapToScene(QPoint(300, 250))
    _wheel(view, (300, 250), 4)                                      # up = larger, at the cursor
    z1 = view.zoom
    assert z1 > z0 * 1.5
    after = view.mapToScene(QPoint(300, 250))
    assert abs(after.x() - anchor.x()) < 3 and abs(after.y() - anchor.y()) < 3
    _wheel(view, (300, 250), -2)                                     # down = smaller again
    assert z0 < view.zoom < z1


def test_left_drag_moves_the_photo(view):
    """확대/축소 (the starting tool): a left drag moves the photo, the hand shows it."""
    from PySide6.QtCore import Qt
    assert view.tool == "zoom"
    assert view.viewport().cursor().shape() == Qt.CursorShape.OpenHandCursor
    _wheel(view, (400, 300), 6)
    z1 = view.zoom
    assert view.zoomed_in()
    view.stop_motion()
    h0, v0 = view.horizontalScrollBar().value(), view.verticalScrollBar().value()
    _drag(view, Qt.MouseButton.LeftButton, (400, 300), (340, 250))
    view.stop_motion()                                               # no slide after the drag
    assert view.zoom == pytest.approx(z1)
    assert view.horizontalScrollBar().value() == h0 + 60
    assert view.verticalScrollBar().value() == v0 + 50
    assert view.viewport().cursor().shape() == Qt.CursorShape.OpenHandCursor
    _drag(view, Qt.MouseButton.LeftButton, (400, 300), (400, 420))   # straight down: moves, no zoom out
    assert view.zoom == pytest.approx(z1)


def test_double_click_turns_on_a_loupe_that_follows_the_mouse(view):
    """2D view / 비교 (``dblclick_loupe``): a double click shows the loupe, which follows the mouse —
    through drags and zooms too — until the next double click or Esc. Other views: a double click fits."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    vp, lab = view.viewport(), view._loupe

    def at(p):
        c = lab.geometry().center()
        return abs(c.x() - p[0]) <= 2 and abs(c.y() - p[1]) <= 2

    view.zoom_to(3.0)
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
    assert not view.loupe_on and view.zoom == pytest.approx(view._fit_zoom())   # without it: fit
    view.stop_motion()
    view.fit()
    view.dblclick_loupe = True
    z0 = view.zoom
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
    assert view.loupe_on and lab.isVisible() and at((300, 250))
    assert view.zoom == pytest.approx(z0)                            # the double click is not a zoom
    QTest.mouseMove(vp, QPoint(420, 330))
    assert lab.isVisible() and at((420, 330))                        # it follows the mouse
    _wheel(view, (400, 180), 4)                                      # a wheel zoom: still on, under the mouse
    assert view.loupe_on and view.zoom > z0 * 1.5 and at((400, 180))
    view.stop_motion()
    h0 = view.horizontalScrollBar().value()
    _drag(view, Qt.MouseButton.LeftButton, (400, 300), (340, 300))   # zoomed in: the drag moves the photo
    view.stop_motion()
    assert view.horizontalScrollBar().value() == h0 + 60 and view.loupe_on and at((340, 300))
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, pos=QPoint(340, 300))
    assert not view.loupe_on and not lab.isVisible()                 # double click again: off
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert view.loupe_on
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.loupe_on and not lab.isVisible()                 # Esc: off
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    view.set_tool("length")
    assert not view.loupe_on                                         # another tool: off


def test_pan_with_middle_button_or_pan_tool(view):
    from PySide6.QtCore import Qt
    view.zoom_to(3.0)
    h0 = view.horizontalScrollBar().value()
    _drag(view, Qt.MouseButton.MiddleButton, (400, 300), (300, 300))
    h1 = view.horizontalScrollBar().value()
    assert h1 == h0 + 100 and view.zoom == pytest.approx(3.0)
    view.set_tool("pan")
    _drag(view, Qt.MouseButton.LeftButton, (300, 300), (360, 300))
    assert view.horizontalScrollBar().value() == h1 - 60 and view.zoom == pytest.approx(3.0)


def test_length_measurement_in_retinal_units(view):
    from PySide6.QtCore import Qt
    got = []
    view.measured.connect(got.append)
    view.set_tool("length")
    a = view.mapFromScene(400, 300)
    b = view.mapFromScene(480, 300)
    _drag(view, Qt.MouseButton.LeftButton, (a.x(), a.y()), (b.x(), b.y()))
    assert view.annotation_count == 1
    assert got[-1].startswith("길이:") and "px" in got[-1] and "mm" in got[-1] and "°" in got[-1]
    view.undo_annotation()
    assert view.annotation_count == 0


def test_angle_and_cup_disc(view):
    from PySide6.QtCore import Qt
    got = []
    view.measured.connect(got.append)
    view.set_tool("angle")
    for sp in ((300, 300), (400, 300), (400, 200)):
        q = view.mapFromScene(*sp)
        _click(view, (q.x(), q.y()))
    assert got[-1].startswith("각도") and float(got[-1].split()[1].rstrip("°")) == pytest.approx(90, abs=1.5)
    view.set_tool("cd_length")
    for (x1, y1), (x2, y2) in (((390, 300), (410, 300)), ((370, 300), (430, 300))):
        a, b = view.mapFromScene(x1, y1), view.mapFromScene(x2, y2)
        _drag(view, Qt.MouseButton.LeftButton, (a.x(), a.y()), (b.x(), b.y()))
    assert got[-1].startswith("C/D (길이)") and float(got[-1].split("=")[1]) == pytest.approx(1 / 3, abs=0.02)
    view.set_tool("cd_area")
    from PySide6.QtTest import QTest
    for half in (10, 20):   # squares: cup 20×20 inside disc 40×40 -> area ratio 0.25
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            q = view.mapFromScene(400 + dx * half, 300 + dy * half)
            _click(view, (q.x(), q.y()))
        QTest.keyClick(view, Qt.Key.Key_Return)
    assert got[-1].startswith("C/D (면적)") and float(got[-1].split("=")[1].split()[0]) == pytest.approx(0.25, abs=0.03)
    assert view.annotation_count == 3


def test_rotation_flip_and_render(view):
    w, h = view.render_image().width(), view.render_image().height()
    assert (w, h) == (800, 600)
    view.rotate90()
    img = view.render_image()
    assert (img.width(), img.height()) == (600, 800)
    view.flip(True)
    view.reset_orientation()
    assert view.render_image().width() == 800


def test_retinal_distance_is_symmetric():
    geo = measure.Geometry(1000, 1000, 1000, 176, "internal", "radial")
    deg, mm = measure.retinal_distance((1000, 1000), (1000 + 324, 1000), geo)
    assert deg == pytest.approx(22.0, abs=0.3)        # RetiCam calibration point
    assert mm == pytest.approx(math.radians(deg) * 12.0)
    assert measure.retinal_distance((0, 0), (1000, 1000), geo) is None   # corner: outside the field


@pytest.mark.parametrize("op", imaging.OPS)
def test_processing_ops(op):
    rgb = synth_fundus(size=(272, 287))
    out = imaging.apply_op(rgb, op)
    assert out.shape == rgb.shape and out.dtype == np.uint8
    assert not np.array_equal(out, rgb)


def test_levels():
    rgb = np.full((4, 4, 3), 100, np.uint8)
    out = imaging.adjust(rgb, levels=(50, 150))
    assert out[0, 0, 0] == 128


def test_main_window_tools(app, tmp_path, demo_dir, import_and_wait):
    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam"])
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        assert w.thumbs.count() == 3
        w.f_mod.setCurrentIndex(w.f_mod.findData("color"))   # the two single shots (no montage)
        assert w.thumbs.count() == 2 and w.view2d.geometry is not None
        # 확대 is on from the start (wheel zoom, drag moves): 2D, compare and multi views, the ZOOM button lit
        assert w.view2d.tool == "zoom" and w.acts["tool:zoom"].isChecked()
        assert all(v.tool == "zoom" for v in w.cmp_views)
        # a double click shows the loupe in 비교; on Detail's big photo it goes back where one was (the multi
        # view opens the photo instead)
        assert w.view2d.dblclick_leaves and not w.view2d.dblclick_loupe and all(v.dblclick_loupe for v in w.cmp_views)
        first = w.current["id"]
        w._on_action("op:sharpen")
        w._on_action("op:enhance")
        w._on_action("chan:redfree")
        assert w._ops == ["sharpen", "enhance"] and w._channel == "redfree"
        assert w.acts["chan:redfree"].isChecked() and w.acts["op:sharpen"].isChecked()
        w.acts["chan:redfree"].trigger()      # clicking the lit filter again -> colour
        assert w._channel == "rgb" and not w.acts["chan:redfree"].isChecked()
        w.acts["chan:redfree"].trigger()
        assert w._channel == "redfree"
        w._on_action("undo")
        assert w._channel == "rgb" and w._ops == ["sharpen", "enhance"]
        w._on_action("original")
        assert w._ops == [] and w._channel == "rgb" and not w.acts["op:sharpen"].isChecked()
        w._on_action("adj:gamma")                # VK-2 GAMMA: slider popup
        assert w.pop_gamma.isVisible()
        w.s_gamma.setValue(150)
        w._apply_adjust()
        assert w.acts["adj:gamma"].isChecked()
        # 감마 is a graph (입력 → 출력): a click or a drag on it bends the curve through that point —
        # above the diagonal lighter (감마 > 1), below it darker, on it 1.00; one 실행 취소 per drag
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtTest import QTest
        curve = w.pop_gamma.curve
        app.processEvents()
        r = curve.plot()
        assert curve.isVisible() and r.width() == r.height() and r.width() >= 150

        def at(x, y):                            # the place of (입력 x, 출력 y) on the graph
            return QPointF(r.left() + x * r.width(), r.bottom() - y * r.height()).toPoint()

        for x, y, want in ((0.5, 0.5, 1.0), (0.25, 0.5, 2.0), (0.5, 0.25, 0.5), (0.5, 0.75, 2.41)):
            QTest.mouseClick(curve, Qt.MouseButton.LeftButton, pos=at(x, y))
            assert w.s_gamma.value() / 100 == pytest.approx(want, abs=0.06)
            dot = curve.point(curve._at)         # the handle sits on the curve where it was clicked
            assert abs(dot.x() - at(x, y).x()) <= 1.5 and abs(dot.y() - at(x, y).y()) <= 2.5
        QTest.mouseClick(curve, Qt.MouseButton.LeftButton, pos=at(0.01, 0.99))    # (a corner: the strongest)
        assert w.s_gamma.value() == w.s_gamma.maximum() == 400
        QTest.mouseClick(curve, Qt.MouseButton.LeftButton, pos=at(0.99, 0.01))
        assert w.s_gamma.value() == w.s_gamma.minimum() == 20
        w._on_action("adj_reset")
        w._apply_adjust()
        plain = w.view2d._rgb.copy()
        depth = len(w._history)
        QTest.mousePress(curve, Qt.MouseButton.LeftButton, pos=at(0.5, 0.5))
        QTest.mouseMove(curve, at(0.4, 0.6))
        QTest.mouseMove(curve, at(0.3, 0.7))
        QTest.mouseRelease(curve, Qt.MouseButton.LeftButton, pos=at(0.3, 0.7))
        assert w.s_gamma.value() / 100 == pytest.approx(3.38, abs=0.08) and len(w._history) == depth + 1
        w._apply_adjust()
        assert w.view2d._rgb.astype(int).sum() > plain.astype(int).sum()          # the photo is lighter
        assert w.pop_gamma.value.text() == f"{w.s_gamma.value() / 100:.2f}"
        w._on_action("undo")
        assert w.s_gamma.value() == 100
        QTest.mouseClick(curve, Qt.MouseButton.LeftButton, pos=at(0.25, 0.5))
        QTest.mouseDClick(curve, Qt.MouseButton.LeftButton, pos=at(0.25, 0.5))    # a double click: 1.00 again
        assert w.s_gamma.value() == 100
        w.s_gamma.setValue(150)                  # the slider under it still sets it (fine steps): the curve follows
        assert curve.gamma() == 1.5
        w.pop_gamma.hide()
        w._on_action("adj_reset")
        assert w.s_gamma.value() == 100 and not w.acts["adj:gamma"].isChecked()
        # on the photo: its number and the eye — no patient name, ID or date
        assert w.view2d._captions[0] == "1/2" and w.view2d._captions[1] in ("OD (R)", "OS (L)")
        assert w.view2d._captions[2:] == ("", "")
        w._on_action("tools")                    # TOOLS hides / shows the processing toolbar
        assert w.tb_proc.isHidden() and not w.acts["tools"].isChecked()
        w._on_action("tools")
        assert w.tb_proc.isVisible()
        # 0.13.7: 확대 · 연속 · 히스토그램 · 이동 · 돋보기 · 회색조 · 지우기 are not on the toolbar (the 영상 처리
        # menu has them); a lit tool button again: back to 확대
        for gone in ("tool:zoom", "slideshow", "histogram", "tool:pan", "tool:loupe", "tool:profile", "annot_undo"):
            assert w.tb_proc.widgetForAction(w.acts[gone]) is None, gone
        length = w.tb_proc.widgetForAction(w.acts["tool:length"])
        length.click()
        assert w.view2d.tool == "length" and w.acts["tool:length"].isChecked()
        length.click()
        assert w.view2d.tool == "zoom" and w.acts["tool:zoom"].isChecked() and not w.acts["tool:length"].isChecked()
        w._on_action("next")
        assert w.current["id"] != first
        w._on_action("prev")
        assert w.current["id"] == first
        w._go("multi")                       # multi view
        w.multi.set_count(4)
        app.processEvents()
        assert sum(1 for c in w.multi.cells if c.image_id is not None and c.isVisible()) == 2
        assert all(c.view.tool == "zoom" for c in w.multi.cells)
        w._go("2d")
        w._on_action("op:sharpen")
        new_id = w.service.importer.add_derived(w.current, w.view2d._rgb, "편집 영상 (테스트)")
        assert db.get_image(new_id)["patient_ref"] == w.current["patient_ref"]
        assert db.get_image(new_id)["note"].startswith("편집 영상")
    finally:
        w.close()
        db.close()
