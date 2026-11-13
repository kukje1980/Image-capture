from __future__ import annotations

import sqlite3
import threading
from typing import List, Optional

from app.models.patient import Patient, PatientSummary


class PatientsDAO:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._c = conn
        self._lock = lock

    def insert(self, p: Patient) -> int:
        with self._lock:
            cur = self._c.execute(
                """INSERT INTO patients
                   (chart_no, patient_id, name, birth_date, sex, phone, memo, symptoms,
                    diagnosis, doctor)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (p.chart_no, p.patient_id, p.name, p.birth_date, p.sex, p.phone, p.memo, p.symptoms,
                 p.diagnosis, p.doctor),
            )
            self._c.commit()
            return cur.lastrowid

    def update(self, p: Patient) -> None:
        with self._lock:
            self._c.execute(
                """UPDATE patients SET
                     chart_no=?, patient_id=?, name=?, birth_date=?, sex=?, phone=?,
                     memo=?, symptoms=?, diagnosis=?, doctor=?,
                     updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (p.chart_no, p.patient_id, p.name, p.birth_date, p.sex, p.phone,
                 p.memo, p.symptoms, p.diagnosis, p.doctor, p.id),
            )
            self._c.commit()

    def delete(self, pid: int) -> None:
        with self._lock:
            self._c.execute("DELETE FROM patients WHERE id=?", (pid,))
            self._c.commit()

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

    def list_with_stats(self) -> List[PatientSummary]:
        """환자 목록 화면용: 모든 환자 + 최근 검사일 + 검사 수를 한 번의 질의로.

        검사 = 그 환자의 영상(captures)이 있는 날짜. 최근 검사가 있는 환자부터, 그다음 이름순.
        """
        with self._lock:
            rows = self._c.execute(
                """SELECT p.*, MAX(substr(c.captured_at, 1, 10)) AS _last_exam,
                          COUNT(DISTINCT substr(c.captured_at, 1, 10)) AS _exam_count
                   FROM patients p LEFT JOIN captures c ON c.patient_id = p.id
                   GROUP BY p.id
                   ORDER BY (_last_exam IS NULL), _last_exam DESC, p.name, p.id"""
            ).fetchall()
        out = []
        for r in rows:
            keys = [k for k in r.keys() if not k.startswith("_")]
            out.append(PatientSummary(Patient(**{k: r[k] for k in keys}),
                                      r["_last_exam"], int(r["_exam_count"] or 0)))
        return out

    @staticmethod
    def _row(r) -> Optional[Patient]:
        if r is None:
            return None
        return Patient(**{k: r[k] for k in r.keys()})
