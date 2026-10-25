from __future__ import annotations

import sqlite3
from typing import List, Optional

from app.models.patient import Patient


class PatientsDAO:
    """patients 테이블 접근. 쓰기는 `with self._lock, self._c:` 로 묶어
    성공 시 commit, 예외 시 rollback 되게 한다 (차트번호 중복 실패가 다음 저장에 영향 없음)."""

    def __init__(self, conn: sqlite3.Connection, lock):
        self._c = conn
        self._lock = lock

    def insert(self, p: Patient) -> int:
        with self._lock, self._c:
            cur = self._c.execute(
                """INSERT INTO patients
                   (chart_no, patient_id, name, birth_date, sex, phone, memo, symptoms,
                    diagnosis, doctor)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (p.chart_no, p.patient_id, p.name, p.birth_date, p.sex, p.phone, p.memo, p.symptoms,
                 p.diagnosis, p.doctor),
            )
            return cur.lastrowid

    def update(self, p: Patient) -> None:
        with self._lock, self._c:
            self._c.execute(
                """UPDATE patients SET
                     chart_no=?, patient_id=?, name=?, birth_date=?, sex=?, phone=?,
                     memo=?, symptoms=?, diagnosis=?, doctor=?,
                     updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (p.chart_no, p.patient_id, p.name, p.birth_date, p.sex, p.phone,
                 p.memo, p.symptoms, p.diagnosis, p.doctor, p.id),
            )

    def delete(self, pid: int) -> None:
        with self._lock, self._c:
            self._c.execute("DELETE FROM patients WHERE id=?", (pid,))

    def get(self, pid: int) -> Optional[Patient]:
        with self._lock:
            r = self._c.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        return self._row(r)

    def search(self, q: str, limit: int = 200) -> List[Patient]:
        like = f"%{q}%"
        with self._lock:
            rows = self._c.execute(
                """SELECT * FROM patients
                   WHERE name LIKE ? OR chart_no LIKE ? OR phone LIKE ? OR patient_id LIKE ?
                   ORDER BY name LIMIT ?""",
                (like, like, like, like, limit),
            ).fetchall()
        return [self._row(r) for r in rows]

    def list_all(self, limit: int = 500, offset: int = 0) -> List[Patient]:
        with self._lock:
            rows = self._c.execute(
                "SELECT * FROM patients ORDER BY name LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> Optional[Patient]:
        if r is None:
            return None
        return Patient(**{k: r[k] for k in r.keys()})
