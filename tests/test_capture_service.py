from __future__ import annotations

from pathlib import Path

import numpy as np

from app.models.patient import Patient
from app.services.capture_service import CaptureService


def _frame():
    return np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)


def _patient(db):
    p = Patient(chart_no="S001", name="환자", sex="F")
    p.id = db.patients.insert(p)
    return p


def test_save_photo_triple_write(app_env):
    config, db = app_env
    service = CaptureService(db, config)
    patient = _patient(db)

    cap = service.save_photo(_frame(), patient, eye="OD")

    # 1) 기본 파일
    assert Path(cap.file_path).exists()
    # 2) export 파일
    assert cap.export_path is not None
    assert Path(cap.export_path).exists()
    # 3) 썸네일
    assert cap.thumbnail_path is not None
    assert Path(cap.thumbnail_path).exists()
    # 4) DB 레코드
    assert cap.id is not None
    rows = db.captures.list_by_patient(patient.id)
    assert len(rows) == 1
    assert rows[0].eye == "OD"
    assert rows[0].media_type == "photo"


def test_save_photo_export_failure_is_nonfatal(app_env):
    config, db = app_env
    config.export_root = ""  # export 비활성화 → export_path=None 이지만 저장은 성공
    service = CaptureService(db, config)
    patient = _patient(db)

    cap = service.save_photo(_frame(), patient, eye="OS")
    assert Path(cap.file_path).exists()
    assert cap.export_path is None
    assert cap.id is not None


def test_jpg_format(app_env):
    config, db = app_env
    config.photo_format = "jpg"
    service = CaptureService(db, config)
    patient = _patient(db)

    cap = service.save_photo(_frame(), patient, eye="NA")
    assert cap.file_path.endswith(".jpg")
    assert Path(cap.file_path).exists()


def test_export_on_capture_off_then_send(app_env):
    """촬영 시 자동 전송을 끄면 export 복사본이 없고, 목록 '보내기'로 나중에 전송된다."""
    config, db = app_env
    config.export_on_capture = False
    service = CaptureService(db, config)
    patient = _patient(db)

    cap = service.save_photo(_frame(), patient, eye="OD")
    assert cap.export_path is None
    assert not list(Path(config.export_root).rglob("*.png"))

    dst = service.send_to_export(cap, patient)
    assert dst.exists() and dst.name == Path(cap.file_path).name
    assert str(dst).startswith(config.export_root)
    assert db.captures.get(cap.id).export_path == str(dst)
    # 원본은 그대로
    assert Path(cap.file_path).exists()
    # 다시 보내도 같은 경로, 예외 없음
    assert service.send_to_export(cap, patient) == dst


def test_send_recopies_when_export_copy_missing(app_env):
    config, db = app_env
    service = CaptureService(db, config)
    patient = _patient(db)
    cap = service.save_photo(_frame(), patient, eye="OS")
    Path(cap.export_path).unlink()                   # 누군가 전송 폴더에서 지움
    dst = service.send_to_export(cap, patient)
    assert dst.exists() and str(dst) == cap.export_path


def test_send_requires_export_root(app_env):
    import pytest
    config, db = app_env
    config.export_root = ""
    service = CaptureService(db, config)
    patient = _patient(db)
    cap = service.save_photo(_frame(), patient)
    with pytest.raises(RuntimeError):
        service.send_to_export(cap, patient)


def test_delete_capture_keeps_export_copy(app_env):
    config, db = app_env
    service = CaptureService(db, config)
    patient = _patient(db)
    cap = service.save_photo(_frame(), patient, eye="OD")
    service.delete_capture(cap)
    assert not Path(cap.file_path).exists()
    assert not Path(cap.thumbnail_path).exists()
    assert Path(cap.export_path).exists()             # 전송 폴더 복사본은 남는다
    assert db.captures.get(cap.id) is None
    assert db.captures.list_by_patient(patient.id) == []
    service.delete_capture(cap)                       # 이미 없어도 예외 없음
