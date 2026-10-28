"""DB 안전성: 실패 시 롤백, 잠금 대기, 손상 감지, 자동 백업, 종료 시 체크포인트."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.db.database import BACKUP_KEEP, Database, DatabaseError
from app.models.capture import Capture
from app.models.patient import Patient


def test_failed_write_rolls_back_and_next_write_works(app_env):
    _, db = app_env
    db.patients.insert(Patient(chart_no="DUP", name="a"))
    with pytest.raises(sqlite3.IntegrityError):
        db.patients.insert(Patient(chart_no="DUP", name="b"))
    assert not db._conn.in_transaction            # 실패한 쓰기가 트랜잭션을 열어 둔 채 남기지 않는다
    pid = db.patients.insert(Patient(chart_no="OK", name="c"))
    assert db.patients.get(pid).name == "c"
    # 다른 연결에서도 바로 보인다 (커밋 누락 없음)
    other = sqlite3.connect(db.db_path)
    try:
        assert other.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 2
    finally:
        other.close()


def test_capture_insert_for_missing_patient_fails_cleanly(app_env):
    _, db = app_env
    with pytest.raises(sqlite3.IntegrityError):
        db.captures.insert(Capture(patient_id=9999, media_type="photo", file_path="x",
                                   captured_at="2026-01-01 00:00:00"))
    assert not db._conn.in_transaction
    assert db.captures.list_by_patient(9999) == []


def test_pragmas(app_env):
    _, db = app_env
    c = db._conn
    assert c.execute("PRAGMA busy_timeout").fetchone()[0] >= 10000
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert c.execute("PRAGMA synchronous").fetchone()[0] == 2     # FULL


def test_waits_for_lock_instead_of_failing(app_env):
    """다른 프로세스(두 번째 실행·DB 뷰어)가 잠시 잠가도 즉시 'database is locked' 로 실패하지 않는다."""
    import threading
    import time

    _, db = app_env
    other = sqlite3.connect(db.db_path, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")           # 쓰기 잠금

    def release():
        time.sleep(0.5)
        other.execute("COMMIT")

    t = threading.Thread(target=release)
    t.start()
    t0 = time.time()
    pid = db.patients.insert(Patient(chart_no="L1", name="lock"))
    t.join()
    other.close()
    assert pid > 0 and time.time() - t0 >= 0.4


def test_corrupt_file_is_detected(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database, just garbage " * 50)
    with pytest.raises(DatabaseError) as ei:
        Database(str(bad)).init()
    assert "손상" in str(ei.value) and "backups" in str(ei.value)
    assert bad.read_bytes().startswith(b"this is not")      # 원본 파일은 건드리지 않는다


def test_daily_backup_created_once_and_pruned(tmp_path):
    db = Database(str(tmp_path / "d" / "slitlamp.db")).init()
    try:
        db.patients.insert(Patient(chart_no="B1", name="backup"))
        bdir = db.backup_dir
        today = datetime.now()
        dest = bdir / f"slitlamp-{today:%Y%m%d}.db"
        assert dest.exists()                                   # init 에서 생성
        before = dest.stat().st_mtime_ns
        assert db.daily_backup(today) == dest
        assert dest.stat().st_mtime_ns == before               # 같은 날은 다시 만들지 않는다

        # 백업은 독립적으로 열 수 있는 정상 DB 여야 한다 (init 당시 내용)
        chk = sqlite3.connect(dest)
        try:
            assert chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"patients", "captures"}
        finally:
            chk.close()

        # 오래된 백업은 BACKUP_KEEP 개만 남긴다
        for i in range(BACKUP_KEEP + 5):
            (bdir / f"slitlamp-2000{i:04d}.db").write_bytes(b"old")
        db.daily_backup(datetime(2030, 1, 2))
        assert len(list(bdir.glob("slitlamp-*.db"))) == BACKUP_KEEP
        assert (bdir / "slitlamp-20300102.db").exists()
    finally:
        db.close()


def test_backup_failure_does_not_block_startup(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "slitlamp.db"))
    monkeypatch.setattr(Database, "backup_to", lambda self, dest: (_ for _ in ()).throw(OSError("disk")))
    db.init()
    try:
        assert db.last_backup is None
        assert db.patients.insert(Patient(chart_no="X", name="x")) > 0
    finally:
        db.close()


def test_close_checkpoints_wal(tmp_path):
    path = tmp_path / "slitlamp.db"
    db = Database(str(path)).init()
    db.patients.insert(Patient(chart_no="W1", name="wal"))
    wal = Path(str(path) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0
    db.close()
    assert not db.is_open
    assert not wal.exists() or wal.stat().st_size == 0        # 본 파일에 합쳐짐
    chk = sqlite3.connect(path)
    try:
        assert chk.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1
    finally:
        chk.close()


def test_stats(app_env):
    _, db = app_env
    db.patients.insert(Patient(chart_no="S", name="s"))
    st = db.stats()
    assert st["patients"] == 1 and st["captures"] == 0 and st["path"] == db.db_path
