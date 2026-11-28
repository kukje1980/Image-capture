"""데이터베이스 관리: backups of the library's database, its check-up, and going back to a backup.

The library is a folder of photo files and one SQLite file (``fundus.db``: the patients, which photo is
whose, where the disc and the macula are …). The photo files can be imported again; what is written in
the database by hand (환자 지정, 직접 지정한 유두 · 황반, 메모) cannot. So:

* **backup** — a copy of the database made with SQLite's own backup (safe while the program works),
  into ``<library>/backups/fundus-YYYYMMDD-HHMMSS.db``. One is made by itself the first time the program
  starts on a day (``auto_backup``); the newest ``KEEP`` are kept.
* **check** — is the file sound (``PRAGMA integrity_check``), are there rows pointing at a patient that
  is gone, and are the photo files of the rows still on the disk.
* **restore** — put a backup in the place of the database. The database of now is kept beside it
  (``fundus.db.before-restore-날짜``), never deleted. Done with the database closed: the program starts
  again afterwards.

No Qt in here (``ui/dbadmin_dialog.py`` is the window).
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

KEEP = 14                      # backups kept (the newest)
BACKUP_DIR = "backups"
PREFIX, SUFFIX = "fundus-", ".db"


@dataclass
class Backup:
    path: Path
    when: float                # its time (the file's)
    size: int
    patients: int | None = None   # counted when asked for (``describe``)
    images: int | None = None

    @property
    def label(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.when))


@dataclass
class Report:
    ok: bool = True                              # the file is sound and nothing below is wrong
    integrity: str = "ok"                        # what SQLite says ("ok", or the first lines of what is wrong)
    patients: int = 0
    images: int = 0
    unassigned: int = 0
    orphans: int = 0                             # photos of a patient that is no longer there
    missing: list[str] = field(default_factory=list)   # photo files of rows that are not on the disk
    checked_files: int = 0
    size: int = 0                                # of the database file, bytes

    def lines(self) -> list[str]:
        out = [f"데이터베이스 파일: {'이상 없음' if self.integrity == 'ok' else '손상됨 — ' + self.integrity}",
               f"환자 {self.patients}명 · 사진 {self.images}장 (미분류 {self.unassigned}장)"]
        if self.orphans:
            out.append(f"없는 환자를 가리키는 사진 {self.orphans}장 (미분류로 보입니다)")
        if self.missing:
            out.append(f"사진 파일이 없는 항목 {len(self.missing)}개 (확인한 {self.checked_files}개 중) — "
                       "파일을 옮기거나 지웠다면 그 사진은 열리지 않습니다")
        elif self.checked_files:
            out.append(f"사진 파일 {self.checked_files}개 모두 제자리에 있습니다")
        return out


def backup_dir(library: Path) -> Path:
    return Path(library) / BACKUP_DIR


def list_backups(library: Path) -> list[Backup]:
    """The backups of the library, the newest first."""
    out = []
    try:
        files = list(backup_dir(library).glob(f"{PREFIX}*{SUFFIX}"))
    except OSError:
        return []
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        out.append(Backup(p, st.st_mtime, st.st_size))
    return sorted(out, key=lambda b: b.when, reverse=True)


def describe(backup: Backup) -> Backup:
    """How many patients and photos the backup holds (None each: it cannot be read)."""
    try:
        con = sqlite3.connect(f"file:{backup.path.as_posix()}?mode=ro", uri=True)
        try:
            backup.patients = con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
            backup.images = con.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        backup.patients = backup.images = None
    return backup


def sound(path: Path) -> bool:
    """Is the file at ``path`` a database SQLite calls sound, with this program's tables in it?"""
    try:
        con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            con.execute("SELECT COUNT(*) FROM patients").fetchone()
            con.execute("SELECT COUNT(*) FROM images").fetchone()
            return ok
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return False


def backup(db, library: Path, keep: int = KEEP) -> Backup:
    """A backup of the open database ``db`` now. Raises OSError / sqlite3.Error when it cannot be made
    (the half-written file is taken away). The oldest beyond ``keep`` are removed."""
    folder = backup_dir(library)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{PREFIX}{time.strftime('%Y%m%d-%H%M%S')}{SUFFIX}"
    n = 1
    while dest.exists():                         # (two in one second)
        n += 1
        dest = folder / f"{PREFIX}{time.strftime('%Y%m%d-%H%M%S')}-{n}{SUFFIX}"
    part = dest.with_name(dest.name + ".part")
    try:
        db.backup_to(part)
        if not sound(part):
            raise sqlite3.DatabaseError("백업 파일을 확인하지 못했습니다")
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    st = dest.stat()
    prune(library, keep, spare=dest)
    return Backup(dest, st.st_mtime, st.st_size)


def prune(library: Path, keep: int = KEEP, spare: Path | None = None) -> int:
    """Only the newest ``keep`` backups stay (and ``spare``, the one just made — whatever the clock of
    the older files says). How many were removed."""
    gone = 0
    for old in list_backups(library)[max(1, int(keep)):]:
        if spare is not None and old.path == spare:
            continue
        try:
            old.path.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def auto_backup(db, library: Path, keep: int = KEEP) -> Backup | None:
    """The day's first start: a backup, unless there is one of today or the database is empty. Never
    raises (a full disk must not keep the program from starting): None when none was made."""
    try:
        if db.count_patients() == 0 and db.count_unassigned() == 0:
            return None
        newest = next(iter(list_backups(library)), None)
        today = time.strftime("%Y%m%d")
        if newest is not None and time.strftime("%Y%m%d", time.localtime(newest.when)) == today:
            return None
        return backup(db, library, keep)
    except Exception:
        return None


def check(db, files: bool = True, limit: int = 20000) -> Report:
    """The check-up of the open database (and, with ``files``, whether the photo files of up to
    ``limit`` rows are on the disk)."""
    rep = Report()
    try:
        rep.size = Path(db.path).stat().st_size
    except OSError:
        rep.size = 0
    try:
        rows = db._all("PRAGMA integrity_check")
        said = [str(r[0]) for r in rows]
        rep.integrity = "ok" if said == ["ok"] else "; ".join(said[:3]) or "확인하지 못함"
        rep.patients = db.count_patients()
        rep.images = db._one("SELECT COUNT(*) AS n FROM images")["n"]
        rep.unassigned = db.count_unassigned()
        rep.orphans = db._one("SELECT COUNT(*) AS n FROM images WHERE patient_ref IS NOT NULL AND "
                              "patient_ref NOT IN (SELECT id FROM patients)")["n"]
        if files:
            for r in db._all("SELECT file_path FROM images ORDER BY id DESC LIMIT ?", (int(limit),)):
                rep.checked_files += 1
                p = r["file_path"]
                try:
                    if not p or not os.path.isfile(p):
                        rep.missing.append(p or "")
                except OSError:
                    rep.missing.append(p or "")
    except sqlite3.Error as exc:
        rep.integrity = str(exc)
    rep.ok = rep.integrity == "ok" and not rep.orphans and not rep.missing
    return rep


def restore(db_path: Path, backup_path: Path) -> Path:
    """Put the backup in the place of the database at ``db_path`` — which must be closed. The database of
    now is kept beside it (returned). Raises ValueError for a backup that is not sound, OSError when the
    files cannot be moved (then nothing is changed)."""
    db_path, backup_path = Path(db_path), Path(backup_path)
    if not sound(backup_path):
        raise ValueError("이 백업 파일은 읽을 수 없습니다 (손상되었거나 이 프로그램의 파일이 아님)")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    kept = db_path.with_name(f"{db_path.name}.before-restore-{stamp}")
    new = db_path.with_name(db_path.name + ".restoring")
    # a copy first (the backup itself stays where it is), by SQLite: a whole, checkpointed file
    src = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(new))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    moved = []
    try:
        for tail in ("", "-wal", "-shm"):
            part = db_path.with_name(db_path.name + tail)
            if part.exists():
                to = kept.with_name(kept.name + tail)
                os.replace(part, to)
                moved.append((to, part))
        os.replace(new, db_path)
    except OSError:
        for to, part in reversed(moved):         # as it was
            try:
                os.replace(to, part)
            except OSError:
                pass
        try:
            new.unlink()
        except OSError:
            pass
        raise
    return kept


# -- going back to a backup from the running program: asked for now, done at the next start ---------------
PENDING = "restore-pending.txt"


def request_restore(library: Path, backup_path: Path) -> None:
    """Remember to put ``backup_path`` in the database's place at the next start (the database is open
    now). Raises ValueError for a backup that cannot be read."""
    if not sound(backup_path):
        raise ValueError("이 백업 파일은 읽을 수 없습니다 (손상되었거나 이 프로그램의 파일이 아님)")
    folder = backup_dir(library)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / PENDING).write_text(str(Path(backup_path).resolve()), encoding="utf-8")


def pending_restore(library: Path) -> Path | None:
    try:
        text = (backup_dir(library) / PENDING).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(text) if text else None


def cancel_restore(library: Path) -> None:
    try:
        (backup_dir(library) / PENDING).unlink()
    except OSError:
        pass


def apply_pending(library: Path, db_path: Path) -> tuple[Path | None, str]:
    """At the start, before the database is opened: the restore asked for, once. ``(kept, "")`` when done
    (``kept``: the database as it was), ``(None, "")`` when none was asked for, ``(None, why)`` when it
    could not be done (the database is as it was). The request is forgotten either way."""
    wanted = pending_restore(library)
    if wanted is None:
        return None, ""
    cancel_restore(library)
    try:
        return restore(db_path, wanted), ""
    except (ValueError, OSError, sqlite3.Error) as exc:
        return None, str(exc)
