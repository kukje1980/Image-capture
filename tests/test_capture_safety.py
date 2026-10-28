"""캡처 저장 안전성: 파일명 충돌 방지, 한글 경로, 원자적 쓰기, 디스크 공간 검사, DB 실패 시 파일 보존."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from app.models.patient import Patient
from app.services import capture_service as cs
from app.services.capture_service import (
    CaptureService,
    DiskFullError,
    atomic_write_bytes,
    unique_path,
)


def _frame():
    return np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)


def _patient(db, chart="S1"):
    p = Patient(chart_no=chart, name="환자")
    p.id = db.patients.insert(p)
    return p


def test_same_millisecond_does_not_overwrite(app_env, monkeypatch):
    config, db = app_env
    svc = CaptureService(db, config)
    p = _patient(db)
    monkeypatch.setattr(CaptureService, "_filename", staticmethod(lambda ts, eye, ext: f"same_{eye}.{ext}"))
    a = svc.save_photo(_frame(), p, eye="OD")
    b = svc.save_photo(_frame(), p, eye="OD")
    assert a.file_path != b.file_path
    assert Path(a.file_path).exists() and Path(b.file_path).exists()
    assert a.thumbnail_path != b.thumbnail_path
    assert Path(a.export_path).name != Path(b.export_path).name
    assert len(db.captures.list_by_patient(p.id)) == 2


def test_unique_path():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.png"
        assert unique_path(p) == p
        p.write_bytes(b"1")
        assert unique_path(p) == Path(d) / "x_1.png"
        (Path(d) / "x_1.png").write_bytes(b"1")
        assert unique_path(p) == Path(d) / "x_2.png"


def test_korean_path_and_template_name(app_env, tmp_path):
    """Windows 한글 사용자 폴더·환자 이름 폴더에도 저장된다 (cv2.imwrite 대신 imencode + 파일 쓰기)."""
    config, db = app_env
    config.media_root = str(tmp_path / "홍길동 사진")
    config.export_root = str(tmp_path / "내보내기 폴더")
    config.subfolder_template = "{name}_{chart_no}/{date}"
    svc = CaptureService(db, config)
    cap = svc.save_photo(_frame(), _patient(db, "한글1"), eye="OS")
    assert "홍길동 사진" in cap.file_path and "환자_한글1" in cap.file_path
    assert Path(cap.file_path).stat().st_size > 0
    assert Path(cap.export_path).exists() and Path(cap.thumbnail_path).exists()
    assert not list(Path(cap.file_path).parent.glob(".*.part"))     # 임시 파일이 남지 않는다


def test_saved_image_is_decodable(app_env):
    cv2 = pytest.importorskip("cv2")
    config, db = app_env
    config.photo_format = "jpg"
    cap = CaptureService(db, config).save_photo(_frame(), _patient(db), eye="NA")
    img = cv2.imdecode(np.fromfile(cap.file_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape == (120, 160, 3)


def test_atomic_write_leaves_no_partial_file(tmp_path, monkeypatch):
    target = tmp_path / "a.png"
    monkeypatch.setattr(cs.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"data")
    assert not target.exists() and not list(tmp_path.iterdir())


def test_disk_full_refuses_before_writing(app_env, monkeypatch):
    config, db = app_env
    svc = CaptureService(db, config)
    p = _patient(db)
    monkeypatch.setattr(cs, "free_space_mb", lambda path: 10.0)
    with pytest.raises(DiskFullError):
        svc.save_photo(_frame(), p, eye="OD")
    with pytest.raises(DiskFullError):
        svc.begin_video(p, eye="OD")
    assert db.captures.list_by_patient(p.id) == []
    assert not list(Path(config.media_root).rglob("*.png"))
    assert svc.low_space_warning() is not None


def test_free_space_unknown_is_not_an_error(app_env, monkeypatch):
    config, db = app_env
    monkeypatch.setattr(cs, "free_space_mb", lambda path: None)
    assert CaptureService(db, config).save_photo(_frame(), _patient(db), eye="OD").id


def test_free_space_mb_walks_up_to_existing_parent(tmp_path):
    assert cs.free_space_mb(tmp_path / "없는폴더" / "더없는폴더") > 0


def test_db_failure_keeps_file(app_env, monkeypatch):
    """DB 기록이 실패해도 (환자가 그 사이 삭제됨 등) 이미 저장한 영상 파일은 지우지 않는다."""
    config, db = app_env
    svc = CaptureService(db, config)
    p = _patient(db)
    db.patients.delete(p.id)
    with pytest.raises(sqlite3.IntegrityError):
        svc.save_photo(_frame(), p, eye="OD")
    assert len(list(Path(config.media_root).rglob("*.png"))) == 1


def test_unsaved_patient_rejected(app_env):
    config, db = app_env
    with pytest.raises(ValueError):
        CaptureService(db, config).save_photo(_frame(), Patient(name="미저장"), eye="OD")


def test_finish_video_rejects_empty_file(app_env, tmp_path):
    from datetime import datetime
    config, db = app_env
    svc = CaptureService(db, config)
    p = _patient(db)
    empty = tmp_path / "v.mp4"
    empty.write_bytes(b"")
    with pytest.raises(RuntimeError):
        svc.finish_video(empty, p, "OD", datetime.now(), 1000)
    with pytest.raises(RuntimeError):
        svc.finish_video(tmp_path / "missing.mp4", p, "OD", datetime.now(), 1000)
    assert db.captures.list_by_patient(p.id) == []
