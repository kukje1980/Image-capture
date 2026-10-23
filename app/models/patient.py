from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Patient:
    id: Optional[int] = None
    chart_no: Optional[str] = None       # 차트번호
    patient_id: Optional[str] = None     # 환자ID(선택)
    name: str = ""
    birth_date: Optional[str] = None     # 'YYYY-MM-DD'
    sex: Optional[str] = None            # 'M' | 'F' | 'O'
    phone: Optional[str] = None
    memo: Optional[str] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None      # 진단명
    doctor: Optional[str] = None         # 담당의
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
