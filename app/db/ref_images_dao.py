"""참조 영상 라이브러리 — 질환별 대표 영상을 분류해 두고 환자 영상과 나란히 비교한다."""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from app.models.ref_image import RefImage


class RefImagesDAO:
    def __init__(self, conn: sqlite3.Connection, lock):
        self._c = conn
        self._lock = lock

    def insert(self, r: RefImage) -> int:
        with self._lock, self._c:
            cur = self._c.execute(
                """INSERT INTO ref_images
                   (file_path, thumbnail_path, category, title, description, source_capture_id)
                   VALUES (?,?,?,?,?,?)""",
                (r.file_path, r.thumbnail_path, r.category, r.title, r.description, r.source_capture_id),
            )
            return cur.lastrowid

    def update(self, r: RefImage) -> None:
        with self._lock, self._c:
            self._c.execute(
                "UPDATE ref_images SET category=?, title=?, description=? WHERE id=?",
                (r.category, r.title, r.description, r.id),
            )

    def get(self, rid: int) -> Optional[RefImage]:
        with self._lock:
            r = self._c.execute("SELECT * FROM ref_images WHERE id=?", (rid,)).fetchone()
        return self._row(r)

    def list(self, category: Optional[str] = None, q: str = "") -> List[RefImage]:
        sql, args = "SELECT * FROM ref_images WHERE 1=1", []
        if category:
            sql += " AND category=?"
            args.append(category)
        if q:
            like = f"%{q}%"
            sql += " AND (title LIKE ? OR description LIKE ? OR category LIKE ?)"
            args += [like, like, like]
        sql += " ORDER BY category, created_at DESC, id DESC"
        with self._lock:
            rows = self._c.execute(sql, args).fetchall()
        return [self._row(r) for r in rows]

    def categories(self) -> List[str]:
        with self._lock:
            rows = self._c.execute(
                "SELECT DISTINCT category FROM ref_images WHERE category IS NOT NULL AND category<>'' "
                "ORDER BY category"
            ).fetchall()
        return [r[0] for r in rows]

    def delete(self, rid: int) -> Optional[dict]:
        with self._lock, self._c:
            r = self._c.execute("SELECT file_path, thumbnail_path FROM ref_images WHERE id=?", (rid,)).fetchone()
            self._c.execute("DELETE FROM ref_images WHERE id=?", (rid,))
        return dict(r) if r is not None else None

    @staticmethod
    def _row(r) -> Optional[RefImage]:
        if r is None:
            return None
        return RefImage(**{k: r[k] for k in r.keys()})
