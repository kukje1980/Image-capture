"""The 3D eye renders every mode with real OpenGL (CI: Mesa llvmpipe under Xvfb).

Skipped where no OpenGL context can be created (QT_QPA_PLATFORM=offscreen has
none); FUNDUSVIEW_REQUIRE_GL=1 turns that skip into a failure. A shader that
does not compile always fails.
"""
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


def _render(eye, **state):
    v, app, errors = eye
    v.mode, v.cut, v.show_muscles = "outside", 1.0, False
    for k, val in state.items():
        setattr(v, k, val)
    v.update()
    _settle(app, 0.2)
    assert not errors, errors
    img = v.grabFramebuffer()
    return lambda fx, fy: img.pixelColor(int(fx * (img.width() - 1)), int(fy * (img.height() - 1))).getRgb()[:3]


def test_closed_eye_front(eye):
    px = _render(eye, yaw=0.0, pitch=0.0, dist=3.3)
    assert sum(px(0.5, 0.5)) < 60                      # pupil
    r, g, b = px(0.5 + 0.11, 0.5)                      # iris stroma, nasal of the pupil
    assert r > b + 15 and r > g
    assert min(px(0.5, 0.17)) > 150                    # sclera above the cornea, lit
    assert sum(px(0.02, 0.02)) < 150                   # dark studio background


def test_cut_open_eye_shows_the_retina(eye):
    px = _render(eye, cut=0.25, yaw=38.0, pitch=18.0, dist=3.3)
    samples = [px(0.5 + dx, 0.5 + dy) for dx in (-0.05, 0.0, 0.05) for dy in (-0.05, 0.0, 0.05)]
    r, g, b = (sum(c[i] for c in samples) / len(samples) for i in range(3))
    assert r > g > b and r > 80                        # fundus orange inside the eye cup


def test_inside_view_looks_at_the_posterior_pole(eye):
    px = _render(eye, mode="inside", in_yaw=0.0, in_pitch=0.0, in_fov=85.0)
    r, g, b = px(0.5, 0.5)
    assert r > g > b


@pytest.mark.parametrize("cut", [-0.3, 0.5, 0.7, 0.81, 0.86, 0.95])
def test_every_section_renders(eye, cut):
    px = _render(eye, cut=cut, yaw=30.0, pitch=20.0, dist=3.0)
    assert len({px(x / 10, 0.5) for x in range(1, 10)}) > 3


def test_left_eye_and_muscles(eye):
    v = eye[0]
    v.set_disc("OS", None, None)
    px = _render(eye, show_muscles=True, yaw=150.0, pitch=25.0, dist=3.6)
    assert len({px(x / 10, y / 10) for x in range(2, 9) for y in range(2, 9)}) > 10
    v.set_disc("OD", None, None)
