"""The 3D eye renders every mode with real OpenGL (CI: Mesa llvmpipe under Xvfb).

Skipped where no OpenGL context can be created (QT_QPA_PLATFORM=offscreen has
none); FUNDUSVIEW_REQUIRE_GL=1 turns that skip into a failure. A shader that
does not compile always fails.
"""
import math
import os
import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("OpenGL")


def _settle(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


@pytest.fixture(scope="module")
def eye():
    from PySide6.QtWidgets import QApplication

    from fundusview import demo, imaging
    from fundusview.ui.eye3d import EyeView

    app = QApplication.instance() or QApplication([])
    v = EyeView()
    errors: list[str] = []
    v.glError.connect(errors.append)
    v.resize(400, 300)
    v.show()
    _settle(app)
    if errors:
        pytest.fail(errors[0])
    if not (v.isValid() and v._ok):
        if os.getenv("FUNDUSVIEW_REQUIRE_GL") == "1":
            pytest.fail("no OpenGL context")
        pytest.skip("no OpenGL context on this platform")
    rgb = demo.synth_fundus(eye="OD", size=(512, 540))
    circle = imaging.detect_circle(rgb)
    v.set_image(rgb, imaging.fundus_alpha(rgb, circle), circle)
    v.set_mapping(fov_deg=135, fov_type="internal", projection="equidistant")
    v.set_disc("OD", None, circle)
    yield v, app, errors
    v.close()


PLAIN = dict(half=0.0, xray=0.0, scan=None, scan_dim=1.0, scan_beam=1.0, fov_sweep=0.0, fov_alpha=0.0,
             fov_ring=0.0, black=False, show_nerve=True, relief=0.0, unwrap=0.0, dark=0.0, glass=0.0)


def _render(eye, detail="detailed", **state):
    v, app, errors = eye
    v.set_detail(detail)
    v.reset_view()
    v.mode, v.cut, v.show_muscles = "outside", 1.0, False
    for k, val in {**PLAIN, **state}.items():
        if k == "pose":
            v.set_pose(**val)
        else:
            setattr(v, k, val)
    v.update()
    _settle(app, 0.2)
    assert not errors, errors
    img = v.grabFramebuffer()
    v._last_img = img
    return lambda fx, fy: img.pixelColor(int(fx * (img.width() - 1)), int(fy * (img.height() - 1))).getRgb()[:3]


def _at(v, p, r: int = 0):
    """Mean colour of the last frame around the screen position of object point ``p``."""
    import numpy as np

    img = v._last_img
    w, h = img.width(), img.height()
    q = v._camera(w / h)[0] @ np.array([p[0], p[1], p[2], 1.0], np.float32)
    x, y = (q[0] / q[3] + 1) / 2 * (w - 1), (1 - q[1] / q[3]) / 2 * (h - 1)
    cs = [img.pixelColor(int(round(x)) + dx, int(round(y)) + dy).getRgb()[:3]
          for dx in range(-r, r + 1) for dy in range(-r, r + 1)]
    return tuple(sum(c[i] for c in cs) / len(cs) for i in range(3))


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_closed_eye_front(eye, detail):
    px = _render(eye, detail, yaw=0.0, pitch=0.0, dist=3.3)
    assert sum(px(0.5, 0.5)) < (60 if detail == "detailed" else 110)   # pupil (simple: under a glassy cornea)
    r, g, b = px(0.5 + 0.11, 0.5)                      # iris stroma, nasal of the pupil
    assert r > b + 15 and r > g
    assert min(px(0.5, 0.17)) > 150                    # sclera above the cornea, lit
    assert sum(px(0.02, 0.02)) < 150                   # dark studio background


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_cut_open_eye_shows_the_retina(eye, detail):
    px = _render(eye, detail, cut=0.25, yaw=38.0, pitch=18.0, dist=3.3)
    samples = [px(0.5 + dx, 0.5 + dy) for dx in (-0.05, 0.0, 0.05) for dy in (-0.05, 0.0, 0.05)]
    r, g, b = (sum(c[i] for c in samples) / len(samples) for i in range(3))
    assert r > g > b and r > 80                        # fundus orange inside the eye cup


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_inside_view_looks_at_the_posterior_pole(eye, detail):
    px = _render(eye, detail, mode="inside", in_yaw=0.0, in_pitch=0.0, in_fov=85.0)
    r, g, b = px(0.5, 0.5)
    assert r > g > b


@pytest.mark.parametrize("detail", ["simple", "detailed"])
@pytest.mark.parametrize("cut", [-0.3, 0.5, 0.7, 0.81, 0.86, 0.95])
def test_every_section_renders(eye, cut, detail):
    px = _render(eye, detail, cut=cut, yaw=30.0, pitch=20.0, dist=3.0)
    assert len({px(x / 10, 0.5) for x in range(1, 10)}) > 3


def test_left_eye_and_muscles(eye):
    v = eye[0]
    v.set_disc("OS", None, None)
    px = _render(eye, show_muscles=True, yaw=150.0, pitch=25.0, dist=3.6)
    assert len({px(x / 10, y / 10) for x in range(2, 9) for y in range(2, 9)}) > 10
    v.set_disc("OD", None, None)


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_zoomed_onto_the_retina(eye, detail):
    from PySide6.QtCore import QPointF
    v, app, _ = eye
    v.set_detail(detail)
    v.reset_view()
    v.mode, v.cut = "outside", 0.25
    pos = QPointF(v.width() * 0.6, v.height() * 0.45)
    for _ in range(14):
        v.zoom_at(1.0, pos)
    assert v.magnification > 5
    v.update()
    _settle(app, 0.2)
    img = v.grabFramebuffer()
    r, g, b = img.pixelColor(int(0.6 * (img.width() - 1)), int(0.45 * (img.height() - 1))).getRgb()[:3]
    assert r > g > b and r > 60                        # close up, the fundus fills the view


# -- 세로 단면 · 망막 투시 · 슬릿 스캔 -------------------------------------------------------
@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_section_view(eye, detail):
    """The eye cut in half and seen from the side: wall section, far retina, black background."""
    import numpy as np

    from fundusview.ui import eye_model as em
    v = eye[0]
    _render(eye, detail, half=1.0, black=True, pose=v.section_pose())
    k = v.half_plane()[0]
    m = v.meridian()
    sclera = _at(v, m * (1.0 - em.SCLERA_T / 2), 1)            # in the section plane, top of the wall
    assert min(sclera) > 150                                          # white sclera, as in a real eye
    choroid = _at(v, m * (1.0 - em.SCLERA_T - em.CHOROID_T / 2))      # under it: the dark red choroid
    assert choroid[0] > choroid[2] + 20 and sum(choroid) < sum(sclera) * 0.6
    retina = _at(v, em.R_RET * np.array([k[0] * 0.75, 0.3, -0.59]), 2)    # the far wall, in the photo
    assert retina[0] > retina[1] > retina[2] and retina[0] > 60
    lens = _at(v, (0.0, 0.0, em.LENS_EQ_Z), 1)                          # lens in section: translucent,
    assert 25 < sum(lens) / 3 < 200 and lens[0] >= lens[2]               # the yellowish nucleus
    assert sum(v._last_img.pixelColor(2, 2).getRgb()[:3]) < 10         # plain black background


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_slit_scan_and_field_of_view(eye, detail):
    import numpy as np

    from fundusview.ui import eye_model as em
    v = eye[0]
    _render(eye, detail, half=1.0, black=True, scan=0.5, fov_sweep=1.0, fov_alpha=1.0, pose=v.section_pose())
    k = v.half_plane()[0]
    m = v.meridian()
    up = _at(v, em.R_RET * np.array([k[0] * 0.75, 0.45, -0.48]), 2)     # superior: already scanned
    down = _at(v, em.R_RET * np.array([k[0] * 0.75, -0.45, -0.48]), 2)  # inferior: not yet
    assert sum(down) < 0.6 * sum(up)
    ray = _at(v, 0.5 * em.R_RET * (math.sin(v.theta_max) * m - math.cos(v.theta_max) * np.array([0, 0, 1.0])))
    assert ray[2] > ray[0] + 60                                         # cyan field-of-view ray
    _render(eye, detail, half=1.0, black=True, scan=0.2, fov_alpha=0.0, pose=v.section_pose())
    th, side = v.scan_theta(0.2)
    hit = em.R_RET * (math.sin(th) * side * m - math.cos(th) * np.array([0, 0, 1.0]))
    beam = _at(v, 0.5 * (hit + np.array([0.0, 0.0, em.IRIS_Z])))       # half way along the beam
    assert beam[0] > beam[2] + 80                                       # orange slit light
    # the overlay leaves the GL state clean for the next plain frame
    px = _render(eye, detail, yaw=0.0, pitch=0.0, dist=3.3)
    r, g, b = px(0.5 + 0.11, 0.5)
    assert r > b + 15 and r > g
    assert min(px(0.5, 0.17)) > 150


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_xray_shows_the_retina_on_the_globe(eye, detail):
    # from behind, below-right of the key light's highlight and away from the nerve
    back = dict(yaw=180.0, pitch=0.0, dist=3.3)
    assert min(_render(eye, detail, pose=back, show_nerve=False)(0.6, 0.62)) > 150   # the sclera
    r, g, b = _render(eye, detail, xray=1.0, pose=back, show_nerve=False)(0.6, 0.62)  # 망막 투시: the fundus
    assert r > g > b and b < 120


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_glass_sclera_keeps_the_photographed_retina_solid(eye, detail):
    """공막 투명도: the shell turns to glass; where there is a photo the retina stays solid and in
    full colour, beside it the inside of the eye shows through (frosted at 60 %, clear at 100 %)."""
    import numpy as np

    back, side = dict(yaw=180.0, pitch=0.0, dist=3.3), dict(yaw=90.0, pitch=0.0, dist=3.3)
    assert min(_render(eye, detail, pose=back, show_nerve=False)(0.6, 0.62)) > 150      # 0 %: the white sclera
    some = _render(eye, detail, pose=back, show_nerve=False, glass=0.6)(0.6, 0.62)
    full = _render(eye, detail, pose=back, show_nerve=False, glass=1.0)(0.6, 0.62)
    r, g, b = some
    assert r > g + 50 and g > b and b < 100                          # the fundus, seen from behind …
    assert max(abs(a - c) for a, c in zip(some, full)) <= 6          # … as solid at 60 % as at 100 %
    white = _render(eye, detail, pose=side, show_nerve=False)(0.36, 0.5)                # in front of the photo
    frost = _render(eye, detail, pose=side, show_nerve=False, glass=0.6)(0.36, 0.5)
    clear = _render(eye, detail, pose=side, show_nerve=False, glass=1.0)(0.36, 0.5)
    assert sum(white) > sum(frost) + 60 and sum(frost) > sum(clear) + 60
    look = dict(mode="inside", in_yaw=0.0, in_pitch=0.0, in_fov=60.0)                   # from inside: no glass
    _render(eye, detail, **look)
    plain = _frame(eye)
    _render(eye, detail, glass=0.6, **look)
    assert np.abs(_frame(eye) - plain).max() <= 2


def test_section_and_xray_together(eye):
    """The end of the 슬릿 스캔 presentation: opened off the axis, coats see-through."""
    v = eye[0]
    for detail in ("simple", "detailed"):
        px = _render(eye, detail, half=0.62, xray=1.0, black=True, pose=v.showcase_pose())
        assert len({px(x / 10, y / 10) for x in range(2, 9) for y in range(2, 9)}) > 20


def _frame(eye):
    """The last rendered frame as an integer RGB array."""
    from fundusview.ui.image_view import from_qimage

    return from_qimage(eye[0]._last_img).astype(int)


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_relief_lighting_brings_out_the_vessels(eye, detail):
    """입체 조명: vessel edges get a lit and a shaded side; the retina between them stays as it was."""
    import numpy as np

    look = dict(mode="inside", in_yaw=0.0, in_pitch=0.0, in_fov=60.0)
    _render(eye, detail, **look)
    plain = _frame(eye)
    _render(eye, detail, relief=0.8, **look)
    lit = _frame(eye)
    changed = np.abs(lit - plain).max(axis=2) > 12
    assert 0.004 < changed.mean() < 0.5
    assert (lit - plain)[changed].max() > 12 and (lit - plain)[changed].min() < -12   # highlights and shadows
    assert abs(lit.mean() - plain.mean()) < 4                                         # not brighter overall


@pytest.mark.parametrize("detail", ["simple", "detailed"])
def test_unwrap_lays_the_photo_flat_at_the_opening(eye, detail):
    """사진 펼치기: at 1 the photo is a flat sheet at the eye's opening, pixel for pixel the photo."""
    import numpy as np

    from fundusview.ui import eye_model as em
    from fundusview.ui.eye3d import SHEET_R

    v = eye[0]
    front = dict(cut=0.25, yaw=0.0, pitch=0.0, dist=3.0)
    _render(eye, detail, **front)
    on_retina = _frame(eye)
    _render(eye, detail, unwrap=0.5, **front)
    half_way = _frame(eye)
    _render(eye, detail, unwrap=1.0, **front)
    flat = _frame(eye)
    assert np.abs(flat - on_retina).mean() > 2 and np.abs(half_way - flat).mean() > 0.5
    assert np.abs(half_way - on_retina).mean() > 0.5
    # where the photo's points must be: on the disc of radius r_flat just above the cut plane
    r_in = (1.0 if detail == "simple" else em.R_RET) - 0.004
    r_flat = min(SHEET_R, 0.97 * math.sqrt(r_in * r_in - 0.25 * 0.25))
    h, w = v._rgba.shape[:2]
    for rho, deg in ((0.2, 100.0), (0.5, 45.0), (0.7, 160.0), (0.6, 270.0), (0.85, 20.0)):
        a = math.radians(deg)
        seen = _at(v, (rho * r_flat * math.cos(a), rho * r_flat * math.sin(a), 0.25 + 0.012), r=1)
        x = int((v._center[0] + math.cos(a) * v._radius[0] * rho) * w)
        y = int((v._center[1] - math.sin(a) * v._radius[1] * rho) * h)
        want = v._rgba[y - 3:y + 4, x - 3:x + 4, :3].reshape(-1, 3).mean(axis=0)   # a screen pixel ≈ 2 photo pixels
        assert np.abs(np.array(seen) - want).max() < 25, (rho, deg, seen, want)
    assert v._unwrap_on()
    v.mode = "inside"                           # 내부 · 세로 단면 · 닫힌 안구: the photo is on the retina
    assert not v._unwrap_on()
    v.mode, v.cut = "outside", 1.0
    assert not v._unwrap_on()


def test_dark_fades_the_picture_to_black(eye):
    """들어가기: the dive through the pupil goes through black."""
    px = _render(eye, "detailed", cut=0.25, yaw=38.0, pitch=18.0, dist=3.3)
    bright = px(0.5, 0.5)
    px = _render(eye, "detailed", cut=0.25, yaw=38.0, pitch=18.0, dist=3.3, dark=0.5)
    dim = px(0.5, 0.5)
    assert all(abs(d - b / 2) < 12 for d, b in zip(dim, bright))
    px = _render(eye, "detailed", cut=0.25, dark=1.0)
    assert all(sum(px(x / 4, y / 4)) == 0 for x in range(5) for y in range(5))


def test_moving_on_a_slow_computer_draws_small_then_sharp(eye):
    """A frame that takes too long is drawn at half size while the eye moves — and sharp again
    as soon as it rests (a saved picture is always sharp)."""
    import numpy as np
    from PySide6.QtCore import QPointF

    v, app, errors = eye
    _render(eye, "detailed", cut=0.25, yaw=38.0, pitch=18.0, dist=3.3)
    sharp = _frame(eye)
    try:
        v._render_ms = 90.0                     # as on a PC without a graphics card …
        v._drag = QPointF(1.0, 1.0)             # … while the eye is dragged
        v.update()
        _settle(app, 0.1)
        assert not errors and v._scale == 0.5 and v._fbo is not None
        assert (v._fbo.width(), v._fbo.height()) == (max(16, int(v.width() * v.devicePixelRatioF() * 0.5)),
                                                     max(16, int(v.height() * v.devicePixelRatioF() * 0.5)))
        v._drag = None
        _settle(app, 0.5)                       # let go: one more frame at full size
        assert v._scale == 1.0
        v._drag = QPointF(1.0, 1.0)
        v._last_img = v.grabFramebuffer()       # 화면 저장 while moving: sharp
        assert v._scale == 1.0
        assert np.abs(_frame(eye) - sharp).mean() < 1.0
    finally:
        v._drag, v._render_ms = None, 0.0


def test_overview_shows_the_eye_in_its_pane(tmp_path, demo_dir, import_and_wait):
    """모두 보기 with OpenGL: the 3D eye sits in its small pane and moves to the 3D tab,
    to 크게 보기 and back without losing its place."""
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow, gl_available

    app = QApplication.instance() or QApplication([])
    if not gl_available():
        if os.getenv("FUNDUSVIEW_REQUIRE_GL") == "1":
            pytest.fail("no OpenGL context")
        pytest.skip("no OpenGL context on this platform")
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)

    def inside(widget, ancestor):
        while widget is not None and widget is not ancestor:
            widget = widget.parentWidget()
        return widget is ancestor

    try:
        w.resize(1400, 900)
        w.show()
        import_and_wait(app, w, [demo_dir])
        w._select_patient_ref(db.find_patient("20260115001")["id"])
        _settle(app, 0.5)
        assert w._tab() == "all" and w._ov_gl and inside(w.eye3d, w.ov_3d)
        assert w.eye3d._ok and not w._3d_dirty               # the photo is on the eye
        w._go("3d")
        _settle(app)
        assert inside(w.eye3d, w.page3d)
        w._go("all")
        _settle(app)
        assert inside(w.eye3d, w.ov_3d)
        w._toggle_full_3d()                                   # 크게 보기 from 모두 보기 ...
        _settle(app)
        assert inside(w.eye3d, w._full3d)
        w._exit_full_3d()                                     # ... comes back to the small pane
        _settle(app)
        assert inside(w.eye3d, w.ov_3d) and w.eye3d._ok
    finally:
        w.close()
        db.close()
