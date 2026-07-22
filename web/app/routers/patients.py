"""환자 CRUD API (/api/v1/patients)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import PatientIn, PatientOut

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


def _db(request: Request):
    return request.app.state.db


@router.get("", response_model=List[PatientOut])
def list_patients(request: Request, q: str = ""):
    return _db(request).list_patients(q)


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(request: Request, patient: PatientIn):
    db = _db(request)
    data = patient.model_dump()
    try:
        pid = db.create_patient(data)
    except Exception as e:  # UNIQUE 위반 등
        raise HTTPException(status_code=400, detail=f"저장 실패(차트번호 중복 여부 확인): {e}")
    return db.get_patient(pid)


@router.get("/{pid}", response_model=PatientOut)
def get_patient(request: Request, pid: int):
    p = _db(request).get_patient(pid)
    if not p:
        raise HTTPException(status_code=404, detail="환자를 찾을 수 없습니다.")
    return p


@router.put("/{pid}", response_model=PatientOut)
def update_patient(request: Request, pid: int, patient: PatientIn):
    db = _db(request)
    if not db.get_patient(pid):
        raise HTTPException(status_code=404, detail="환자를 찾을 수 없습니다.")
    try:
        db.update_patient(pid, patient.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"수정 실패: {e}")
    return db.get_patient(pid)


@router.delete("/{pid}", status_code=204)
def delete_patient(request: Request, pid: int):
    _db(request).delete_patient(pid)
