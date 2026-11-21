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
    lit = disc3d.render(tex, H, 40, 0, 0, zoom=1.0)
    assert np.abs(lit.astype(int) - front.astype(int)).max() > 20   # the slopes catch the light
    lines = disc3d.render(tex, H, 40, 0, 0, zoom=1.0, light=0.0, contours=True)
    assert (np.abs(lines.astype(int) - front.astype(int)).sum(axis=2) > 60).sum() > 200
    small = disc3d.render(tex, H, 40, 20, -15, out_px=200)
    assert small.shape == (200, 200, 3)
    ana = disc3d.anaglyph(tex, H, 40, 0, 0)
    assert (ana[..., 1] == ana[..., 2]).all() and not (ana[..., 0] == ana[..., 1]).all()


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
    assert "추정" in tab.status.text() and tab.note().startswith("녹내장 분석 — 유두 3D (1장 추정)")
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
    assert tab.depth_px() == pytest.approx(2.0 * 0.5 * disc3d.TEX_PX / 5.0)
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
    assert tab.note().startswith("녹내장 분석 — 유두 3D (2장 스테레오)") and tab.image_ids() == [1, 2] and tab.eye() == "OD"
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
    assert "다른 눈" in odos.surface.status.text() and odos.surface.eye() is None


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
        assert edge.shape[1] == 2 and np.hypot(*(edge - (out["cx"], out["cy"])).T).max() < r
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


def test_tab_estimates_the_cd_ratio_and_hands_the_cup_to_the_disc_tab(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    dlg = GlaucomaDialog(_photo(1, _disc_picture(cup=0.6)))
    tab = dlg.surface
    tab.set_view(0, 0)
    m = tab.metrics()
    assert m["vertical"] == pytest.approx(0.6 / 1.05, abs=0.08)     # (the disc tab's outline starts 1.05 tall)
    assert tab.lbl_cd.text() == f"{m['vertical']:.2f}" and "수평 C/D" in tab.lbl_cd2.text()
    assert tab.note().endswith(f"추정 수직 C/D {m['vertical']:.2f}")
    lines = tab.compose()
    tab.sw_lines.setChecked(False)
    assert not (tab.compose() == lines).all()                       # the disc and cup lines are on the surface
    tab.s_level.set(60)
    assert tab.metrics()["vertical"] < m["vertical"]
    tab.s_level.set(30)
    d = dict(dlg.disc.disc)                                         # the disc margin is the disc tab's green line
    dlg.disc.set_ellipses({**d, "top": d["top"] * 1.25, "bottom": d["bottom"] * 1.25}, dlg.disc.cup)
    assert tab.metrics()["vertical"] == pytest.approx(m["vertical"] / 1.25, abs=0.02)
    dlg.disc.set_field("wide")                                      # … whatever field either tab shows
    tab.set_field("near")
    assert tab.metrics()["vertical"] == pytest.approx(0.6 / 1.05, abs=0.08)
    tab.b_apply.click()
    assert dlg.tabs.currentWidget() is dlg.disc
    assert dlg.disc.metrics()["vertical"] == pytest.approx(tab.metrics()["vertical"], abs=0.01)
    assert dlg.disc.metrics()["area"] == pytest.approx(tab.metrics()["area"], abs=0.01)
    blank = GlaucomaDialog(_photo(1, np.full((N, N, 3), 120, np.uint8))).surface    # no cup to see
    assert blank.metrics() is None and blank.lbl_cd.text() == "–" and "추정하지 못했습니다" in blank.lbl_cd2.text()
    assert not blank.b_apply.isEnabled() and blank.note() == "녹내장 분석 — 유두 3D (1장 추정)"
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
    assert "다른 날짜" in tab.status.text() and tab.metrics() is None
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
    for yaw, pitch in ((0, 0), (30, -35), (-60, 60), (65, -65), (-65, -65)):
        lit = disc3d.shade(tex, H, 40.0, disc3d.rotation(yaw, pitch))
        assert abs(int(lit[5, 5, 0]) - 150) <= 1                    # away from the hollow: as taken
        assert lit[40:88, 40:88].max() > 160 and lit[40:88, 40:88].min() < 140    # its walls: lit and shaded
