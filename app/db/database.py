from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.db.captures_dao import CapturesDAO
from app.db.exams_dao import ExamsDAO
from app.db.patients_dao import PatientsDAO
from app.db.ref_images_dao import RefImagesDAO

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
        self.exams: ExamsDAO | None = None
        self.references: RefImagesDAO | None = None

    def init(self) -> "Database":
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.patients = PatientsDAO(self._conn, self._lock)
        self.captures = CapturesDAO(self._conn, self._lock)
        self.exams = ExamsDAO(self._conn, self._lock)
        self.references = RefImagesDAO(self._conn, self._lock)
        return self

    def _migrate(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(ddl)
            _add_missing_columns(self._conn, "patients",
                                 {"diagnosis": "TEXT", "doctor": "TEXT"})
            _add_missing_columns(self._conn, "captures",
                                 {"exam_id": "INTEGER REFERENCES exams(id) ON DELETE SET NULL"})
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_captures_exam ON captures(exam_id)")
            _backfill_exams(self._conn)
            self._conn.commit()

    # ---- 백업 / 복원 (Explorer 판 파일 메뉴) ----
    def backup_to(self, dest_path) -> Path:
        """사용 중인 DB 를 그대로 한 파일로 복사 (SQLite 온라인 백업 — 앱을 끄지 않아도 안전)."""
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dst = sqlite3.connect(str(dest_path))
        try:
            with self._lock:
                self._conn.backup(dst)
        finally:
            dst.close()
        return dest_path

    def restore_from(self, src_path) -> None:
        """백업 파일 내용으로 지금 DB 를 바꾼다 (연결은 그대로 — 다시 시작할 필요 없음)."""
        src = sqlite3.connect(str(src_path))
        try:
            ok = src.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if ok != "ok" or not {"patients", "captures"} <= tables:
                raise ValueError("슬릿램프 영상 시스템의 백업 파일이 아닙니다.")
            with self._lock:
                src.backup(self._conn)
        finally:
            src.close()
        self._migrate()                      # 구버전 백업이면 새 컬럼·검사 묶음을 채움

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


def _backfill_exams(conn: sqlite3.Connection) -> None:
    """검사가 없는 캡처(구버전·다른 판에서 찍은 영상)를 촬영 날짜별 검사로 묶는다."""
    rows = conn.execute(
        """SELECT DISTINCT patient_id, substr(captured_at, 1, 10) AS d
           FROM captures WHERE exam_id IS NULL"""
    ).fetchall()
    for pid, day in rows:
        r = conn.execute(
            "SELECT id FROM exams WHERE patient_id=? AND exam_date=? ORDER BY id DESC LIMIT 1", (pid, day)
        ).fetchone()
        eid = r[0] if r else conn.execute(
            "INSERT INTO exams (patient_id, exam_date, title) VALUES (?,?,?)", (pid, day, "세극등 검사")
        ).lastrowid
        conn.execute(
            "UPDATE captures SET exam_id=? WHERE exam_id IS NULL AND patient_id=? AND substr(captured_at,1,10)=?",
            (eid, pid, day),
        )
