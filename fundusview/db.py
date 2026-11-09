"""SQLite store for patients, images, the import log and seen-file index.

A single connection shared across the GUI and importer threads, guarded by a
re-entrant lock (WAL mode keeps readers from blocking the writer).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import ExtractedMeta

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY,
    patient_id  TEXT NOT NULL UNIQUE,
    name        TEXT,
    birth_date  TEXT,
    sex         TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY,
    patient_ref   INTEGER REFERENCES patients(id) ON DELETE SET NULL,  -- NULL = 미분류
    exam_date     TEXT,
    exam_time     TEXT,
    laterality    TEXT,
    modality      TEXT,
    device        TEXT,
    profile       TEXT,
    fov_deg       REAL,
    fov_type      TEXT,            -- external (at the pupil) / internal (eye centre)
    projection    TEXT,
    file_path     TEXT NOT NULL,   -- stored file (library copy, or original when referenced)
    display_path  TEXT,            -- decoded viewable copy (DICOM -> PNG); NULL = file_path
    thumb_path    TEXT,
    original_path TEXT,
    sha256        TEXT NOT NULL UNIQUE,
    width         INTEGER,
    height        INTEGER,
    circle_cx     REAL,            -- fundus image circle (pixels)
    circle_cy     REAL,
    circle_r      REAL,
    disc_x        REAL,            -- optic disc estimate (pixels), may be NULL
    disc_y        REAL,
    meta_json     TEXT,
    note          TEXT,
    imported_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_images_patient ON images(patient_ref, exam_date);
CREATE TABLE IF NOT EXISTS seen_files (
    path      TEXT PRIMARY KEY,
    size      INTEGER,
    mtime     REAL,
    status    TEXT,        -- imported / duplicate / skipped / error
    image_id  INTEGER,
    message   TEXT,
    seen_at   TEXT
);
CREATE TABLE IF NOT EXISTS import_log (
    id       INTEGER PRIMARY KEY,
    at       TEXT NOT NULL,
    level    TEXT NOT NULL,  -- info / warn / error
    path     TEXT,
    message  TEXT
);
"""

IMAGE_COLUMNS = (
    "patient_ref", "exam_date", "exam_time", "laterality", "modality", "device",
    "profile", "fov_deg", "fov_type", "projection", "file_path", "display_path", "thumb_path",
    "original_path", "sha256", "width", "height", "circle_cx", "circle_cy",
    "circle_r", "disc_x", "disc_y", "meta_json", "note",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._lock:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA foreign_keys=ON")
            self._con.executescript(SCHEMA)
            self._con.commit()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def _exec(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._con.execute(sql, args)
            self._con.commit()
            return cur

    def _all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._con.execute(sql, args).fetchall()

    def _one(self, sql: str, args=()) -> sqlite3.Row | None:
        with self._lock:
            return self._con.execute(sql, args).fetchone()

    # -- patients ----------------------------------------------------------
    def upsert_patient(self, meta: ExtractedMeta) -> int:
        """Create the patient on first sight; fill blanks on later imports.

        Existing non-empty demographics are never overwritten by an import —
        a corrected name in the viewer must not be reverted by the next file.
        """
        with self._lock:
            row = self._one("SELECT * FROM patients WHERE patient_id = ?", (meta.patient_id,))
            if row is None:
                cur = self._exec(
                    "INSERT INTO patients (patient_id, name, birth_date, sex, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (meta.patient_id, meta.name, meta.birth_date, meta.sex, _now(), _now()),
                )
                return cur.lastrowid
            updates = {k: getattr(meta, k) for k in ("name", "birth_date", "sex")
                       if not row[k] and getattr(meta, k)}
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                self._exec(f"UPDATE patients SET {sets}, updated_at = ? WHERE id = ?",
                           (*updates.values(), _now(), row["id"]))
            return row["id"]

    def update_patient(self, ref: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items()
                   if k in ("patient_id", "name", "birth_date", "sex", "note")}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        self._exec(f"UPDATE patients SET {sets}, updated_at = ? WHERE id = ?",
                   (*allowed.values(), _now(), ref))

    def get_patient(self, ref: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM patients WHERE id = ?", (ref,))

    def find_patient(self, patient_id: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))

    def list_patients(self, search: str = "") -> list[sqlite3.Row]:
        sql = (
            "SELECT p.*, COUNT(i.id) AS n_images, MAX(i.exam_date) AS last_exam"
            " FROM patients p LEFT JOIN images i ON i.patient_ref = p.id"
        )
        args: tuple = ()
        if search:
            like = f"%{search}%"
            sql += " WHERE p.patient_id LIKE ? OR p.name LIKE ? OR p.birth_date LIKE ?"
            args = (like, like, like)
        sql += " GROUP BY p.id ORDER BY COALESCE(MAX(i.imported_at), p.updated_at) DESC"
        return self._all(sql, args)

    def delete_patient(self, ref: int) -> None:
        self._exec("DELETE FROM patients WHERE id = ?", (ref,))

    def merge_patients(self, from_ref: int, into_ref: int) -> None:
        """Move all images of ``from_ref`` to ``into_ref`` and drop ``from_ref``."""
        with self._lock:
            self._con.execute("UPDATE images SET patient_ref = ? WHERE patient_ref = ?", (into_ref, from_ref))
            self._con.execute("DELETE FROM patients WHERE id = ?", (from_ref,))
            self._con.commit()

    # -- images ------------------------------------------------------------
    def insert_image(self, **values) -> int:
        cols = [c for c in IMAGE_COLUMNS if c in values]
        if isinstance(values.get("meta_json"), dict):
            values["meta_json"] = json.dumps(values["meta_json"], ensure_ascii=False)
        sql = (f"INSERT INTO images ({', '.join(cols)}, imported_at)"
               f" VALUES ({', '.join('?' for _ in cols)}, ?)")
        return self._exec(sql, (*(values[c] for c in cols), _now())).lastrowid

    def update_image(self, image_id: int, **values) -> None:
        cols = [c for c in IMAGE_COLUMNS if c in values]
        if not cols:
            return
        if isinstance(values.get("meta_json"), dict):
            values["meta_json"] = json.dumps(values["meta_json"], ensure_ascii=False)
        sets = ", ".join(f"{c} = ?" for c in cols)
        self._exec(f"UPDATE images SET {sets} WHERE id = ?", (*(values[c] for c in cols), image_id))

    def get_image(self, image_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM images WHERE id = ?", (image_id,))

    def image_by_sha(self, sha256: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM images WHERE sha256 = ?", (sha256,))

    def images_for_patient(self, ref: int | None) -> list[sqlite3.Row]:
        """Images of a patient, newest exam first; ``None`` = unassigned (미분류)."""
        order = " ORDER BY exam_date DESC, exam_time DESC, laterality, id DESC"
        if ref is None:
            return self._all("SELECT * FROM images WHERE patient_ref IS NULL" + order)
        return self._all("SELECT * FROM images WHERE patient_ref = ?" + order, (ref,))

    def count_unassigned(self) -> int:
        return self._one("SELECT COUNT(*) FROM images WHERE patient_ref IS NULL")[0]

    def delete_image(self, image_id: int) -> None:
        self._exec("DELETE FROM images WHERE id = ?", (image_id,))

    # -- seen-file index (so restarts / rescans skip finished files) ------
    def seen(self, path: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM seen_files WHERE path = ?", (path,))

    def seen_index(self) -> dict[str, tuple[int, float]]:
        """``path -> (size, mtime)`` of files already handled; failed files are
        left out so each start retries them once."""
        return {r["path"]: (r["size"], r["mtime"])
                for r in self._all("SELECT path, size, mtime FROM seen_files WHERE status != 'error'")}

    def mark_seen(self, path: str, size: int, mtime: float, status: str,
                  image_id: int | None = None, message: str = "") -> None:
        self._exec(
            "INSERT INTO seen_files (path, size, mtime, status, image_id, message, seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,"
            " status=excluded.status, image_id=excluded.image_id, message=excluded.message,"
            " seen_at=excluded.seen_at",
            (path, size, mtime, status, image_id, message, _now()),
        )

    # -- log ---------------------------------------------------------------
    def log(self, level: str, message: str, path: str = "") -> None:
        self._exec("INSERT INTO import_log (at, level, path, message) VALUES (?, ?, ?, ?)",
                   (_now(), level, path, message))

    def recent_logs(self, limit: int = 200) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM import_log ORDER BY id DESC LIMIT ?", (limit,))
