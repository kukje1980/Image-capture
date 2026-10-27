"""데스크탑 앱 브랜드(이름·로고·아이콘·색) 설정 — 웹의 web/app/brands.py 와 같은 구성.

브랜드 선택 우선순위
    1) 실행 옵션  --brand keeler   (--brand explorer = Explorer 판: 메뉴·툴바·환자/검사 트리 화면,
                                    --brand keeler_explorer = Keeler 로고·색의 Explorer 판)
    2) 환경변수  SLITLAMP_BRAND=keeler   (Keeler 전용 설치본은 빌드 때 이 값이 들어감)
    3) 설정 파일 config.json 의 "brand"
    4) 기본 (슬릿램프 영상 시스템)

UI 모듈이 처음 import 되기 전에 select() 로 정해야 아이콘 색 등이 반영된다 (app/__main__.py 참고).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_KEY = "SLITLAMP_BRAND"

BRANDS: dict[str, dict] = {
    "default": {
        "app_name": "슬릿램프 영상 시스템",
        "window_title": "슬릿램프 디지털 영상 시스템",
        "report_title": "슬릿램프 영상 보고서",
        "logo": None, "logo_dark": None, "icon": None,
        "logo_only": False,
        "palette": {},
    },
    # Explorer 판 — 같은 엔진에 메뉴바·툴바·환자 › 검사 트리 화면과 겹쳐보기·참조 영상·슬라이드쇼·
    # Word 보고서·카메라 속성을 더한 판 (app/ui/explorer). 기본판·Keeler 판과 나란히 설치된다.
    "explorer": {
        "app_name": "슬릿램프 영상 시스템 Explorer",
        "window_title": "슬릿램프 영상 시스템 Explorer",
        "report_title": "슬릿램프 영상 보고서",
        "logo": None, "logo_dark": None, "icon": "brand/explorer/app.png",
        "logo_only": False,
        "layout": "explorer",
        "icon_bg": "#1f6feb",
        "icon_accent": "#5aa2ff",
        "icon_on_accent": "#04162e",
        "report_rule": "#1f6feb",
        "palette": {
            "dark": {
                "bg": "#0a0e15", "panel": "#111722", "panel2": "#171f2d", "raised": "#1c2536",
                "rule": "#222c3c", "rule_strong": "#2e3a4e",
                "accent": "#4f9dff", "accent_hover": "#8cc0ff", "accent_ink": "#04162e", "accent_soft": "#142742",
                "field": "#0d121b",
            },
            "light": {
                "bg": "#eef2f8", "panel": "#ffffff", "panel2": "#f3f6fb", "raised": "#ffffff",
                "accent": "#1f6feb", "accent_hover": "#1858c4", "accent_ink": "#ffffff", "accent_soft": "#dbe8fd",
            },
        },
    },
    # Keeler 공식 홈페이지의 로고·브랜드 색 (assets/brand/keeler/SOURCE.md)
    "keeler": {
        "app_name": "Keeler 슬릿램프 영상 시스템",
        "window_title": "Keeler 슬릿램프 영상 시스템",
        "report_title": "Keeler 슬릿램프 영상 보고서",
        "logo": "brand/keeler/logo.svg",            # 밝은 화면용 (네이비 글자)
        "logo_dark": "brand/keeler/logo-dark.svg",  # 어두운 화면용 (흰 글자, 원본)
        "icon": "brand/keeler/app.png",
        "logo_only": True,                          # 상단에는 로고만 (프로그램 이름 숨김)
        "icon_accent": "#4aa8dc",
        "icon_on_accent": "#052133",
        "report_rule": "#052133",
        # 홈페이지처럼 머리(기본판 상단바 · Explorer 메뉴바·툴바)는 밝은/어두운 테마와 상관없이 Keeler 네이비 + 흰 글자 로고,
        # 아래 선과 셔터 링은 로고 마크의 하늘색·주황 (assets/brand/keeler/SOURCE.md 의 브랜드 색)
        "header": {"bg": "#052133", "hover": "#0e2c42", "rule": "#12334b", "line": "#1981b7",
                   "ink": "#ffffff", "ink_soft": "#cfe0ec", "disabled": "#4f6b80",
                   "accent": "#6cbce8", "active": "#12344a", "seg": "#0a2436"},
        "header_logo": "brand/keeler/logo-dark.svg",
        "shutter_ring": "rgba(237, 111, 30, 0.85)",
        # 로고 K 마크의 4색 — 하늘(위 곡선) · 파랑 · 네이비(세로획) · 주황(아래 곡선)
        "k_colors": ["#6cbce8", "#1981b7", "#052133", "#ed6f1e"],
        "stripe": True,                             # 상단바 아래 K 4색 줄무늬
        "eye_colors": {"OD": "#6cbce8", "OS": "#ed6f1e", "OU": "#1981b7"},   # 우안 = 하늘, 좌안 = 주황
        "home_image": "brand/keeler/home.png",      # 홈 화면 큰 사진: 장비만 떼어 낸 Keeler 슬릿램프 (없으면 그림)
        "palette": {
            "dark": {
                "bg": "#03131f", "panel": "#061c2c", "panel2": "#0a2436", "raised": "#0e2c42",
                "ink": "#e8f1f8", "ink_soft": "#a6bccd", "ink_muted": "#6c8599",
                "rule": "#12334b", "rule_strong": "#1b425f",
                "accent": "#6cbce8", "accent_hover": "#a9dbf5", "accent_ink": "#052133", "accent_soft": "#12344a",
                "field": "#041624", "disabled": "#2d4a60",
                "od": "#6cbce8", "os": "#ed6f1e", "ou": "#4aa8dc",
            },
            "light": {
                "bg": "#f1f8fd", "panel": "#ffffff", "panel2": "#f4f9fd", "raised": "#ffffff",
                "ink": "#052133", "ink_soft": "#3d5568", "ink_muted": "#7b8e9c",
                "rule": "#d3dde3", "rule_strong": "#bccbd6",
                "accent": "#1981b7", "accent_hover": "#0f6593", "accent_ink": "#ffffff", "accent_soft": "#cde1ef",
                "field": "#ffffff", "disabled": "#b7c6d1",
                "od": "#1981b7", "os": "#d9621a", "ou": "#0f6593",
            },
        },
    },
}

# Keeler Explorer 판 — Keeler 로고·색 그대로 + Explorer 화면 (메뉴·툴바·환자/검사 트리·겹쳐보기·참조 영상 …)
BRANDS["keeler_explorer"] = {
    **BRANDS["keeler"],
    "app_name": "Keeler 슬릿램프 영상 시스템 Explorer",
    "window_title": "Keeler 슬릿램프 영상 시스템 Explorer",
    "layout": "explorer",
}


def _norm(key: str | None) -> str:
    """'Keeler-Explorer' · 'keeler explorer' 처럼 적어도 같은 브랜드로."""
    return (key or "").strip().lower().replace("-", "_").replace(" ", "_")


def _assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller 번들 안
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def key_from(argv=None, config_brand: str | None = None) -> str:
    argv = list(sys.argv if argv is None else argv)
    for i, a in enumerate(argv):
        if a == "--brand" and i + 1 < len(argv):
            return _norm(argv[i + 1])
        if a.startswith("--brand="):
            return _norm(a.split("=", 1)[1])
    env = _norm(os.environ.get(ENV_KEY, ""))
    if env:
        return env
    return _norm(config_brand) or "default"


def select(key: str) -> dict:
    """브랜드를 정하고 환경변수에도 기록 (이후 import 되는 UI 모듈이 같은 값을 보게)."""
    key = _norm(key)
    key = key if key in BRANDS else "default"
    os.environ[ENV_KEY] = key
    return current()


def current() -> dict:
    key = _norm(os.environ.get(ENV_KEY, "default"))
    if key not in BRANDS:
        key = "default"
    return {"key": key, **BRANDS[key]}


def layout() -> str:
    """화면 구성: "explorer" (메뉴·툴바·트리) 또는 "standard" (촬영 / Pro 검토)."""
    return current().get("layout", "standard")


def asset(rel: str | None) -> str | None:
    if not rel:
        return None
    p = _assets_dir() / rel
    return str(p) if p.is_file() else None
