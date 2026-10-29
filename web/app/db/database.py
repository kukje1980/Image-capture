"""SQLite 연결/마이그레이션 + 간단 DAO.

FastAPI는 여러 스레드에서 요청을 처리하므로 check_same_thread=False +
Lock 직렬화. 단일 클리닉 PC / 저빈도 쓰기라 충분하다.

안전성: busy_timeout(다른 프로세스가 잠근 동안 대기), 쓰기는 `with lock, conn:` 로 실패 시 롤백,
시작 시 quick_check 로 손상 감지, WAL + synchronous=FULL.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_SEC = 10.0
log = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """DB 를 열 수 없거나 손상된 경우."""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def init(self) -> "Database":
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SEC, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_SEC * 1000)}")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            try:
                rows = conn.execute("PRAGMA quick_check").fetchall()
                problems = [r[0] for r in rows if r[0] != "ok"]
            except sqlite3.DatabaseError as e:
                raise DatabaseError(
                    f"데이터베이스 파일이 손상되었거나 SQLite 파일이 아닙니다: {self.db_path} ({e})") from e
            if problems:
                raise DatabaseError(f"데이터베이스 손상이 감지되었습니다: {self.db_path} — "
                                    + "; ".join(problems[:5]))
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            with conn:
                _add_missing_columns(conn, "patients", {"diagnosis": "TEXT", "doctor": "TEXT"})
        except Exception:
            conn.close()
            raise
        self._conn = conn
        return self

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                conn, self._conn = self._conn, None
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    log.warning("wal_checkpoint 실패", exc_info=True)
                conn.close()

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
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO patients
                   (chart_no, patient_id, name, birth_date, sex, phone, memo, symptoms,
                    diagnosis, doctor)
                   VALUES (:chart_no, :patient_id, :name, :birth_date, :sex, :phone, :memo, :symptoms,
                           :diagnosis, :doctor)""",
                _patient_params(p),
            )
            return cur.lastrowid

    def update_patient(self, pid: int, p: dict) -> None:
        params = _patient_params(p)
        params["id"] = pid
        with self._lock, self._conn:
            self._conn.execute(
                """UPDATE patients SET
                     chart_no=:chart_no, patient_id=:patient_id, name=:name,
                     birth_date=:birth_date, sex=:sex, phone=:phone, memo=:memo,
                     symptoms=:symptoms, diagnosis=:diagnosis, doctor=:doctor,
                     updated_at=datetime('now','localtime')
                   WHERE id=:id""",
                params,
            )

    def delete_patient(self, pid: int) -> List[str]:
        """환자 삭제 (영상 레코드는 CASCADE). 지워야 할 미디어 파일 경로 목록을 돌려준다."""
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT file_path FROM captures WHERE patient_id=?", (pid,)
            ).fetchall()
            self._conn.execute("DELETE FROM patients WHERE id=?", (pid,))
        return [r["file_path"] for r in rows if r["file_path"]]

    # ---- captures ----
    def create_capture(self, c: dict) -> int:
        with self._lock, self._conn:
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
        with self._lock, self._conn:
            self._conn.execute("UPDATE captures SET note=? WHERE id=?", (note, cid))

    def delete_capture(self, cid: int) -> Optional[dict]:
        with self._lock, self._conn:
            r = self._conn.execute(
                "SELECT file_path FROM captures WHERE id=?", (cid,)
            ).fetchone()
            self._conn.execute("DELETE FROM captures WHERE id=?", (cid,))
        return dict(r) if r else None

    # ---- 검사 기록 소견 (환자·촬영일별 한 건) ----
    def list_exams(self, patient_id: int) -> List[dict]:
        """촬영일별 요약(장수·OD/OS/동영상 수)과 소견을 합쳐 최근 날짜부터 돌려준다."""
        with self._lock:
            days = self._conn.execute(
                """SELECT substr(captured_at, 1, 10) AS exam_date,
                          COUNT(*) AS count,
                          SUM(CASE WHEN eye='OD' THEN 1 ELSE 0 END) AS od,
                          SUM(CASE WHEN eye='OS' THEN 1 ELSE 0 END) AS os,
                          SUM(CASE WHEN eye='OU' THEN 1 ELSE 0 END) AS ou,
                          SUM(CASE WHEN media_type='video' THEN 1 ELSE 0 END) AS video,
                          MIN(substr(captured_at, 12, 5)) AS first_time,
                          MAX(substr(captured_at, 12, 5)) AS last_time
                   FROM captures WHERE patient_id=?
                   GROUP BY exam_date ORDER BY exam_date DESC""",
                (patient_id,),
            ).fetchall()
            notes = {r["exam_date"]: dict(r) for r in self._conn.execute(
                "SELECT * FROM exam_notes WHERE patient_id=?", (patient_id,)).fetchall()}
        out = []
        for d in days:
            row = dict(d)
            n = notes.pop(row["exam_date"], None) or {}
            row.update(exam_type=n.get("exam_type"), notes=n.get("notes"), updated_at=n.get("updated_at"))
            out.append(row)
        for n in notes.values():                      # 영상은 지웠지만 소견만 남은 날
            out.append({"exam_date": n["exam_date"], "count": 0, "od": 0, "os": 0, "ou": 0, "video": 0,
                        "first_time": None, "last_time": None,
                        "exam_type": n.get("exam_type"), "notes": n.get("notes"), "updated_at": n.get("updated_at")})
        out.sort(key=lambda r: r["exam_date"], reverse=True)
        return out

    def get_exam_note(self, patient_id: int, exam_date: str) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM exam_notes WHERE patient_id=? AND exam_date=?", (patient_id, exam_date)).fetchone()
        return dict(r) if r else None

    def upsert_exam_note(self, patient_id: int, exam_date: str, exam_type: Optional[str], notes: Optional[str]) -> dict:
        exam_type = (exam_type or "").strip() or None
        notes = (notes or "").strip() or None
        with self._lock:
            self._conn.execute(
                """INSERT INTO exam_notes (patient_id, exam_date, exam_type, notes) VALUES (?,?,?,?)
                   ON CONFLICT(patient_id, exam_date) DO UPDATE SET
                     exam_type=excluded.exam_type, notes=excluded.notes,
                     updated_at=datetime('now','localtime')""",
                (patient_id, exam_date, exam_type, notes),
            )
            self._conn.commit()
        return self.get_exam_note(patient_id, exam_date)


    # ---- measurements (혼탁 지수 등 측정 기록) ----
    def create_measurement(self, m: dict) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO measurements
                   (patient_id, capture_id, eye, kind, value, detail, locs, conditions, measured_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (m["patient_id"], m.get("capture_id"), m.get("eye"), m["kind"], float(m["value"]),
                 json.dumps(m.get("detail") or {}, ensure_ascii=False),
                 json.dumps(m.get("locs") or {}, ensure_ascii=False),
                 m.get("conditions") or "", m["measured_at"]),
            )
            return cur.lastrowid

    def list_measurements(self, patient_id: int, kind: Optional[str] = None,
                          eye: Optional[str] = None) -> List[dict]:
        q, args = "SELECT * FROM measurements WHERE patient_id=?", [patient_id]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if eye:
            q += " AND eye=?"
            args.append(eye)
        with self._lock:
            rows = self._conn.execute(q + " ORDER BY measured_at ASC, id ASC", args).fetchall()
        return [_measurement(r) for r in rows]

    def get_measurement(self, mid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM measurements WHERE id=?", (mid,)).fetchone()
        return _measurement(r) if r else None

    def delete_measurement(self, mid: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM measurements WHERE id=?", (mid,))


    # ---- ref_samples (참조 샘플 라이브러리) ----
    def create_ref(self, r: dict) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO ref_samples (region, condition, disease, note, file_path, url, created_at)
                   VALUES (:region, :condition, :disease, :note, :file_path, :url, :created_at)""", r)
            return cur.lastrowid

    def list_refs(self, region: Optional[str] = None, condition: Optional[str] = None) -> List[dict]:
        q, args = "SELECT * FROM ref_samples WHERE 1=1", []
        if region:
            q += " AND region=?"
            args.append(region)
        if condition:
            q += " AND condition=?"
            args.append(condition)
        with self._lock:
            rows = self._conn.execute(q + " ORDER BY region, condition DESC, disease, id", args).fetchall()
        return [dict(r) for r in rows]

    def get_ref(self, rid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM ref_samples WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def delete_ref(self, rid: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM ref_samples WHERE id=?", (rid,))


def _measurement(r) -> dict:
    d = dict(r)
    for k in ("detail", "locs"):
        try:
            d[k] = json.loads(d.get(k) or "{}")
        except (TypeError, ValueError):
            d[k] = {}
    d["conditions"] = d.get("conditions") or ""
    return d


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
