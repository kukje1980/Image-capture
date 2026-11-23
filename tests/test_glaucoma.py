"""녹내장 분석: the image work (glaucoma.py), the window's four tabs and the main-window flow."""
import os

import math

import numpy as np
import pytest

from fundusview import glaucoma as G
from fundusview.demo import synth_fundus


def _texture(seed=0, size=(240, 320)):
    rng = np.random.default_rng(seed)
    import cv2
    g = cv2.GaussianBlur((rng.random(size) * 255).astype(np.float32), (0, 0), 3)
    g = ((g - g.min()) / (g.max() - g.min()) * 255).astype(np.uint8)
    return np.dstack([g, g // 2 + 60, 255 - g])


# -- image work -------------------------------------------------------------------------------------
def test_fit_and_crop():
    img = np.zeros((1000, 2000, 3), np.uint8)
    assert G.fit(img).shape[:2] == (450, 900) and G.fit_scale(img.shape) == pytest.approx(0.45)
    small = np.full((100, 120, 3), 7, np.uint8)
    assert G.fit(small).shape == small.shape and G.fit(small) is not small
    crop, x0, y0 = G.crop_square(small, 10, 10, 40)
    assert crop.shape == (40, 40, 3) and (x0, y0) == (-10, -10)
    assert crop[0, 0].max() == 0 and crop[-1, -1].min() == 7        # black outside the photo


def test_find_shift_recovers_a_translation():
    a = _texture()
    b = G.shifted(a, -9, 6)
    dx, dy = G.find_shift(a, b)
    assert (dx, dy) == pytest.approx((9, -6), abs=1.5)
    back = G.shifted(b, dx, dy)
    core = (slice(30, -30), slice(30, -30))
    assert np.abs(back[core].astype(int) - a[core].astype(int)).mean() < 12


def test_stereo_pictures():
    a, b = _texture(1), _texture(2)
    sbs = G.side_by_side(a, b)
    assert sbs.shape == (240, 650, 3) and (sbs[:, :320] == a).all() and (sbs[:, 330:] == b).all()
    ana = G.anaglyph(a, b)                                          # left eye red, right eye cyan (RGB)
    import cv2
    assert (ana[..., 0] == cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)).all()
    assert (ana[..., 1] == ana[..., 2]).all() and (ana[..., 1] == cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)).all()


def test_disparity_sees_a_shifted_patch_as_depth():
    left = _texture(3, (300, 400))
    right = left.copy()
    right[100:200, 150:250] = left[100:200, 140:240]                # the middle moved 10 px to the right
    disp = G.disparity(left, right)
    assert disp.shape[1] == 200
    centre, edge = disp[75, 100], disp[20, 30]
    assert abs(centre) > abs(edge) + 1.5
    deep, high = G.disparity_range(disp, 400)
    assert deep >= high
    over = G.depth_overlay(left, disp)
    assert over.shape == left.shape and over.dtype == np.uint8
    if centre > 0:      # deep = blue, raised = red
        assert over[150, 200, 2] > left[150, 200, 2] or over[150, 200, 0] < left[150, 200, 0]
    prof = G.depth_profile(disp, 150, 300, 400)
    assert prof.shape == (120, 400, 3)


def test_cdr_metrics_and_isnt():
    disc = {"cx": 100, "cy": 100, "rx": 50, "ry": 60}
    cup = {"cx": 100, "cy": 100, "rx": 25, "ry": 30}
    m = G.cdr_metrics(disc, cup, "OD")
    assert m["vertical"] == pytest.approx(0.5) and m["horizontal"] == pytest.approx(0.5)
    assert m["area"] == pytest.approx(0.25) and m["dd"] == pytest.approx(120)
    assert m["rim"]["I"] == pytest.approx(0.25) and m["rim"]["S"] == pytest.approx(0.25)
    assert set(m["rim"]) == {"S", "I", "N", "T", "SN", "ST", "IN", "IT"}        # the rim in eight directions
    # healthy order I ≥ S ≥ N ≥ T: cup towards the temporal side (left in a right eye) and up
    cup2 = {"cx": 97, "cy": 98, "rx": 30, "ry": 30}
    ok = G.cdr_metrics(disc, cup2, "OD")
    assert ok["rim"]["I"] > ok["rim"]["S"] > ok["rim"]["N"] > ok["rim"]["T"] and ok["isnt"] == []
    assert ok["rim"]["IN"] > ok["rim"]["ST"] and ok["thinnest"] == "T"
    # the same picture read as a left eye has nasal and temporal exchanged
    os_ = G.cdr_metrics(disc, cup2, "OS")
    assert os_["rim"]["N"] == pytest.approx(ok["rim"]["T"]) and "비측 림이 이측보다 얇음" in os_["isnt"]
    assert os_["rim"]["ST"] == pytest.approx(ok["rim"]["SN"])
    # inferior notch
    low = G.cdr_metrics(disc, {"cx": 100, "cy": 115, "rx": 25, "ry": 40}, "OD")
    assert "하측 림이 상측보다 얇음" in low["isnt"] and low["vertical"] == pytest.approx(40 / 60)
    # four quarter ellipses (the reach up · right · down · left): a cup reaching further down than up —
    # the inferior rim alone thins
    notch = {"cx": 100, "cy": 100, "top": 30, "right": 25, "bottom": 48, "left": 25}
    m2 = G.cdr_metrics(disc, notch, "OD")
    assert m2["rim"]["S"] == pytest.approx(m["rim"]["S"]) and m2["rim"]["I"] == pytest.approx((60 - 48) / 120)
    assert m2["vertical"] == pytest.approx((30 + 48) / 120) and "하측 림이 상측보다 얇음" in m2["isnt"]
    assert G.area(notch) == pytest.approx(math.pi / 4 * (25 * 30 * 2 + 25 * 48 * 2), rel=1e-3)
    # … and the narrowest rim round the whole disc: at 6 o'clock, a tenth of the disc's diameter there
    assert m2["narrow"]["hour"] == 6 and m2["narrow"]["name"] == "I" and m2["thinnest"] == "I"
    assert m2["narrow"]["ratio"] == pytest.approx(12 / 120) and m2["narrow"]["absent"] == 0 and m2["ddls"] == 4


def test_outlines_as_points_a_smooth_line_through_them():
    circle = {"cx": 200, "cy": 150, "rx": 80, "ry": 80}
    pts = G.ring(circle)                                            # up first, then clockwise on the screen
    assert pts.shape == (G.RING, 2) and pts[0] == pytest.approx((200, 70)) and pts[2] == pytest.approx((280, 150))
    assert pts[4] == pytest.approx((200, 230)) and pts[1] == pytest.approx((200 + 80 * 0.7071, 150 - 80 * 0.7071), abs=0.01)
    line = G.curve({"pts": pts})                                    # the smooth line through eight points
    r = np.hypot(line[:, 0] - 200, line[:, 1] - 150)
    assert len(line) == G.RING * G.CURVE_PER and 79.5 < r.min() and r.max() < 80.01
    assert G.area({"pts": pts}) == pytest.approx(math.pi * 80 * 80, rel=0.005)
    assert G.centre({"pts": pts}) == pytest.approx((200, 150), abs=0.01)
    oval = {"cx": 100, "cy": 100, "rx": 50, "ry": 60}
    as_pts = {"pts": G.ring(oval)}
    assert G.area(as_pts) == pytest.approx(G.area(oval), rel=0.005)
    m = G.cdr_metrics(as_pts, {"pts": G.ring({"cx": 100, "cy": 100, "rx": 25, "ry": 30})})
    assert m["vertical"] == pytest.approx(0.5, abs=1e-6) and m["area"] == pytest.approx(0.25, abs=1e-6)
    # one point moved: the line bulges there, its middle follows, the far side stays
    out = pts.copy()
    out[2] += (30, 0)
    bulged = G.curve({"pts": out})
    assert bulged[:, 0].max() == pytest.approx(310, abs=0.5) and bulged[:, 0].min() == pytest.approx(120, abs=1.0)
    assert G.centre({"pts": out})[0] > 202 and G.centre({"pts": out})[1] == pytest.approx(150, abs=0.01)
    # two points close together: no loop (the line stays outside the middle)
    near = pts.copy()
    near[1] = near[2] + (-2, -3)
    tight = G.curve({"pts": near})
    assert np.hypot(tight[:, 0] - 200, tight[:, 1] - 150).min() > 60
    # another picture's pixels
    moved = G.moved({"pts": pts}, 0.5, 10, -5)
    assert moved["pts"][0] == pytest.approx((110, 30)) and G.moved(oval, 2, 1, 1)["top"] == 120
    assert G.reach(line, (200, 150), 0.0) == pytest.approx(80, abs=0.01) and G.reach(line, (500, 150), 0.0) == 0


def test_a_traced_outline_as_points_and_evened_out():
    t = np.linspace(0, 2 * math.pi, 300, endpoint=False)
    oval = np.stack([120 + 40 * np.cos(t), 90 + 55 * np.sin(t)], axis=1)
    pts = G.ring({"poly": oval})                                    # its top · bottom · sides, the diagonals between
    assert pts[0] == pytest.approx((120, 35), abs=0.2) and pts[4] == pytest.approx((120, 145), abs=0.2)
    assert pts[2] == pytest.approx((160, 90), abs=0.2) and pts[6] == pytest.approx((80, 90), abs=0.2)
    through = G.curve({"pts": pts})
    assert np.ptp(through[:, 1]) == pytest.approx(110, abs=0.3) and np.ptp(through[:, 0]) == pytest.approx(80, abs=0.3)
    assert G.area({"pts": pts}) == pytest.approx(G.area({"poly": oval}), rel=0.01)
    even = G.evened(oval)                                           # an oval stays what it is
    assert np.ptp(even[:, 1]) == pytest.approx(110, abs=2.5) and np.ptp(even[:, 0]) == pytest.approx(80, abs=2.5)
    # a narrow tongue (along a vessel) does not stand as drawn: the evened line stays near the oval
    r = np.where(np.abs(t - 0.4) < 0.12, 1.7, 1.0)
    tongue = np.stack([120 + 40 * r * np.cos(t), 90 + 55 * r * np.sin(t)], axis=1)
    assert np.hypot(*(tongue - (120, 90)).T).max() > 70
    even = G.evened(tongue)
    assert np.hypot(*(even - G.centre({"poly": even})).T).max() < 60
    assert G.area({"poly": even}) == pytest.approx(G.area({"poly": oval}), rel=0.08)


def test_the_narrowest_rim_ddls_and_the_cup_a_disc_of_that_size_has():
    disc = {"cx": 100, "cy": 100, "rx": 50, "ry": 60}
    # a cup that reaches the margin below and to the temporal side (a right eye: left of the photo)
    m = G.cdr_metrics(disc, {"cx": 90, "cy": 112, "rx": 36, "ry": 46}, "OD")
    assert m["narrow"]["name"] in ("IT", "I") and m["narrow"]["hour"] in (6, 7, 8) and m["narrow"]["ratio"] < 0.05
    assert m["ddls"] >= 5 and m["rim"]["IT"] < m["rim"]["SN"]
    gone = G.cdr_metrics(disc, {"cx": 86, "cy": 116, "rx": 40, "ry": 50}, "OD")      # … and past it: no rim there
    assert gone["narrow"]["absent"] >= 20 and gone["narrow"]["ratio"] == 0 and gone["ddls"] >= 6
    assert gone["rim"]["IT"] < 0
    # the nomogram for a disc of average size (1.5–2.0 mm): rim/disc ratio, then how much has no rim
    assert [G.ddls_stage(r, 0) for r in (0.45, 0.4, 0.35, 0.25, 0.15, 0.05)] == [1, 1, 2, 3, 4, 5]
    assert [G.ddls_stage(0, d) for d in (30, 60, 120, 200, 300)] == [6, 7, 8, 9, 10]
    assert G.ddls_stage(0.35, 0, 1.3) == 3 and G.ddls_stage(0.35, 0, 2.3) == 1     # a small disc: one up, a large: one down
    assert G.ddls_stage(0.45, 0, 2.3) == 1 and G.ddls_stage(0, 300, 1.3) == 10     # (never off the scale)
    assert G.cdr_metrics(disc, {"cx": 100, "cy": 100, "rx": 25, "ry": 30}, "OD", disc_mm=1.3)["ddls"] == 4
    # Garway-Heath 1998: a large disc has a large cup — CDR = (−1.31 + 1.194 · DD) / DD
    assert G.expected_cdr(1.8) == pytest.approx(0.466, abs=0.001) and G.expected_cdr(2.2) == pytest.approx(0.599, abs=0.001)
    assert G.expected_cdr(1.5) < G.expected_cdr(1.8) < G.expected_cdr(2.2) and G.expected_cdr(1.0) == 0.0
    assert G.ring_names("OD") == ("S", "SN", "N", "IN", "I", "IT", "T", "ST")
    assert G.ring_names("OS") == ("S", "ST", "T", "IT", "I", "IN", "N", "SN")


def _disc_crop(n=420, frac=1 / 3.5, rx=0.9, ry=1.1, cup=0.5, offset=(14, -9), seed=2):
    """A square picture round an optic disc: an upright oval disc (``rx`` · ``ry`` of the radius expected,
    its middle ``offset`` px off the picture's) paler than the retina, a pale cup in it, vessels across."""
    import cv2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    c, rd = (n - 1) / 2, frac * n / 2
    r = np.hypot((xx - c - offset[0]) / rx, (yy - c - offset[1]) / ry) / rd
    img = np.empty((n, n, 3), np.float32)
    img[:] = (185, 85, 45)
    img[r < 1.0] = (240, 160, 100)
    img[r < cup] = (255, 235, 200)
    out = np.clip(cv2.GaussianBlur(img, (0, 0), 2.5), 0, 255).astype(np.uint8)
    for a in (25, 100, 200, 290):
        t = math.radians(a)
        p0 = (int(c + offset[0] + 0.1 * rd * math.cos(t)), int(c + offset[1] + 0.1 * rd * math.sin(t)))
        p1 = (int(c + 3.0 * rd * math.cos(t + 0.2)), int(c + 3.0 * rd * math.sin(t + 0.2)))
        cv2.line(out, p0, p1, (150, 35, 30), 4, cv2.LINE_AA)
    noise = cv2.GaussianBlur(np.random.default_rng(seed).normal(0, 25, (n, n)).astype(np.float32), (0, 0), 1.5)
    return np.clip(out.astype(np.float32) + noise[..., None], 0, 255).astype(np.uint8)


def test_the_disc_margin_is_found_where_the_brightness_falls_to_the_retina():
    n, frac = 420, 1 / 3.5
    rd = frac * n / 2
    for rx, ry, offset, cup in ((0.9, 1.1, (14, -9), 0.5), (1.15, 1.25, (-10, 6), 0.3), (0.8, 0.95, (0, 0), 0.7)):
        found = G.find_disc_margin(_disc_crop(n, frac, rx, ry, cup, offset), frac)
        assert found is not None and found["pts"].shape == (G.RING, 2) and found["confidence"] > 0.3
        line = G.curve({"pts": found["pts"]})
        assert np.ptp(line[:, 1]) == pytest.approx(2 * ry * rd, rel=0.06)       # as tall and as wide as the disc
        assert np.ptp(line[:, 0]) == pytest.approx(2 * rx * rd, rel=0.06)
        mid = G.centre({"pts": found["pts"]})                                     # … round its own middle
        assert mid == pytest.approx(((n - 1) / 2 + offset[0], (n - 1) / 2 + offset[1]), abs=4)
    assert G.find_disc_margin(np.full((n, n, 3), 120, np.uint8), frac) is None   # nothing there: not found
    assert G.find_disc_margin(np.zeros((n, n, 3), np.uint8), frac) is None


def test_sectors_and_clock_hours():
    disc, fovea = (600.0, 400.0), (340.0, 400.0)                    # right eye: the disc is right of the fovea
    ax = G.axes(disc, fovea)
    assert ax["od"] and ax["t"] == pytest.approx((-1, 0)) and ax["u"] == pytest.approx((0, -1))
    assert ax["rd"] == pytest.approx(50.0)
    up = G.sector_info(disc, fovea, (600, 300))
    assert up["hour"] == 12 and up["dd"] == pytest.approx(1.0)
    temporal = G.sector_info(disc, fovea, (500, 400))
    assert temporal["hour"] == 9 and temporal["sector"] == "이측"
    nasal = G.sector_info(disc, fovea, (700, 400))
    assert nasal["hour"] == 3 and nasal["sector"] == "비측"
    st = G.sector_info(disc, fovea, (550, 320))                     # up and temporal
    assert st["sector"] == "상이측" and "하측" in st["field"]
    it = G.sector_info(disc, fovea, (550, 480))
    assert it["sector"] == "하이측" and "상측" in it["field"]
    # left eye: mirrored — temporal is at 3 o'clock
    l_disc, l_fovea = (340.0, 400.0), (600.0, 400.0)
    assert not G.axes(l_disc, l_fovea)["od"]
    assert G.sector_info(l_disc, l_fovea, (440, 400))["hour"] == 3
    polys = G.sector_polygons(disc, fovea)
    assert [p[0] for p in polys] == [s[0] for s in G.SECTORS]
    for _name, _rgb, pts in polys:
        for x, y in pts:
            assert 1.2 * 50 <= np.hypot(x - 600, y - 400) <= 2.05 * 50
    assert G.disc_fovea_angle(disc, (340.0, 430.0)) > 0 > G.disc_fovea_angle(disc, (340.0, 370.0))


def test_visual_field_points():
    disc, fovea = (600.0, 400.0), (340.0, 400.0)
    pts = G.vf_points(disc, fovea)
    assert len(pts) == 54                                           # 24-2: 54 points (blind spot pair included)
    upper = [p for p in pts if p[2]]
    assert len(upper) == 27 and all(p[1] > 400 for p in upper)      # the upper field lies on the lower retina
    sc = 260 / 15.5
    xs = sorted({round((p[0] - 340) / sc) for p in pts})
    assert xs[0] == -27 and xs[-1] == 21        # 27° into the nasal field (temporal retina), 21° towards the disc


def test_enhance_and_change_map():
    rgb = synth_fundus(eye="OD", fov_deg=45, size=(400, 400), circle=(200, 200, 190), seed=2)
    out = G.enhance_wide(rgb)
    assert out.shape == rgb.shape and (out[..., 0] == out[..., 1]).all()       # red-free: grey
    assert (out[0, 0] == rgb[0, 0]).all()                                       # outside the circle untouched
    assert (G.enhance_wide(rgb, False, 0) == rgb).all()
    colour = G.enhance_wide(rgb, False, 2.0)
    assert not (colour[..., 0] == colour[..., 1]).all()
    same = G.diff_map(rgb, rgb)
    assert (same[..., 0] == same[..., 1]).all()                                 # no change: all grey
    changed = rgb.copy()
    changed[180:220, 180:220] = 255
    d = G.diff_map(rgb, changed)
    assert d[200, 200, 0] > d[200, 200, 1] + 80 and d[200, 200, 2] > d[200, 200, 1]   # pink where it changed
    assert (d[60, 200, 0] == d[60, 200, 1])
    assert (G.blend(rgb, changed, 0.0) == rgb).all()


# -- the window -------------------------------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _photo(image_id, eye="OD", seed=4, when="2026-01-05 10:00:00", shift=0):
    from fundusview import discpair, imaging, measure
    from fundusview.ui.glaucoma_dialog import Photo

    circle = (400, 400, 380)
    rgb = synth_fundus(eye=eye, fov_deg=45, size=(800, 800), circle=circle, seed=seed)
    geo = measure.Geometry(*circle, fov_deg=45, fov_type="external", projection="perspective")
    disc = imaging.detect_disc(rgb, circle, disc_frac=0.085)
    assert disc is not None
    disc_px = discpair.disc_diameter_px(geo, disc[:2], (800, 800))
    if shift:                                                       # the same photo, framed ``shift`` px to the right
        rgb = G.shifted(rgb, shift, 0)
    return Photo(image_id, rgb, eye, (disc[0] + shift, disc[1]), disc_px, (400.0 + shift, 400.0), True, when, "45°")


def test_disc_tab_cuts_around_the_disc_and_each_point_moves_on_its_own(app):
    from fundusview.ui.glaucoma_dialog import DT_CUP_DOT, DT_GRAB, DiscTab

    tab = DiscTab(_photo(1))
    assert tab.has_image() and tab.img.shape[0] == tab.img.shape[1]
    assert tab.disc["pts"].shape == (G.RING, 2) == tab.cup["pts"].shape       # eight points an outline
    assert not tab.warn.isVisibleTo(tab)
    tab.reset_outlines()                                            # (the size a disc has there: not yet fitted)
    tab._changed()
    side = tab.img.shape[0]
    # the outlines at the disc's own size: 3.5 disc diameters across the picture
    assert np.ptp(G.curve(tab.disc)[:, 1]) == pytest.approx(side / 3.5 * 1.05, rel=0.01)
    assert tab.metrics()["vertical"] == pytest.approx(0.50 / 1.05, abs=0.01)
    assert tab.state == {"disc": "default", "cup": "default"} and "기본 크기" in tab.lbl_auto.text()
    u = 1.0 / tab.view.scale()                                      # one screen pixel in the picture's
    mid = side / 2.0
    # the two middles lie on each other: the dot in the middle is the cup's, the ring round it the disc's
    assert G.centre(tab.disc) == pytest.approx((mid, mid), abs=0.01) == G.centre(tab.cup)
    disc0, cup0 = tab.disc["pts"].copy(), tab.cup["pts"].copy()
    tab._press(mid + 0.5 * DT_CUP_DOT * u, mid)
    tab._move(mid + 0.5 * DT_CUP_DOT * u + 10, mid + 4)
    tab._release()
    assert tab.cup["pts"] == pytest.approx(cup0 + (10, 4)) and (tab.disc["pts"] == disc0).all()
    assert tab.state == {"disc": "default", "cup": "hand"} and "컵: 직접 맞춤" in tab.lbl_auto.text()
    tab._press(mid - 0.6 * DT_GRAB * u, mid)                        # (nearer the disc's middle than the cup's now)
    tab._move(mid - 0.6 * DT_GRAB * u - 6, mid + 8)
    tab._release()
    assert tab.disc["pts"] == pytest.approx(disc0 + (-6, 8)) and tab.cup["pts"] == pytest.approx(cup0 + (10, 4))
    assert G.centre(tab.disc) == pytest.approx((mid - 6, mid + 8), abs=0.01)   # the mark follows its outline
    tab.reset_outlines()
    tab._changed()
    # drag the cup's lower point down: that point alone moves — the vertical C/D grows, the inferior rim
    # narrows, the superior one is as it was; the cup's middle follows
    c, rim0, v0 = tab.cup["pts"].copy(), tab.metrics()["rim"], tab.metrics()["vertical"]
    low = c[4][1] - mid
    tab._press(*c[4])
    assert tab._drag["key"] == "cup" and tab._drag["what"] == 4
    tab._move(c[4][0], c[4][1] + 0.6 * low)
    assert tab.cup["pts"][4] == pytest.approx((c[4][0], c[4][1] + 0.6 * low))
    assert (np.delete(tab.cup["pts"], 4, axis=0) == np.delete(c, 4, axis=0)).all()
    assert tab.metrics()["vertical"] == pytest.approx(v0 * 1.3, abs=0.01)
    assert tab.metrics()["rim"]["S"] == pytest.approx(rim0["S"], abs=0.004) and tab.metrics()["rim"]["I"] < rim0["I"] - 0.05
    assert G.centre(tab.cup)[1] > mid + 2
    tab._release()
    assert tab._drag is None and tab.lbl_v.text() == f"{tab.metrics()['vertical']:.2f}"
    # … the disc's nasal point on its own, and a point between them wherever it is dragged (not along an axis)
    d = tab.disc["pts"].copy()
    tab._press(*d[2])
    tab._move(d[2][0] + 12, d[2][1])
    tab._release()
    assert tab.disc["pts"][2] == pytest.approx(d[2] + (12, 0)) and (tab.disc["pts"][6] == d[6]).all()
    tab._press(*d[1])
    tab._move(d[1][0] + 6, d[1][1] - 9)
    tab._release()
    assert tab.disc["pts"][1] == pytest.approx(d[1] + (6, -9))
    # … but not past its neighbour: the line does not cross itself
    tab._press(*tab.disc["pts"][1])
    tab._move(d[3][0], d[3][1] + 20)                                # (dragged round to below the next two points)
    tab._release()
    turn = [math.atan2(y - G.centre(tab.disc)[1], x - G.centre(tab.disc)[0]) for x, y in tab.disc["pts"][:3]]
    assert turn[0] < turn[1] < turn[2]
    # the line itself, between two points: the whole outline
    tab.reset_outlines()
    d = tab.disc["pts"].copy()
    on_line = G.curve(tab.disc)[G.CURVE_PER // 2]
    assert np.hypot(*(d - on_line).T).min() > DT_GRAB * u            # (no point within reach there)
    tab._press(*on_line)
    assert tab._drag["key"] == "disc" and tab._drag["what"] == "c"
    tab._move(on_line[0] + 5, on_line[1] - 7)
    tab._release()
    assert tab.disc["pts"] == pytest.approx(d + (5, -7))
    tab._press(3, 3)                                                # nothing there: nothing is held
    assert tab._drag is None
    # another field: the outlines stay where they are on the photo
    tab.reset_outlines()
    tab.set_outlines(tab.disc, {"pts": tab.cup["pts"] + (-10, 0)})
    before, tall = tab.metrics(), np.ptp(G.curve(tab.disc)[:, 1]) / side
    tab.set_field("wide")
    assert tab.metrics()["vertical"] == pytest.approx(before["vertical"]) and tab.metrics()["area"] == pytest.approx(before["area"])
    assert np.ptp(G.curve(tab.disc)[:, 1]) / tab.img.shape[0] == pytest.approx(tall * 3.5 / 5.0, rel=1e-6)
    n_od = tab.metrics()["rim"]["N"]
    tab.set_eye("OS")
    assert tab.eye() == "OS" and tab.metrics()["rim"]["T"] == pytest.approx(n_od)
    assert "DDLS" in tab.lbl_rim.text() and "가장 얇은 림" in tab.lbl_rim.text() and "하이측" in tab.lbl_rim.text()
    tab.set_eye("")
    assert "눈(OD/OS)" in tab.lbl_rim.text() and "DDLS" in tab.lbl_rim.text()
    out = tab.render()
    assert out.shape == tab.img.shape and (out != tab.img).any()                # the outlines are drawn in
    assert "C/D" in tab.note() and "mm" not in tab.lbl_ratio.text()             # (a photo without a scale)


def _disc_photo(image_id=1, cup=0.5, rx=0.9, ry=1.1, offset=(14, -9), scale_known=False, found=True, rgb=None):
    """A photo that is all optic disc region: a disc ``rx`` · ``ry`` of the size expected, a pale cup."""
    from fundusview.ui.glaucoma_dialog import Photo

    n = 630
    rgb = _disc_crop(n, 1 / 3.0, rx, ry, cup, offset) if rgb is None else rgb
    return Photo(image_id, rgb, "OD", ((n - 1) / 2, (n - 1) / 2), n / 3.0, None, found, "2026-01-05 10:00:00", "",
                 scale_known=scale_known)


def test_disc_tab_starts_on_the_disc_margin_and_the_cup_on_a_line_of_equal_depth(app):
    from fundusview import disc3d
    from fundusview.ui.glaucoma_dialog import DiscTab

    tab = DiscTab(_disc_photo(cup=0.5, scale_known=True))
    assert tab.state == {"disc": "auto", "cup": "auto"} and tab.method == "hybrid"
    side = tab.img.shape[0]
    rd = side / 3.5 / 2.0                                           # the radius a disc is expected to have there
    disc = G.curve(tab.disc)
    assert np.ptp(disc[:, 1]) == pytest.approx(2 * 1.1 * rd, rel=0.06)          # the green line: on the disc drawn
    assert np.ptp(disc[:, 0]) == pytest.approx(2 * 0.9 * rd, rel=0.06)
    k = side / 3.5 / (630 / 3.0)                                    # photo px → the picture shown
    assert G.centre(tab.disc) == pytest.approx((side / 2 + 14 * k, side / 2 - 9 * k), abs=4)
    m = tab.metrics()
    assert m["vertical"] == pytest.approx(0.5, abs=0.06) and m["horizontal"] == pytest.approx(0.5, abs=0.08)
    assert "사진에서 찾음" in tab.lbl_auto.text() and "하이브리드 등고선 30%" in tab.lbl_auto.text()
    v = tab.by_method()                                             # each way of estimating, on its own line
    assert set(v) == set(disc3d.METHODS) and v["hybrid"] == pytest.approx(m["vertical"], abs=0.01)
    assert "추정 방식별 수직 C/D" in tab.lbl_auto.text() and f"<b>하이브리드 {v['hybrid']:.2f}</b>" in tab.lbl_auto.text()
    # the lines of equal depth drawn over the photo: nested, the cup's among them
    lines = tab.contours()
    levels = [lv for lv, _ in lines]
    areas = [G.area({"poly": pts}) for _, pts in lines]
    assert 0.3 in levels and len(lines) >= 6 and all(a > b for a, b in zip(areas, areas[1:]))
    on = dict(lines)[0.3]
    assert np.ptp(on[:, 1]) == pytest.approx(np.ptp(G.curve(tab.cup)[:, 1]), rel=0.02)   # the yellow line lies on it
    shown = tab.render()
    tab.sw_contour.setChecked(False)
    assert not (tab.render() == shown).all()
    # 컵 기준 깊이: a deeper line of equal depth is a smaller cup — the cup goes there
    tab.s_level.slider.setValue(round(60 / 5))
    assert tab.metrics()["vertical"] < m["vertical"] - 0.03 and "등고선 60%" in tab.lbl_auto.text()
    tab.s_level.slider.setValue(round(30 / 5))
    assert tab.metrics()["vertical"] == pytest.approx(m["vertical"], abs=1e-6)
    # a point moved by hand stays until the cup is put back on its line
    p = tab.cup["pts"][0].copy()
    tab._press(*p)
    tab._move(p[0], p[1] - 0.1 * rd)
    tab._release()
    assert tab.state["cup"] == "hand" and tab.metrics()["vertical"] > m["vertical"] + 0.01
    tab.b_cup.click()
    assert tab.state["cup"] == "auto" and tab.metrics()["vertical"] == pytest.approx(m["vertical"], abs=1e-6)
    tab.set_method("pallor")
    assert tab.methods.key() == "pallor" and "밝기 등고선 30%" in tab.lbl_auto.text()
    assert tab.metrics()["vertical"] == pytest.approx(v["pallor"], abs=0.01)
    # the green line moved by hand, then 자동 맞춤: both back where the photo puts them
    tab.set_method("hybrid")
    tab.set_outlines({"pts": tab.disc["pts"] * 1.2}, tab.cup)
    assert tab.state == {"disc": "hand", "cup": "auto"}             # (the cup, handed back as it is, stands as it did)
    tab.b_auto.click()
    assert tab.state == {"disc": "auto", "cup": "auto"} and tab.metrics()["vertical"] == pytest.approx(m["vertical"], abs=0.01)
    # the disc's size by the photo's scale, and the cup a disc of that size has
    assert tab.disc_mm() == pytest.approx(1.8 * 1.1, rel=0.06) and "mm" in tab.lbl_ratio.text()
    assert "정상 평균 C/D" in tab.lbl_ratio.text() and "디스크 크기 반영" in tab.lbl_rim.text()
    # a large cup is read large; a photo with no disc to see keeps the size a disc has there
    big = DiscTab(_disc_photo(cup=0.8))
    assert big.metrics()["vertical"] == pytest.approx(0.8, abs=0.07) and big.disc_mm() is None
    flat = DiscTab(_disc_photo(rgb=np.full((630, 630, 3), 120, np.uint8)))
    assert flat.state == {"disc": "none", "cup": "none"} and "찾지 못함" in flat.lbl_auto.text()
    assert flat.metrics()["vertical"] == pytest.approx(0.50 / 1.05, abs=0.01)
    lost = DiscTab(_disc_photo(found=False))                        # the disc's place is only a guess: not fitted
    assert lost.state == {"disc": "default", "cup": "default"} and lost.warn.isVisibleTo(lost)
    lost.auto_fit()                                                 # … until asked
    assert lost.state == {"disc": "auto", "cup": "auto"}
    assert DiscTab(None).metrics() is None


def test_wide_tab_starts_from_the_photo_landmarks(app):
    from fundusview.ui.glaucoma_dialog import WideTab

    ph = _photo(1)
    tab = WideTab(ph)
    assert tab.disc == pytest.approx(ph.disc) and tab.fovea == pytest.approx((400, 400))
    assert tab.tool == "mark" and tab.eye() == "OD"                 # nothing to point at first
    dx, dy = tab.disc
    tab.click(dx, dy - 60)
    tab.c_kind.setCurrentText("디스크 출혈")
    tab.click(dx - 60, dy)
    f = tab.findings()
    assert [x["hour"] for x in f] == [12, 9] and f[1]["kind"] == "디스크 출혈" and f[1]["sector"] == "이측"
    assert "12시 방향" in tab.lbl_list.text() and "소견 2곳" in tab.note()
    grey = tab.render()
    tab.sw_rf.setChecked(False)
    assert not (tab.render() == grey).all()
    tab.clear_marks()
    assert tab.findings() == []
    # a photo without landmarks: point at the disc, then the fovea
    bare = WideTab(type(ph)(2, ph.rgb, None, ph.disc, ph.disc_px, None, False))
    assert bare.disc is None and bare.tool == "disc"
    bare.click(600, 400)
    assert bare.tool == "fovea"
    bare.click(340, 400)
    assert bare.tool == "mark" and bare.eye() == "OD" and "OD" in bare.lbl_geo.text()


def test_pair_tabs_register_and_compose(app):
    from fundusview.ui.glaucoma_dialog import PAIR_PX, ProgressTab, StereoTab

    a, b = _photo(1), _photo(2, shift=12, when="2026-03-01 09:00:00")
    st = StereoTab((a, b))
    assert st.a.shape == (PAIR_PX, PAIR_PX, 3) and st.b.shape == st.a.shape    # both cut around their discs
    assert abs(st.dx) < 6 and abs(st.dy) < 6                        # the discs are centred: nearly registered
    assert st.compose().shape == st.a.shape                         # wiggle: one photo at a time
    first = st.compose().copy()
    st._phase = 1
    assert st.compose() is st._bs and first.shape == st._bs.shape
    for mode, shape in (("sbs", (PAIR_PX, 2 * PAIR_PX + 10)), ("cross", (PAIR_PX, 2 * PAIR_PX + 10)),
                        ("ana", (PAIR_PX, PAIR_PX)), ("depth", (PAIR_PX + 120, PAIR_PX))):
        st.set_mode(mode)
        assert st.compose().shape[:2] == shape and not st._timer.isActive()
    assert "시차" in st.status.text() and st.note() == "스테레오 깊이 지도"
    st.set_mode("wiggle")
    assert st._timer.isActive()
    st.set_region("full")                                           # whole photos: the 12 px shift is found
    assert st.a.shape[:2] == (800, 800) and st.dx == pytest.approx(-12, abs=1.5)
    st.set_offset(100, -100)
    assert (st.dx, st.dy) == (60.0, -40.0)
    st.set_swap(True)
    assert st.eyes()[1] is st.a and st.sw_swap.isChecked()
    st._timer.stop()

    pg = ProgressTab((b, a))                                        # given later-first: the earlier is the baseline
    assert [p.image_id for p in pg.pair] == [1, 2] and "2026-01-05" in pg.lbl_dates.text()
    assert pg.mix.isHidden() and not pg.speed.isHidden()
    pg.set_mode("blend")
    assert not pg.mix.isHidden() and pg.speed.isHidden() and not pg._timer.isActive()
    assert pg.compose().shape == pg.a.shape
    pg.set_mode("diff")
    d = pg.compose()
    assert d.shape == pg.a.shape
    assert pg.note() == "녹내장 분석 — 경과 비교 (2026-01-05 → 2026-03-01)" and pg.eye() == "OD"

    empty = StereoTab(None)
    assert not empty.has_image() and empty.compose() is None and not empty._timer.isActive()
    empty.auto_align()
    empty.set_offset(3, 3)


def test_dialog_saves_what_it_shows(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    saved = []

    def save(rgb, note, eye, ids):
        saved.append((rgb.shape, note, eye, ids))
        return 77

    one = GlaucomaDialog(_photo(1), title_line="홍길동", save_record=save)
    assert one.tabs.currentWidget() is one.disc and not one.stereo.has_image()
    assert one.save_to_record() == 77 and saved[-1][2:] == ("OD", [1]) and "C/D" in saved[-1][1]
    one.tabs.setCurrentWidget(one.stereo)                           # no pair: nothing to save
    assert one.save_to_record() is None and len(saved) == 1 and "없습니다" in one.status.text()
    one.copy()
    assert "없습니다" in one.status.text()

    a, b = _photo(1), _photo(2, when="2026-03-01 09:00:00")
    two = GlaucomaDialog(a, b, save_record=save)
    assert two.tabs.currentWidget() is two.progress                 # two days: a follow-up
    two.progress._timer.stop()
    two.stereo._timer.stop()
    assert two.save_to_record() == 77 and saved[-1][3] == [1, 2] and saved[-1][0] == two.progress.a.shape
    same_day = GlaucomaDialog(a, _photo(3, seed=5))
    assert same_day.tabs.currentWidget() is same_day.stereo and not same_day.b_record.isEnabled()
    same_day.stereo._timer.stop()
    same_day.progress._timer.stop()

    out = tmp_path / "분석"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    two.tabs.setCurrentWidget(two.wide)
    two.save_file()
    assert (tmp_path / "분석.jpg").stat().st_size > 1000
    two.copy()
    assert not QApplication.clipboard().image().isNull() or "복사" in two.status.text()


def test_main_window_flow(app, demo_dir, tmp_path, monkeypatch, import_and_wait):
    from PySide6.QtWidgets import QMessageBox

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.models import MODALITY_LABELS
    from fundusview.ui.main_window import MainWindow

    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, title, text, *a, **k: said.append((title, text)))
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    w = MainWindow(s, Database(tmp_path / "lib" / "fundus.db"))
    try:
        w.show()
        btn = w.tb_cmd.widgetForAction(w.acts["glaucoma"])            # on the command toolbar, 디스크 2장 under ▾
        assert btn.text() == "Glaucoma" and "glaucoma" in MODALITY_LABELS
        assert [a.text() for a in btn.menu().actions()] == ["녹내장 분석", "시간별 비교 (이 눈의 유두 사진 여러 장)",
                                                              "디스크 2장 (보험 청구용)"]
        w.open_glaucoma()                                           # no photo yet
        assert said and said[-1] == ("녹내장 분석", "사진을 고르세요.")
        import_and_wait(app, w, [demo_dir / "PatientCapture", demo_dir / "RetiCam"])
        by_patient = {}
        for pt in w.db.list_patients():
            rows = [r for r in w.db.images_for_patient(pt["id"]) if r["modality"] not in ("anterior", "disc")]
            if rows:
                by_patient[pt["id"]] = rows
        first, second = next(v for v in by_patient.values() if len(v) >= 2)[:2]

        def show(image_id):                                         # as the user does: the patient, then the photo
            w._select_patient_ref(w.db.get_image(image_id)["patient_ref"])
            w._show_image(image_id)
            w.compare = None
            app.processEvents()
            assert w.current["id"] == image_id

        show(first["id"])
        dlg, why = w._build_glaucoma()
        assert why == "" and dlg.disc.has_image() and dlg.wide.has_image() and not dlg.stereo.has_image()
        assert dlg.disc.photo.disc_px > 4
        n = len(w.db.images_for_patient(first["patient_ref"]))
        new_id = dlg.save_to_record()
        row = w.db.get_image(new_id)
        assert len(w.db.images_for_patient(first["patient_ref"])) == n + 1
        assert row["modality"] == "glaucoma" and row["patient_ref"] == first["patient_ref"]
        assert "C/D" in row["note"] and row["disc_x"] is None and row["fov_deg"] is None
        assert first["id"] in (__import__("json").loads(row["meta_json"])["derived_from"])
        assert dlg.save_to_record() == new_id                       # the same picture is stored once

        show(first["id"])
        pair, why = w._build_glaucoma(second["id"])
        assert why == "" and pair.disc.has_image() and pair.surface.has_image()
        same_eye = first["laterality"] in ("OD", "OS") and first["laterality"] == second["laterality"]
        assert pair.stereo.has_image() == same_eye and pair.progress.has_image() == same_eye
        assert pair.stereo.image_ids() == ([first["id"], second["id"]] if same_eye else [])
        for t in (pair.stereo, pair.progress):
            t._timer.stop()

        show(new_id)                                                # an analysis picture is not analysed again
        again, why = w._build_glaucoma()
        assert again is None and "녹내장 분석" in why
        other = next((v[0] for k, v in by_patient.items() if k != first["patient_ref"]), None)
        if other is not None:
            show(first["id"])
            assert w._build_glaucoma(other["id"]) == (None, "서로 다른 환자의 사진입니다.")
    finally:
        w.close()


def test_patient_explanation_model():
    """환자 설명: the field narrows and the schematic cup grows with the stage."""
    import numpy as np

    from fundusview import glaucoma as G

    assert G.STAGES == ("정상", "초기", "중기", "말기") and len(G.STAGE_TEXT) == 4
    assert all(t.startswith(name + ":") for t, name in zip(G.STAGE_TEXT, G.STAGES))
    scene = G.sample_scene(300)
    assert scene.shape == (198, 300, 3) and scene.dtype == np.uint8
    assert scene[10, 10, 2] > scene[10, 10, 0]                         # RGB: the sky is blue
    fields = [G.field_simulation(k, 300, scene) for k in range(4)]
    assert np.array_equal(fields[0], scene)                            # 정상: the whole field
    h, w = scene.shape[:2]
    lost = [float(np.mean(np.abs(f.astype(int) - scene).sum(axis=2) > 30)) for f in fields]
    assert lost[0] == 0 and lost[0] < lost[1] < lost[2] < lost[3] and lost[3] > 0.8
    for f in fields:                                                   # fixation is spared at every stage
        assert np.array_equal(f[h // 2, w // 2], scene[h // 2, w // 2])
    assert np.abs(fields[3][5, 5].astype(int) - scene[5, 5]).sum() > 100           # 말기: the corner is gone
    # 초기: an arc above fixation is dimmed, below it is not
    up = np.abs(fields[1][int(h * 0.27), w // 2].astype(int) - scene[int(h * 0.27), w // 2]).sum()
    down = np.abs(fields[1][int(h * 0.73), w // 2].astype(int) - scene[int(h * 0.73), w // 2]).sum()
    assert up > 60 and down < 10
    assert np.array_equal(G.field_simulation(9, 300, scene), fields[3])             # out of range: clipped
    cups = [int((G.disc_schematic(k, 200)[100][:, 1] > 215).sum()) for k in range(4)]       # the pale row of the cup
    assert cups == sorted(cups) and cups[0] < cups[3] and cups[0] > 0             # the pale cup widens
    pic = G.explain_picture(2, 300, scene)
    assert pic.shape[0] == h and pic.shape[1] > w + h


def test_patient_explanation_tab(tmp_path):
    import numpy as np
    from PySide6.QtWidgets import QApplication

    from fundusview import glaucoma as G
    from fundusview.demo import synth_fundus
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog, Photo

    app = QApplication.instance() or QApplication([])
    rgb = synth_fundus(eye="OD", size=(400, 420))
    saved = []
    photo = Photo(1, rgb, "OD", (300.0, 200.0), 60.0, (200.0, 205.0), True, "2026-01-15", "OD 2026-01-15")
    dlg = GlaucomaDialog(photo, None, save_record=lambda *a: saved.append(a) or 7)
    try:
        dlg.show()
        app.processEvents()
        names = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
        assert names == ["디스크 C/D", "3D 입체", "광각 분석", "스테레오 보기", "경과 비교", "시간별 비교",
                         "환자 설명"]
        assert dlg.tabs.currentWidget() is dlg.disc                  # the analysis still comes first
        tab = dlg.explain
        dlg.tabs.setCurrentWidget(tab)
        app.processEvents()
        assert [b.text() for b in tab.stages.buttons] == list(G.STAGES)
        assert tab.stage == 0 and tab.lbl_text.text() == G.STAGE_TEXT[0] and tab.has_image()
        assert tab.lbl_model.text() == G.NOTE_MODEL and "실제 진행 단계를 뜻하지 않습니다" in G.NOTE_MODEL
        first = dlg.shown()
        tab.stages.buttons[3].click()                                # 말기
        assert tab.stage == 3 and tab.lbl_text.text().startswith("말기:") and "22%" in tab.lbl_cd.text()
        last = dlg.shown()
        assert first.shape == last.shape and float(last.mean()) < float(first.mean()) * 0.8
        assert np.array_equal(last, G.explain_picture(3, 600, tab._scene))
        tab.set_stage(1)
        assert tab.stages.key() == "1" and tab.note() == "녹내장 환자 설명 — 초기 (설명용 모형)"
        # a model is not a finding: it can be copied or saved to a file, never into the patient record
        assert dlg.save_to_record() is None and saved == [] and "설명용 모형" in dlg.status.text()
        dlg.copy()
        assert not QApplication.clipboard().image().isNull()
        dlg.tabs.setCurrentWidget(dlg.disc)                          # the analysis tabs save as before
        assert dlg.save_to_record() == 7 and len(saved) == 1
    finally:
        dlg.close()


def test_find_turn_and_match_point():
    """Two photos of one eye from slightly different places differ by a small turn and size too: 자동 맞춤
    finds them from matched vessel points; a 기준점 then lays the two exactly on each other there."""
    from fundusview import imaging

    circle = (400, 400, 380)
    a = synth_fundus(eye="OD", fov_deg=45, size=(800, 800), circle=circle, seed=4)
    b = G.turned(a, -3.0, 1.03, 14.0, -9.0)                         # b: a turned, enlarged and moved
    found = G.find_turn(a, b)
    assert found is not None
    angle, scale, dx, dy = found
    assert angle == pytest.approx(3.0, abs=0.3) and scale == pytest.approx(1 / 1.03, abs=0.01)
    back = G.turned(b, angle, scale, dx, dy)
    core = (slice(250, 550), slice(250, 550))
    assert np.abs(back[core].astype(int) - a[core].astype(int)).mean() < 6
    # 기준점: where b lies 2.5 px off, the point is found and the shift that lays it on a
    disc = imaging.detect_disc(a, circle, disc_frac=0.085)
    x, y = disc[0] + 40, disc[1] - 30                               # by the disc: vessels to go by
    off = G.shifted(a, 2.5, -1.5)
    assert G.match_point(a, off, x, y) == pytest.approx((-2.5, 1.5), abs=0.3)
    assert G.match_point(a, off, 3, 3) is None                       # at the edge: nothing to go by
    flat = np.full_like(a, 90)
    assert G.match_point(flat, flat, 400, 400) is None               # an even patch: nothing to go by


def test_stereo_reference_point_holds_the_picture_still_there(app):
    from fundusview.ui.glaucoma_dialog import StereoTab

    a = _photo(1)
    b = _photo(2)
    import dataclasses
    b = dataclasses.replace(b, rgb=G.turned(b.rgb, 2.0, 1.0, 5.0, -4.0))   # taken from a little aside
    st = StereoTab((a, b))
    st.set_region("full")
    assert abs(st.angle) == pytest.approx(2.0, abs=0.4)             # 자동 맞춤: the turn as well as the shift
    assert "회전" in st.status.text()
    x, y = a.disc[0] - 60, a.disc[1] + 50
    st.set_mode("wiggle")
    st._on_press(x, y)                                              # 위글: a click is the 기준점
    assert st.ref == (x, y) and "기준점" in st.status.text()
    pa = st.a[int(y) - 20:int(y) + 21, int(x) - 20:int(x) + 21].astype(int)
    pb = st._bs[int(y) - 20:int(y) + 21, int(x) - 20:int(x) + 21].astype(int)
    assert np.abs(pa - pb).mean() < 5                               # there the two are one picture
    # the point is marked on the screen, not in what is saved
    st._phase = 0
    shown = st.compose()
    assert not np.array_equal(shown, st.a)
    st._timer.stop()
    saved = st.render()
    assert saved is not None
    # 맞춤 해제: no turn, no 기준점
    st.clear_alignment()
    assert st.ref is None and st.angle == 0.0 and (st.dx, st.dy) == (0.0, 0.0)
    st._timer.stop()
