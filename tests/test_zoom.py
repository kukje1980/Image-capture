"""Zooming in on wide-field photos: 2D mini-map, regions and keys; 3D zoom toward the cursor."""
import math
import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fundusview import measure  # noqa: E402
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
    v.set_rgb(synth_fundus(eye="OD", size=(900, 600), circle=(450, 300, 330), seed=5))
    app.processEvents()
    return v


def _centre(view):
    return view.mapToScene(view.viewport().rect().center())


# -- 2D ------------------------------------------------------------------------------
def test_navigator_only_while_zoomed_in(view):
    assert not view._nav.isVisible()
    view.zoom_to(3.0)
    assert view._nav.isVisible()
    view.fit()
    assert not view._nav.isVisible()
    view.zoom_to(3.0)
    view.set_navigator(False)
    assert not view._nav.isVisible()


@pytest.mark.parametrize("turns, flip", [(0, False), (1, False), (1, True), (2, True)])
def test_navigator_maps_the_oriented_photo(view, turns, flip):
    from PySide6.QtCore import QPointF
    for _ in range(turns):
        view.rotate90()
    if flip:
        view.flip(True)
    view.zoom_to(3.0)
    nav = view._nav
    for p in (QPointF(10, 20), QPointF(450, 300), QPointF(880, 590)):
        back = nav.from_nav(nav.to_nav(p))
        assert (back.x(), back.y()) == pytest.approx((p.x(), p.y()), abs=1e-6)
    tw, th = nav.width() - 2 * nav.BORDER, nav.height() - 2 * nav.BORDER
    assert (tw > th) == (turns % 2 == 0)                 # a 900×600 photo turned on its side


def test_clicking_the_navigator_moves_there(view):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    view.zoom_to(4.0)
    nav = view._nav
    target = nav.to_nav(QPointF(150, 120))
    QTest.mouseClick(nav, Qt.MouseButton.LeftButton, pos=QPoint(round(target.x()), round(target.y())))
    c = _centre(view)
    assert (c.x(), c.y()) == pytest.approx((150, 120), abs=6)


def test_zoom_to_rect_fills_the_view(view):
    from PySide6.QtCore import QRectF
    rect = QRectF(600, 100, 200, 100)
    view.zoom_to_rect(rect)
    vp = view.viewport().rect()
    assert view.zoom == pytest.approx(min(vp.width() / 200, vp.height() / 100) * 0.97, rel=1e-3)
    c = _centre(view)
    assert (c.x(), c.y()) == pytest.approx((700, 150), abs=2)
    assert view.mapToScene(vp).boundingRect().contains(rect)


def test_zoom_keys(view):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    z0 = view.zoom
    QTest.keyClick(view, Qt.Key.Key_Plus)
    assert view.zoom == pytest.approx(z0 * 1.25)
    QTest.keyClick(view, Qt.Key.Key_Minus)
    assert view.zoom == pytest.approx(z0)
    QTest.keyClick(view, Qt.Key.Key_1)
    assert view.zoom == pytest.approx(1.0)
    QTest.keyClick(view, Qt.Key.Key_0)
    assert view._fit and view.zoom == pytest.approx(z0)


def test_fundus_regions():
    circle, size = (1000.0, 800.0, 700.0), (2000, 1500)
    disc = (1160.0, 790.0)                                       # disc right of the fovea: nasal = right
    post = measure.fundus_region("posterior", circle, disc, "OD", size)
    x, y, w, h = post
    assert x < 1000 < x + w and x < disc[0] < x + w and y < 800 < y + h
    nasal = measure.fundus_region("nasal", circle, disc, None, size)
    temporal = measure.fundus_region("temporal", circle, disc, None, size)
    assert nasal[0] > 1000 > temporal[0] + temporal[2]
    # without a disc the eye decides: OS has the nasal retina on the left of the photo
    assert measure.fundus_region("nasal", circle, None, "OS", size)[0] < 1000
    assert measure.fundus_region("nasal", circle, None, None, size) is None
    sup = measure.fundus_region("superior", circle, disc, "OD", size)
    inf = measure.fundus_region("inferior", circle, disc, "OD", size)
    assert sup[1] + sup[3] < 800 < inf[1]
    # a wide-field circle larger than the frame: the region stays on the photo
    cut = measure.fundus_region("superior", (700.0, 540.0, 760.0), None, "OD", (1434, 1076))
    assert cut[1] >= 0 and cut[1] + cut[3] <= 1076


# -- 3D (camera maths, no OpenGL needed) ---------------------------------------------------
@pytest.fixture()
def eye(app):
    from fundusview.ui.eye3d import EyeView
    v = EyeView()
    v.resize(900, 700)
    return v


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_3d_zoom_keeps_the_retina_under_the_cursor(eye, detail):
    from PySide6.QtCore import QPointF
    eye.set_detail(detail)
    eye.cut = 0.25
    pos = QPointF(560, 330)
    p0 = eye._pick(*eye._ray(pos))
    assert p0 is not None and p0[2] < 0                         # on the retina, inside the eye cup
    for _ in range(20):
        eye.zoom_at(1.0, pos)
        p = eye._pick(*eye._ray(pos))
        assert np.allclose(p, p0, atol=1e-6)
    assert eye.magnification > 10
    for _ in range(20):
        eye.zoom_at(-1.0, pos)
    assert eye.magnification == pytest.approx(1.0, abs=0.01)    # back where it started
    for _ in range(6):
        eye.zoom_at(-1.0, pos)
    assert eye.magnification < 1.0
    assert np.linalg.norm(eye.target) < 0.05                    # the pivot comes home


def test_3d_zoom_stops_outside_the_closed_globe(eye):
    from PySide6.QtCore import QPointF
    eye.cut = 1.0
    for _ in range(80):
        eye.zoom_at(1.0, QPointF(450, 350))
    camera = eye._view_basis()[0]
    assert np.linalg.norm(camera) > 1.0 and eye.magnification > 20


def test_3d_inside_zoom_turns_toward_the_cursor(eye):
    from PySide6.QtCore import QPointF
    eye.mode = "inside"
    pos = QPointF(700, 250)
    p0 = eye._pick(*eye._ray(pos))
    for _ in range(12):
        eye.zoom_at(1.0, pos)
    p = eye._pick(*eye._ray(pos))
    assert np.linalg.norm(p - p0) < 0.03
    assert eye.in_fov < 30 and eye.magnification > 3
    for _ in range(60):
        eye.zoom_at(1.0, pos)
    assert eye.in_fov == pytest.approx(4.0)                     # strongest zoom


def test_3d_pan_reset_and_signal(eye):
    got = []
    eye.zoomChanged.connect(got.append)
    eye.pan(400, -300)
    assert np.linalg.norm(eye.target) > 0.1
    for _ in range(50):
        eye.pan(5000, 0)
    assert np.linalg.norm(eye.target) <= 1.5 + 1e-9
    eye.zoom_at(3.0)
    assert got and got[-1] > 1.0
    eye.reset_view()
    assert got[-1] == pytest.approx(1.0) and not eye.target.any()


def test_3d_detail_switch(eye):
    assert eye.detail == "simple"
    eye.set_detail("detailed")
    assert eye.detail == "detailed"
    eye.set_detail("nonsense")
    assert eye.detail == "detailed"
    assert math.isclose(eye.magnification, 1.0)
