from __future__ import annotations

import pytest

from app.models.capture import Capture
from app.models.patient import Patient


def _make_patient(name="홍길동", chart="C001"):
    return Patient(chart_no=chart, name=name, sex="M", phone="010-1234-5678",
                   symptoms="충혈", memo="초진")


def test_patient_crud(app_env):
    _, db = app_env
    pid = db.patients.insert(_make_patient())
    assert pid > 0

    got = db.patients.get(pid)
    assert got.name == "홍길동"
    assert got.chart_no == "C001"

    got.name = "김철수"
    db.patients.update(got)
    assert db.patients.get(pid).name == "김철수"

    assert len(db.patients.search("김철수")) == 1
    assert len(db.patients.search("없는이름")) == 0

    db.patients.delete(pid)
    assert db.patients.get(pid) is None


def test_unique_chart_no(app_env):
    _, db = app_env
    db.patients.insert(_make_patient(chart="DUP"))
    with pytest.raises(Exception):
        db.patients.insert(_make_patient(name="다른사람", chart="DUP"))


def test_capture_insert_and_fk_cascade(app_env):
    _, db = app_env
    pid = db.patients.insert(_make_patient(chart="C100"))
    cap = Capture(patient_id=pid, media_type="photo", file_path="/tmp/a.png",
                  captured_at="2026-05-28 10:00:00", eye="OD")
    cid = db.captures.insert(cap)
    assert cid > 0

    rows = db.captures.list_by_patient(pid)
    assert len(rows) == 1
    assert rows[0].eye == "OD"

    # ON DELETE CASCADE: 환자 삭제 시 캡처도 삭제
    db.patients.delete(pid)
    assert db.captures.list_by_patient(pid) == []


def test_capture_order(app_env):
    _, db = app_env
    pid = db.patients.insert(_make_patient(chart="C200"))
    for t in ("09:00:00", "10:00:00", "11:00:00"):
        db.captures.insert(Capture(patient_id=pid, media_type="photo",
                                   file_path=f"/tmp/{t}.png",
                                   captured_at=f"2026-05-28 {t}"))
    desc = db.captures.list_by_patient(pid, order="desc")
    asc = db.captures.list_by_patient(pid, order="asc")
    assert desc[0].captured_at.endswith("11:00:00")
    assert asc[0].captured_at.endswith("09:00:00")
