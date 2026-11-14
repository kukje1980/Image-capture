"""Where a photo lies on the eye (placement.py): the fovea at the posterior pole, the disc nasal —
found in the photo (imaging.detect_fovea / detect_disc) or marked by hand."""
import math
import sqlite3

import numpy as np
import pytest

from fundusview import demo, imaging, placement
from fundusview import projection as proj
from fundusview.placement import POLE, Camera, angle_between


def _turned(eye="OD", gaze=None, *, fov=135.0, ftype="internal", projection="equidistant", size=(544, 574), seed=1):
    """A demo photo with the camera turned by ``gaze`` and the true pixels of its fovea and disc."""
    rgb = demo.synth_fundus(eye=eye, fov_deg=fov, fov_type=ftype, projection=projection, size=size, seed=seed,
                            gaze=gaze)
    circle = imaging.detect_circle(rgb)
    cam = Camera(*circle, fov, ftype, projection)
    r = demo.gaze_rotation(*gaze) if gaze else np.eye(3)
    side = 1.0 if eye != "OS" else -1.0                      # the demo retina: disc at (±21°, 1.5°) from the fovea
    disc_eye = np.array(proj.sphere_point(math.radians(math.hypot(21.0, 1.5)), math.atan2(1.5, side * 21.0)))
    return rgb, cam, cam.pixel(r.T @ POLE), cam.pixel(r.T @ disc_eye), r, disc_eye


def _found(rgb, cam, eye):
    tmax = math.degrees(cam.tmax)
    disc = imaging.detect_disc(rgb, (cam.cx, cam.cy, cam.r), disc_frac=min(0.25, 3.8 / max(tmax, 5.0)))
    fovea = imaging.detect_fovea(rgb, cam, disc[:2] if disc else None, eye)
    return (disc[:2] if disc else None), (fovea[:2] if fovea else None)


def _apart(cam, a, b) -> float:
    return angle_between(cam.direction(*a), cam.direction(*b))


# -- the turn ------------------------------------------------------------------------------------
@pytest.mark.parametrize("c", [(0.2, 0.1, -0.97), (-0.5, 0.3, -0.8), (0.0, 0.9, -0.4), (0.7, -0.6, 0.3)])
def test_tilt_takes_the_pole_to_the_centre_without_torsion(c):
    c = np.array(c) / np.linalg.norm(c)
    m = placement.tilt(c)
    assert np.allclose(m @ POLE, c) and np.allclose(m @ m.T, np.eye(3)) and np.linalg.det(m) == pytest.approx(1.0)
    axis = np.array([m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1]])
    assert abs(axis[2]) < 1e-9 * max(1.0, np.linalg.norm(axis))          # the axis lies in the xy-plane
    assert np.allclose(placement.tilt(POLE), np.eye(3))


def test_centre_for_puts_a_point_where_it_belongs():
    rng = np.random.default_rng(3)
    for _ in range(50):
        q = rng.normal(size=3) * (1, 1, 0.4) + (0, 0, -1)
        t = rng.normal(size=3) * (1, 1, 0.4) + (0, 0, -1)
        q, t = q / np.linalg.norm(q), t / np.linalg.norm(t)
        m = placement.tilt(placement.centre_for(q, t))
        assert np.allclose(m @ q, t, atol=1e-9)
    assert np.allclose(placement.centre_for(POLE), POLE)                 # already there: no turn
    # the fovea seen 10° right of the photo's centre: the photo is centred 10° left of the fovea
    c = placement.centre_for(proj.sphere_point(math.radians(10.0), 0.0))
    assert np.allclose(c, proj.sphere_point(math.radians(10.0), math.pi))


def test_the_disc_is_nasal_and_a_little_superior():
    od, os_ = placement.anatomical_disc("OD"), placement.anatomical_disc("OS")
    assert od[0] > 0.3 and os_[0] < -0.3 and od[1] > 0 and os_[1] > 0     # +x: the photo's right (OD nasal)
    assert angle_between(od, POLE) == pytest.approx(placement.DISC_FOVEA_DEG)
    assert math.radians(placement.DISC_FOVEA_DEG) * placement.EYE_RADIUS_MM == pytest.approx(4.5, abs=0.05)
    assert np.allclose(od * (-1, 1, 1), os_)


# -- placing by landmarks --------------------------------------------------------------------------
def test_place_by_fovea_by_disc_or_not_at_all():
    cam = Camera(500.0, 480.0, 450.0, 135.0, "internal", "equidistant")
    fovea, disc = (560.0, 470.0), (700.0, 455.0)
    both = placement.place(cam, fovea=fovea, disc=disc, laterality="OD")
    assert both.by == "fovea" and np.allclose(both.fovea, POLE)
    assert both.distance_deg == pytest.approx(_apart(cam, fovea, disc))
    assert angle_between(both.disc, POLE) == pytest.approx(both.distance_deg)        # a turn keeps distances
    assert both.disc[0] > 0 and both.offset_deg == pytest.approx(angle_between(cam.direction(*fovea), POLE))
    assert both.distance_mm == pytest.approx(math.radians(both.distance_deg) * 12.0)
    only = placement.place(cam, disc=disc, laterality="OD")
    assert only.by == "disc" and only.fovea is None and only.distance_deg is None
    assert np.allclose(only.disc, placement.anatomical_disc("OD"))
    left = placement.place(cam, disc=(300.0, 455.0))                                 # the eye from the disc's side
    assert left.by == "disc" and np.allclose(left.disc, placement.anatomical_disc("OS"))
    unknown = placement.place(cam, disc=(510.0, 470.0))                              # a central disc: which eye?
    assert unknown.by == "centre" and np.allclose(unknown.matrix, np.eye(3))
    none = placement.place(cam)
    assert none.by == "centre" and np.allclose(none.matrix, np.eye(3)) and none.offset_deg == 0.0
    off = placement.place(cam, fovea=fovea, disc=disc, laterality="OD", align=False)
    assert off.by == "off" and np.allclose(off.matrix, np.eye(3)) and off.distance_deg == both.distance_deg
    outside = placement.place(cam, fovea=(5000.0, 5000.0), disc=disc, laterality="OD")   # a mark off the photo
    assert outside.by == "disc"
    rolled = Camera(500.0, 480.0, 450.0, 135.0, "internal", "equidistant", roll_deg=20.0)
    assert np.allclose(placement.place(rolled, fovea=fovea).fovea, POLE)


@pytest.mark.parametrize("eye,gaze,kw", [
    ("OD", (10.0, 4.0), {}),
    ("OS", (-8.0, -5.0), dict(fov=176.0, projection="radial", size=(717, 538))),
    ("OD", (21.0, 1.5), dict(fov=45.0, ftype="external", projection="perspective", size=(600, 600))),   # disc-centred
    ("OS", (-12.0, 6.0), dict(fov=45.0, ftype="external", projection="perspective", size=(600, 600))),
])
def test_true_landmarks_undo_the_cameras_turn(eye, gaze, kw):
    """With the fovea and the disc marked exactly, the photo lies on the eye as it was taken."""
    _, cam, fovea, disc, r, disc_eye = _turned(eye, gaze, **kw)
    pl = placement.place(cam, fovea=fovea, disc=disc, laterality=eye)
    assert pl.by == "fovea" and angle_between(pl.fovea, POLE) < 1e-6
    assert angle_between(pl.disc, disc_eye) < 0.9             # (the demo's turn has a trace of torsion)
    assert pl.offset_deg == pytest.approx(angle_between(r @ POLE, POLE), abs=0.3)
    assert angle_between(pl.centre, r @ POLE) < 0.3
    assert pl.distance_deg == pytest.approx(angle_between(disc_eye, POLE), abs=0.05)
    by_disc = placement.place(cam, disc=disc, laterality=eye)                   # the disc alone: nearly the same
    assert by_disc.by == "disc" and angle_between(by_disc.centre, pl.centre) < 3.0


# -- finding them ------------------------------------------------------------------------------------
@pytest.mark.parametrize("eye,gaze,kw", [
    ("OD", None, {}),
    ("OD", (10.0, 4.0), {}),
    ("OS", None, dict(seed=4)),
    ("OS", (-8.0, -5.0), dict(fov=176.0, projection="radial", size=(717, 538))),
    ("OD", None, dict(fov=45.0, ftype="external", projection="perspective", size=(600, 600))),
    ("OD", (21.0, 1.5), dict(fov=45.0, ftype="external", projection="perspective", size=(600, 600))),
    ("OD", (27.0, 1.0, 2.0), dict(fov=45.0, ftype="external", projection="perspective", size=(600, 600), seed=31)),
])
def test_fovea_and_disc_are_found_and_the_photo_placed(eye, gaze, kw):
    rgb, cam, fovea_true, disc_true, r, _ = _turned(eye, gaze, **kw)
    disc, fovea = _found(rgb, cam, eye)
    assert disc is not None and _apart(cam, disc, disc_true) < 2.5
    assert fovea is not None and _apart(cam, fovea, fovea_true) < 1.8
    pl = placement.place(cam, fovea=fovea, disc=disc, laterality=eye)
    assert pl.by == "fovea"
    assert angle_between(pl.matrix @ cam.direction(*fovea_true), POLE) < 1.8     # the true fovea: at the pole
    assert angle_between(pl.centre, r @ POLE) < 1.8                               # the field: where it was taken
    assert pl.distance_deg == pytest.approx(21.05, abs=2.5)
    guess = placement.expected_fovea(cam, disc, eye)                              # the disc alone already says where
    assert guess is not None and _apart(cam, guess, fovea_true) < 3.5


def test_no_fovea_without_a_disc_or_outside_the_photo():
    rgb, cam, _, _, _, _ = _turned("OD")
    assert imaging.detect_fovea(rgb, cam, None, "OD") is None
    # a 30° disc-centred photo: the macula is cut by the edge — the disc alone places it
    rgb, cam, _, disc_true, r, _ = _turned("OS", (-21.0, 1.5), fov=30.0, ftype="external", projection="perspective",
                                           size=(600, 600))
    disc, fovea = _found(rgb, cam, "OS")
    assert disc is not None and _apart(cam, disc, disc_true) < 1.5 and fovea is None
    pl = placement.place(cam, disc=disc, laterality="OS")
    assert pl.by == "disc" and angle_between(pl.centre, r @ POLE) < 2.5 and pl.offset_deg > 18.0
    # a flat grey picture: nothing dark enough where the macula should be
    flat = np.full_like(rgb, 120)
    assert imaging.detect_fovea(flat, cam, disc, "OS") is None


def test_the_dark_centre_of_a_fovea_centred_photo_is_not_a_disc():
    rgb, cam, _, disc_true, _, _ = _turned("OD")
    circle = (cam.cx, cam.cy, cam.r)
    disc = imaging.detect_disc(rgb, circle, disc_frac=3.8 / 67.5)
    assert disc is not None and _apart(cam, disc[:2], disc_true) < 2.0           # the real disc, 21° nasal
    crop = rgb.copy()                                                            # the disc painted over: only the
    yy, xx = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]]                            # macula with its reflex is left
    crop[np.hypot(xx - disc_true[0], yy - disc_true[1]) < 0.13 * cam.r] = crop[int(cam.cy), int(cam.cx + 0.5 * cam.r)]
    again = imaging.detect_disc(crop, circle, disc_frac=3.8 / 67.5)
    assert again is None or math.hypot(again[0] - cam.cx, again[1] - cam.cy) > 0.08 * cam.r


# -- the size ---------------------------------------------------------------------------------------
def test_field_of_view_from_the_fovea_disc_distance():
    _, cam, fovea, disc, _, disc_eye = _turned("OD", fov=45.0, ftype="external", projection="perspective",
                                               size=(600, 600))
    true_deg = angle_between(disc_eye, POLE)
    wrong = cam.with_fov(60.0)                                                   # the camera's angle not known
    assert placement.place(wrong, fovea=fovea, disc=disc).distance_deg > true_deg * 1.2
    fov = placement.fit_fov(wrong, fovea, disc, target_deg=true_deg)
    assert fov == pytest.approx(45.0, abs=0.3)
    assert placement.fit_fov(wrong, fovea, disc) == pytest.approx(45.0, rel=0.05)     # with the usual 4.5 mm
    assert placement.fit_fov(wrong, fovea, (5000.0, 5000.0)) is None


def test_many_pixels_at_once_agree_with_one_at_a_time():
    for projection, fov, ftype in (("equidistant", 135.0, "internal"), ("radial", 176.0, "internal"),
                                   ("perspective", 45.0, "external"), ("stereographic", 100.0, "internal")):
        cam = Camera(300.0, 280.0, 250.0, fov, ftype, projection, roll_deg=7.0)
        xs, ys = np.array([300.0, 420.0, 180.0, 300.0, 500.0]), np.array([280.0, 300.0, 150.0, 60.0, 280.0])
        dirs, inside = cam.directions(xs, ys)
        for x, y, d, ok in zip(xs, ys, dirs, inside):
            one = cam.direction(x, y)
            assert (one is not None) == bool(ok)
            if one is not None:
                assert angle_between(one, d) < 0.05
                assert np.allclose(cam.pixel(one), (x, y), atol=0.05)


# -- kept with the photo ------------------------------------------------------------------------------
def test_old_libraries_get_the_fovea_columns(tmp_path):
    from fundusview.db import SCHEMA, Database

    path = tmp_path / "old.db"
    old = "\n".join(line for line in SCHEMA.splitlines() if "fovea_" not in line)
    assert "fovea_x" not in old and "disc_y" in old
    con = sqlite3.connect(str(path))
    con.executescript(old)
    con.execute("INSERT INTO images (sha256, file_path, disc_x, disc_y, imported_at) VALUES ('abc', 'a.jpg', 10, 20, 'x')")
    con.commit()
    con.close()
    db = Database(path)
    try:
        row = db.image_by_sha("abc")
        assert row["fovea_x"] is None and row["disc_x"] == 10
        db.update_image(row["id"], fovea_x=5.5, fovea_y=6.5)
        assert (db.get_image(row["id"])["fovea_x"], db.get_image(row["id"])["fovea_y"]) == (5.5, 6.5)
    finally:
        db.close()
    Database(path).close()                                                       # opening again: nothing to add
