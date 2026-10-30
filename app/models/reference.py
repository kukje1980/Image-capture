from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReferenceImage:
    """질환별 참고 사진 (병원이 등록한 비교용 사진). 환자 정보와 연결되지 않는다."""
    id: Optional[int] = None
    disease: str = ""                    # assets/dx/library.json 의 질환 id
    file_path: str = ""
    caption: Optional[str] = None
    created_at: Optional[str] = None
