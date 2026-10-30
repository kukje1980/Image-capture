from __future__ import annotations

import sqlite3
import threading
from typing import List, Optional

from app.models.reference import ReferenceImage


class ReferencesDAO:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._c = conn
        self._lock = lock

    def insert(self, ref: ReferenceImage) -> int:
        with self._lock:
            cur = self._c.execute(
                "INSERT INTO reference_images (disease, file_path, caption, created_at) VALUES (?,?,?,?)",
                (ref.disease, ref.file_path, ref.caption, ref.created_at),
            )
            self._c.commit()
            return cur.lastrowid

    def list_by_disease(self, disease: str) -> List[ReferenceImage]:
        with self._lock:
            rows = self._c.execute(
                "SELECT * FROM reference_images WHERE disease=? ORDER BY created_at, id", (disease,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, rid: int) -> Optional[ReferenceImage]:
        with self._lock:
            r = self._c.execute("SELECT * FROM reference_images WHERE id=?", (rid,)).fetchone()
        return self._row(r)

    def delete(self, rid: int) -> Optional[dict]:
        with self._lock:
            r = self._c.execute("SELECT file_path FROM reference_images WHERE id=?", (rid,)).fetchone()
            self._c.execute("DELETE FROM reference_images WHERE id=?", (rid,))
            self._c.commit()
        return dict(r) if r is not None else None

    @staticmethod
    def _row(r) -> Optional[ReferenceImage]:
        if r is None:
            return None
        return ReferenceImage(**{k: r[k] for k in r.keys()})
