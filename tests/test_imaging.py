import math
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from fundusview import imaging
from fundusview.demo import synth_fundus


def test_circle_with_text_strip_and_logo():
    """APOLLO-like frame: circle + burned-in text below it + logo in a corner."""
    w, h = 1088, 1148
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    d.ellipse([33, 33, 33 + 1022, 33 + 1022], fill=(190, 110, 70))
    d.rectangle([10, 1080, 400, 1140], fill=(255, 255, 255))      # corner text
    d.rectangle([900, 1090, 1080, 1140], fill=(230, 230, 230))    # logo
    cx, cy, r = imaging.detect_circle(np.asarray(img))
    assert (cx, cy, r) == pytest.approx((544, 544, 511), abs=4)


def test_clipped_circle():
    """45° camera frame: circle clipped at top and bottom."""
    img = Image.new("RGB", (1000, 750))
    ImageDraw.Draw(img).ellipse([50, -75, 950, 825], fill=(180, 90, 50))
    cx, cy, r = imaging.detect_circle(np.asarray(img))
    assert (cx, cy, r) == pytest.approx((500, 375, 450), abs=5)


@pytest.mark.parametrize("eye,fov,ftype,proj_", [
    ("OD", 135, "internal", "equidistant"), ("OS", 165, "internal", "equidistant"),
    ("OD", 45, "external", "perspective")])
def test_disc_found_on_synthetic_retina(eye, fov, ftype, proj_):
    from fundusview import projection as proj

    rgb = synth_fundus(eye=eye, fov_deg=fov, fov_type=ftype, projection=proj_, size=(544, 574), seed=3)
    circle = imaging.detect_circle(rgb)
    tmax = proj.theta_max(fov, ftype)
    disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / math.degrees(tmax)), search=0.8)
    assert disc is not None
    # expected: 21° nasal, 1.5° up
    exp = proj.sphere_to_image(proj.sphere_point(math.radians(21.05), (0.071 if eye == "OD" else math.pi - 0.071)),
                               *circle, tmax, proj_)
    assert math.dist(disc[:2], exp) < 0.08 * circle[2]
    assert imaging.laterality_from_disc(disc, circle) == eye


def test_adjust_identity_and_channels():
    rgb = (np.arange(48, dtype=np.uint8).reshape(4, 4, 3) * 5)
    assert imaging.adjust(rgb) is rgb
    g = imaging.adjust(rgb, channel="green")
    assert (g[..., 0] == rgb[..., 1]).all() and (g[..., 2] == rgb[..., 1]).all()
    inv = imaging.adjust(rgb, invert=True)
    assert (inv.astype(int) == 255 - rgb.astype(int)).all()


def test_alpha_mask_excludes_surround():
    rgb = synth_fundus(size=(272, 287))
    circle = imaging.detect_circle(rgb)
    a = imaging.fundus_alpha(rgb, circle)
    assert a[5, 5] == 0 and a[int(circle[1]), int(circle[0])] == 255


def test_fast_paths_match_the_plain_ones(monkeypatch):
    """OpenCV does the per-pixel work of the alpha mask and the display adjustments (a 24-megapixel
    photo: 0.06 s instead of 1.5 s) — with the results the numpy / Pillow code gives."""
    pytest.importorskip("cv2")
    rgb = synth_fundus(size=(1434, 1076), fov_deg=176, projection="radial", circle=(717, 538, 522)).copy()
    rgb[5:40, 5:200] = 255                                     # text the device burns into the corner
    circle = imaging.detect_circle(rgb)
    fast = (imaging.fundus_alpha(rgb, circle), imaging.adjust(rgb, brightness=0.1, contrast=1.3, gamma=0.8),
            imaging.adjust(rgb, channel="redfree", invert=True), imaging.adjust(rgb, channel="blue", auto=True))
    monkeypatch.setattr(imaging, "cv2", None)
    plain = (imaging.fundus_alpha(rgb, circle), imaging.adjust(rgb, brightness=0.1, contrast=1.3, gamma=0.8),
             imaging.adjust(rgb, channel="redfree", invert=True), imaging.adjust(rgb, channel="blue", auto=True))
    assert np.abs(fast[0].astype(int) - plain[0].astype(int)).max() <= 6      # the soft edge, within rounding
    assert fast[0][10, 10] == 0 and fast[0][538, 717] == 255
    for a, b in zip(fast[1:], plain[1:]):
        assert a.dtype == np.uint8 and np.array_equal(a, b)


def test_shrink_and_qimage_copies():
    pytest.importorskip("PySide6")
    from fundusview.ui.image_view import from_qimage, to_pixmap, to_qimage

    rgb = synth_fundus(size=(400, 300))
    small = imaging.shrink(rgb, 0.25)
    assert small.shape == (75, 100, 3) and abs(int(small.mean()) - int(rgb.mean())) <= 2
    assert imaging.shrink(rgb[..., 0], 0.5, like=small).shape == (75, 100)
    back = from_qimage(to_qimage(rgb))                         # its own memory: valid after the image is gone
    assert back.flags.owndata and np.array_equal(back, rgb)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    pm = to_pixmap(rgb)
    assert (pm.width(), pm.height()) == (400, 300) and app is not None
    assert np.array_equal(from_qimage(pm.toImage()), rgb)


@pytest.mark.parametrize("eye", ["OD", "OS"])
def test_fovea_tells_an_unknown_eye(eye):
    """A nasal photo whose eye is not named: the macula is looked for on both sides of the disc,
    and the side it is found on names the eye (as the web page does)."""
    import math

    from fundusview import demo, imaging, placement
    from fundusview import projection as proj

    gaze = (27.0, 1.0, 2.0) if eye == "OD" else (-27.0, 1.0, -2.0)
    rgb = demo.synth_fundus(eye=eye, fov_deg=45.0, size=(900, 900), fov_type="external",
                            projection="perspective", seed=31, gaze=gaze)
    circle = imaging.detect_circle(rgb)
    tmax = math.degrees(proj.theta_max(45.0, "external"))
    disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / tmax), search=0.7)
    assert disc is not None
    cam = placement.Camera(*circle, 45.0, "external", "perspective")
    found = imaging.detect_fovea(rgb, cam, disc[:2], None, with_side=True)
    assert found is not None and found[3] == eye
    named = imaging.detect_fovea(rgb, cam, disc[:2], eye)
    assert named is not None and math.hypot(found[0] - named[0], found[1] - named[1]) < 3.0
