"""영상 편집 기능 테스트 (VK-2 Image Process 계열 + 일반 슬릿램프 편집 기능)."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.capture import image_process as ip
from app.capture.image_process import Adjust, apply_adjust
from app.models.patient import Patient
from app.services.capture_service import CaptureService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _img(h=60, w=80):
    rng = np.random.default_rng(0)
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(20, 120, w, dtype=np.uint8)[None, :]
    a[..., 1] = 110
    a[..., 2] = np.linspace(60, 200, h, dtype=np.uint8)[:, None]
    a[20:40, 30:50] = (40, 200, 230)                 # 밝은 사각형(경계)
    return np.clip(a.astype(int) + rng.integers(-3, 4, a.shape), 0, 255).astype(np.uint8)


# ---------------- 보정 엔진 ----------------
def test_channels_red_blue_and_saturation():
    f = _img()
    r = apply_adjust(f, Adjust(channel="red"))
    assert np.array_equal(r[..., 0], f[..., 2]) and np.array_equal(r[..., 1], f[..., 2])
    b = apply_adjust(f, Adjust(channel="blue"))
    assert np.array_equal(b[..., 2], f[..., 0])
    gray = apply_adjust(f, Adjust(saturation=0.0))
    assert np.abs(gray[..., 0].astype(int) - gray[..., 2].astype(int)).max() <= 1   # 채도 0 = 무채색


def test_rgb_gain_and_levels():
    f = _img()
    warm = apply_adjust(f, Adjust(r_gain=1.3, b_gain=0.7))
    assert warm[..., 2].mean() > f[..., 2].mean() and warm[..., 0].mean() < f[..., 0].mean()
    lv = apply_adjust(f, Adjust(black=60, white=180))
    assert lv.std() > f.std()                                                  # 레벨로 대비 확장


def test_sharpen_denoise_enhance():
    f = _img()
    lap = lambda x: np.abs(np.diff(x.astype(int), axis=1)).mean()  # noqa: E731
    assert lap(apply_adjust(f, Adjust(sharpen=3))) > lap(f)                   # 경계 강조
    noisy = f.copy()
    noisy[::7, ::7] = 255                                                      # 소금 노이즈
    med = apply_adjust(noisy, Adjust(denoise="median"))
    assert (med == 255).all(axis=-1).sum() < (noisy == 255).all(axis=-1).sum()
    assert not np.array_equal(apply_adjust(f, Adjust(enhance=2)), f)          # 국소 대비 향상
    assert apply_adjust(f, Adjust(enhance=2)).shape == f.shape


def test_auto_levels_histogram_geometry():
    f = (_img() // 2 + 40).astype(np.uint8)                                    # 좁은 범위 영상
    lo, hi = ip.auto_levels(f)
    assert 30 < lo < hi < 200
    h = ip.histogram(f)
    assert h["lum"].sum() == f.shape[0] * f.shape[1] and len(h["r"]) == 256
    assert ip.rotate90(f, 1).shape[:2] == (80, 60)
    assert np.array_equal(ip.rotate90(ip.rotate90(f, 1), -1), f)
    assert np.array_equal(ip.flip(f, True)[:, 0], f[:, -1])
    assert ip.crop(f, 10, 5, 50, 45).shape[:2] == (40, 40)


# ---------------- 캔버스 편집 ----------------
def _canvas(qapp):
    from app.ui.pro.image_canvas import ImageCanvas
    cv = ImageCanvas()
    cv.resize(400, 300)
    cv.set_image(_img())                     # 80×60
    return cv


def test_rotate_flip_crop_move_annotations(qapp):
    cv = _canvas(qapp)
    cv.add_text(10, 20, "A")
    cv.rotate(1)                             # 시계 90°: (x,y) → (h - y, x)
    assert cv.image().shape[:2] == (80, 60)
    t = cv.annotations()[0]
    assert (t["x"], t["y"]) == (40, 10)
    cv.flip(True)                            # 좌우: x → w - x  (w=60)
    assert cv.annotations()[0]["x"] == 20
    assert cv.crop_to(5, 5, 45, 65)
    assert cv.image().shape[:2] == (60, 40)
    assert (cv.annotations()[0]["x"], cv.annotations()[0]["y"]) == (15, 5)
    assert cv.geometry_changed() and cv.is_modified()
    assert not cv.crop_to(0, 0, 3, 3)        # 너무 작은 자르기는 무시


def test_undo_redo_original(qapp):
    cv = _canvas(qapp)
    cv.set_adjust(Adjust(brightness=30), record=True)
    cv.rotate(-1)
    cv.add_circle(QPointF(5, 5), QPointF(30, 20))
    assert cv.annotation_kinds() == ["circle"]
    assert cv.undo() and cv.annotation_kinds() == []
    assert cv.undo() and cv.image().shape[:2] == (60, 80)
    assert cv.adjust().brightness == 30
    assert cv.undo() and cv.adjust().is_identity()
    assert not cv.undo()
    assert cv.redo() and cv.redo() and cv.image().shape[:2] == (80, 60)
    assert cv.restore_original()
    assert not cv.is_modified() and cv.image() is cv.original()
    assert cv.undo() and cv.image().shape[:2] == (80, 60)   # 원본 복원도 취소 가능


def test_slider_drag_is_one_undo_step(qapp):
    cv = _canvas(qapp)
    for v in (5, 10, 15, 20):                # 연속 슬라이더 이동
        cv.set_adjust(Adjust(brightness=v), record=True)
    assert cv.undo() and cv.adjust().is_identity() and not cv.can_undo()


def test_measurements_px_mm_and_angle(qapp):
    cv = _canvas(qapp)
    cv.add_length(QPointF(0, 0), QPointF(30, 40))           # 50 px
    cv.add_angle(QPointF(10, 0), QPointF(0, 0), QPointF(0, 10))
    assert cv.measurements() == [("length", "50 px"), ("angle", "90.0°")]
    cv.set_px_per_mm(25.0)
    assert cv.measurements()[0] == ("length", "2.00 mm")
    out = cv.render_to_bgr()
    assert out.shape == cv.image().shape and not np.array_equal(out, apply_adjust(cv.image(), cv.adjust()))


# ---------------- 작업공간 (보정·필터·편집 탭) ----------------
def _workspace(app_env, qapp, n=2):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="E1", name="편집"))
    patient = db.patients.get(pid)
    for k in range(n):
        svc.save_photo((_img() // 2 + 40 + k).astype(np.uint8), patient, eye="OD")
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OD")
    ws.resize(1300, 860)
    ws.set_patient(patient)
    ws.open_index(n - 1)
    return ws, db, config


def test_workspace_filters_and_auto_contrast(qapp, app_env):
    ws, _, _ = _workspace(app_env, qapp)
    ws.c_sharpen.setCurrentIndex(2)
    ws.c_denoise.setCurrentIndex(1)
    ws.c_enhance.setCurrentIndex(1)
    a = ws.single_canvas.adjust()
    assert (a.sharpen, a.denoise, a.enhance) == (2, "median", 1)
    ws.auto_contrast()
    assert ws.s_black.value() > 0 and ws.s_white.value() < 255
    assert ws.single_canvas.adjust().black == ws.s_black.value()
    assert ws.hist.pixmap() is not None and not ws.hist.pixmap().isNull()


def test_workspace_undo_syncs_controls(qapp, app_env):
    ws, _, _ = _workspace(app_env, qapp)
    ws.s_bright.setValue(40)
    assert ws.single_canvas.adjust().brightness == 40
    assert ws.b_undo.isEnabled()
    ws.undo()
    assert ws.s_bright.value() == 0 and ws.adjust().brightness == 0       # 슬라이더도 되돌아감
    ws.rotate(1)
    assert ws.single_canvas.geometry_changed() and ws.b_orig.isEnabled()
    ws.restore_original()
    assert not ws.single_canvas.is_modified()


def test_workspace_calibration_and_save_notes(qapp, app_env):
    ws, db, config = _workspace(app_env, qapp)
    ws.set_px_per_mm(20.0)
    assert config.px_per_mm == 20.0 and "20.0 px" in ws.lbl_calib.text()
    ws.single_canvas.add_length(QPointF(0, 0), QPointF(40, 0))
    assert ws.single_canvas.measurements()[0][1] == "2.00 mm"
    saved = ws.save_edited()
    assert saved[0].note == "측정"
    ws.rotate(-1)
    saved = ws.save_edited()
    assert saved[0].note == "편집본"
    assert db.captures.get(saved[0].id).file_path
    ws.set_px_per_mm(0)
    assert config.px_per_mm == 0.0


def test_workspace_tools_by_mode(qapp, app_env):
    ws, _, _ = _workspace(app_env, qapp)
    ws.set_tool("crop")
    assert ws.single_canvas.tool() == "crop"
    ws.select_for_compare(0, 1)
    ws.set_mode("compare")
    assert not ws.tool_buttons["crop"].isEnabled()          # 자르기는 1화면 전용
    assert ws.cmp_left.tool() == "pan"
    ws.set_tool("length")
    assert ws.cmp_right.tool() == "length"
