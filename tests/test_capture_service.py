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


def test_delete_capture_removes_record_and_files(app_env):
    config, db = app_env
    service = CaptureService(db, config)
    patient = _patient(db)
    cap = service.save_photo(_frame(), patient, eye="OD")
    paths = [Path(cap.file_path), Path(cap.thumbnail_path)]
    assert all(p.exists() for p in paths) and Path(cap.export_path).exists()

    assert service.delete_capture(cap) is True
    assert db.captures.get(cap.id) is None
    assert not any(p.exists() for p in paths)              # 기본 저장·썸네일 삭제
    assert Path(cap.export_path).exists()                  # 지정 폴더 사본은 백업으로 남김

    assert service.delete_capture(cap) is False            # 이미 지운 영상은 False (예외 없음)


def test_delete_captures_counts_only_existing(app_env):
    config, db = app_env
    service = CaptureService(db, config)
    patient = _patient(db)
    a = service.save_photo(_frame(), patient, eye="OD")
    b = service.save_photo(_frame(), patient, eye="OS")
    assert service.delete_captures([a, b, a]) == 2
    assert db.captures.list_by_patient(patient.id) == []
