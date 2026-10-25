"""DB 튼튼함: 손상 복구 · 백업 · 잠금 대기."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.database import Database
from app.models.patient import Patient


def _fresh(tmp_path, name="a.db", backups=True):
    return Database(str(tmp_path / name), backups=backups).init()


def test_daily_backup_created_once_and_rotated(tmp_path):
    db = _fresh(tmp_path)
    db.patients.insert(Patient(chart_no="B1", name="백업"))
    backups = db.list_backups()
    assert len(backups) == 1 and backups[0].parent == tmp_path / "backups"
    assert db.backup_daily() is None                      # 같은 날은 다시 만들지 않는다
    # 오래된 백업 파일을 흉내 내서 보관 개수 제한 확인
    for i in range(20):
        f = tmp_path / "backups" / f"a-2000010{i:02d}.db"
        f.write_bytes(b"")
    db.backup_daily(keep=5)
    assert len(db.list_backups()) == 5
    db.close()


def test_backup_is_a_complete_copy(tmp_path):
    db = _fresh(tmp_path)
    pid = db.patients.insert(Patient(chart_no="C1", name="홍길동"))
    out = db.backup(tmp_path / "copy.db")
    c = sqlite3.connect(str(out))
    assert c.execute("SELECT name FROM patients WHERE id=?", (pid,)).fetchone()[0] == "홍길동"
    c.close()
    db.close()


def test_corrupt_db_is_quarantined_and_restored_from_backup(tmp_path):
    db = _fresh(tmp_path)
    db.patients.insert(Patient(chart_no="K1", name="복원대상"))
    db.close()                                            # 닫을 때 체크포인트 → 백업·본 파일 모두 완전
    assert db.list_backups()
    # 본 파일을 깨뜨린다 (헤더를 쓰레기로)
    p = Path(db.db_path)
    p.write_bytes(b"not a sqlite file" * 100)
    db2 = Database(db.db_path).init()
    assert db2.recovery and db2.recovery["quarantined"] and db2.recovery["restored_from"]
    assert Path(db2.recovery["quarantined"]).exists()     # 손상본은 지우지 않고 보관
    assert db2.patients.search("복원대상")[0].chart_no == "K1"
    db2.close()


def test_corrupt_db_without_backup_starts_empty(tmp_path):
    p = tmp_path / "n.db"
    p.write_bytes(b"garbage" * 50)
    db = Database(str(p)).init()
    assert db.recovery and db.recovery["restored_from"] is None
    assert db.patients.list_all() == []
    db.close()


def test_busy_timeout_and_wal(tmp_path):
    db = _fresh(tmp_path)
    assert db._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert db._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()
    assert not Path(db.db_path + "-wal").exists() or Path(db.db_path + "-wal").stat().st_size == 0


def test_failed_write_rolls_back_and_backup_still_works(tmp_path):
    """차트번호 중복으로 INSERT 가 실패해도 트랜잭션이 열린 채 남지 않아야 한다 (백업·다음 작업이 잠기지 않게)."""
    import pytest
    db = _fresh(tmp_path)
    db.patients.insert(Patient(chart_no="DUP", name="a"))
    with pytest.raises(sqlite3.IntegrityError):
        db.patients.insert(Patient(chart_no="DUP", name="b"))
    assert not db._conn.in_transaction
    assert db.backup(tmp_path / "after-fail.db").exists()
    db.close()
