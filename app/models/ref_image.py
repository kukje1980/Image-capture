from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RefImage:
    id: Optional[int] = None
    file_path: str = ""
    thumbnail_path: Optional[str] = None
    category: Optional[str] = None       # 분류 (각막·수정체 등)
    title: Optional[str] = None
    description: Optional[str] = None
    source_capture_id: Optional[int] = None
    created_at: Optional[str] = None
