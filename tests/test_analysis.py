"""Pro 분석: 형광염색·충혈·마이봄샘·수정체·품질·정렬·TBUT·DICOM — 합성 영상으로 동작 확인."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.analysis import clinical, dicom_export, tbut
from app.models.capture import Capture
from app.models.patient import Patient
from app.services.capture_service import CaptureService

CORNEA = {"kind": "circle", "x1": 340, "y1": 60, "x2": 940, "y2": 660}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fluo(n_dots: int, seed: int = 0) -> np.ndarray:
    """코발트블루 조명 각막 + 녹황색 점상 염색."""
    rng = np.random.default_rng(seed)
    img = np.zeros((720, 1280, 3), np.uint8)
    img[:] = (90, 30, 10)
    cv2.circle(img, (640, 360), 300, (120, 60, 20), -1)
    centers = []
    while len(centers) < n_dots:
        x, y = int(rng.integers(420, 860)), int(rng.integers(140, 580))
        if all((x - a) ** 2 + (y - b) ** 2 > 400 for a, b in centers):
            centers.append((x, y))
    for x, y in centers:
        cv2.circle(img, (x, y), 5, (60, 230, 170), -1)
    return img


def _sclera(n_vessels: int, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((600, 800, 3), (200, 210, 225), np.uint8)
    for _ in range(n_vessels):
        p1 = (int(rng.integers(0, 800)), int(rng.integers(0, 600)))
        p2 = (int(rng.integers(0, 800)), int(rng.integers(0, 600)))
        cv2.line(img, p1, p2, (60, 60, 190), 2)
    return img


def _meibo(keep_until_x: int) -> np.ndarray:
    img = np.full((400, 800, 3), 70, np.uint8)
    for x in range(20, 800, 40):
        if x < keep_until_x:
            cv2.rectangle(img, (x, 60), (x + 14, 340), (170, 170, 170), -1)
    return img


EYELID = {"kind": "circle", "x1": 0, "y1": 40, "x2": 800, "y2": 360}


def test_region_mask_uses_last_circle():
    m = clinical.region_mask((100, 200, 3), {"kind": "circle", "x1": 50, "y1": 0, "x2": 150, "y2": 100})
    assert m[50, 100] and not m[5, 5] and not m[50, 10]
    assert clinical.region_mask((10, 10, 3), None).all()
    anns = [{"kind": "arrow"}, {"kind": "circle", "x1": 0, "y1": 0, "x2": 5, "y2": 5},
            {"kind": "circle", "x1": 1, "y1": 1, "x2": 9, "y2": 9}]
    assert clinical.last_circle(anns)["x2"] == 9


def test_fluorescein_counts_spots_and_area():
    r = clinical.analyze("fluorescein", _fluo(20), [CORNEA], px_per_mm=50.0)
    assert 17 <= r.values["spots"] <= 20 and r.values["grade"] == 3          # 16~30 → III
    assert 0.2 < r.values["area_pct"] < 2.0 and "mm²" in r.rows[0][1]
    assert r.overlay is not None and r.overlay.shape == (720, 1280, 4) and not r.warning
    clean = clinical.analyze("fluorescein", _fluo(0), [CORNEA])
    assert clean.values["spots"] == 0 and clean.values["grade"] == 0
    few = clinical.analyze("fluorescein", _fluo(4), [CORNEA])
    assert few.values["grade"] == 1


def test_fluorescein_warns_on_white_light_image():
    white = np.full((300, 400, 3), 150, np.uint8)
    r = clinical.analyze("fluorescein", white)
    assert r.values["spots"] == 0 and "코발트블루" in r.warning


def test_hyperemia_increases_with_vessels():
    none = clinical.analyze("hyperemia", _sclera(0))
    some = clinical.analyze("hyperemia", _sclera(15))
    many = clinical.analyze("hyperemia", _sclera(60))
    assert none.values["vessel_pct"] < 0.5 and none.values["grade"] == 0
    assert none.values["vessel_pct"] < some.values["vessel_pct"] < many.values["vessel_pct"]
    assert many.values["grade"] > some.values["grade"]
    assert many.values["redness"] > none.values["redness"]


def test_meibography_dropout_and_meiboscore():
    full = clinical.analyze("meibography", _meibo(800), [EYELID])
    half = clinical.analyze("meibography", _meibo(400), [EYELID])
    none = clinical.analyze("meibography", _meibo(0), [EYELID])
    assert full.values["meiboscore"] == 0 and full.values["dropout_pct"] < 10
    assert 40 < half.values["dropout_pct"] < 70 and half.values["meiboscore"] == 2
    assert none.values["dropout_pct"] > 95 and none.values["meiboscore"] == 3
    dark = clinical.analyze("meibography", 255 - _meibo(800), [EYELID], glands_dark=True)
    assert dark.values["meiboscore"] == 0


def test_lens_index_tracks_brightness_and_yellow():
    clear = np.full((200, 200, 3), (60, 60, 60), np.uint8)
    cloudy = np.full((200, 200, 3), (90, 170, 190), np.uint8)       # 밝고 노란 핵
    a, b = clinical.analyze("lens", clear), clinical.analyze("lens", cloudy)
    assert b.values["L"] > a.values["L"] and b.values["b"] > a.values["b"] + 10


def test_quality_flags_blur_and_glare():
    from tests.test_smart_capture import _scene
    sharp = clinical.analyze("quality", _scene())
    blurry = clinical.analyze("quality", cv2.GaussianBlur(_scene(), (0, 0), 12))
    assert sharp.values["sharpness"] > 3 * blurry.values["sharpness"]
    assert "양호" in sharp.summary and "흐림" in blurry.summary
    glare = _scene()
    cv2.circle(glare, (640, 360), 250, (255, 255, 255), -1)
    assert "반사광" in clinical.analyze("quality", glare).summary


def test_align_recovers_rotation_and_scale():
    from tests.test_smart_capture import _scene
    ref = cv2.GaussianBlur(_scene(), (0, 0), 1.0)
    M = cv2.getRotationMatrix2D((640, 360), 7, 1.1)
    M[0, 2] += 30
    mov = cv2.warpAffine(ref, M, (1280, 720))
    r = clinical.align(ref, mov)
    assert r.ok and abs(r.rotation) == pytest.approx(7, abs=0.5) and r.scale == pytest.approx(1 / 1.1, abs=0.02)
    centre = (slice(200, 520), slice(400, 880))
    assert np.abs(r.image[centre].astype(int) - ref[centre].astype(int)).mean() < 8
    flat = np.full((300, 300, 3), 90, np.uint8)
    assert not clinical.align(flat, flat).ok


# ---------------- TBUT ----------------
def _tear_film(fps=30.0, blink_at=1.0, breakup_after=4.0, total=8.0):
    """밝은 녹색 눈물막 → 1초에 깜빡임(0.2초) → 4초 뒤부터 검은 반점이 커짐."""
    frames = []
    yy, xx = np.mgrid[0:240, 0:320]
    for i in range(int(total * fps)):
        t = i / fps
        f = np.zeros((240, 320, 3), np.uint8)
        f[:] = (20, 180, 60)
        if blink_at <= t < blink_at + 0.2:
            f[:] = (10, 30, 15)                                     # 눈꺼풀이 덮음
        start = blink_at + 0.2 + breakup_after
        if t >= start:
            r = 4 + (t - start) * 30
            f[(yy - 120) ** 2 + (xx - 160) ** 2 < r * r] = (10, 40, 15)
        frames.append(f)
    return frames, fps


def test_tbut_from_frames():
    frames, fps = _tear_film()
    r = tbut.analyze_frames(frames, fps)
    assert r.ok and r.blink_end_s == pytest.approx(1.2, abs=0.05)
    assert r.tbut_s == pytest.approx(4.0, abs=0.3)
    assert len(r.dark_frac) == len(frames)


def test_tbut_without_breakup_reports_lower_bound():
    frames, fps = _tear_film(breakup_after=99)
    r = tbut.analyze_frames(frames, fps)
    assert not r.ok and "TBUT >" in r.message


def test_tbut_from_video_file(tmp_path):
    frames, fps = _tear_film()
    path = str(tmp_path / "tbut.avi")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
    for f in frames:
        vw.write(f)
    vw.release()
    r = tbut.analyze_video(path)
    assert r.ok and r.tbut_s == pytest.approx(4.0, abs=0.4)
    assert r.breakup_frame is not None and r.breakup_frame.shape == (240, 320, 3)
    assert not tbut.analyze_video(str(tmp_path / "none.mp4")).ok


# ---------------- DICOM ----------------
def test_dicom_ophthalmic_photography(tmp_path):
    pydicom = pytest.importorskip("pydicom")
    img = np.zeros((40, 60, 3), np.uint8)
    img[:, :, 2] = 200                                             # BGR 의 R
    p = Patient(id=3, chart_no="C-77", name="홍길동", birth_date="1970-05-06", sex="M", doctor="김원장")
    cap = Capture(id=9, patient_id=3, file_path="x.png", captured_at="2026-10-25 09:30:15", eye="OS",
                  note="각막 미란")
    path = dicom_export.export(img, p, tmp_path / dicom_export.default_name(p, cap), cap, "국제안과")
    ds = pydicom.dcmread(str(path))
    assert ds.SOPClassUID == dicom_export.OP_8BIT and ds.Modality == "OP"
    assert str(ds.PatientName) == "홍길동" and ds.PatientID == "C-77" and ds.PatientBirthDate == "19700506"
    assert ds.ImageLaterality == "L" and ds.StudyDate == "20261025" and ds.ImageComments == "각막 미란"
    arr = ds.pixel_array
    assert arr.shape == (40, 60, 3) and int(arr[0, 0, 0]) == 200          # RGB 순서
    # 같은 환자·같은 날 = 같은 Study
    cap2 = Capture(id=10, patient_id=3, file_path="y.png", captured_at="2026-10-25 11:00:00", eye="OD")
    ds2 = dicom_export.build_dataset(img, p, cap2)
    assert ds2.StudyInstanceUID == ds.StudyInstanceUID and ds2.SOPInstanceUID != ds.SOPInstanceUID


# ---------------- Pro 화면 연동 ----------------
def _workspace(app_env, images):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    config.save = lambda: None
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="A1", name="분석", sex="F"))
    patient = db.patients.get(pid)
    for img in images:
        svc.save_photo(img, patient, eye="OD")
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OD")
    ws.resize(1300, 850)
    ws.set_patient(patient)
    return ws, db, patient


def test_pro_analysis_tab_flow(qapp, app_env):
    ws, db, patient = _workspace(app_env, [_fluo(20)])
    panel = ws.analysis
    assert ws.tabs.tabText(3) == "분석"
    ws.open_index(0)
    assert panel.b_run.isEnabled() and not panel.b_note.isEnabled()
    ws.single_canvas.add_circle(*(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(x, y)
                                  for x, y in ((340, 60), (940, 660))))
    panel.set_kind("fluorescein")
    res = panel.run()
    assert res is not None and res.values["spots"] >= 17
    assert ws.single_canvas.has_analysis_overlay() and "형광염색" in panel.lbl_result.text()
    # 코멘트에 추가 → DB 에 기록, 오버레이 유지
    panel.add_to_comment()
    cap = db.captures.list_by_patient(patient.id)[0]
    assert "형광염색" in (cap.note or "") and ws.single_canvas.has_analysis_overlay()
    # 결과 영상 저장 → 새 영상(원본 보존)
    n0 = len(ws.captures())
    saved = panel.save_result_image()
    assert saved is not None and saved.note.startswith("분석 ·") and len(ws.captures()) == n0 + 1
    # 다른 영상으로 넘어가면 결과는 지워짐
    ws.step(1)
    assert panel.result is None and not ws.single_canvas.has_analysis_overlay()


def test_pro_align_sharpest_and_dicom(qapp, app_env, tmp_path):
    from tests.test_smart_capture import _scene
    ref = cv2.GaussianBlur(_scene(), (0, 0), 1.0)
    M = cv2.getRotationMatrix2D((640, 360), 5, 1.0)
    moved = cv2.warpAffine(ref, M, (1280, 720))
    blurry = cv2.GaussianBlur(_scene(), (0, 0), 6)
    ws, db, patient = _workspace(app_env, [blurry, ref, moved])
    panel = ws.analysis
    # 가장 선명한 영상: 같은 날 3장 중 ref(1) 또는 moved(2)
    best = panel.open_sharpest()
    assert best in (1, 2) and ws.mode() == "single" and "선명도 순위" in panel.lbl_result.text()
    # 비교 + 자동 정렬
    ws.set_mode("multi")
    ws.select_for_compare(1, 2)
    ws.set_mode("compare")
    r = panel.align_compare()
    assert r is not None and r.ok and abs(abs(r.rotation) - 5) < 0.6
    assert ws.cmp_right.image().shape == ref.shape
    # DICOM: 비교 중인 2장
    paths = panel.export_dicom(str(tmp_path))
    assert len(paths) == 2 and all(p.exists() for p in paths)


def test_pro_tbut_save(qapp, app_env, tmp_path):
    ws, db, patient = _workspace(app_env, [_fluo(3)])
    frames, fps = _tear_film()
    path = str(tmp_path / "t.avi")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
    for f in frames:
        vw.write(f)
    vw.release()
    res = ws.analysis.run_tbut(path)
    assert res.ok
    cap = ws.analysis.save_tbut(res)
    assert cap is not None and cap.note.startswith("TBUT 4.")
