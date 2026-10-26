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

    # 검색 항목 (Explorer 판 환자 목록) — 진단명·병력(증상·메모·검사 소견·검사 기록 소견)으로도 찾는다
    SEARCH_FIELDS = {
        "all": "전체",
        "name": "이름",
        "chart": "차트번호",
        "diagnosis": "진단명",
        "history": "병력·소견",
    }

    def search_by(self, q: str, field: str = "all", limit: int = 500) -> List[Patient]:
        q = (q or "").strip()
        if not q:
            return self.list_all(limit=limit)
        like = f"%{q}%"
        exam_hit = ("EXISTS (SELECT 1 FROM exams e WHERE e.patient_id=patients.id "
                    "AND (e.diagnosis LIKE ? OR e.memo LIKE ? OR e.title LIKE ?))")
        conds = {
            "name": (["name LIKE ?"], [like]),
            "chart": (["chart_no LIKE ?", "patient_id LIKE ?"], [like, like]),
            "diagnosis": (["diagnosis LIKE ?", "EXISTS (SELECT 1 FROM exams e WHERE e.patient_id=patients.id "
                           "AND e.diagnosis LIKE ?)"], [like, like]),
            "history": (["symptoms LIKE ?", "memo LIKE ?", exam_hit,
                         "EXISTS (SELECT 1 FROM exam_notes n WHERE n.patient_id=patients.id AND n.notes LIKE ?)"],
                        [like, like, like, like, like, like]),
        }
        if field in conds:
            where, args = conds[field]
        else:
            where, args = [], []
            for w, a in conds.values():
                where += w
                args += a
            where.append("phone LIKE ?")
            args.append(like)
        with self._lock:
            rows = self._c.execute(
                f"SELECT * FROM patients WHERE {' OR '.join(where)} ORDER BY name LIMIT ?",
                (*args, limit),
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
