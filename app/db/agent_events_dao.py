"""agent_events 테이블 — 에이전트 사용 이벤트 (익명 세션). 학습 라벨과 사용성 분석의 원천."""
from __future__ import annotations

import json
from typing import List, Optional


class AgentEventsDAO:
    def __init__(self, conn, lock):
        self._conn = conn
        self._lock = lock

    def insert(self, ev: dict) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO agent_events(session_id, ts, type, capture_id, payload) "
                "VALUES (?,?,?,?,?)",
                (ev.get("session"), ev.get("ts"), ev.get("type"), ev.get("capture_id"),
                 json.dumps(ev.get("data", {}), ensure_ascii=False)))
            return int(cur.lastrowid)

    def for_capture(self, capture_id: int) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_events WHERE capture_id=? ORDER BY id", (capture_id,)).fetchall()
        return [self._row(r) for r in rows]

    def recent(self, limit: int = 200, type_: Optional[str] = None) -> List[dict]:
        if type_:
            rows = self._conn.execute(
                "SELECT * FROM agent_events WHERE type=? ORDER BY id DESC LIMIT ?",
                (type_, limit)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM agent_events ORDER BY id DESC LIMIT ?",
                                      (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def labels_by_capture(self) -> dict:
        """캡처 ID → 장면 라벨 (마지막 기록 우선: 의사가 확정한 라벨이 자동 라벨을 덮는다)."""
        out: dict = {}
        rows = self._conn.execute(
            "SELECT capture_id, type, payload FROM agent_events "
            "WHERE capture_id IS NOT NULL ORDER BY id").fetchall()
        for r in rows:
            try:
                data = json.loads(r["payload"] or "{}")
            except ValueError:
                continue
            label = data.get("scene_label") or (data.get("scene") or {}).get("label")
            if label:
                out[int(r["capture_id"])] = {"label": label, "type": r["type"], "data": data}
        return out

    @staticmethod
    def _row(r) -> dict:
        try:
            data = json.loads(r["payload"] or "{}")
        except ValueError:
            data = {}
        return {"id": r["id"], "session": r["session_id"], "ts": r["ts"], "type": r["type"],
                "capture_id": r["capture_id"], "data": data}
