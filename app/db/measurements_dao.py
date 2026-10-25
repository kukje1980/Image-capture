"""측정 기록 (혼탁 지수·형광 면적 등) — 영상별 측정값 + 의사 입력(LOCS III 등급) 저장.

경과 그래프와 나중의 등급 추정 모델 학습 데이터(의사 라벨)가 여기에 쌓인다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Measurement:
    id: Optional[int] = None
    patient_id: int = 0
    capture_id: Optional[int] = None
    eye: Optional[str] = None            # 'OD' | 'OS' | 'OU' | 'NA'
    kind: str = ""                       # nuclear | cortical | fluorescein | redness
    value: float = 0.0                   # 지수 (0~100) 또는 면적 %
    detail: dict = field(default_factory=dict)   # 비율·밝기·동공 직경·촬영 조건 등
    locs: dict = field(default_factory=dict)     # 의사 입력 LOCS III {"NO":..,"NC":..,"C":..,"P":..} (1~6, 없으면 생략)
    conditions: str = ""                 # 촬영 조건 메모 (슬릿 폭·각도·배율·노출)
    measured_at: str = ""                # 'YYYY-MM-DD HH:MM:SS'


class MeasurementsDAO:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._c = conn
        self._lock = lock

    def insert(self, m: Measurement) -> int:
        if not m.measured_at:
            m.measured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._c.execute(
                """INSERT INTO measurements
                   (patient_id, capture_id, eye, kind, value, detail, locs, conditions, measured_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (m.patient_id, m.capture_id, m.eye, m.kind, float(m.value),
                 json.dumps(m.detail, ensure_ascii=False), json.dumps(m.locs, ensure_ascii=False),
                 m.conditions or "", m.measured_at),
            )
            self._c.commit()
            m.id = cur.lastrowid
            return m.id

    def list_by_patient(self, pid: int, kind: Optional[str] = None,
                        eye: Optional[str] = None) -> List[Measurement]:
        q = "SELECT * FROM measurements WHERE patient_id=?"
        args: list = [pid]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        if eye:
            q += " AND eye=?"
            args.append(eye)
        q += " ORDER BY measured_at ASC, id ASC"
        with self._lock:
            rows = self._c.execute(q, args).fetchall()
        return [self._row(r) for r in rows]

    def latest(self, pid: int, kind: str, eye: Optional[str] = None) -> Optional[Measurement]:
        items = self.list_by_patient(pid, kind, eye)
        return items[-1] if items else None

    def delete_by_capture(self, cid: int) -> None:
        with self._lock:
            self._c.execute("DELETE FROM measurements WHERE capture_id=?", (cid,))
            self._c.commit()

    @staticmethod
    def _row(r) -> Measurement:
        def js(v):
            try:
                return json.loads(v) if v else {}
            except (TypeError, ValueError):
                return {}
        return Measurement(id=r["id"], patient_id=r["patient_id"], capture_id=r["capture_id"], eye=r["eye"],
                           kind=r["kind"], value=float(r["value"] or 0.0), detail=js(r["detail"]),
                           locs=js(r["locs"]), conditions=r["conditions"] or "", measured_at=r["measured_at"])
