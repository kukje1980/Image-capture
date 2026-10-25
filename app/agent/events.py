"""사용 이벤트 로그 — 의사가 프로그램을 어떻게 쓰는지 (무엇을 찍고, 무엇을 버리고, 얼마나 걸리는지).

- 환자 식별 정보는 쓰지 않는다. 세션 ID(무작위)·캡처 ID·장면·품질 수치·시각만 남긴다.
- 파일: <앱데이터>/agent/events/YYYY-MM-DD.jsonl (한 줄 = 한 이벤트, JSON)
- DB: agent_events 테이블(있으면) 에도 같은 내용
  — 학습 데이터 내보내기(dataset.py) 가 캡처와 합친다.
- 설정 agent_logging 이 꺼져 있으면 아무것도 쓰지 않는다.

이벤트 종류 (type)
    session_start/end, capture(manual), auto_capture, candidate_shown/accepted/rejected,
    clip_saved, freeze, pause, record_start/stop, delete, scene_changed, checklist_item, settings
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Optional

log = logging.getLogger(__name__)


class EventLog:
    def __init__(self, root: Path, db=None, enabled: bool = True, tail: int = 200):
        self.root = Path(root)
        self.db = db
        self.enabled = enabled
        self.session_id = uuid.uuid4().hex[:12]
        self.tail: Deque[dict] = deque(maxlen=tail)
        self._lock = threading.Lock()
        self._t0 = time.monotonic()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)

    def log(self, type_: str, capture_id: Optional[int] = None, **payload) -> Optional[dict]:
        ev = {"session": self.session_id, "ts": datetime.now().isoformat(timespec="milliseconds"),
              "t": round(time.monotonic() - self._t0, 3), "type": type_}
        if capture_id is not None:
            ev["capture_id"] = int(capture_id)
        if payload:
            ev["data"] = _jsonable(payload)
        with self._lock:
            self.tail.append(ev)
        if not self.enabled:
            return ev
        try:
            day = self.root / "events"
            day.mkdir(parents=True, exist_ok=True)
            with open(day / f"{datetime.now():%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError:
            log.warning("이벤트 로그 파일 쓰기 실패", exc_info=True)
        if self.db is not None:
            try:
                self.db.agent_events.insert(ev)
            except Exception:  # noqa: BLE001
                log.debug("이벤트 DB 기록 실패", exc_info=True)
        return ev

    def events_dir(self) -> Path:
        return self.root / "events"


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if hasattr(v, "__dataclass_fields__"):
            v = {f: getattr(v, f) for f in v.__dataclass_fields__ if not f.startswith("_")}
            ok = (int, float, str, bool, type(None), dict, list)
            v = {kk: vv for kk, vv in v.items() if isinstance(vv, ok)}
        elif isinstance(v, float):
            v = round(v, 4)
        elif not isinstance(v, (int, str, bool, type(None), dict, list)):
            v = str(v)
        out[k] = v
    return out
