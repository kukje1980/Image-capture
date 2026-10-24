from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Capture:
    id: Optional[int] = None
    patient_id: int = 0
    media_type: str = "photo"            # 'photo' | 'video'
    file_path: str = ""                  # 기본 저장 경로
    export_path: Optional[str] = None    # 지정 폴더 복사본 (실패 시 None)
    thumbnail_path: Optional[str] = None
    captured_at: str = ""                # 'YYYY-MM-DD HH:MM:SS'
    eye: Optional[str] = None            # 'OD' | 'OS' | 'OU' | 'NA'
    duration_ms: Optional[int] = None    # 동영상만
    note: Optional[str] = None
