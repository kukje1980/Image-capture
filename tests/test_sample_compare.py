"""Pro '샘플과 비교' — 현재 환자 영상 ↔ 질환별 샘플 사진 나란히 보기, 샘플은 환자 이름으로 저장하지 않음."""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QMessageBox

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui.pro.sample_picker import SamplePicker, sample_patients


def _img(v=80):
    a = np.full((120, 160, 3), v, np.uint8)
    a[40:80, 60:100] = 255 - v
    return a


def _setup(app_env, with_samples=True):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="P1", name="김영희", diagnosis="결막하출혈"))
    patient = db.patients.get(pid)
    for k in range(3):
        svc.save_photo(_img(40 + k * 30), patient, eye="OD")
    samples = {}
    if with_samples:
        for chart, name in (("SAMPLE-01", "건성안"), ("SAMPLE-06", "결막하출혈")):
            sid = db.patients.insert(Patient(chart_no=chart, name=f"샘플 · {name}", diagnosis=name))
            sp = db.patients.get(sid)
            samples[name] = svc.save_photo(_img(200), sp, eye="NA", note=f"[샘플] {name} 사진\n출처: EyeRounds · CC BY-NC-ND 3.0")
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OD")
    ws.resize(1200, 800)
    ws.set_patient(patient)
    return ws, db, patient, samples


def test_compare_with_sample(qapp, app_env):
    ws, db, patient, samples = _setup(app_env)
    ws.open_index(1)
    assert ws.compare_with_sample(samples["결막하출혈"])
    assert ws.mode() == "compare"
    left, right = ws._pair
    assert left.id == ws.captures()[1].id and right.id == samples["결막하출혈"].id
    assert ws.cmp_left.image() is not None and ws.cmp_right.image() is not None
    assert "샘플 · 결막하출혈" in ws.cmp_right._caption

    # 비교 중에 다른 샘플로 바꾸면 왼쪽은 그대로
    ws.compare_with_sample(samples["건성안"])
    assert ws._pair[0].id == left.id and ws._pair[1].id == samples["건성안"].id

    # 샘플 쪽을 편집해도 이 환자 영상으로 저장하지 않음, 왼쪽(환자 영상)은 저장
    before = len(db.captures.list_by_patient(patient.id))
    for cv in (ws.cmp_left, ws.cmp_right):
        cv.rotate(1)
    saved = ws.save_edited()
    assert len(saved) == 1
    assert len(db.captures.list_by_patient(patient.id)) == before + 1
    assert all(c.patient_id == patient.id for c in db.captures.list_by_patient(patient.id))


def test_picker_prefers_patient_diagnosis(qapp, app_env):
    ws, db, _, samples = _setup(app_env)
    pats = sample_patients(db)
    assert [p.chart_no for p in pats] == ["SAMPLE-01", "SAMPLE-06"]
    dlg = SamplePicker(db, pats, prefer="결막하출혈")
    assert dlg.diseases.currentRow() == 1
    assert dlg.photos.count() == 1
    dlg._accept()
    assert dlg.chosen().id == samples["결막하출혈"].id


def test_no_samples_message(qapp, app_env, monkeypatch):
    ws, *_ = _setup(app_env, with_samples=False)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    ws.open_index(0)
    assert not ws.compare_with_sample()
    assert shown and "샘플" in shown[0]
