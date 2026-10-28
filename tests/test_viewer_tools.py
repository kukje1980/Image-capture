"""VK-2 style viewer tools: drag zoom, measurements, processing stack, multi view."""
import math
import os
import time

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
    return v


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


def test_right_drag_zooms(view):
    from PySide6.QtCore import Qt
    z0 = view.zoom
    _drag(view, Qt.MouseButton.RightButton, (400, 300), (400, 200))   # up = zoom in
    z1 = view.zoom
    assert z1 > z0 * 1.5
    _drag(view, Qt.MouseButton.RightButton, (400, 300), (400, 420))   # down = zoom out
    assert view.zoom < z1


def test_zoom_tool_drag_and_click(view):
    from PySide6.QtCore import Qt
    view.set_tool("zoom")
    z0 = view.zoom
    _drag(view, Qt.MouseButton.LeftButton, (300, 300), (300, 220))
    assert view.zoom > z0
    z1 = view.zoom
    _click(view, (300, 300))
    assert view.zoom == pytest.approx(z1 * 2)


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


def test_main_window_tools(app, tmp_path, demo_dir):
    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        w.service.import_paths([str(demo_dir / "RetiCam")])
        deadline = time.time() + 20
        while db.find_patient("PID20260310-0A1B2C3D") is None and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        time.sleep(0.5)
        for _ in range(60):
            app.processEvents()
            time.sleep(0.01)
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        assert w.thumbs.count() == 3
        w.f_mod.setCurrentIndex(w.f_mod.findData("color"))   # the two single shots (no montage)
        assert w.thumbs.count() == 2 and w.view2d.geometry is not None
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
        w.pop_gamma.hide()
        w._on_action("adj_reset")
        assert w.s_gamma.value() == 100 and not w.acts["adj:gamma"].isChecked()
        assert w.view2d._captions[0] == "1/2" and w.view2d._captions[2].endswith("PID20260310-0A1B2C3D")
        w._on_action("tools")                    # TOOLS hides / shows the processing toolbar
        assert w.tb_proc.isHidden() and not w.acts["tools"].isChecked()
        w._on_action("tools")
        assert w.tb_proc.isVisible()
        w._on_action("next")
        assert w.current["id"] != first
        w._on_action("prev")
        assert w.current["id"] == first
        w.tabs.setCurrentIndex(2)            # multi view
        w.multi.set_count(4)
        app.processEvents()
        assert sum(1 for c in w.multi.cells if c.image_id is not None and c.isVisible()) == 2
        w.tabs.setCurrentIndex(0)
        w._on_action("op:sharpen")
        new_id = w.service.importer.add_derived(w.current, w.view2d._rgb, "편집 영상 (테스트)")
        assert db.get_image(new_id)["patient_ref"] == w.current["patient_ref"]
        assert db.get_image(new_id)["note"].startswith("편집 영상")
    finally:
        w.close()
        db.close()
