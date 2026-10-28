"""SQLite 연결/마이그레이션 + 간단 DAO.

FastAPI는 여러 스레드에서 요청을 처리하므로 check_same_thread=False +
Lock 직렬화. 단일 클리닉 PC / 저빈도 쓰기라 충분하다.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def init(self) -> "Database":
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            _add_missing_columns(self._conn, "patients", {"diagnosis": "TEXT", "doctor": "TEXT"})
            self._conn.commit()
        return self

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.close()
                self._conn = None

    # ---- patients ----
    def list_patients(self, q: str = "") -> List[dict]:
        with self._lock:
            if q:
                # % _ 는 글자 그대로 찾는다 (차트번호 '1_2' 가 '102' 같은 다른 환자와 맞지 않게)
                like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                rows = self._conn.execute(
                    """SELECT * FROM patients
                       WHERE name LIKE ? ESCAPE '\\' OR chart_no LIKE ? ESCAPE '\\'
                          OR phone LIKE ? ESCAPE '\\' OR patient_id LIKE ? ESCAPE '\\'
                       ORDER BY name LIMIT 500""",
                    (like, like, like, like),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM patients ORDER BY name LIMIT 500"
                ).fetchall()
        return [dict(r) for r in rows]

    def get_patient(self, pid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    def create_patient(self, p: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO patients
                   (chart_no, patient_id, name, birth_date, sex, phone, memo, symptoms,
                    diagnosis, doctor)
                   VALUES (:chart_no, :patient_id, :name, :birth_date, :sex, :phone, :memo, :symptoms,
                           :diagnosis, :doctor)""",
                _patient_params(p),
            )
            self._conn.commit()
            return cur.lastrowid

    def update_patient(self, pid: int, p: dict) -> None:
        params = _patient_params(p)
        params["id"] = pid
        with self._lock:
            self._conn.execute(
                """UPDATE patients SET
                     chart_no=:chart_no, patient_id=:patient_id, name=:name,
                     birth_date=:birth_date, sex=:sex, phone=:phone, memo=:memo,
                     symptoms=:symptoms, diagnosis=:diagnosis, doctor=:doctor,
                     updated_at=datetime('now','localtime')
                   WHERE id=:id""",
                params,
            )
            self._conn.commit()

    def delete_patient(self, pid: int) -> List[str]:
        """환자 삭제 (영상 레코드는 CASCADE). 지워야 할 미디어 파일 경로 목록을 돌려준다."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT file_path FROM captures WHERE patient_id=?", (pid,)
            ).fetchall()
            self._conn.execute("DELETE FROM patients WHERE id=?", (pid,))
            self._conn.commit()
        return [r["file_path"] for r in rows if r["file_path"]]

    # ---- captures ----
    def create_capture(self, c: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO captures
                   (patient_id, media_type, file_path, url, captured_at, eye, duration_ms, note)
                   VALUES (:patient_id, :media_type, :file_path, :url, :captured_at, :eye, :duration_ms, :note)""",
                {
                    "patient_id": c["patient_id"],
                    "media_type": c["media_type"],
                    "file_path": c["file_path"],
                    "url": c["url"],
                    "captured_at": c["captured_at"],
                    "eye": c.get("eye"),
                    "duration_ms": c.get("duration_ms"),
                    "note": c.get("note"),
                },
            )
            self._conn.commit()
            return cur.lastrowid

    def list_captures(self, patient_id: int, order: str = "desc") -> List[dict]:
        o = "DESC" if order.lower() == "desc" else "ASC"
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT * FROM captures WHERE patient_id=?
                    ORDER BY captured_at {o}, id {o}""",
                (patient_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_capture(self, cid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def update_capture_note(self, cid: int, note: Optional[str]) -> None:
        with self._lock:
            self._conn.execute("UPDATE captures SET note=? WHERE id=?", (note, cid))
            self._conn.commit()

    def delete_capture(self, cid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute(
                "SELECT file_path FROM captures WHERE id=?", (cid,)
            ).fetchone()
            self._conn.execute("DELETE FROM captures WHERE id=?", (cid,))
            self._conn.commit()
        return dict(r) if r else None


def _patient_params(p: dict) -> dict:
    return {
        "chart_no": p.get("chart_no"),
        "patient_id": p.get("patient_id"),
        "name": p.get("name"),
        "birth_date": p.get("birth_date"),
        "sex": p.get("sex") or None,
        "phone": p.get("phone"),
        "memo": p.get("memo"),
        "symptoms": p.get("symptoms"),
        "diagnosis": p.get("diagnosis"),
        "doctor": p.get("doctor"),
    }


def _add_missing_columns(conn: sqlite3.Connection, table: str, cols: dict) -> None:
    """기존 DB에 새 컬럼이 없으면 추가 (구버전 DB 자동 업그레이드)."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in cols.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
