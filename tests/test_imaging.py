import math

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
