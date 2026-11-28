"""유두 3D (3D 입체): the shape from one photo and from a stereo pair, the turned view, the tab."""
import os

import cv2
import numpy as np
import pytest

from fundusview import disc3d
from fundusview import glaucoma as G

N = 320


def _disc_picture(n=N, frac=1 / 3.5, cup=0.5, offset=(0, 0)):
    """An orange retina with a paler disc and a white cup in its middle, vessels across."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    c = (n - 1) / 2
    r = np.hypot(xx - c - offset[0], yy - c - offset[1]) / (frac * n / 2)
    img = np.empty((n, n, 3), np.float32)
    img[:] = (190, 80, 40)
    img[r < 1.0] = (235, 150, 95)
    img[r < cup] = (255, 240, 205)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    out = np.clip(img, 0, 255).astype(np.uint8)
    cv2.line(out, (0, n // 3), (n, n // 2), (120, 25, 20), 3, cv2.LINE_AA)
    rng = np.random.default_rng(1)
    noise = cv2.GaussianBlur(rng.normal(0, 40, (n, n)).astype(np.float32), (0, 0), 1.5)
    return np.clip(out.astype(np.float32) + noise[..., None], 0, 255).astype(np.uint8)


def test_one_photo_gives_a_cup_where_the_disc_is_pale():
    H = disc3d.height_from_photo(_disc_picture(), 1 / 3.5)
    n = H.shape[0]
    assert H.shape == (256, 256) and H.dtype == np.float32
    assert H[n // 2, n // 2] < -0.7                                 # the cup's floor
    rim = int(n / 3.5 / 2)                                          # the disc margin, above the retina
    assert H[n // 2 + rim, n // 2] > 0.05
    assert abs(H[n // 8, n // 8]) < 0.08 and H[0].max() == 0 == H[:, -1].min()   # flat away from it and at the edge
    big = disc3d.height_from_photo(_disc_picture(cup=0.8), 1 / 3.5)
    assert (big < -0.5).sum() > 1.8 * (H < -0.5).sum()              # a larger cup is a wider hollow
    off = disc3d.height_from_photo(_disc_picture(offset=(20, -12)), 1 / 3.5)   # a disc a little off centre
    iy, ix = np.unravel_index(np.argmin(off), off.shape)
    assert (ix - n / 2) * N / n == pytest.approx(20, abs=8) and (iy - n / 2) * N / n == pytest.approx(-12, abs=8)
    flat = disc3d.height_from_photo(np.full((N, N, 3), 120, np.uint8), 1 / 3.5)
    assert -0.5 < flat.min() < -0.1                                 # nothing pale: only a shallow bowl


def _stereo_pair():
    """The right picture is the left one with its middle (the cup) moved 6 px."""
    left = _disc_picture()
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    r = np.hypot(xx - N / 2, yy - N / 2) / (N / 3.5 / 2)
    shift = 6.0 * np.clip(1.0 - r / 0.8, 0, 1)
    return left, cv2.remap(left, xx - shift, yy, cv2.INTER_LINEAR)


def test_stereo_depth_follows_the_parallax():
    left, right = _stereo_pair()
    H, info = disc3d.height_from_stereo(left, right, 1 / 3.5)
    n = H.shape[0]
    assert info["enough"] and info["reliable"] and info["parallax"] > 2
    assert H[n // 2, n // 2] < -0.5 and abs(H[n // 8, n // 8]) < 0.25
    H2, info2 = disc3d.height_from_stereo(right, left, 1 / 3.5)     # the other order: still a cup
    assert H2[n // 2, n // 2] < -0.5 and info2["flipped"] != info["flipped"]
    up, _ = disc3d.height_from_stereo(left, right, 1 / 3.5, flip=True)
    assert up[n // 2, n // 2] > 0.5
    _, none = disc3d.height_from_stereo(left, left, 1 / 3.5)        # the same photo twice: no depth
    assert not none["enough"] and not none["reliable"]
    other = cv2.flip(_disc_picture(), 0)                            # not a pair: bumps all over, no flat retina
    rng = np.random.default_rng(3)
    other = np.clip(other + cv2.GaussianBlur(rng.normal(0, 90, (N, N, 1)).astype(np.float32), (0, 0), 4)[..., None],
                    0, 255).astype(np.uint8)
    _, bad = disc3d.height_from_stereo(left, other, 1 / 3.5)
    assert not bad["reliable"]


def test_render_front_is_the_photo_and_turning_moves_the_deep_part():
    tex = _disc_picture()
    H = disc3d.height_from_photo(tex, 1 / 3.5)
    front = disc3d.render(tex, H, 40, 0, 0, zoom=1.0, light=0.0)
    assert front.shape == tex.shape and np.abs(front.astype(int) - tex.astype(int)).max() <= 1
    flat = disc3d.render(tex, np.zeros_like(H), 40, 30, 0, zoom=1.0, light=0.0)
    deep = disc3d.render(tex, H, 40, 30, 0, zoom=1.0, light=0.0)

    def cup_x(img):                                                 # where the white cup is drawn
        ys, xs = np.nonzero(img[..., 2] > 170)
        return xs.mean()

    assert abs(cup_x(deep) - cup_x(flat)) > 5                       # the floor shifts against the surface
    assert np.abs(deep[N // 2, 30].astype(int) - flat[N // 2, 30].astype(int)).max() <= 2   # the flat part does not
    w = np.nonzero(flat[N // 2].sum(axis=1) > 60)[0]
    assert (w[-1] - w[0]) == pytest.approx(N * np.cos(np.radians(30)), abs=4)    # foreshortened, the rest background
    assert tuple(flat[2, 2]) == (0, 0, 0)
    other = disc3d.render(tex, H, 40, -30, 0, zoom=1.0, light=0.0)
    assert (cup_x(deep) - cup_x(flat)) * (cup_x(other) - cup_x(flat)) < 0       # the other way from the other side
    lit = disc3d.render(tex, H, 40, 0, 0, zoom=1.0)                 # from the front: the photo as it was taken,
    assert np.abs(lit.astype(int) - front.astype(int)).max() <= 1   # its own light — nothing added
    turned = disc3d.render(tex, H, 40, 30, 0, zoom=1.0)             # turned: the slopes towards the viewer a touch
    change = turned.astype(int) - deep.astype(int)                  # lighter, those turned away a touch darker
    assert change.max() > 12 and change.min() < -12
    seen = deep.sum(axis=2) > 60
    ratio = turned[seen].astype(float).sum(axis=1) / deep[seen].astype(float).sum(axis=1)
    assert disc3d.SHADE_RANGE[0] - 0.03 < ratio.min() and ratio.max() < disc3d.SHADE_RANGE[1] + 0.03   # … and no more
    lines = disc3d.render(tex, H, 40, 0, 0, zoom=1.0, light=0.0, contours=True)
    assert (np.abs(lines.astype(int) - front.astype(int)).sum(axis=2) > 60).sum() > 200
    small = disc3d.render(tex, H, 40, 20, -15, out_px=200)
    assert small.shape == (200, 200, 3)
    ana = disc3d.anaglyph(tex, H, 40, 0, 0)
    assert (ana[..., 1] == ana[..., 2]).all() and not (ana[..., 0] == ana[..., 1]).all()


def test_a_camera_at_a_distance_draws_the_near_side_larger():
    tex = np.full((N, N, 3), 140, np.uint8)
    H = np.zeros((256, 256), np.float32)
    front = disc3d.render(tex, H, 40, 0, 0, perspective=disc3d.VIEW_DIST, light=0.0)
    assert (front == disc3d.render(tex, H, 40, 0, 0, light=0.0)).all()          # from the front: no difference
    flat = disc3d.render(tex, H, 40, 35, 0, light=0.0)                           # parallel rays: both sides as tall
    near = disc3d.render(tex, H, 40, 35, 0, perspective=disc3d.VIEW_DIST, light=0.0)

    def heights(img):
        cols = np.nonzero((img.sum(axis=2) > 60).any(axis=0))[0]
        tall = (img.sum(axis=2) > 60).sum(axis=0)
        return tall[cols[0] + 2], tall[cols[-1] - 2]

    a, b = heights(flat)
    assert abs(int(a) - int(b)) <= 2
    a, b = heights(near)
    assert abs(int(a) - int(b)) > 0.15 * max(a, b)                              # one side nearer: taller
    other = disc3d.render(tex, H, 40, -35, 0, perspective=disc3d.VIEW_DIST, light=0.0)
    c, d = heights(other)
    assert (int(a) - int(b)) * (int(c) - int(d)) < 0                            # the other side, turned the other way
    assert tuple(near[2, 2]) == (0, 0, 0) and near.shape == flat.shape


def test_vessels_stand_as_even_low_ridges():
    """A vessel is as high all along, however dark it is from place to place (no beads), and low: about
    half its width above the surface."""
    n = N
    plain = np.full((n, n, 3), (190, 110, 60), np.uint8)
    img = plain.copy()
    for x in range(20, n - 20):                                     # one vessel, its darkness going up and down
        dark = 55 + 20 * np.sin(x / 9.0)
        img[n // 4 - 2:n // 4 + 3, x] = (150, 110 - dark, 40)
    img = cv2.GaussianBlur(img, (0, 0), 1.0)
    rise = disc3d.height_from_photo(img, 1 / 3.5) - disc3d.height_from_photo(plain, 1 / 3.5)
    row = int(round((n // 4) * rise.shape[0] / n))
    ridge = rise[row - 2:row + 3, 40:rise.shape[1] - 40].max(axis=0)
    assert ridge.min() > 0.5 * disc3d.VESSEL_H and ridge.max() < 1.05 * disc3d.VESSEL_H
    assert ridge.std() < 0.05 * ridge.mean()                        # even along it
    assert np.abs(rise[row + 25, 40:-40]).max() < 0.01              # beside it: the surface as it was
    assert disc3d.VESSEL_H <= 0.1 and 0.3 <= disc3d.DEPTH_DD <= 0.45


# -- the tab -----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _photo(i, rgb, eye="OD", when="2026-01-15 10:00:00"):
    from fundusview.ui.glaucoma_dialog import Photo
    return Photo(i, rgb, eye, (N / 2, N / 2), N / 3.5, None, True, when, "")


def test_tab_with_one_photo(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    saved = []
    dlg = GlaucomaDialog(_photo(1, _disc_picture()), save_record=lambda *a: saved.append(a) or 5)
    tab = dlg.surface
    assert tab.has_image() and tab.sources is None and tab.source == "a" and not tab._timer.isActive()
    assert tab.method == "hybrid"                                   # (설정 → 일반: 하이브리드 at first)
    assert "추정" in tab.status.text() and tab.note().startswith("녹내장 분석 — 유두 3D (1장 추정 · 하이브리드)")
    assert tab.image_ids() == [1] and tab.eye() == "OD"
    tab.set_view(0, 0)                                              # (stops the rocking)
    assert not tab.sw_auto.isChecked()
    front = tab.compose()
    tab.set_view(30, 10)
    turned = tab.compose()
    assert front.shape == turned.shape == (disc3d.TEX_PX, disc3d.TEX_PX, 3) and not (front == turned).all()
    tab._press(100, 100)
    tab._move(140, 100)                                             # dragging turns it
    assert tab.yaw == pytest.approx(42) and tab.pitch == pytest.approx(10)
    tab.s_depth.set(0)
    tab.sw_light.setChecked(False)
    flat = tab.compose()
    tab.s_depth.set(200)
    assert not (tab.compose() == flat).all()
    tab.set_field("wide")
    assert tab.depth_px() == pytest.approx(2.0 * disc3d.DEPTH_DD * disc3d.TEX_PX / 5.0)
    dlg.tabs.setCurrentWidget(tab)
    assert dlg.save_to_record() == 5 and saved[-1][1] == tab.note() and saved[-1][3] == [1]
    empty = GlaucomaDialog(None).surface
    assert not empty.has_image() and empty.compose() is None and empty.image_ids() == [] and empty.eye() is None


def test_tab_with_two_photos_stereo_and_flicker(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    left, right = _stereo_pair()
    dlg = GlaucomaDialog(_photo(1, left), _photo(2, right))
    dlg.stereo._timer.stop()
    dlg.progress._timer.stop()
    tab = dlg.surface
    assert tab.source == "stereo" and tab.stereo_ok and "시차" in tab.status.text()
    assert tab.note().startswith("녹내장 분석 — 유두 3D (2장 스테레오 · 혈관 꺾임)") and tab.image_ids() == [1, 2]
    assert tab.eye() == "OD" and "혈관 꺾임을 찾지 못해" in tab.status.text()     # (a straight vessel: no bend)
    H = tab.heights()
    assert H[H.shape[0] // 2, H.shape[1] // 2] < -0.4
    tab.sw_flip.setChecked(True)
    assert tab.heights()[H.shape[0] // 2, H.shape[1] // 2] > 0.4
    tab.sw_flip.setChecked(False)
    tab.set_view(20, 10)
    tab.sw_flick.setChecked(True)                                   # the two photos in turn on one surface
    one = tab.compose()
    tab._phase = 1
    assert tab.shown_photo() == 1 and not (tab.compose() == one).all()
    tab.sw_flick.setChecked(False)
    tab.set_source("b")
    assert tab.shown_photo() == 1 and tab.image_ids() == [2] and "추정" in tab.status.text()
    assert tab.sw_flip.isHidden()
    dlg.show()                                                      # the rocking runs only while the tab is seen
    dlg.tabs.setCurrentWidget(tab)
    app.processEvents()
    tab.sw_auto.setChecked(True)
    assert tab._timer.isActive()
    dlg.tabs.setCurrentWidget(dlg.disc)
    app.processEvents()
    assert not tab._timer.isActive()
    dlg.close()
    stranger = cv2.GaussianBlur(np.random.default_rng(5).integers(0, 255, (N, N, 3)).astype(np.uint8), (0, 0), 3)
    lone = GlaucomaDialog(_photo(1, left), _photo(2, stranger))     # two photos that are no stereo pair
    lone.stereo._timer.stop()
    lone.progress._timer.stop()
    assert lone.surface.source == "a" and lone.surface.stereo_ok
    lone.surface.set_source("stereo")
    assert "맞지 않아" in lone.surface.status.text() or "부족" in lone.surface.status.text()
    odos = GlaucomaDialog(_photo(1, left, "OD"), _photo(2, right, "OS"))
    odos.stereo._timer.stop()
    odos.progress._timer.stop()
    assert odos.surface.source == "a" and not odos.surface.stereo_ok
    odos.surface.set_source("stereo")
    assert "다른 눈" in odos.surface.status.text() and odos.surface.source == "a"
    assert odos.surface.eye() == "OD" and not odos.stereo.has_image() and not odos.progress.has_image()


def test_cup_read_off_the_surface_follows_the_cup():
    n, frac = 256, 1 / 3.5
    c, r = (n - 1) / 2, frac * n / 2
    disc = {"cx": c, "cy": c, "rx": r, "ry": r}
    seen = {}
    for cup in (0.3, 0.5, 0.7, 0.85):
        info = {}
        H = disc3d.height_from_photo(_disc_picture(cup=cup), frac, info=info)
        out, edge = disc3d.cup_from_surface(H, disc)
        m = G.cdr_metrics(disc, out)
        assert info["cup"] and m["vertical"] == pytest.approx(cup, abs=0.1) == m["horizontal"]
        assert edge.shape[1] == 2 and np.hypot(*(edge - G.centre(out)).T).max() < r
        seen[cup] = m["area"]
    assert seen[0.3] < seen[0.5] < seen[0.7] < seen[0.85]
    H = disc3d.height_from_photo(_disc_picture(), frac)
    wide, narrow = (G.cdr_metrics(disc, disc3d.cup_from_surface(H, disc, lv)[0])["vertical"] for lv in (0.15, 0.6))
    assert wide > narrow                                            # a deeper level: a smaller cup
    info = {}
    flat = disc3d.height_from_photo(np.full((N, N, 3), 120, np.uint8), frac, info=info)
    assert info["cup"] is False                                     # nothing pale: no cup to measure
    assert disc3d.cup_from_surface(np.zeros((n, n), np.float32), disc) is None
    pts = disc3d.outline_points({"cx": 10, "cy": 20, "top": 4, "right": 3, "bottom": 6, "left": 5}, 8)
    assert pts[0] == pytest.approx((13, 20)) and pts[2] == pytest.approx((10, 26)) and pts[4] == pytest.approx((5, 20))
    even = disc3d.outline_points({"pts": G.ring({"cx": 50, "cy": 50, "rx": 20, "ry": 20})}, 36)    # … along a line
    assert even.shape == (36, 2) and np.hypot(*(even - 50).T) == pytest.approx(20, abs=0.1)
    steps = np.hypot(*(np.roll(even, -1, axis=0) - even).T)
    assert steps.max() - steps.min() < 0.05


def test_lines_of_equal_depth_are_nested_and_the_cup_is_one_of_them():
    n, frac = 256, 1 / 3.5
    c, r = (n - 1) / 2, frac * n / 2
    disc = {"cx": c, "cy": c, "rx": r, "ry": r}
    H = disc3d.height_from_photo(_disc_picture(cup=0.6), frac)
    lines = disc3d.depth_contours(H, disc)
    assert [lv for lv, _ in lines] == list(disc3d.CONTOUR_LEVELS)
    tall = [float(np.ptp(edge[:, 1])) for _, edge in lines]
    assert all(a > b for a, b in zip(tall, tall[1:]))               # deeper: smaller
    for _lv, edge in lines:                                         # smooth closed lines round the hollow
        assert np.hypot(*(edge - (c, c)).T).max() < r and len(edge) >= 100
    cup, edge = disc3d.cup_from_surface(H, disc, 0.3)
    assert set(cup) == {"poly"} and np.allclose(edge, dict(lines)[0.3], atol=1e-4)
    assert G.cdr_metrics(disc, {"pts": G.ring(cup)})["vertical"] == pytest.approx(G.cdr_metrics(disc, cup)["vertical"],
                                                                                 abs=0.005)
    assert disc3d.depth_contours(np.zeros((n, n), np.float32), disc) == []
    # the disc's outline as eight points (the C/D tab's): the same cup as from its ellipse
    as_pts = disc3d.cup_from_surface(H, {"pts": G.ring(disc)}, 0.3)[0]
    assert G.cdr_metrics(disc, as_pts)["vertical"] == pytest.approx(G.cdr_metrics(disc, cup)["vertical"], abs=0.01)


def test_tab_estimates_the_cd_ratio_and_hands_the_cup_to_the_disc_tab(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    dlg = GlaucomaDialog(_photo(1, _disc_picture(cup=0.6)))
    tab = dlg.surface
    tab.set_view(0, 0)
    m = tab.metrics()
    assert m["vertical"] == pytest.approx(0.6, abs=0.08)            # (the disc tab's outline: on the disc's margin)
    assert tab.lbl_cd.text() == f"{m['vertical']:.2f}" and "수평 C/D" in tab.lbl_cd2.text()
    assert tab.note().endswith(f"추정 수직 C/D {m['vertical']:.2f}")
    lines = tab.compose()
    tab.sw_lines.setChecked(False)
    assert not (tab.compose() == lines).all()                       # the disc and cup lines are on the surface
    tab.s_level.set(60)
    assert tab.metrics()["vertical"] < m["vertical"]
    tab.s_level.set(30)
    assert dlg.disc.metrics()["vertical"] == pytest.approx(m["vertical"], abs=0.02)   # both tabs: the same cup
    pts, mid = dlg.disc.disc["pts"], G.centre(dlg.disc.disc)        # the disc margin is the disc tab's green line
    tall = pts.copy()
    tall[:, 1] = mid[1] + (pts[:, 1] - mid[1]) * 1.25
    dlg.disc.set_outlines({"pts": tall}, dlg.disc.cup)
    assert tab.metrics()["vertical"] == pytest.approx(m["vertical"] / 1.25, abs=0.02)
    dlg.disc.set_field("wide")                                      # … whatever field either tab shows
    tab.set_field("near")
    assert tab.metrics()["vertical"] == pytest.approx(m["vertical"] / 1.25, abs=0.04)
    tab.b_apply.click()                                             # the cup's line as the disc tab's eight points
    assert dlg.tabs.currentWidget() is dlg.disc and dlg.disc.cup["pts"].shape == (G.RING, 2)
    assert dlg.disc.state == {"disc": "hand", "cup": "given"} and "3D 입체 탭" in dlg.disc.lbl_auto.text()
    assert dlg.disc.metrics()["vertical"] == pytest.approx(tab.metrics()["vertical"], abs=0.01)
    assert dlg.disc.metrics()["area"] == pytest.approx(tab.metrics()["area"], abs=0.01)
    blank = GlaucomaDialog(_photo(1, np.full((N, N, 3), 120, np.uint8))).surface    # no cup to see
    assert blank.metrics() is None and blank.lbl_cd.text() == "–" and "추정하지 못했습니다" in blank.lbl_cd2.text()
    assert not blank.b_apply.isEnabled() and blank.note() == "녹내장 분석 — 유두 3D (1장 추정 · 하이브리드)"
    blank.set_method("pallor")
    assert blank.note() == "녹내장 분석 — 유두 3D (1장 추정)"
    assert GlaucomaDialog(None).surface.metrics() is None


def test_tab_with_two_photos_gives_the_cd_of_each_and_the_change_between_two_days(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    left, right = _stereo_pair()
    dlg = GlaucomaDialog(_photo(1, left), _photo(2, right))         # one day: two estimates and the stereo depth
    dlg.stereo._timer.stop()
    dlg.progress._timer.stop()
    tab = dlg.surface
    v = tab.both()
    assert v["days"] is None and None not in (v["a"], v["b"], v["stereo"])
    assert v["mean"] == pytest.approx((v["a"] + v["b"]) / 2) and v["spread"] == pytest.approx(abs(v["a"] - v["b"]))
    text = tab.lbl_cd2.text()
    assert f"사진 ① {v['a']:.2f}" in text and f"<b>스테레오 {v['stereo']:.2f}</b>" in text and "두 사진 평균" in text
    assert tab.note().endswith(f"(두 사진 평균 {v['mean']:.2f})")
    tab.set_source("b")
    assert tab.metrics()["vertical"] == v["b"] and f"<b>사진 ② {v['b']:.2f}</b>" in tab.lbl_cd2.text()
    # two days: the older one first, whichever was picked first, and the change to the newer one
    then, now = _disc_picture(cup=0.4), _disc_picture(cup=0.7)
    dlg = GlaucomaDialog(_photo(1, now, when="2026-01-15 10:00:00"), _photo(2, then, when="2024-03-02 09:00:00"))
    dlg.stereo._timer.stop()
    dlg.progress._timer.stop()
    tab = dlg.surface
    assert tab.follow_up and not tab.stereo_ok and tab.source == "a"   # two days are no stereo pair
    tab.set_source("stereo")
    assert "다른 날짜" in tab.status.text() and tab.source == "a" and tab.metrics() is not None
    tab.set_source("a")
    v = tab.both()
    assert v["stereo"] is None
    d = v["days"]
    assert (d["old"], d["new"], d["old_day"], d["new_day"]) == ("b", "a", "2024-03-02", "2026-01-15")
    assert d["change"] == pytest.approx(v["a"] - v["b"]) and 0.15 < d["change"] < 0.4
    text = tab.lbl_cd2.text()
    assert text.index("2024-03-02") < text.index("2026-01-15") and f"{d['change']:+.2f}" in text
    assert "오차 범위" not in text and "두 사진 평균" not in text
    tab.set_source("a")
    assert tab.note().endswith(f"(2024-03-02 {v['b']:.2f} → 2026-01-15 {v['a']:.2f})")
    same = GlaucomaDialog(_photo(1, now, when="2026-01-15 10:00:00"), _photo(2, now, when="2025-01-15 10:00:00"))
    same.stereo._timer.stop()
    same.progress._timer.stop()
    assert "오차 범위" in same.surface.lbl_cd2.text() and GlaucomaDialog(_photo(1, now)).surface.both() is None


def test_the_flat_retina_keeps_its_brightness_however_far_the_surface_is_turned():
    tex = np.full((128, 128, 3), 150, np.uint8)
    H = np.zeros((128, 128), np.float32)
    H[40:88, 40:88] = -0.5
    H = cv2.GaussianBlur(H, (0, 0), 4)
    assert (disc3d.shade(tex, H, 40.0, disc3d.rotation(0, 0)) == tex).all()     # from the front: the photo itself
    for yaw, pitch in ((30, -35), (-60, 60), (65, -65), (-65, -65)):
        lit = disc3d.shade(tex, H, 40.0, disc3d.rotation(yaw, pitch))
        assert abs(int(lit[5, 5, 0]) - 150) <= 1                    # away from the hollow: as taken
        assert lit[40:88, 40:88].max() > 160 and lit[40:88, 40:88].min() < 140    # its walls: lit and shaded
        lo, hi = disc3d.SHADE_RANGE                                 # … gently: the photo keeps its colours
        assert lit.min() >= int(150 * lo) - 1 and lit.max() <= int(150 * hi) + 1


# -- one photo: 밝기 · 혈관 꺾임 · 하이브리드 ----------------------------------------------------------
BENDING = (20, 65, 110, 160, 200, 250, 290, 335)       # the vessels' directions (degrees, y down)


def _cupped_picture(n=640, frac=1 / 3.5, cup=0.7, pallor=0.4, angles=BENDING, bend=True, pigment=False):
    """A disc whose hollow reaches ``cup`` (disc radii) but whose pale part only ``pallor`` (as in
    glaucoma): the vessels from its middle step aside where they go down the wall at ``cup``
    (bayoneting) — or run straight on (``bend`` False). ``pigment``: a dark crescent and flecks
    at the temporal margin, dark in red too (not vessels)."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    c, rd = (n - 1) / 2, frac * n / 2
    r = np.hypot(xx - c, yy - c) / rd
    img = np.empty((n, n, 3), np.float32)
    img[:] = (190, 80, 40)
    img[r < 1.0] = (235, 150, 95)
    img[r < pallor] = (255, 235, 200)
    out = np.clip(cv2.GaussianBlur(img, (0, 0), 3 * n / 320), 0, 255).astype(np.uint8)
    for a in angles:
        t = np.radians(a)
        rr = np.linspace(0.06, 1.7, 400)
        k = 1.0 - np.clip((rr - (cup - 0.05)) / 0.05, 0.0, 1.0) if bend else np.zeros_like(rr)
        ang = t + 0.22 * k * k * (3 - 2 * k)
        pts = np.stack([c + rr * rd * np.cos(ang), c + rr * rd * np.sin(ang)], axis=1)
        cv2.polylines(out, [np.round(pts * 8).astype(np.int32)], False, (175, 45, 40),
                      max(2, round(3 * n / 320)), cv2.LINE_AA, shift=3)
    if pigment:
        arc = np.linspace(-0.9, 0.9, 60)
        pts = np.stack([c + 1.05 * rd * np.cos(arc), c + 1.05 * rd * np.sin(arc)], axis=1)
        cv2.polylines(out, [np.int32(pts)], False, (70, 45, 30), 7, cv2.LINE_AA)
        for t in np.linspace(-0.7, 0.7, 5):
            cv2.circle(out, (int(c + 0.95 * rd * np.cos(t)), int(c + 0.95 * rd * np.sin(t))), 5, (60, 40, 28), -1)
    noise = cv2.GaussianBlur(np.random.default_rng(1).normal(0, 30, (n, n)).astype(np.float32), (0, 0), 1.5)
    return np.clip(out.astype(np.float32) + noise[..., None], 0, 255).astype(np.uint8)


def _vertical_cd(H, frac=1 / 3.5):
    n = H.shape[0]
    c, r = (n - 1) / 2, frac * n / 2
    disc = {"cx": c, "cy": c, "rx": r, "ry": r}
    found = disc3d.cup_from_surface(H, disc)
    return G.cdr_metrics(disc, found[0]) if found else None


def test_thinning_leaves_lines_one_pixel_wide():
    mask = np.zeros((60, 80), bool)
    mask[25:32, 5:75] = True                                        # a bar 7 px thick
    line = disc3d._thin(mask)
    assert line.sum() > 50 and (line[:, 12:68].sum(axis=0) == 1).all()
    assert (np.nonzero(line[:, 40])[0] == 28).all()                 # along its middle
    assert not disc3d._thin(np.zeros((10, 10), bool)).any()


def test_bends_are_found_where_the_vessels_step_down_into_the_cup():
    frac = 1 / 3.5
    for cup in (0.5, 0.7, 0.85):
        b = disc3d.find_bends(_cupped_picture(cup=cup, pallor=min(0.4, cup - 0.1)), frac)
        assert b["vessels"] >= 7 and b["xy"].shape == (len(b["r"]), 2)
        main = b["weight"] >= 0.4 * b["weight"].max()
        assert np.median(b["r"][main]) == pytest.approx(cup, abs=0.06)
        x, y = b["xy"].T * 640 - 319.5                              # (fractions of the picture's side)
        assert np.hypot(x, y) / (640 * frac / 2) == pytest.approx(b["r"], abs=0.01)
        radius, support = disc3d.margin_from_bends(b)
        assert radius.shape == support.shape == (360,) and np.median(radius) == pytest.approx(cup, abs=0.05)
        assert support.mean() > 0.6
    for straight in (_cupped_picture(bend=False), _cupped_picture(bend=False, pigment=True), _disc_picture()):
        b = disc3d.find_bends(straight, frac)                       # straight vessels, pigment: no bend
        assert b["vessels"] == 0 and disc3d.margin_from_bends(b) is None
    for n, field in ((320, 3.5), (640, 2.5), (640, 5.0)):           # other sizes and fields alike
        b = disc3d.find_bends(_cupped_picture(n=n, frac=1 / field), 1 / field)
        assert np.median(disc3d.margin_from_bends(b)[0]) == pytest.approx(0.7, abs=0.05)
        assert disc3d.find_bends(_cupped_picture(n=n, frac=1 / field, bend=False), 1 / field)["vessels"] == 0
    # vessels only above and below: the margin is backed there, not at the sides
    b = disc3d.find_bends(_cupped_picture(angles=(70, 110, 250, 290)), frac)
    radius, support = disc3d.margin_from_bends(b)
    assert support[60:120].max() > 0.6 and support[240:300].max() > 0.6     # (y down: 90° is below)
    assert support[0] < 0.3 and support[180] < 0.3
    assert disc3d.margin_from_bends({**b, "weight": b["weight"] * 0.05}) is None     # too few to speak of


def test_vessels_and_hybrid_read_a_cup_wider_than_its_pallor():
    frac = 1 / 3.5
    img = _cupped_picture(cup=0.7, pallor=0.4)
    surfaces = {}
    for method in disc3d.METHODS:
        info = {}
        H = disc3d.height_one_photo(img, frac, method, info=info)
        assert H.shape == (256, 256) and H.dtype == np.float32 and H.min() >= -1.0 and info["cup"]
        surfaces[method] = (H, info)
    assert np.array_equal(surfaces["pallor"][0], disc3d.height_from_photo(img, frac))
    cd = {k: _vertical_cd(H)["vertical"] for k, (H, _) in surfaces.items()}
    assert cd["pallor"] < 0.55                                      # the pale part only
    # (0.13.21: the margin is the learned one drawn to the bends — on this drawing a little inside them)
    assert all(0.55 < cd[k] < 0.8 and cd[k] > cd["pallor"] + 0.08 for k in ("vessels", "hybrid"))
    for k in ("vessels", "hybrid"):
        info = surfaces[k][1]
        assert info["bends"]["vessels"] >= 7 and info["support"] > 0.6
    # vessels only above and below: there the margin is theirs, at the sides the pallor's
    partial = disc3d.height_hybrid(_cupped_picture(angles=(70, 110, 250, 290)), frac)
    m = _vertical_cd(partial)
    assert m["vertical"] == pytest.approx(0.7, abs=0.08) and m["horizontal"] < m["vertical"] - 0.1
    # no bends (0.13.21): the vessels' pattern still gives a margin — no bend is needed for it
    straight = _cupped_picture(bend=False)
    info = {}
    H = disc3d.height_from_vessels(straight, frac, info=info)
    assert info["cup"] is True and info["learned"] and len(info["bends"]["r"]) == 0
    assert 0.2 < _vertical_cd(H)["vertical"] < 0.9
    # nothing on the picture at all: no cup from the vessels (a stand-in), and the hybrid is the brightness
    blank = np.full((400, 400, 3), 120, np.uint8)
    info = {}
    disc3d.height_from_vessels(blank, frac, info=info)
    assert info["cup"] is False and info["support"] == 0.0
    info = {}
    assert np.array_equal(disc3d.height_hybrid(blank, frac, info=info), disc3d.height_from_photo(blank, frac))
    assert info["cup"] is False and info["support"] == 0.0


def _big_photo(i, rgb):
    from fundusview.ui.glaucoma_dialog import Photo
    n = rgb.shape[0]
    return Photo(i, rgb, "OD", (n / 2, n / 2), n / 3.5, None, True, "2026-01-15 10:00:00", "")


def test_tab_shows_the_three_estimates_alone_and_side_by_side(app):
    from fundusview.ui.glaucoma_dialog import (GlaucomaDialog, S3_COMPARE_PX, S3_GAP, S3_ONE)

    dlg = GlaucomaDialog(_big_photo(1, _cupped_picture()))
    tab = dlg.surface
    tab.set_view(-20, 10)                                           # (stops the rocking)
    assert tab.method == "hybrid" and tab.methods.key() == "hybrid" and not tab.sw_bends.isHidden()
    tab.set_method("pallor")
    assert tab.status.text() == S3_ONE and not tab.methods.isHidden()
    assert tab.sw_bends.isHidden() and not len(tab.bends()[0])
    v = tab.by_method()
    assert v["pallor"] < 0.55 and 0.5 < v["vessels"] < 0.78 and v["vessels"] > v["pallor"] + 0.05
    assert v["hybrid"] == pytest.approx(v["vessels"], abs=0.06)
    assert "추정 방식별 수직 C/D" in tab.lbl_cd2.text() and f"<b>밝기 {v['pallor']:.2f}</b>" in tab.lbl_cd2.text()
    tab.set_method("vessels")
    assert tab.metrics()["vertical"] == v["vessels"] and f"<b>혈관 꺾임 {v['vessels']:.2f}</b>" in tab.lbl_cd2.text()
    assert "혈관이 지나는 모양으로 읽은 컵 경계" in tab.status.text() and "점으로 표시" in tab.status.text()
    assert tab.note().startswith("녹내장 분석 — 유두 3D (1장 추정 · 혈관 꺾임) · 추정 수직 C/D")
    pts, used = tab.bends()
    assert len(pts) >= 8 and used.sum() >= 7 and not tab.sw_bends.isHidden()
    marked = tab.compose()
    tab.sw_bends.setChecked(False)                                  # the bends drawn on the photo
    assert not (tab.compose() == marked).all()
    tab.set_method("hybrid")
    assert "하이브리드" in tab.note() and "밝기로 추정" in tab.status.text()
    tab.b_apply.click()                                             # the hybrid's cup to the disc tab
    assert dlg.disc.metrics()["vertical"] == pytest.approx(v["hybrid"], abs=0.01)
    tab.sw_compare.setChecked(True)
    assert tab.comparing() and not tab.sw_bends.isHidden()
    three = tab.compose()
    assert three.shape == (S3_COMPARE_PX, 3 * S3_COMPARE_PX + 2 * S3_GAP, 3)
    shown = tab.render()                                            # (with each one's name and C/D over it)
    assert shown.shape == three.shape and not (shown[:40] == three[:40]).all()
    assert tab.note() == ("녹내장 분석 — 유두 3D (1장 추정 · 셋 나란히) · 수직 C/D "
                          f"밝기 {v['pallor']:.2f} · 혈관 꺾임 {v['vessels']:.2f} · 하이브리드 {v['hybrid']:.2f}")
    tab.sw_compare.setChecked(False)
    assert tab.compose().shape == (disc3d.TEX_PX, disc3d.TEX_PX, 3)
    # straight vessels (0.13.21): their pattern is read all the same — said without bends to show
    plain = GlaucomaDialog(_big_photo(1, _cupped_picture(bend=False))).surface
    plain.set_method("vessels")
    assert "뚜렷한 꺾임은 찾지 못함" in plain.status.text() and plain.metrics() is not None
    # a picture with nothing on it: no cup from the vessels, the hybrid as the brightness
    blank = GlaucomaDialog(_big_photo(1, np.full((400, 400, 3), 120, np.uint8))).surface
    blank.set_method("vessels")
    assert "충분히 찾지 못했습니다" in blank.status.text() and blank.metrics() is None and blank.lbl_cd.text() == "–"
    blank.set_method("hybrid")
    assert "[밝기]와 같은 모양" in blank.status.text()


def test_the_window_opens_on_the_estimate_set_in_the_settings(app):
    from fundusview.config import Settings
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    assert Settings().disc3d_method == "hybrid"
    for method in disc3d.METHODS:
        tab = GlaucomaDialog(_big_photo(1, _cupped_picture()), method=method).surface
        assert tab.method == method and tab.methods.key() == method
        assert tab.metrics()["vertical"] == tab.by_method()[method]
    assert GlaucomaDialog(_big_photo(1, _cupped_picture()), method="what").surface.method == "hybrid"
    # … and the stereo depth on the one set there too (처음 설정: 시차 + 혈관 꺾임)
    assert Settings().disc3d_stereo_method == "parallax_vessels"
    left, right = _cupped_stereo_pair()
    for method in disc3d.STEREO_METHODS:
        dlg = GlaucomaDialog(_big_photo(1, left), _big_photo(2, right), stereo_method=method)
        dlg.stereo._timer.stop()
        dlg.progress._timer.stop()
        tab = dlg.surface
        assert tab.source == "stereo" and tab.stereo_method == method and tab.stereo_methods.key() == method
        assert tab.metrics()["vertical"] == tab.by_method()[method]
    assert GlaucomaDialog(_big_photo(1, left), stereo_method="what").surface.stereo_method == "parallax_vessels"


def _cupped_stereo_pair(bend=True, cup=0.7, shift=8.0):
    """``_cupped_picture`` and the same seen from beside: the hollow (its wall at ``cup``) moved."""
    left = _cupped_picture(cup=cup, pallor=0.4, bend=bend)
    n = left.shape[0]
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    r = np.hypot(xx - (n - 1) / 2, yy - (n - 1) / 2) / (n / 3.5 / 2)
    k = np.clip((cup + 0.08 - r) / 0.16, 0, 1)
    return left, cv2.remap(left, xx - shift * k * k * (3 - 2 * k), yy, cv2.INTER_LINEAR)


def test_stereo_depth_with_the_cup_margin_where_the_vessels_bend():
    frac = 1 / 3.5
    left, right = _cupped_stereo_pair()
    plain, info = disc3d.height_from_stereo(left, right, frac)
    both, info2 = disc3d.height_stereo_vessels(left, right, frac)
    assert info["reliable"] and info2["reliable"] and info2["parallax"] == info["parallax"]
    assert info2["bends"]["vessels"] >= 7 and info2["support"] > 0.6
    n = both.shape[0]
    assert both[n // 2, n // 2] < -0.8 and abs(both[n // 8, n // 8]) < 0.25        # the parallax's depth
    wall = _vertical_cd(both)["vertical"]
    assert wall == pytest.approx(0.7, abs=0.06)                    # the margin where the vessels bend …
    assert abs(_vertical_cd(plain)["vertical"] - 0.7) > abs(wall - 0.7)            # … nearer than the parallax's
    up, i_up = disc3d.height_stereo_vessels(left, right, frac, flip=True)    # 깊이 뒤집기: raised — no hollow
    assert up[n // 2, n // 2] > 0.5 and i_up["no_hollow"] and i_up["support"] == 0.0    # for the bends to wall
    assert np.array_equal(up, disc3d.height_from_stereo(left, right, frac, flip=True)[0])
    flat, flat_info = _cupped_stereo_pair(bend=False)               # straight vessels: the parallax itself
    H, i3 = disc3d.height_stereo_vessels(flat, flat_info, frac)
    assert np.array_equal(H, disc3d.height_from_stereo(flat, flat_info, frac)[0]) and i3["support"] == 0.0
    # each photo's bends half: a bend the two share counts in full
    one = disc3d.find_bends(left, frac)
    merged = disc3d.merge_bends(one, disc3d.find_bends(right, frac))
    assert len(merged["r"]) == len(one["r"]) + len(disc3d.find_bends(right, frac)["r"])
    assert merged["weight"].sum() == pytest.approx((one["weight"].sum() + disc3d.find_bends(right, frac)["weight"].sum()) / 2)
    alone = disc3d.merge_bends(one, disc3d.find_bends(flat, frac))
    assert alone["weight"].sum() == pytest.approx(one["weight"].sum() / 2) and alone["vessels"] == one["vessels"]


def test_tab_stereo_depth_with_or_without_the_bends(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog, S3_COMPARE_PX, S3_GAP

    left, right = _cupped_stereo_pair()
    dlg = GlaucomaDialog(_big_photo(1, left), _big_photo(2, right))
    dlg.stereo._timer.stop()
    dlg.progress._timer.stop()
    tab = dlg.surface
    tab.set_view(-20, 10)
    assert tab.source == "stereo" and tab.stereo_method == "parallax_vessels"       # (처음: 시차 + 혈관 꺾임)
    assert tab.methods.isHidden() and not tab.stereo_methods.isHidden() and not tab.sw_bends.isHidden()
    assert "컵 경계는 혈관이 꺾이는 곳" in tab.status.text() and "시차" in tab.status.text()
    v = tab.by_method()
    assert set(v) == {"parallax", "parallax_vessels"} and v["parallax_vessels"] == pytest.approx(0.7 / 1.05, abs=0.08)
    assert tab.metrics()["vertical"] == v["parallax_vessels"] and tab.both()["stereo"] == v["parallax_vessels"]
    assert "깊이 방식별 수직 C/D" in tab.lbl_cd2.text() and f"<b>시차 + 혈관 꺾임 {v['parallax_vessels']:.2f}</b>" in tab.lbl_cd2.text()
    assert tab.note().startswith("녹내장 분석 — 유두 3D (2장 스테레오 · 혈관 꺾임) · 추정 수직 C/D")
    pts, used = tab.bends()
    assert len(pts) >= 8 and used.any()
    tab.set_stereo_method("parallax")                               # the parallax alone, as before
    assert tab.note().startswith("녹내장 분석 — 유두 3D (2장 스테레오) · 추정 수직 C/D") and not len(tab.bends()[0])
    assert tab.sw_bends.isHidden() and tab.metrics()["vertical"] == v["parallax"] and "꺾임" not in tab.status.text()
    tab.set_stereo_method("parallax_vessels")
    tab.sw_flip.setChecked(True)                                    # raised: the bends are not used
    assert "쓰지 않았습니다" in tab.status.text()
    tab.sw_flip.setChecked(False)
    tab.set_stereo_method("parallax")
    tab.sw_compare.setChecked(True)                                 # 둘 나란히: the two, turned alike
    assert tab.comparing() and tab.sw_compare.text() == "둘 나란히 비교"
    two = tab.compose()
    assert two.shape == (S3_COMPARE_PX, 2 * S3_COMPARE_PX + S3_GAP, 3)
    assert tab.note() == ("녹내장 분석 — 유두 3D (2장 스테레오 · 둘 나란히) · 수직 C/D "
                          f"시차 {v['parallax']:.2f} · 시차 + 혈관 꺾임 {v['parallax_vessels']:.2f}")
    tab.set_source("a")                                             # one photo of the two: its three estimates
    assert not tab.methods.isHidden() and tab.stereo_methods.isHidden() and tab.sw_compare.text() == "셋 나란히 비교"
    assert tab.compose().shape == (S3_COMPARE_PX, 3 * S3_COMPARE_PX + 2 * S3_GAP, 3)
    tab.sw_compare.setChecked(False)
    tab.set_method("vessels")
    assert tab.note().startswith("녹내장 분석 — 유두 3D (1장 추정 · 혈관 꺾임)")


# -- the nerve behind the disc -------------------------------------------------------------------------
def _outlines(n, frac=1 / 3.5, cup=0.4):
    c, r = (n - 1) / 2, frac * n / 2
    def oval(k):
        return {"cx": c, "cy": c, "top": r * k, "right": r * k, "bottom": r * k, "left": r * k}
    return oval(1.0), oval(cup)


def test_the_stripes_of_a_photo_give_their_direction_and_grain_gives_none():
    n, ang = 400, np.radians(30.0)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    rng = np.random.default_rng(3)
    grain = rng.normal(0, 0.6, (n, n)).astype(np.float32) + 40 * np.cos(xx / n * 3) * np.sin(yy / n * 2.5)   # (and shading)
    across = -xx * np.sin(ang) + yy * np.cos(ang)                   # constant along the 30° direction
    striped = 120 + 1.3 * np.sin(across * 2 * np.pi / 9.0) + grain    # faint stripes …
    for g, sure in ((striped, True), (120 + grain, False)):
        tex = np.clip(np.stack([g + 60, g, g - 60], -1), 0, 255).astype(np.uint8)
        for x in range(20, n, 130):                                  # … under dark vessels running another way
            cv2.line(tex, (x, 0), (x + 40, n), (110, 30, 25), 7, cv2.LINE_AA)
        f = disc3d.fibre_field(tex, 1 / 3.5)
        conf = np.hypot(f[..., 0], f[..., 1])
        far = disc3d._radius(f.shape[0], 1 / 3.5) > 1.6
        assert f.shape == (128, 128, 2)
        if not sure:
            assert (conf[far] > disc3d.FIELD_MIN).mean() < 0.05
            continue
        assert (conf[far] > disc3d.FIELD_MIN).mean() > 0.5
        theta = np.degrees(0.5 * np.arctan2(f[..., 1], f[..., 0]))[far & (conf > disc3d.FIELD_MIN)]
        assert abs(float(np.median(theta)) - 30.0) < 4.0
        assert conf[disc3d._radius(f.shape[0], 1 / 3.5) < 0.8].max() < disc3d.FIELD_MIN  # nothing is read on the disc itself


def test_strands_thin_out_with_the_rim_and_follow_the_photo_where_it_was_read():
    n = disc3d.TEX_PX
    H = np.zeros((64, 64), np.float32)
    disc, cup = _outlines(n)
    full = disc3d.fibre_paths(disc, cup, H, 40.0, n, 150)
    assert 100 < len(full) <= 150 and len(disc3d.fibre_paths(disc, cup, H, 40.0, n, 40)) < 41
    wide = _outlines(n, cup=0.85)[1]
    assert len(disc3d.fibre_paths(disc, wide, H, 40.0, n, 150)) < len(full) / 2       # a thin rim: few strands
    # a cup grown downwards only: the strands lost are the ones below
    low = {**cup, "bottom": disc["bottom"] * 0.9}
    lost = [p for p, q in zip(full, [None] * len(full))
            if not any((p["seed"] == r["seed"]).all() for r in disc3d.fibre_paths(disc, low, H, 40.0, n, 150))]
    assert lost and all(np.sin(p["seed"][0]) > 0 for p in lost)
    c = (n - 1) / 2
    for p in full:
        assert np.hypot(*(p["retina"][0] - c)) > np.hypot(*(p["retina"][-1] - c))    # from far out to the rim
        assert p["behind"][0][2] == pytest.approx(0.0) and p["behind"][-1][2] < -40.0 - 0.09 * n / 2     # … and out behind
    assert disc3d.read_share(full) == 0.0
    # the photo's stripes run straight up and down: the strands turn that way where they can
    field = np.zeros((32, 32, 2), np.float32)
    field[..., 0] = -1.0                                             # 2θ = 180°: θ = 90°
    read = disc3d.fibre_paths(disc, cup, H, 40.0, n, 150, field=field)
    assert disc3d.read_share(read) > 0.3
    turned = [p["retina"][0] - p["retina"][3] for p in read if p["read"][:8].all()]
    assert turned and all(abs(d[1]) > abs(d[0]) for d in turned)
    # … and a strand ends where the photo does
    mask = np.ones((n, n), bool)
    mask[:, :n // 3] = False
    assert all(p["retina"][:, 0].min() >= n // 3 for p in disc3d.fibre_paths(disc, cup, H, 40.0, n, 150, mask=mask)
               if len(p["retina"]))


def test_the_nerve_is_drawn_behind_the_sheet_and_shows_through_it():
    tex = cv2.resize(_disc_picture(), (disc3d.TEX_PX, disc3d.TEX_PX))
    H = disc3d.height_from_photo(tex, 1 / 3.5)
    disc, cup = _outlines(disc3d.TEX_PX)
    paths = disc3d.fibre_paths(disc, cup, H, 60.0)
    drawn = disc3d.fibres_on_texture(tex, paths)
    assert drawn.shape == tex.shape and not (drawn == tex).all()
    flat, deep = disc3d.pulses(paths, 2.0)
    assert len(flat) + len(deep) == len(paths) and len(disc3d.pulses(paths, 2.0, on_retina=False)[1]) == len(paths)
    behind = disc3d.fibres_behind(paths, disc, 60.0, dots=deep)
    plain = disc3d.render(tex, H, 60.0, -60, 10)
    solid = disc3d.render(tex, H, 60.0, -60, 10, behind=behind)
    glass = disc3d.render(tex, H, 60.0, -60, 10, behind=behind, sheet_alpha=0.6)
    sheet = cv2.erode((plain.sum(axis=2) > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    assert (solid[sheet] == plain[sheet]).all()                      # an opaque sheet hides what is behind it
    assert (solid != plain).any()                                    # … the bundle comes out beside it
    assert not (glass[sheet] == plain[sheet]).all()
    front = disc3d.render(tex, H, 60.0, 0, 0, behind=behind)
    assert (front[60:-60, 60:-60] == disc3d.render(tex, H, 60.0, 0, 0)[60:-60, 60:-60]).all()        # from the front it is all behind the photo


def test_tab_shows_the_nerve_only_when_asked(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    dlg = GlaucomaDialog(_photo(1, _disc_picture(), eye="OS"))
    tab = dlg.surface
    tab.set_view(-50, 10)
    assert not tab.sw_nerve.isChecked() and tab.fibres() is None and tab.nerve_rows.isHidden()
    before = tab.compose()
    assert not tab._timer.isActive() and "시신경" not in tab.note()
    dlg.tabs.setCurrentWidget(tab)
    dlg.show()
    assert not tab._timer.isActive()
    tab.sw_nerve.setChecked(True)
    assert tab._timer.isActive() and not tab.nerve_rows.isHidden()  # (the signals move)
    paths, drawn, _disc = tab.fibres()
    assert paths and tab.temporal() == 0.0 and "가닥" in tab.lbl_nerve.text() and "시신경 다발" in tab.note()
    shown = tab.compose()
    assert shown.shape == before.shape and not (shown == before).all()
    tab.sw_pulse.setChecked(False)
    assert not tab._timer.isActive()
    still = tab.compose()
    assert (still == tab.compose()).all()
    tab.sw_xray.setChecked(False)
    tab.sw_rnfl.setChecked(False)
    solid = tab.compose()
    sheet = cv2.erode((before.sum(axis=2) > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    assert (solid[sheet] == before[sheet]).all() and not (solid == before).all()
    tab.s_strands.set(40)
    assert len(tab.fibres()[0]) <= 40
    tab.sw_ana.setChecked(True)
    assert tab.compose().shape == before.shape
    tab.sw_nerve.setChecked(False)
    tab.sw_ana.setChecked(False)
    assert (tab.compose() == before).all()
    dlg.close()
