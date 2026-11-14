"""망막 높낮이 (relief.py): the shape of the retina under a photo — raised vessels, the disc's cup, the
foveal pit — and the fine mesh the 3D eye builds from it."""
import math

import numpy as np
import pytest

from fundusview import demo, imaging, placement, relief
from fundusview import projection as proj


@pytest.fixture(scope="module")
def photo():
    rgb = demo.synth_fundus(eye="OD", fov_deg=45.0, size=(700, 700), fov_type="external", projection="perspective")
    circle = imaging.detect_circle(rgb)
    tmax = math.degrees(proj.theta_max(45.0, "external"))
    disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / tmax))
    cam = placement.Camera(*circle, 45.0, "external", "perspective")
    fovea = imaging.detect_fovea(rgb, cam, disc[:2], "OD")
    return rgb, circle, tmax, disc[:2], fovea[:2], cam


def test_vessels_stand_up_the_cup_and_pit_go_down(photo):
    rgb, circle, tmax, disc, fovea, _ = photo
    v, step = relief.vessels(rgb, circle, tmax)
    assert v.shape == (math.ceil(rgb.shape[0] / step), math.ceil(rgb.shape[1] / step))
    assert 0.0 <= v.min() and v.max() <= 1.0
    # vessels are thin dark lines: the strong part is a small share of the field, darker than the rest
    g = rgb[::int(step), ::int(step), 1].astype(float)
    strong = v > 0.5
    assert 0.01 < strong.mean() < 0.2 and g[strong].mean() < g[~strong].mean()
    H = relief.height_map(v, step, circle, tmax, disc, fovea)
    at = lambda p: H[int(p[1] / step), int(p[0] / step)]      # noqa: E731
    assert at(disc) < -0.5                                      # the cup's floor
    assert at(fovea) < -0.3                                     # the pit
    assert H.max() > 0.3 and -1.0 <= H.min() and H.max() <= 1.0
    cx, cy, r = circle                                          # flat at the edge of the image circle
    assert abs(H[int(cy / step), min(H.shape[1] - 1, int((cx + 0.99 * r) / step))]) < 0.05
    no_marks = relief.height_map(v, step, circle, tmax)
    assert at(disc) < no_marks[int(disc[1] / step), int(disc[0] / step)] - 0.5


def test_heights_in_sixteen_bits(photo):
    H = np.linspace(-1.0, 1.0, 1001, dtype=np.float32).reshape(1, -1)
    img = relief.encode16(H)
    assert img.dtype == np.uint8 and img.shape == (1, 1001, 4) and (img[..., 3] == 255).all()
    back = (img[..., 0].astype(float) * 256 + img[..., 1]) / 65535.0 * 2.0 - 1.0     # as the shader reads it
    assert np.abs(back - H).max() < 1e-4


def test_sheet_follows_the_photo_on_the_eye(photo):
    rgb, circle, tmax, disc, fovea, cam = photo
    v, step = relief.vessels(rgb, circle, tmax)
    H = relief.height_map(v, step, circle, tmax, disc, fovea)
    pl = placement.place(cam, fovea=fovea, disc=disc, laterality="OD")
    R, A = 0.9, 0.05
    pos, nrm, idx = relief.sheet_mesh(H, step, circle, cam, pl.matrix, A, R, n=96)
    rad = np.linalg.norm(pos, axis=1)
    assert rad.min() >= R - A - 1e-4 and rad.max() <= R + A + 1e-4
    assert rad.min() < R - 0.2 * A and rad.max() > R + 0.5 * A          # raised and sunk
    d = pos / rad[:, None]
    assert (np.sum(nrm * -d, axis=1) > 0.0).all()                       # normals into the eye
    assert idx.dtype == np.uint32 and len(idx) % 3 == 0 and idx.max() < len(pos)
    # the fovea's direction on the sheet: the posterior pole (the photo was placed by its fovea)
    pole = np.array(placement.POLE)
    nearest = d[np.argmax(d @ pole)]
    assert placement.angle_between(nearest, pole) < 2.0
