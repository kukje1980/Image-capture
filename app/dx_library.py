"""질환별 참고 사진 라이브러리 — assets/dx/library.json (웹의 web/static/dx/library.json 과 같은 파일).

각 질환: id · name · short(아이콘 밑 짧은 이름) · en · icon(아이콘 이름) · summary · findings(세극등 소견)
· explain(환자 설명) · compare(비교 포인트) · illustrations([{file, caption}] 모식도 SVG).
모식도는 소견 위치를 설명하는 그림이며 실제 사진이 아니다. 실제 사례 사진은 병원이 직접 등록한다
(app/services/reference_service.py).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app import brand


def dx_dir() -> Path:
    return brand.assets_dir() / "dx"


@lru_cache(maxsize=1)
def load() -> dict:
    p = dx_dir() / "library.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 0, "notice": "", "diseases": []}
    data.setdefault("diseases", [])
    data.setdefault("notice", "")
    return data


def diseases() -> list[dict]:
    return list(load()["diseases"])


def get(disease_id: str) -> dict | None:
    return next((d for d in load()["diseases"] if d["id"] == disease_id), None)


def notice() -> str:
    return load().get("notice", "")


def illustration_path(file: str) -> str | None:
    """모식도 파일의 절대 경로 (없으면 None)."""
    if not file or "/" in file or "\\" in file or file.startswith("."):
        return None
    p = dx_dir() / file
    return str(p) if p.is_file() else None
