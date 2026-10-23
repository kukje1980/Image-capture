"""브랜드(화면 이름·로고·색) 설정.

같은 코드로 여러 브랜드 버전을 배포한다. 환경변수 SLITLAMP_BRAND 로 고른다.
    SLITLAMP_BRAND=keeler   → Keeler 전용 화면
    (없거나 default)         → 기본 슬릿램프 영상 시스템

브랜드별 파일은 static/brand/<키>/ 에 둔다.
    theme.css   색 테마 (app.css 의 색 변수를 덮어씀)
    logo.svg | logo.png         상단·로그인·보고서 로고 (없으면 글자 로고로 표시)
    logo-dark.svg | logo-dark.png  어두운 배경용 로고 (선택, 없으면 logo 사용)
"""
from __future__ import annotations

import os
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

BRANDS: dict[str, dict] = {
    "default": {
        "app_name": "슬릿램프 영상 시스템",
        "sub": "Slit Lamp Imaging",
        "badge": "Web",
        "wordmark": "",
        "report_title": "슬릿램프 영상 보고서",
        "theme_color": "#0b0e13",
    },
    "keeler": {
        "app_name": "Keeler 슬릿램프 영상 시스템",
        "sub": "Slit Lamp Imaging",
        "badge": "Keeler",
        "wordmark": "Keeler",
        "report_title": "Keeler 슬릿램프 영상 보고서",
        "theme_color": "#071a3d",
    },
}


def _find(key: str, stem: str) -> str | None:
    for ext in ("svg", "png", "webp", "jpg"):
        if (STATIC_DIR / "brand" / key / f"{stem}.{ext}").is_file():
            return f"/static/brand/{key}/{stem}.{ext}"
    return None


def get_brand(key: str | None = None) -> dict:
    key = (key if key is not None else os.environ.get("SLITLAMP_BRAND", "default")).strip().lower() or "default"
    if key not in BRANDS:
        key = "default"
    b = {"key": key, **BRANDS[key]}
    css = STATIC_DIR / "brand" / key / "theme.css"
    b["css"] = f"/static/brand/{key}/theme.css" if css.is_file() else None
    b["logo"] = _find(key, "logo")
    b["logo_dark"] = _find(key, "logo-dark") or b["logo"]
    b["favicon"] = _find(key, "favicon")
    return b


def public(b: dict) -> dict:
    """브라우저 스크립트에 넘길 항목만."""
    return {k: b[k] for k in ("key", "app_name", "report_title", "logo", "wordmark")}
