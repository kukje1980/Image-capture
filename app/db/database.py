from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.db.captures_dao import CapturesDAO
from app.db.patients_dao import PatientsDAO

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """SQLite 연결/마이그레이션 관리 + DAO 보유.

    GUI 스레드와 백그라운드 작업이 같은 연결을 쓸 수 있도록
    check_same_thread=False + Lock 직렬화. 단일 PC/단일 writer라 충분하다.
    """

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.patients: PatientsDAO | None = None
        self.captures: CapturesDAO | None = None

    def init(self) -> "Database":
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.patients = PatientsDAO(self._conn, self._lock)
        self.captures = CapturesDAO(self._conn, self._lock)
        return self

    def _migrate(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(ddl)
            _add_missing_columns(self._conn, "patients",
                                 {"diagnosis": "TEXT", "doctor": "TEXT"})
            self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.close()
                self._conn = None


def _add_missing_columns(conn: sqlite3.Connection, table: str, cols: dict) -> None:
    """기존 DB에 새 컬럼이 없으면 추가 (구버전 DB 자동 업그레이드)."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in cols.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
