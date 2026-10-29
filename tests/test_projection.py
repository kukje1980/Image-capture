import math

import pytest

from fundusview import projection as proj


def test_external_internal_convention():
    # ultra-wide-field convention: 200° internal ≈ 135° external
    assert proj.external_from_internal(200) == pytest.approx(135, abs=1.0)
    assert proj.internal_from_external(135) == pytest.approx(200, abs=1.0)
    for ext in (30, 45, 50, 90):
        assert proj.external_from_internal(proj.internal_from_external(ext)) == pytest.approx(ext, abs=1e-6)


def test_stereographic_is_perspective_from_front_pole():
    for t in (0.1, 0.6, 1.2):
        assert proj.g(t, "perspective", d=1.0) == pytest.approx(proj.g(t, "stereographic"))


@pytest.mark.parametrize("projection", proj.PROJECTIONS)
def test_rho_inverse(projection):
    tmax = math.radians(82.5)
    for r in (0.0, 0.2, 0.5, 0.9, 1.0):
        assert proj.rho(proj.theta_of_rho(r, tmax, projection), tmax, projection) == pytest.approx(r, abs=1e-9)


@pytest.mark.parametrize("projection", proj.PROJECTIONS)
def test_image_sphere_round_trip(projection):
    cx, cy, rad, tmax, roll = 1088.0, 1088.0, 1023.0, math.radians(67.5), math.radians(12)
    for u, v in ((1088, 1088), (1500, 900), (300, 1700), (1088 + 1000, 1088)):
        p = proj.image_to_sphere(u, v, cx, cy, rad, tmax, projection, rotation=roll)
        assert p is not None and math.isclose(sum(c * c for c in p), 1.0, rel_tol=1e-9)
        back = proj.sphere_to_image(p, cx, cy, rad, tmax, projection, rotation=roll)
        assert back == pytest.approx((u, v), abs=1e-6)
    assert proj.image_to_sphere(0, 0, cx, cy, rad, tmax, projection) is None  # outside the circle


def test_image_orientation():
    # image right -> +x, image up -> +y, centre -> posterior pole
    tmax = math.radians(60)
    assert proj.image_to_sphere(100, 100, 100, 100, 50, tmax, "equidistant") == pytest.approx((0, 0, -1), abs=1e-6)
    x, y, z = proj.image_to_sphere(150, 100, 100, 100, 50, tmax, "equidistant")
    assert x > 0 and abs(y) < 1e-9
    x, y, z = proj.image_to_sphere(100, 50, 100, 100, 50, tmax, "equidistant")
    assert y > 0 and abs(x) < 1e-9


def test_disc_distance_on_apollo_uwa():
    """Equidistant 165°: the measured disc of the vendor UWA sample (~250 px from
    centre at r = 1023 px) lies ~20° from the pole — anatomically 4.5 mm / 12 mm."""
    tmax = proj.theta_max(165, "internal")
    theta = proj.theta_of_rho(250 / 1023, tmax, "equidistant")
    assert math.degrees(theta) == pytest.approx(20.2, abs=0.5)


def test_radial_model():
    tmax = math.radians(88)
    for r in (0.0, 0.1, 0.324, 0.7, 1.0):
        t = proj.theta_of_rho(r, tmax, "radial")
        assert proj.rho(t, tmax, "radial") == pytest.approx(r, abs=1e-9)
    # RetiCam calibration: the disc measured at 0.324 R lies ≈ 22° from the fovea (176° field)
    assert math.degrees(proj.theta_of_rho(0.324, tmax, "radial")) == pytest.approx(22.0, abs=0.3)
    # c = 0 is equidistant
    assert proj.rho(0.5, tmax, "radial", c=0.0) == pytest.approx(proj.rho(0.5, tmax, "equidistant"))
