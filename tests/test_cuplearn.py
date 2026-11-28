"""학습한 컵 경계 (cuplearn.py): the ring of profiles round the disc and the margin read off it."""
import math

import numpy as np
import pytest

from fundusview import cuplearn as L
from fundusview import disc3d


def _disc_picture(cup=0.5, n=420, rd=60.0, centre=(210.0, 210.0)):
    """A pale disc on a darker fundus, a paler cup in it, dark vessels fanning out from the middle."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    r = np.hypot(xx - centre[0], yy - centre[1]) / rd
    img = np.zeros((n, n, 3), np.float32)
    img[..., 0], img[..., 1], img[..., 2] = 150, 80, 40
    on = np.clip((1.05 - r) / 0.1, 0, 1)
    img += on[..., None] * np.float32([70, 80, 60])
    img += np.clip((cup - r) / 0.12, 0, 1)[..., None] * np.float32([25, 60, 70])
    th = np.arctan2(yy - centre[1], xx - centre[0])
    for a in np.radians([20, 75, 105, 160, 200, 255, 285, 340]):
        d = np.abs(np.angle(np.exp(1j * (th - a)))) * r * rd
        img -= (np.clip(1.0 - d / 2.5, 0, 1) * (r > 0.12) * (r < 2.2))[..., None] * np.float32([40, 60, 30])
    return np.clip(img, 0, 255).astype(np.uint8)


def _circle(c, r, k=96):
    t = np.linspace(0, 2 * math.pi, k, endpoint=False)
    return np.stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)], 1)


def test_the_profiles_follow_the_disc_whatever_its_size_and_place():
    a = L.profiles(_disc_picture(), _circle((210, 210), 60))
    assert a.shape == (L.A, L.R, 3) and a.dtype == np.float32 and np.isfinite(a).all()
    # the same disc drawn larger and off the middle, outlined as it is: the same ring of profiles
    b = L.profiles(_disc_picture(rd=80.0, centre=(190.0, 230.0)), _circle((190, 230), 80))
    assert float(np.abs(a - b).mean()) < 0.06
    # an outline as its middle and radii round it
    (cx, cy), rad = L.disc_polar(_circle((100.0, 120.0), 40.0))
    assert (cx, cy) == pytest.approx((100.0, 120.0), abs=0.2) and rad == pytest.approx(np.full(L.A, 40.0), abs=0.3)
    assert L.design(a, "both").shape == (L.A, 3 * L.R * 5 + 4) and L.design(a, "vessels").shape == (L.A, L.R * 5 + 4)


def test_the_weights_are_there_and_the_margin_stays_inside_the_disc():
    m = L.weights()
    for which in L.CHANNELS:
        width = L.design(np.zeros((L.A, L.R, 3), np.float32), which).shape[1]
        assert m[f"{which}_w"].shape == (width,) and m[f"{which}_mu"].shape == (width,) and np.isfinite(m[f"{which}_w"]).all()
    img, curve = _disc_picture(cup=0.5), _circle((210, 210), 60)
    for which in L.CHANNELS:
        k = L.ratio(L.profiles(img, curve), which)
        assert k.shape == (L.A,) and (k >= L.RATIO[0] - 1e-6).all() and (k <= L.RATIO[1] + 1e-6).all()
        cup = L.cup_curve(img, curve, which)
        assert cup.shape == (L.A, 2)
        assert (np.hypot(cup[:, 0] - 210, cup[:, 1] - 210) <= 60 * L.RATIO[1] + 0.5).all()
        f = np.fft.rfft(k)                                             # smooth round the disc
        assert np.abs(f[L.HARMONICS:]).max() < 0.02 * L.A
    # a larger pale cup is read larger (the model goes by what the photo shows)
    small = L.ratio(L.profiles(_disc_picture(cup=0.3), curve), "both").mean()
    large = L.ratio(L.profiles(_disc_picture(cup=0.75), curve), "both").mean()
    assert large > small + 0.1


def test_the_one_photo_surfaces_use_the_learned_margin():
    img = _disc_picture(cup=0.5)
    frac = 1 / 3.5
    for method in ("vessels", "hybrid"):
        info = {}
        H = disc3d.height_one_photo(img, frac, method, info=info)
        assert H.shape == (256, 256) and info["cup"] and info["learned"] and info["support"] == 1.0
    p = disc3d._pallor(img, frac, 256)
    r = disc3d.learned_margin(img, frac, p, "both")
    assert r.shape == (360,) and 0.12 <= float(r.min()) and float(r.max()) <= 0.97
    # a picture with nothing on it: no cup is claimed
    info = {}
    disc3d.height_one_photo(np.full((300, 300, 3), 110, np.uint8), frac, "vessels", info=info)
    assert info["cup"] is False
