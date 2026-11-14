"""몽타주: photos of one eye placed on the eyeball (자동 · 기준점 · 수동) and blended into one picture."""
import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from fundusview import demo, imaging, montage as mt  # noqa: E402
from fundusview import projection as proj  # noqa: E402

SIDE = 640


def rot_err(a, b) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(a.T @ b) - 1) / 2))))


@pytest.fixture(scope="module")
def series():
    """The demo's 5-field 45° series (4:3 frames like the camera) and the true gaze of each photo."""
    h = SIDE * 3 // 4
    top = (SIDE - h) // 2
    photos = [np.ascontiguousarray(p[top:top + h]) for p in demo.montage_fields("OD", size=SIDE)]
    return photos, [demo.gaze_rotation(*g) for g in demo.MONTAGE_GAZES]


def shots_of(photos, fovs=None):
    out = []
    for k, rgb in enumerate(photos):
        circle = imaging.detect_circle(rgb)
        out.append(mt.Shot.from_photo(rgb, imaging.fundus_alpha(rgb, circle), circle,
                                      fov_deg=45.0 if fovs is None else fovs[k], fov_type="external",
                                      projection="perspective", image_id=k + 1))
    return out


@pytest.mark.parametrize("projection", ["perspective", "equidistant", "stereographic", "radial", "orthographic"])
def test_pixels_and_directions_round_trip(projection):
    s = mt.Shot(np.zeros((500, 600, 3), np.uint8), np.full((500, 600), 255, np.uint8), (300.0, 250.0, 240.0),
                fov_deg=100.0 if projection != "perspective" else 45.0, fov_type="internal", projection=projection)
    rng = np.random.default_rng(1)
    uv = np.stack([300 + rng.uniform(-160, 160, 50), 250 + rng.uniform(-160, 160, 50)], axis=1)
    d = s.dirs(uv)
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0)
    u, v, rho = s.pixels(d)
    assert np.allclose(u, uv[:, 0], atol=1e-6) and np.allclose(v, uv[:, 1], atol=1e-6)
    # the edge of the image circle is the edge of the field, the centre the optical axis
    edge = s.dirs(np.array([[540.0, 250.0], [300.0, 250.0]]))
    assert math.degrees(math.acos(-edge[0, 2])) == pytest.approx(math.degrees(s.tmax), abs=1e-6)
    assert np.allclose(edge[1], [0, 0, -1])
    assert np.isinf(s.pixels(np.array([0.0, 0.0, 1.0]))[2])          # behind the camera: not in the photo


def test_rotations():
    a, b = mt._unit([0.3, -0.2, -1.0]), mt._unit([-0.5, 0.4, -0.8])
    assert np.allclose(mt.rotation_between(a, b) @ a, b)
    r = demo.gaze_rotation(20.0, -10.0, 5.0)
    src = mt._unit(np.random.default_rng(0).normal(size=(30, 3)))
    # matrices compared directly: rot_err (an arccos) cannot resolve less than ~1e-6°
    assert np.allclose(mt.kabsch(src, src @ r.T), r, atol=1e-12)
    # 수동 회전: counter-clockwise on the map
    s = mt.Shot(np.zeros((10, 10, 3), np.uint8), None, (5.0, 5.0, 5.0), fov_deg=60.0, fov_type="internal")
    right = s.dirs(np.array([[9.0, 5.0]]))
    mt.roll_about(s, 90.0)
    x, y = mt.plane_xy(right @ s.R.T)
    assert abs(float(x[0])) < 1e-9 and float(y[0]) > 0                # the right edge went up
    mt.move_on_plane(s, math.radians(10.0), 0.0)
    x, y = mt.plane_xy(s.centre())
    assert math.degrees(float(x)) == pytest.approx(10.0) and abs(float(y)) < 1e-9


def test_auto_align_recovers_the_gazes(series):
    photos, truth = series
    shots = shots_of(photos)
    rep = mt.auto_align(shots, 0)
    assert rep.placed == [0, 1, 2, 3, 4] and not rep.unplaced and rep.residual_deg < 0.3
    assert max(rot_err(s.R, r) for s, r in zip(shots, truth)) < 0.3
    assert "5/5장" in rep.text()


def test_auto_align_corrects_a_wrong_field_of_view(series):
    photos, truth = series
    shots = shots_of(photos[:3], fovs=[45.0, 45.0, 50.0])            # the third says 50°, it is 45°
    mt.auto_align(shots, 0)
    assert max(rot_err(s.R, r) for s, r in zip(shots, truth)) < 0.4
    want = proj.theta_max(45.0, "external") / proj.theta_max(50.0, "external")
    assert shots[2].fov_scale == pytest.approx(want, abs=0.01)
    assert shots[0].fov_scale == 1.0 and shots[1].fov_scale == 1.0


def test_unmatched_photos_stay_where_they_are(series):
    photos, _ = series
    blank = np.zeros_like(photos[0])
    shots = shots_of([photos[0], photos[1], blank])
    mt.spread(shots, 0)
    keep = shots[2].R.copy()
    rep = mt.auto_align(shots, 0)
    assert rep.unplaced == [2] and np.allclose(shots[2].R, keep)
    assert "손으로 옮기거나 기준점" in rep.text()


def test_control_points(series):
    """기준점: the same spots clicked on two photos put the second one in place."""
    photos, truth = series
    anchor, moving = shots_of(photos[:2])
    mt.spread([anchor, moving], 0)
    # spots both photos see: true directions near the middle of the overlap
    spots = [mt.plane_dirs(math.radians(x), math.radians(y)) for x, y in ((14, 8), (16, -9), (20, 1), (12, -2))]
    au = np.array([[float(c) for c in anchor.pixels(d @ truth[0])[:2]] for d in spots])
    mu = np.array([[float(c) for c in moving.pixels(d @ truth[1])[:2]] for d in spots])
    err = mt.align_points(moving, mu[:2], anchor, au[:2])
    assert err < 0.05 and rot_err(moving.R, truth[1]) < 0.1
    with pytest.raises(ValueError):
        mt.align_points(moving, mu[:1], anchor, au[:1])
    moving.fov_deg = 52.0                                           # four pairs also fix the field of view
    mt.spread([anchor, moving], 0)
    assert mt.align_points(moving, mu, anchor, au) < 0.1
    assert moving.tmax == pytest.approx(proj.theta_max(45.0, "external"), rel=0.01)


def test_render_is_seamless_and_brightness_matched(series):
    photos, truth = series
    shots = shots_of(photos)
    for s, r in zip(shots, truth):
        s.R = r.copy()
    mt.match_gains(shots)
    g = [float(s.gain.mean()) for s in shots]
    flash = (1.0, 0.85, 1.12, 0.93, 1.06)
    corrected = [gk * fk for gk, fk in zip(g, flash)]
    assert max(corrected) / min(corrected) < 1.04                   # each photo brought to the same level
    geom = mt.map_for(shots, max_size=900)
    rgb, alpha, geom = mt.render(shots, geom)
    assert rgb.shape == (geom.size, geom.size, 3) and alpha.shape == rgb.shape[:2]
    assert math.degrees(geom.angle) > 50                           # the series covers far more than one photo
    # every photo's centre is covered, the corners are not
    for s in shots:
        x, y = geom.xy(s.centre())
        assert alpha[int(y), int(x)] == 255
    assert alpha[0, 0] == 0 and not rgb[0, 0].any()
    # no seam: the brightness changes smoothly across the edge of the centre photo
    lum = cv2.GaussianBlur(rgb.astype(np.float32).mean(axis=2), (0, 0), 6)
    edge = shots[0].outline(72)                                     # its circle and the 4:3 frame
    xs, ys = geom.xy(edge)
    inside = np.array([alpha[int(y), int(x)] == 255 for x, y in zip(xs, ys)])
    c = np.array([geom.radius, geom.radius])
    steps = []
    for x, y in zip(xs[inside], ys[inside]):
        p = np.array([x, y])
        n = (p - c) / np.linalg.norm(p - c)
        a, b = p - 6 * n, p + 6 * n
        steps.append(abs(lum[int(a[1]), int(a[0])] - lum[int(b[1]), int(b[0])]))
    assert np.median(steps) < 3.0


def test_overlay_redraws_only_what_moved(series):
    photos, truth = series
    shots = shots_of(photos[:3])
    for s, r in zip(shots, truth):
        s.R = r.copy()
    ov = mt.Overlay()
    k = math.radians(0.1)
    ov.set_view(-math.radians(30), math.radians(20), k, 400, 300)
    img = ov.compose(shots, highlight=1, opacity=1.0)
    assert img.shape == (300, 400, 3) and img.any()
    calls = []
    real = mt._sample_dirs
    mt._sample_dirs = lambda s, d: calls.append(s) or real(s, d)
    try:
        ov.compose(shots, highlight=1, opacity=0.5)                    # nothing moved: nothing resampled
        assert calls == []
        mt.move_on_plane(shots[1], math.radians(1.0), 0.0)
        ov.compose(shots, highlight=1, opacity=0.5)
        assert calls == [shots[1]]
    finally:
        mt._sample_dirs = real
    tint = ov.compose(shots, highlight=1, tint=True)
    assert tint[..., 0].any() and tint[..., 1].any()                  # magenta (the others) and green (selected)
    assert np.array_equal(tint[..., 0], tint[..., 2])


def test_picking_recentring_and_saving(series):
    photos, truth = series
    shots = shots_of(photos)
    for s, r in zip(shots, truth):
        s.R = r.copy()
    up = shots[3].centre()
    assert mt.shot_at(shots, up) == 3
    assert mt.shot_at(shots, mt.plane_dirs(0.0, math.radians(8.0)), prefer=0) == 0
    assert mt.shot_at(shots, np.array([0.0, 0.0, 1.0])) is None
    assert mt.most_central(shots) == 0
    mt.recentre(shots, 1)
    assert np.allclose(shots[1].R, np.eye(3)) and np.allclose(shots[0].R, truth[1].T, atol=1e-12)
    d = mt.definition(shots, 1)
    fresh = shots_of(photos)
    for s, j in zip(fresh, d["shots"]):
        s.apply_json(j)
    assert all(np.allclose(a.R, b.R) for a, b in zip(fresh, shots)) and d["ref"] == 1
    # the disc of the centre photo lands on the same spot of the map
    mt.recentre(shots, 0)
    geom = mt.map_for(shots, max_size=600)
    disc_eye = mt.plane_dirs(math.radians(21.0), math.radians(1.5))   # the demo retina's disc
    u, v, _ = shots[0].pixels(disc_eye @ shots[0].R)
    x, y = mt.disc_on_map(shots[0], (float(u) * shots[0].scale, float(v) * shots[0].scale), geom)
    ex, ey = geom.xy(disc_eye)
    assert (x, y) == (pytest.approx(float(ex), abs=1e-6), pytest.approx(float(ey), abs=1e-6))


def _poor(rgb, k, *, blur, noise, contrast, vignette, rot=0.0):
    """The photo as a poor camera shot: pale vessels, uneven light, blur, noise, a tilted camera."""
    import cv2

    rng = np.random.default_rng(100 + k)
    f = rgb.astype(np.float32)
    h, w = f.shape[:2]
    if rot:
        f = cv2.warpAffine(f, cv2.getRotationMatrix2D((w / 2, h / 2), rot * (1 if k % 2 else -1), 1.0), (w, h))
    mean = cv2.GaussianBlur(f, (0, 0), 25)
    f = mean + (f - mean) * contrast
    f = cv2.GaussianBlur(f, (0, 0), blur)
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w * (0.5 + 0.15 * rng.standard_normal()), yy - h * (0.5 + 0.15 * rng.standard_normal()))
    f *= (1 - vignette * np.clip(r / (0.6 * max(h, w)), 0, 1) ** 2)[..., None]
    f += rng.normal(0, noise, f.shape)
    out = np.clip(f, 0, 255).astype(np.uint8)
    out[rgb.max(axis=2) < 8] = 0
    return out


def test_auto_align_copes_with_poor_photos(series):
    """Blurred, noisy, pale and unevenly lit photos are still placed — on the vessels alone, at a
    coarser size — and at the right gaze, not just somewhere."""
    photos, truth = series
    poor = [_poor(p, k, blur=2.0, noise=8.0, contrast=0.5, vignette=0.4) for k, p in enumerate(photos)]
    shots = shots_of(poor)
    rep = mt.auto_align(shots, 0)
    assert rep.placed == [0, 1, 2, 3, 4] and rep.residual_deg < 0.6
    assert max(rot_err(s.R, r) for s, r in zip(shots, truth)) < 1.0
    # worse still: what is placed is placed rightly; the rest is left for the hand
    worse = [_poor(p, k, blur=2.2, noise=12.0, contrast=0.35, vignette=0.6) for k, p in enumerate(photos)]
    shots = shots_of(worse)
    rep = mt.auto_align(shots, 0)
    assert len(rep.placed) >= 2 and rep.unplaced               # some are found, the others reported
    assert max(rot_err(shots[k].R, truth[k]) for k in rep.placed) < 1.5


def test_the_looser_second_try_does_not_join_different_eyes(series):
    photos, _ = series
    h = SIDE * 3 // 4
    top = (SIDE - h) // 2
    other = [np.ascontiguousarray(p[top:top + h]) for p in demo.montage_fields("OS", size=SIDE, seed=77)]
    shots = shots_of([photos[0], other[0], other[1]])
    mt.spread(shots, 0)
    rep = mt.auto_align(shots, 0)
    assert rep.placed == [0] and rep.unplaced == [1, 2]            # another retina: nothing in common


WIDE_GAZES = ((0.0, 0.0, 0.0), (22.0, 1.0, 2.0), (-21.0, -1.0, -1.0), (1.0, 20.0, 0.0))


def _wide_series(fov=110.0):
    """A wide-field series whose true lens is equidistant with a ``fov``° (eye-centre) field."""
    return [demo.synth_fundus(eye="OD", fov_deg=fov, fov_type="internal", projection="equidistant",
                              size=(SIDE, SIDE), seed=31, gaze=g) for g in WIDE_GAZES]


def _wide_shots(photos, fov, projection, c=0.2545):
    out = []
    for k, rgb in enumerate(photos):
        circle = imaging.detect_circle(rgb)
        out.append(mt.Shot.from_photo(rgb, imaging.fundus_alpha(rgb, circle), circle, fov_deg=fov, fov_type="internal",
                                      projection=projection, radial_c=c, image_id=k + 1))
    return out


def test_the_lens_is_found_from_the_series_when_the_given_one_is_wrong():
    """Told 176° with the camera's curve, the photos are really 110° equidistant: the overlap of the
    series says so, and the photos then fit — at the true gazes."""
    photos = _wide_series(110.0)
    truth = [demo.gaze_rotation(*g) for g in WIDE_GAZES]
    wrong = _wide_shots(photos, 176.0, "radial")
    rep = mt.auto_align(wrong, 0, calibrate=False, mask=False)
    bad = max(rot_err(s.R, r) for s, r in zip(wrong, truth))
    shots = _wide_shots(photos, 176.0, "radial")
    rep = mt.auto_align(shots, 0)
    assert rep.lens and "렌즈 보정" in rep.text() and rep.placed == [0, 1, 2, 3]
    tmax = [math.degrees(s.tmax) * 2 for s in shots]
    assert all(95 < t < 125 for t in tmax) and abs(shots[0].radial_c) < 0.12      # near 110°, near equidistant
    good = max(rot_err(s.R, r) for s, r in zip(shots, truth))
    assert good < 1.5 and good < 0.5 * bad and rep.residual_deg < 0.3


def test_a_right_lens_and_a_45_degree_camera_are_left_alone(series):
    photos = _wide_series(110.0)
    shots = _wide_shots(photos, 110.0, "equidistant")
    rep = mt.auto_align(shots, 0)
    assert rep.lens == "" and all(s.projection == "equidistant" and s.fov_deg == 110.0 for s in shots)
    cam, _ = series                                                 # perspective cameras are not searched at all
    shots = shots_of(cam)
    rep = mt.auto_align(shots, 0)
    assert rep.lens == "" and all(s.projection == "perspective" and s.fov_deg == 45.0 for s in shots)


def test_glare_and_a_flare_spot_stay_out_of_the_montage():
    import cv2

    photos = [p.copy() for p in _wide_series(110.0)]
    h, w = photos[0].shape[:2]
    fx, fy = int(w * 0.56), int(h * 0.72)                           # a lens flare: the same place in every picture
    for p in photos:
        spot = np.zeros((h, w), np.float32)
        cv2.circle(spot, (fx, fy), int(0.03 * w), 1.0, -1)
        spot = cv2.GaussianBlur(spot, (0, 0), 0.012 * w)[..., None]
        p[:] = np.clip(p * (1 - spot) + np.array([225, 240, 170]) * spot, 0, 255).astype(np.uint8)
    lid = photos[3]                                                 # the eyelid in the last one: a washed-out band
    yy, xx = np.mgrid[0:h, 0:w]
    band = (yy > 0.84 * h) & (np.hypot(xx - w / 2, yy - h / 2) < 0.49 * w)
    lid[band] = (250, 250, 180)
    shots = _wide_shots(photos, 110.0, "equidistant")
    rep = mt.auto_align(shots, 0)
    assert rep.placed == [0, 1, 2, 3] and rep.masked == 4 and "반사·플레어 가림 4장" in rep.text()
    k = shots[0].rgb.shape[1] / w
    for s in shots:
        assert s.alpha[int(fy * k), int(fx * k)] < 30 and s.cut is not None      # the flare is cut from every photo
        assert s.alpha[s.alpha.shape[0] // 2, s.alpha.shape[1] // 2] > 200       # the middle of the field stays
    assert shots[3].alpha[int(0.9 * h * k), int(0.5 * w * k)] < 30               # and so is the eyelid band
    # the optic disc is bright too, but it moves with the retina: it is kept
    for s in shots[:3]:
        bright = (s.rgb[..., 1] > 200) & (np.hypot(*np.indices(s.alpha.shape)[::-1] - np.array([fx * k, fy * k])[:, None, None]) > 0.1 * w * k)
        if bright.any():
            assert s.alpha[bright].mean() > 200
    out, _, _ = mt.render([shots[k] for k in rep.placed])
    assert not ((out[..., 0] > 240) & (out[..., 1] > 240)).any()                 # no washed-out light in the result
    # the cut comes along to the full-size photo of the saved montage
    full = mt.full_alpha(shots[0], imaging.fundus_alpha(photos[0], imaging.detect_circle(photos[0])))
    assert full.shape == photos[0].shape[:2] and full[fy, fx] < 30 and full[h // 2, w // 2] > 200


def test_clean_photos_are_not_cut():
    """Nothing is left out of clean photos — not the optic disc either, bright and near the rim in one."""
    shots = _wide_shots(_wide_series(110.0), 110.0, "equidistant")
    rep = mt.auto_align(shots, 0)
    assert rep.masked == 0 and all(s.cut is None for s in shots) and "가림" not in rep.text()


def test_quick_rotation_agrees_with_the_slow_one():
    rng = np.random.default_rng(3)
    src = rng.normal(size=(120, 3))
    src /= np.linalg.norm(src, axis=1, keepdims=True)
    true = demo.gaze_rotation(14.0, -9.0, 4.0)
    dst = src @ true.T
    dst[:30] = rng.normal(size=(30, 3))                             # a quarter of the matches are wrong
    dst /= np.linalg.norm(dst, axis=1, keepdims=True)
    r, inl = mt.quick_rotation(src, dst, 0.3)
    r2, inl2 = mt.ransac_rotation(src, dst, thresh_deg=0.3)
    assert rot_err(r, true) < 0.05 and rot_err(r, r2) < 0.05
    assert inl[30:].all() and inl.sum() == inl2.sum() and inl[:30].sum() <= 1
    r0, none = mt.quick_rotation(src[:2], dst[:2], 0.3)             # too few points: nothing
    assert np.allclose(r0, np.eye(3)) and not none.any()
