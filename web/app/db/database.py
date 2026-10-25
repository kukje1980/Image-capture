"""SQLite 연결/마이그레이션 + 간단 DAO.

FastAPI는 여러 스레드에서 요청을 처리하므로 check_same_thread=False +
Lock 직렬화. 단일 클리닉 PC / 저빈도 쓰기라 충분하다.

튼튼하게 여는 순서 (데스크탑 app/db/database.py 와 같은 정책)
  1. busy_timeout(5초) — 잠깐의 잠금으로 'database is locked' 오류가 나지 않게
  2. WAL + synchronous=FULL — 전원이 꺼져도 파일이 깨지지 않고 커밋한 기록은 남는다
  3. quick_check — 손상돼 있으면 .corrupt-<시각> 으로 치우고 가장 최근 백업에서 복원
  4. 하루 한 번 backups/ 에 온라인 백업, 최근 14개 보관 (종료 때 그날 기록까지 갱신)
  5. 쓰기는 `with conn:` — 실패하면 롤백 (열린 트랜잭션이 남아 다음 작업을 잠그지 않게)
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_MS = 5000
BACKUP_KEEP = 14
log = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str | Path, backups: bool = True):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._backups = backups
        self._changes_at_open = 0
        self.recovery: dict | None = None

    # ---- 열기 / 닫기 ----
    def init(self) -> "Database":
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._open()
        except sqlite3.DatabaseError as e:
            log.exception("DB 를 열지 못했습니다 — 손상으로 보고 복구를 시도합니다: %s", e)
            self._close_quietly()
            quarantined = self._quarantine()
            restored = self._restore_latest_backup()
            self.recovery = {"quarantined": quarantined, "restored_from": restored, "error": str(e)}
            self._open()
        if self._backups:
            try:
                self.backup_daily()
            except Exception:  # noqa: BLE001
                log.warning("일일 백업 실패 (서버는 계속 실행)", exc_info=True)
        return self

    def _open(self) -> None:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            conn.close()
            raise sqlite3.DatabaseError(f"quick_check: {result}")
        self._conn = conn
        with self._lock, conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            _add_missing_columns(conn, "patients", {"diagnosis": "TEXT", "doctor": "TEXT"})
            _add_missing_columns(conn, "captures", {"thumbnail_path": "TEXT"})
        self._changes_at_open = conn.total_changes

    def _close_quietly(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def close(self) -> None:
        if self._conn is not None:
            if self._backups and self._conn.total_changes > self._changes_at_open:
                try:
                    self.backup_daily(refresh=True)
                except Exception:  # noqa: BLE001
                    log.warning("종료 백업 실패", exc_info=True)
            with self._lock:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                self._conn.close()
                self._conn = None

    # ---- 손상 복구 · 백업 ----
    def _quarantine(self) -> str | None:
        p = Path(self.db_path)
        if not p.exists():
            return None
        dest = p.with_name(f"{p.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(p) + suffix)
            if src.exists():
                try:
                    src.replace(Path(str(dest) + suffix))
                except OSError:
                    log.warning("손상 DB 이동 실패: %s", src, exc_info=True)
        log.warning("손상된 DB 를 보관했습니다: %s", dest)
        return str(dest)

    def backup_dir(self) -> Path:
        return Path(self.db_path).parent / "backups"

    def list_backups(self) -> list[Path]:
        d = self.backup_dir()
        if not d.is_dir():
            return []
        return sorted(d.glob(f"{Path(self.db_path).stem}-*.db"), key=lambda f: f.stat().st_mtime)

    def _restore_latest_backup(self) -> str | None:
        for b in reversed(self.list_backups()):
            if _is_healthy(b):
                shutil.copy2(b, self.db_path)
                log.warning("백업에서 DB 를 복원했습니다: %s", b)
                return str(b)
        log.warning("복원할 백업이 없어 빈 DB 로 시작합니다")
        return None

    def backup(self, dest) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        dst = sqlite3.connect(str(tmp))
        try:
            with self._lock:
                if self._conn.in_transaction:
                    self._conn.rollback()
                self._conn.backup(dst)
        finally:
            dst.close()
        tmp.replace(dest)
        return dest

    def backup_daily(self, keep: int = BACKUP_KEEP, refresh: bool = False) -> Path | None:
        dest = self.backup_dir() / f"{Path(self.db_path).stem}-{time.strftime('%Y%m%d')}.db"
        made = None
        if refresh or not dest.exists():
            made = self.backup(dest)
            log.info("DB 백업: %s", dest)
        for f in self.list_backups()[:-keep] if keep > 0 else []:
            try:
                f.unlink()
            except OSError:
                pass
        return made

    # ---- patients ----
    def list_patients(self, q: str = "") -> List[dict]:
        with self._lock:
            if q:
                like = f"%{q}%"
                rows = self._conn.execute(
                    """SELECT * FROM patients
                       WHERE name LIKE ? OR chart_no LIKE ? OR phone LIKE ? OR patient_id LIKE ?
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
                "SELECT file_path, thumbnail_path FROM captures WHERE patient_id=?", (pid,)
            ).fetchall()
            self._conn.execute("DELETE FROM patients WHERE id=?", (pid,))
        out = []
        for r in rows:
            out.extend(x for x in (r["file_path"], r["thumbnail_path"]) if x)
        return out

    # ---- captures ----
    def create_capture(self, c: dict) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO captures
                   (patient_id, media_type, file_path, url, thumbnail_path, captured_at, eye, duration_ms, note)
                   VALUES (:patient_id, :media_type, :file_path, :url, :thumbnail_path, :captured_at, :eye,
                           :duration_ms, :note)""",
                {
                    "patient_id": c["patient_id"],
                    "media_type": c["media_type"],
                    "file_path": c["file_path"],
                    "url": c["url"],
                    "thumbnail_path": c.get("thumbnail_path"),
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
        return [_with_thumb(dict(r)) for r in rows]

    def get_capture(self, cid: int) -> Optional[dict]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone()
        return _with_thumb(dict(r)) if r else None

    def update_capture_note(self, cid: int, note: Optional[str]) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE captures SET note=? WHERE id=?", (note, cid))

    def delete_capture(self, cid: int) -> Optional[dict]:
        with self._lock, self._conn:
            r = self._conn.execute(
                "SELECT file_path, thumbnail_path FROM captures WHERE id=?", (cid,)
            ).fetchone()
            self._conn.execute("DELETE FROM captures WHERE id=?", (cid,))
        return dict(r) if r else None


def _with_thumb(row: dict) -> dict:
    """썸네일이 있으면 thumb_url 을 붙인다 (없으면 원본 url 로 대신)."""
    tp = row.get("thumbnail_path")
    row["thumb_url"] = ("/media/" + tp.replace("\\", "/")) if tp else row.get("url")
    return row


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


def _is_healthy(path: Path) -> bool:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except sqlite3.Error:
        return False


def _add_missing_columns(conn: sqlite3.Connection, table: str, cols: dict) -> None:
    """기존 DB에 새 컬럼이 없으면 추가 (구버전 DB 자동 업그레이드)."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in cols.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
