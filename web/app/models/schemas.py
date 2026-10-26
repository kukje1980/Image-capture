"""요청/응답 Pydantic 스키마."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PatientIn(BaseModel):
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


class MeasurementIn(BaseModel):
    patient_id: int
    capture_id: Optional[int] = None
    eye: Optional[str] = None
    kind: str = Field(min_length=1, max_length=32)
    value: float
    detail: dict = Field(default_factory=dict)
    locs: dict = Field(default_factory=dict)
    conditions: str = Field(default="", max_length=300)


class MeasurementOut(MeasurementIn):
    id: int
    measured_at: str


class RefOut(BaseModel):
    id: int
    region: str
    condition: str
    disease: Optional[str] = None
    note: Optional[str] = None
    url: str
    created_at: str


class CaptureOut(BaseModel):
    id: int
    patient_id: int
    media_type: str
    url: str
    captured_at: str
    eye: Optional[str] = None
    duration_ms: Optional[int] = None
    note: Optional[str] = None


class ExamNoteIn(BaseModel):
    exam_type: Optional[str] = None
    notes: Optional[str] = None


class ExamOut(BaseModel):
    exam_date: str
    count: int = 0
    od: int = 0
    os: int = 0
    ou: int = 0
    video: int = 0
    first_time: Optional[str] = None
    last_time: Optional[str] = None
    exam_type: Optional[str] = None
    notes: Optional[str] = None
    updated_at: Optional[str] = None
