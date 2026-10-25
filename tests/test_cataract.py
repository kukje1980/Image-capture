"""수정체 혼탁 지수(백내장 측정 보조) · 측정 기록 DB · Pro 연동."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.capture import cataract
from app.db.measurements_dao import Measurement
from app.models.patient import Patient
from app.services.capture_service import CaptureService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def slit_photo(lens_level, cornea=200, w=800, h=600, noise=6, seed=1):
    """합성 슬릿 단면: 좁고 밝은 각막 띠 + 넓은 수정체 띠 + 정반사 점."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w), 12, np.float32) + rng.normal(0, noise, (h, w))
    img[:, 300:308] += cornea
    img[:, 340:420] += lens_level
    img[150:160, 302:312] = 255
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def retro_photo(spots=True):
    img = np.zeros((500, 500, 3), np.uint8)
    cv2.circle(img, (250, 250), 150, (60, 70, 200), -1)          # 붉은 반사 동공
    if spots:
        cv2.circle(img, (200, 220), 25, (20, 20, 60), -1)
        cv2.ellipse(img, (300, 300), (40, 15), 30, 0, 360, (25, 25, 70), -1)
    return img


# ---------------- 알고리즘 ----------------
def test_nuclear_index_monotone_and_normalised_by_cornea():
    idx = [cataract.nuclear_opacity(slit_photo(lv))["index"] for lv in (20, 60, 120, 180)]
    assert idx == sorted(idx) and idx[0] < 25 and idx[-1] > 90
    r = cataract.nuclear_opacity(slit_photo(60))
    assert r["has_cornea"] and 296 <= r["cornea_band"][0] <= 300 and 336 <= r["lens_band"][0] <= 342
    assert r["mask"][:, 350:410].mean() > 0.9 and not r["mask"][:, :280].any()
    # 조명 전체가 어두워져도(×0.6) 각막 기준 비율이라 지수가 비슷하다
    dim = (slit_photo(60).astype(np.float32) * 0.6).astype(np.uint8)
    assert abs(cataract.nuclear_opacity(dim)["index"] - r["index"]) < 8
    # 정반사(포화) 블록을 수정체 띠에 겹쳐도 지수가 튀지 않는다
    glare = slit_photo(60)
    glare[200:260, 350:400] = 255
    assert abs(cataract.nuclear_opacity(glare)["index"] - r["index"]) < 5


def test_nuclear_without_cornea_band_and_with_roi():
    only_lens = slit_photo(60, cornea=0)
    r = cataract.nuclear_opacity(only_lens)
    assert r["lens_band"] is not None and not r["has_cornea"]      # 참고값
    assert cataract.nuclear_opacity(np.zeros((100, 100, 3), np.uint8))["lens_band"] is None
    r2 = cataract.nuclear_opacity(slit_photo(60), roi=(280, 100, 450, 500))
    assert r2["has_cornea"] and abs(r2["index"] - cataract.nuclear_opacity(slit_photo(60))["index"]) < 5


def test_cortical_index_pupil_and_small_pupil_flag():
    r = cataract.cortical_opacity(retro_photo(), (100, 100, 400, 400), px_per_mm=30)
    assert 2 < r["index"] < 8 and r["pupil_diameter_mm"] == pytest.approx(10.0) and not r["small_pupil"]
    assert r["mask"][220, 200] and not r["mask"][250, 250]
    assert cataract.cortical_opacity(retro_photo(spots=False), (100, 100, 400, 400))["index"] == 0.0
    assert cataract.cortical_opacity(retro_photo(), (100, 100, 400, 400), px_per_mm=80)["small_pupil"]


# ---------------- DB ----------------
def test_measurements_dao_roundtrip_and_cascade(app_env):
    _, db = app_env
    pid = db.patients.insert(Patient(chart_no="M1", name="측정"))
    mid = db.measurements.insert(Measurement(patient_id=pid, eye="OD", kind="nuclear", value=42.5,
                                             detail={"ratio": 0.5}, locs={"NO": 3, "NC": 2},
                                             conditions="슬릿 0.2mm 45°"))
    db.measurements.insert(Measurement(patient_id=pid, eye="OS", kind="nuclear", value=10))
    db.measurements.insert(Measurement(patient_id=pid, eye="OD", kind="nuclear", value=50,
                                       measured_at="2030-01-01 00:00:00"))
    od = db.measurements.list_by_patient(pid, "nuclear", "OD")
    assert [m.value for m in od] == [42.5, 50] and od[0].id == mid
    assert od[0].locs == {"NO": 3, "NC": 2} and od[0].detail == {"ratio": 0.5} and od[0].conditions
    assert db.measurements.latest(pid, "nuclear", "OD").value == 50
    assert len(db.measurements.list_by_patient(pid)) == 3
    db.patients.delete(pid) if hasattr(db.patients, "delete") else None


# ---------------- Pro 연동 ----------------
def _workspace(app_env):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    config.save = lambda: None
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="C1", name="백내장"))
    patient = db.patients.get(pid)
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OD")
    ws.resize(1200, 800)
    ws.set_patient(patient)
    return ws, db, patient, svc


def test_pro_cataract_measure_record_trend(qapp, app_env):
    ws, db, patient, svc = _workspace(app_env)
    svc.save_photo(slit_photo(40), patient, eye="OD")
    svc.save_photo(slit_photo(120), patient, eye="OD")
    svc.save_photo(retro_photo(), patient, eye="OD")
    ws.reload()
    assert "측정 기록이 없습니다" in ws.measure.lbl_trend.text()

    ws.open_index(0)
    r = ws.measure_nuclear()
    assert r is not None and r["has_cornea"] and ws.single_canvas.has_overlay()
    ws.measure.e_cond.setText("슬릿 0.2mm · 45° · 16×")
    ws.measure.set_locs({"NO": 2, "NC": 2})
    m = ws.record_cataract()
    assert m is not None and m.kind == "nuclear" and m.locs == {"NO": 2, "NC": 2} and m.capture_id == ws.captures()[0].id
    note = db.captures.get(ws.captures()[0].id).note
    assert "핵 혼탁 지수" in note and "LOCS NO2 NC2" in note and "슬릿 0.2mm" in note
    assert "기록 1건" in ws.measure.lbl_trend.text() and ws._last_conditions() == "슬릿 0.2mm · 45° · 16×"

    ws.open_index(1)                                       # 더 탁한 수정체 → 지난 검사 대비 +
    ws.measure_nuclear()
    assert "대비 +" in ws.measure.lbl_cat.text()
    ws.record_cataract()
    assert len(db.measurements.list_by_patient(patient.id, "nuclear", "OD")) == 2

    ws.open_index(2)                                       # 역조명: 동공 원 없이 → 안내만
    assert ws.measure_cortical() is None and "동공" in ws.measure.lbl_cat.text()
    ws.single_canvas.add_circle(QPointF(100, 100), QPointF(400, 400))
    rc = ws.measure_cortical()
    assert rc is not None and 2 < rc["index"] < 8
    ws.record_cataract()
    assert "피질" in ws.measure.lbl_trend.text() and "기록 3건" in ws.measure.lbl_trend.text()
    rendered = ws.single_canvas.render_to_bgr()
    assert np.array_equal(rendered[:80, :80], retro_photo()[:80, :80])   # 마스크 레이어는 저장본에 없음


def test_pro_live_cataract_guide_hud(qapp, app_env):
    ws, db, patient, _ = _workspace(app_env)
    db.measurements.insert(Measurement(patient_id=patient.id, eye="OD", kind="nuclear", value=30,
                                       conditions="슬릿 0.3mm · 45°"))
    ws.set_mode("live")
    ws.measure.chk_guide.setChecked(True)
    ws.set_live_frame(slit_photo(60))
    texts = [t for t, _c in ws.live_canvas._hud]
    assert any("백내장 모드" in t for t in texts) and any("슬릿 0.3mm" in t for t in texts)
    assert ws.live_canvas._hud_roi is not None and ws.live_canvas._hud_roi.width() < 40
    ws.measure.chk_guide.setChecked(False)
    ws.set_live_frame(slit_photo(60))
    assert not any("백내장" in t for t, _c in ws.live_canvas._hud)
