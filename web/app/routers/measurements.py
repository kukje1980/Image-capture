"""측정 기록 API (/api/v1/measurements) — 수정체 혼탁 지수 등 측정값 · 촬영 조건 · LOCS III 의사 입력.

측정 자체는 브라우저(static/js/smartcv.js)가 하고, 서버는 기록·조회만 한다 (경과 그래프용).
'이 PC에만 저장' 모드에서는 같은 요청을 localstore.js 가 브라우저 저장소에서 처리한다.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from app import config
from app.models.schemas import MeasurementIn, MeasurementOut

router = APIRouter(prefix="/api/v1/measurements", tags=["measurements"])
KINDS = {"nuclear", "cortical", "fluorescein", "redness"}
LOCS_KEYS = {"NO", "NC", "C", "P"}


def _db(request: Request):
    return request.app.state.db


@router.get("", response_model=List[MeasurementOut])
def list_measurements(request: Request, patient_id: int, kind: Optional[str] = None, eye: Optional[str] = None):
    return _db(request).list_measurements(patient_id, kind or None, eye or None)


@router.post("", response_model=MeasurementOut, status_code=201)
def create_measurement(request: Request, body: MeasurementIn):
    db = _db(request)
    if not db.get_patient(body.patient_id):
        raise HTTPException(status_code=404, detail="환자를 찾을 수 없습니다.")
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"알 수 없는 측정 종류입니다: {body.kind}")
    if body.capture_id is not None:
        cap = db.get_capture(body.capture_id)
        if not cap or cap["patient_id"] != body.patient_id:
            raise HTTPException(status_code=400, detail="영상이 이 환자의 것이 아닙니다.")
    locs = {}
    for k, v in (body.locs or {}).items():                 # LOCS III: 항목별 1~6 (소수 0.1 단위 허용)
        if k not in LOCS_KEYS:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if 0.1 <= f <= 6.9:
            locs[k] = f
    data = body.model_dump()
    data.update(locs=locs, eye=body.eye if body.eye in ("OD", "OS", "OU", "NA") else "NA",
                value=max(0.0, min(100.0, float(body.value))),
                measured_at=config.now().strftime("%Y-%m-%d %H:%M:%S"))
    return db.get_measurement(db.create_measurement(data))


@router.delete("/{mid}", status_code=204)
def delete_measurement(request: Request, mid: int):
    db = _db(request)
    if not db.get_measurement(mid):
        raise HTTPException(status_code=404, detail="측정 기록을 찾을 수 없습니다.")
    db.delete_measurement(mid)
