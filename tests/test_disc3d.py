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
    assert "추정" in tab.status.text() and tab.note() == "녹내장 분석 — 유두 3D (1장 추정)"
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
    assert tab.note() == "녹내장 분석 — 유두 3D (2장 스테레오)" and tab.image_ids() == [1, 2] and tab.eye() == "OD"
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
