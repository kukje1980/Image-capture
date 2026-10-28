"""요청/응답 Pydantic 스키마."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PatientIn(BaseModel):
    # 앞뒤 공백 제거 — ' C001' 과 'C001' 은 화면에서 같아 보이므로 다른 환자로 등록되면 안 된다
    model_config = ConfigDict(str_strip_whitespace=True)

    chart_no: str = Field(min_length=1)
    name: str = Field(min_length=1)
    patient_id: Optional[str] = None
    birth_date: Optional[str] = None
    sex: Optional[str] = None
    phone: Optional[str] = None
    memo: Optional[str] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    doctor: Optional[str] = None


class PatientOut(PatientIn):
    id: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CaptureNoteIn(BaseModel):
    note: Optional[str] = None


class CaptureOut(BaseModel):
    id: int
    patient_id: int
    media_type: str
    url: str
    captured_at: str
    eye: Optional[str] = None
    duration_ms: Optional[int] = None
    note: Optional[str] = None
