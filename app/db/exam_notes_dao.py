"""검사 기록 소견 DAO — 환자별·촬영일별 한 건 (exam_notes 테이블)."""
from __future__ import annotations

import sqlite3
import threading
from typing import Optional


class ExamNotesDAO:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._c = conn
        self._lock = lock

    def get(self, patient_id: int, exam_date: str) -> Optional[dict]:
        with self._lock:
            r = self._c.execute(
                "SELECT * FROM exam_notes WHERE patient_id=? AND exam_date=?", (patient_id, exam_date)
            ).fetchone()
        return dict(r) if r is not None else None

    def list_by_patient(self, patient_id: int) -> dict[str, dict]:
        """{촬영일: 행} — 검사 기록 목록에 소견 유무를 표시할 때 쓴다."""
        with self._lock:
            rows = self._c.execute(
                "SELECT * FROM exam_notes WHERE patient_id=? ORDER BY exam_date DESC", (patient_id,)
            ).fetchall()
        return {r["exam_date"]: dict(r) for r in rows}

    def upsert(self, patient_id: int, exam_date: str, exam_type: Optional[str], notes: Optional[str]) -> dict:
        exam_type = (exam_type or "").strip() or None
        notes = (notes or "").strip() or None
        with self._lock:
            self._c.execute(
                """INSERT INTO exam_notes (patient_id, exam_date, exam_type, notes)
                   VALUES (?,?,?,?)
                   ON CONFLICT(patient_id, exam_date) DO UPDATE SET
                     exam_type=excluded.exam_type, notes=excluded.notes,
                     updated_at=datetime('now','localtime')""",
                (patient_id, exam_date, exam_type, notes),
            )
            self._c.commit()
        return self.get(patient_id, exam_date)

    def delete(self, patient_id: int, exam_date: str) -> None:
        with self._lock:
            self._c.execute("DELETE FROM exam_notes WHERE patient_id=? AND exam_date=?", (patient_id, exam_date))
            self._c.commit()
