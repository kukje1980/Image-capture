from __future__ import annotations

import sqlite3
import threading
from typing import List, Optional

from app.models.capture import Capture


class CapturesDAO:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._c = conn
        self._lock = lock

    def insert(self, cap: Capture) -> int:
        with self._lock:
            cur = self._c.execute(
                """INSERT INTO captures
                   (patient_id, media_type, file_path, export_path, thumbnail_path,
                    captured_at, eye, duration_ms, note)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (cap.patient_id, cap.media_type, cap.file_path, cap.export_path,
                 cap.thumbnail_path, cap.captured_at, cap.eye, cap.duration_ms, cap.note),
            )
            self._c.commit()
            return cur.lastrowid

    def list_by_patient(self, pid: int, order: str = "desc") -> List[Capture]:
        o = "DESC" if order.lower() == "desc" else "ASC"
        with self._lock:
            rows = self._c.execute(
                f"""SELECT * FROM captures WHERE patient_id=?
                    ORDER BY captured_at {o}, id {o}""",
                (pid,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, cid: int) -> Optional[Capture]:
        with self._lock:
            r = self._c.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone()
        return self._row(r)

    def update_note(self, cid: int, note: Optional[str]) -> None:
        """영상별 코멘트 수정 (Pro 모드 Edit Data)."""
        with self._lock:
            self._c.execute("UPDATE captures SET note=? WHERE id=?", (note, cid))
            self._c.commit()

    def update_export_path(self, cid: int, export_path: Optional[str]) -> None:
        """목록에서 '보내기'로 전송 폴더에 복사한 뒤 복사본 경로를 기록한다."""
        with self._lock:
            self._c.execute("UPDATE captures SET export_path=? WHERE id=?", (export_path, cid))
            self._c.commit()

    def delete(self, cid: int) -> Optional[dict]:
        """레코드를 지우고, 디스크 정리를 위해 관련 경로를 반환한다."""
        with self._lock:
            r = self._c.execute(
                "SELECT file_path, export_path, thumbnail_path FROM captures WHERE id=?",
                (cid,),
            ).fetchone()
            self._c.execute("DELETE FROM captures WHERE id=?", (cid,))
            self._c.commit()
        return dict(r) if r is not None else None

    @staticmethod
    def _row(r) -> Optional[Capture]:
        if r is None:
            return None
        return Capture(**{k: r[k] for k in r.keys()})
