from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Exam:
    id: Optional[int] = None
    patient_id: int = 0
    exam_date: str = ""                  # 'YYYY-MM-DD'
    title: Optional[str] = None          # 검사명
    diagnosis: Optional[str] = None      # 이번 검사의 진단·소견
    memo: Optional[str] = None           # 병력·메모
    created_at: Optional[str] = None
    n_captures: int = 0                  # 조회 시 채움 (DB 컬럼 아님)
