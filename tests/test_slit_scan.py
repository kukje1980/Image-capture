"""슬릿 스캔 · 세로 단면 · 망막 투시 without OpenGL: geometry, the timeline, the photo panel."""
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


def _eye(app, laterality="OD", fov=176.0, projection="radial"):
    from fundusview.ui.eye3d import EyeView

    v = EyeView()
    v.set_mapping(fov_deg=fov, fov_type="internal", projection=projection)
    v.set_disc(laterality, None, None)
    v.resize(640, 400)
    return v


@pytest.mark.parametrize("lat", ["OD", "OS"])
def test_section_keeps_the_disc_and_faces_the_camera(app, lat):
    v = _eye(app, lat)
    v.half = 1.0
    k, off = v.half_plane()
    assert off == pytest.approx(0.0)
    assert float(v.disc_dir @ k) > 0.2                  # the half with the optic disc stays
    assert abs(k[2]) < 1e-9 and abs(float(k @ v.meridian())) < 1e-9   # holds the axis and the meridian
    v.set_pose(**v.section_pose())
    eye, f, r, u, _ = v._view_basis()
    assert float(eye @ k) < -1.0                        # camera on the cut-away side, looking in
    assert float(u @ v.meridian()) > 0.99               # image up = up: the slit runs down both views
    assert float(r[2]) == pytest.approx(1.0 if lat == "OD" else -1.0, abs=1e-6)   # OD: cornea to the right


def test_half_slides_the_plane_in(app):
    v = _eye(app)
    offs = []
    for h in (0.0, 0.25, 0.5, 1.0):
        v.half = h
        offs.append(v.half_plane()[1])
    assert offs[0] >= 1.0 and offs == sorted(offs, reverse=True) and offs[-1] == 0.0


@pytest.mark.parametrize("projection", ["radial", "equidistant", "perspective"])
def test_slit_reaches_the_retina_under_its_row(app, projection):
    """The beam's end on the vertical meridian maps back to the slit's row of the photo."""
    from fundusview import projection as proj

    v = _eye(app, projection=projection, fov=176.0 if projection != "perspective" else 50.0)
    cx, cy, R = 500.0, 480.0, 450.0
    tmax = v.theta_max
    assert v.scan_theta(0.0) == (pytest.approx(tmax), 1.0)
    assert v.scan_theta(1.0) == (pytest.approx(tmax), -1.0)
    assert v.scan_theta(0.5)[0] == pytest.approx(0.0, abs=1e-6)
    for s in np.linspace(0.05, 0.95, 10):
        th, side = v.scan_theta(float(s))
        p = proj.sphere_point(th, side * math.pi / 2)
        u, row = proj.sphere_to_image(p, cx, cy, R, tmax, projection, v.viewpoint, c=v.radial_c)
        assert u == pytest.approx(cx, abs=1e-6)
        assert row == pytest.approx(cy - R + 2 * R * s, abs=1e-3)


def test_pick_in_the_section_view_finds_the_section_or_the_far_retina(app):
    from fundusview.ui import eye_model as em

    v = _eye(app)
    v.half = 1.0
    v.set_pose(**v.section_pose())
    k, off = v.half_plane()
    o = v._view_basis()[0]
    hit = v._pick(o, -o / np.linalg.norm(o))            # straight at the centre: through the vitreous
    assert hit is not None and float(hit @ k) > 0.5 and np.linalg.norm(hit) == pytest.approx(em.R_RET)
    d = np.array([0.0, 0.95, 0.0]) - o                  # at the wall in the section plane
    hit = v._pick(o, d / np.linalg.norm(d))
    assert hit is not None and abs(float(hit @ k)) < 1e-6 and em.R_RET <= np.linalg.norm(hit) <= 1.0


def test_timeline(app):
    from fundusview.ui.slit_scan import SlitScanShow

    v = _eye(app)
    show = SlitScanShow(v)
    show.start()
    show._timer.stop()
    f0 = show.frame(0.0)
    assert f0.half == pytest.approx(0.0) and f0.scan is None and f0.pose["dist"] == pytest.approx(v.DIST0)
    side = show.frame(show.T_SIDE + 0.01)
    assert side.half == 1.0 and side.pose == v.section_pose() and side.phase == "fov"
    assert show.frame(show.T_FOV[1] - 0.01).fov_sweep == pytest.approx(1.0)
    scans = [show.frame(t).scan for t in np.linspace(show.T_SCAN[0], show.T_SCAN[1], 12)]
    assert scans[0] == pytest.approx(0.0) and scans[-1] == pytest.approx(1.0) and scans == sorted(scans)
    mid = show.frame(sum(show.T_SCAN) / 2)
    assert mid.scan_beam == pytest.approx(1.0) and mid.scan_dim == pytest.approx(1.0)
    done = show.frame(show.T_DONE + 0.01)
    assert done.scan is None and done.phase == "turn"
    end = show.frame(show.total)
    assert end.half == pytest.approx(show.END_HALF) and end.xray == pytest.approx(1.0)
    assert end.pose["yaw"] == pytest.approx(v.showcase_pose()["yaw"])
    later = show.frame(show.total + 5.0)
    assert later.phase == "spin" and later.pose["yaw"] != pytest.approx(end.pose["yaw"])
    assert later.fov_ring == pytest.approx(0.0)          # 화각 표시 off: the ring fades away


def test_stop_leaves_a_clean_section_view(app):
    from fundusview.ui.slit_scan import SlitScanShow

    v = _eye(app)
    show = SlitScanShow(v)
    show.xray_after = True
    show.start()
    show._t0 -= 5.0                                     # in the middle of the scan
    show._tick()
    assert v.scan is not None and show.active()
    v.interacted.emit()                                 # the user grabs the eye
    assert not show.active() and v.scan is None
    assert v.half == 1.0 and v.xray == 1.0              # cut through the axis, 망막 투시 as before
    show.start()
    show._t0 -= show.total + 1.0                        # turning after the timeline
    show._tick()
    show.stop()
    assert v.half == pytest.approx(show.END_HALF) and v.xray == 1.0


def test_slit_in_four_directions(app):
    """Down and up on 세로 단면 from the side; right and left on the eye opened at the front; 상하좌우 all
    four in turn, the section closing while the front opens between them."""
    from fundusview.ui.slit_scan import FRONT_CUT, SlitScanShow

    v = _eye(app)
    show = SlitScanShow(v)
    show.direction = "right"
    show.start()
    show._timer.stop()
    mid = show.frame(sum(show.T_SCAN) / 2)
    assert mid.phase == "scan" and mid.half == 0.0 and mid.cut == pytest.approx(FRONT_CUT)
    assert (mid.pose["yaw"], mid.pose["pitch"]) == (0.0, 0.0) and mid.slit.axis == "h"
    show._apply(mid)
    assert v.scan_dir() == pytest.approx((1.0, 0.0)) and v.slit_axis == "h"
    end = show.frame(show.total)
    assert end.half == 0.0 and end.cut == pytest.approx(FRONT_CUT)       # it ends on the opened eye
    show.direction = "up"
    show.start()
    show._timer.stop()
    f = show.frame(sum(show.T_SCAN) / 2)
    assert f.half == 1.0 and f.cut == 1.0 and f.slit.sign == 1.0
    show._apply(f)
    assert v.scan_dir() == pytest.approx((0.0, -1.0))
    th_lo, side_lo = v.scan_theta(0.1)                                    # up: it starts at the bottom
    assert side_lo == -1.0
    show.direction = "all"
    show.start()
    show._timer.stop()
    kinds = [g[0] for g in show._segs]
    assert kinds == ["scan", "gap", "scan", "switch", "scan", "gap", "scan"]
    sw = next(g for g in show._segs if g[0] == "switch")
    closing = show.frame(sw[1] + 0.9)
    assert 0.0 < closing.half < 1.0 and closing.scan is None
    opened = show.frame(sw[2] - 0.01)
    assert opened.half == pytest.approx(0.0, abs=1e-3) and opened.cut == pytest.approx(FRONT_CUT, abs=0.01)
    show.stop()


def test_photo_panel_slit_and_privacy(app):
    from PySide6.QtGui import QColor

    from fundusview import demo, imaging
    from fundusview.ui.slit_scan import ScanPhotoView

    rgb = demo.synth_fundus(eye="OD", size=(600, 640))
    rgb[5:40, 5:200] = 255                              # text the device burns into the corner
    circle = imaging.detect_circle(rgb)
    p = ScanPhotoView()
    p.resize(500, 500)
    p.set_image(rgb, imaging.fundus_alpha(rgb, circle), circle)
    rect = p.image_rect()
    # the photo is cropped to the image circle: the slit starts at its top and ends at its bottom
    assert p.slit_y(0.0) == pytest.approx(rect.top(), abs=1.5)
    assert p.slit_y(1.0) == pytest.approx(rect.bottom(), abs=1.5)
    assert p.slit_y(0.5) == pytest.approx(rect.center().y(), abs=1.5)
    img = p.grab().toImage()
    corner = img.pixelColor(int(rect.left() + 3), int(rect.top() + 3))
    assert max(corner.red(), corner.green(), corner.blue()) < 30          # burned-in text hidden

    def lum(y):
        c = img.pixelColor(int(rect.center().x()), int(y))
        return c.red() + c.green() + c.blue()

    bright = [lum(rect.top() + rect.height() * f) for f in (0.3, 0.7)]
    p.set_scan(0.5, 1.0)
    img = p.grab().toImage()
    above, below = (lum(rect.top() + rect.height() * f) for f in (0.3, 0.7))
    assert above == pytest.approx(bright[0], abs=6)     # scanned: as before
    assert below < bright[1] * 0.5                      # not yet scanned: dark
    slit = img.pixelColor(int(rect.center().x()), int(p.slit_y(0.5)))
    assert slit.red() > 200 and slit.red() > slit.blue() + 60            # the glowing slit
    p.set_scan(0.5, 1.0, (1.0, 0.0))                   # left to right: the right half not scanned yet
    img = p.grab().toImage()

    def lum_x(f):
        c = img.pixelColor(int(rect.left() + rect.width() * f), int(rect.center().y()))
        return c.red() + c.green() + c.blue()
    assert lum_x(0.7) < lum_x(0.3) * 0.5
    p.set_image(None)
    assert not p.has_image() and isinstance(p.grab().toImage().pixelColor(5, 5), QColor)
