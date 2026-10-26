"""검사 기록 API (/api/v1/patients/{pid}/exams) — 촬영일별 요약 + 소견."""
from __future__ import annotations

import re
from typing import List

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import ExamNoteIn, ExamOut

router = APIRouter(prefix="/api/v1/patients/{pid}/exams", tags=["exams"])
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _db(request: Request):
    return request.app.state.db


def _patient(request: Request, pid: int) -> dict:
    p = _db(request).get_patient(pid)
    if not p:
        raise HTTPException(status_code=404, detail="환자를 찾을 수 없습니다.")
    return p


@router.get("", response_model=List[ExamOut])
def list_exams(request: Request, pid: int):
    _patient(request, pid)
    return _db(request).list_exams(pid)


@router.put("/{day}", response_model=ExamOut)
def save_exam_note(request: Request, pid: int, day: str, body: ExamNoteIn):
    _patient(request, pid)
    if not _DAY.match(day):
        raise HTTPException(status_code=400, detail="날짜는 YYYY-MM-DD 형식이어야 합니다.")
    db = _db(request)
    db.upsert_exam_note(pid, day, body.exam_type, body.notes)
    for row in db.list_exams(pid):
        if row["exam_date"] == day:
            return row
    raise HTTPException(status_code=500, detail="저장 결과를 읽지 못했습니다.")
