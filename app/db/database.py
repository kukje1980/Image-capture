"""SQLite 연결/마이그레이션 관리 + DAO 보유.

튼튼하게 여는 순서
  1. busy_timeout(5초) — 다른 프로세스(백업 도구·두 번째 실행)가 잠깐 잠가도 'database is locked' 로 죽지 않는다
  2. WAL 저널 + synchronous=FULL — 전원이 꺼져도 파일이 깨지지 않고, 커밋한 기록은 남는다
  3. quick_check — 파일이 손상돼 있으면 .corrupt-<시각> 으로 옆에 치우고, 가장 최근 백업에서 복원한다
  4. 하루 한 번 backups/ 에 온라인 백업(sqlite backup API) 을 만들고 최근 14개만 남긴다
  5. 닫을 때 WAL 체크포인트 — .db 파일 하나만 복사해도 완전한 사본이 되게
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from app.db.captures_dao import CapturesDAO
from app.db.patients_dao import PatientsDAO

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_MS = 5000
BACKUP_KEEP = 14
log = logging.getLogger(__name__)


class Database:
    """GUI 스레드와 백그라운드 작업이 같은 연결을 쓸 수 있도록
    check_same_thread=False + Lock 직렬화. 단일 PC/단일 writer라 충분하다.
    """

    def __init__(self, db_path: str, backups: bool = True):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._backups = backups
        self._changes_at_open = 0
        self.patients: PatientsDAO | None = None
        self.captures: CapturesDAO | None = None
        self.recovery: dict | None = None     # 손상 복구를 했으면 {"quarantined": 경로, "restored_from": 백업 경로|None}

    # ---------------- 열기 ----------------
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
            self._open()                      # 복원본(또는 새 빈 DB)으로 다시 연다
        self.patients = PatientsDAO(self._conn, self._lock)
        self.captures = CapturesDAO(self._conn, self._lock)
        if self._backups:
            try:
                self.backup_daily()
            except Exception:  # noqa: BLE001
                log.warning("일일 백업 실패 (앱은 계속 실행)", exc_info=True)
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
        self._migrate()
        self._changes_at_open = conn.total_changes

    def _migrate(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(ddl)
            _add_missing_columns(self._conn, "patients",
                                 {"diagnosis": "TEXT", "doctor": "TEXT"})
            self._conn.commit()

    def _close_quietly(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    # ---------------- 손상 복구 ----------------
    def _quarantine(self) -> str | None:
        """손상된 DB(와 -wal/-shm)를 지우지 않고 옆으로 치운다. 치운 경로를 돌려준다."""
        p = Path(self.db_path)
        if not p.exists():
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = p.with_name(f"{p.name}.corrupt-{stamp}")
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
        stem = Path(self.db_path).stem
        return sorted(d.glob(f"{stem}-*.db"), key=lambda f: f.stat().st_mtime)

    def _restore_latest_backup(self) -> str | None:
        """가장 최근 백업 중 quick_check 를 통과하는 것을 DB 자리로 복사한다."""
        for b in reversed(self.list_backups()):
            if _is_healthy(b):
                import shutil
                shutil.copy2(b, self.db_path)
                log.warning("백업에서 DB 를 복원했습니다: %s", b)
                return str(b)
        log.warning("복원할 백업이 없어 빈 DB 로 시작합니다")
        return None

    # ---------------- 백업 ----------------
    def backup(self, dest) -> Path:
        """사용 중에도 안전한 온라인 백업 (sqlite backup API). dest 경로의 파일을 만든다."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        dst = sqlite3.connect(str(tmp))
        try:
            with self._lock:
                if self._conn.in_transaction:        # 열린 트랜잭션이 있으면 backup 이 영원히 대기한다
                    self._conn.rollback()
                self._conn.backup(dst)
        finally:
            dst.close()
        tmp.replace(dest)
        return dest

    def backup_daily(self, keep: int = BACKUP_KEEP, refresh: bool = False) -> Path | None:
        """오늘 백업이 없으면 만들고(refresh=True 면 다시 만들고), 오래된 백업은 keep 개만 남기고 지운다."""
        stem = Path(self.db_path).stem
        dest = self.backup_dir() / f"{stem}-{time.strftime('%Y%m%d')}.db"
        made = None
        if refresh or not dest.exists():
            made = self.backup(dest)
            log.info("DB 백업: %s", dest)
        olds = self.list_backups()
        for f in olds[:-keep] if keep > 0 else []:
            try:
                f.unlink()
            except OSError:
                pass
        return made

    # ---------------- 닫기 ----------------
    def close(self) -> None:
        if self._conn is not None:
            if self._backups and self._conn.total_changes > self._changes_at_open:
                try:
                    self.backup_daily(refresh=True)      # 오늘 기록까지 백업에 담는다 (종료 때)
                except Exception:  # noqa: BLE001
                    log.warning("종료 백업 실패", exc_info=True)
            with self._lock:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                self._conn.close()
                self._conn = None


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
