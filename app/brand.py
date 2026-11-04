"""데스크탑 앱 브랜드(이름·로고·아이콘·색) 설정 — 웹의 web/app/brands.py 와 같은 구성.

브랜드 선택 우선순위
    1) 실행 옵션  --brand keeler | --brand fundus
    2) 환경변수  SLITLAMP_BRAND=keeler   (Keeler·안저 전용 설치본은 빌드 때 이 값이 들어감)
    3) 설정 파일 config.json 의 "brand"
    4) 기본 (슬릿램프 영상 시스템)

제품(product)
    slitlamp  슬릿램프 — 캡처 장비의 실시간 영상을 촬영·녹화 (기본·Keeler)
    fundus    안저     — 안저카메라가 사진을 저장하는 폴더를 감시해 환자에게 자동 등록
제품마다 데이터 폴더(설정·DB·사진)가 따로라 한 PC에 슬릿램프판과 안저판을 나란히 쓸 수 있다.
제품은 실행 옵션·환경변수로만 정한다 (설정 파일은 같은 제품 안에서 화면 브랜드만 바꾼다).

UI 모듈이 처음 import 되기 전에 select() 로 정해야 아이콘 색 등이 반영된다 (app/__main__.py 참고).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_KEY = "SLITLAMP_BRAND"

BRANDS: dict[str, dict] = {
    "default": {
        "product": "slitlamp",
        "app_name": "슬릿램프 영상 시스템",
        "window_title": "슬릿램프 디지털 영상 시스템",
        "report_title": "슬릿램프 영상 보고서",
        "brand_title": "슬릿램프 영상 시스템",
        "brand_sub": "SLIT LAMP IMAGING",
        "logo": None, "logo_dark": None, "icon": None,
        "logo_only": False,
        "palette": {},
    },
    # Keeler 공식 홈페이지의 로고·브랜드 색 (assets/brand/keeler/SOURCE.md)
    "keeler": {
        "product": "slitlamp",
        "app_name": "Keeler 슬릿램프 영상 시스템",
        "brand_title": "Keeler 슬릿램프 영상 시스템",
        "brand_sub": "SLIT LAMP IMAGING",
        "window_title": "Keeler 슬릿램프 영상 시스템",
        "report_title": "Keeler 슬릿램프 영상 보고서",
        "logo": "brand/keeler/logo.svg",            # 밝은 화면용 (네이비 글자)
        "logo_dark": "brand/keeler/logo-dark.svg",  # 어두운 화면용 (흰 글자, 원본)
        "icon": "brand/keeler/app.png",
        "logo_only": True,                          # 상단에는 로고만 (프로그램 이름 숨김)
        "icon_accent": "#4aa8dc",
        "icon_on_accent": "#052133",
        "report_rule": "#052133",
        "palette": {
            "dark": {
                "bg": "#03131f", "panel": "#061c2c", "panel2": "#0a2436", "raised": "#0e2c42",
                "ink": "#e8f1f8", "ink_soft": "#a6bccd", "ink_muted": "#6c8599",
                "rule": "#12334b", "rule_strong": "#1b425f",
                "accent": "#6cbce8", "accent_hover": "#a9dbf5", "accent_ink": "#052133", "accent_soft": "#12344a",
                "field": "#041624", "disabled": "#2d4a60",
            },
            "light": {
                "bg": "#f1f8fd", "panel": "#ffffff", "panel2": "#f4f9fd", "raised": "#ffffff",
                "ink": "#052133", "ink_soft": "#3d5568", "ink_muted": "#7b8e9c",
                "rule": "#d3dde3", "rule_strong": "#bccbd6",
                "accent": "#1981b7", "accent_hover": "#0f6593", "accent_ink": "#ffffff", "accent_soft": "#cde1ef",
                "field": "#ffffff", "disabled": "#b7c6d1",
            },
        },
    },
    # 안저(망막) 사진 — 안저카메라가 찍어 폴더에 저장한 사진을 자동으로 가져온다
    "fundus": {
        "product": "fundus",
        "app_name": "안저 영상 시스템",
        "window_title": "안저 디지털 영상 시스템",
        "report_title": "안저 영상 보고서",
        "brand_title": "안저 영상 시스템",
        "brand_sub": "FUNDUS IMAGING",
        "logo": None, "logo_dark": None,
        "icon": "brand/fundus/app.png",
        "logo_only": False,
        "palette": {},
    },
}

# 제품별 데이터 폴더·DB 파일 이름 (설치본이 달라도 같은 제품이면 같은 데이터를 쓴다)
PRODUCTS: dict[str, dict] = {
    "slitlamp": {"data_dir": "SlitLampImaging", "db_name": "slitlamp.db"},
    "fundus": {"data_dir": "FundusImaging", "db_name": "fundus.db"},
}


def _assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller 번들 안
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def fixed_key(argv=None) -> str | None:
    """실행 옵션·환경변수로 정해진 브랜드 (없으면 None — 설정 파일 값을 따름)."""
    argv = list(sys.argv if argv is None else argv)
    for i, a in enumerate(argv):
        if a == "--brand" and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        if a.startswith("--brand="):
            return a.split("=", 1)[1].strip().lower()
    env = os.environ.get(ENV_KEY, "").strip().lower()
    return env or None


def key_from(argv=None, config_brand: str | None = None) -> str:
    return fixed_key(argv) or (config_brand or "default").strip().lower() or "default"


def choose(argv=None, config_brand: str | None = None) -> str:
    """최종 브랜드. 설정 파일의 brand 는 실행 옵션·환경변수가 정한 제품 안에서만 바꿀 수 있다
    (예: 슬릿램프 설치본의 config.json 에 "fundus" 가 있어도 슬릿램프 데이터로 안저 화면이 뜨지 않게)."""
    fixed = fixed_key(argv)
    key = key_from(argv, config_brand)
    base = fixed if fixed in BRANDS else "default"
    if key not in BRANDS or BRANDS[key]["product"] != BRANDS[base]["product"]:
        return base
    return key


def select(key: str) -> dict:
    """브랜드를 정하고 환경변수에도 기록 (이후 import 되는 UI 모듈이 같은 값을 보게)."""
    key = key if key in BRANDS else "default"
    os.environ[ENV_KEY] = key
    return current()


def current() -> dict:
    key = os.environ.get(ENV_KEY, "default").strip().lower()
    if key not in BRANDS:
        key = "default"
    return {"key": key, **BRANDS[key]}


def product() -> str:
    """지금 브랜드의 제품: 'slitlamp' | 'fundus'."""
    return current()["product"]


def is_fundus() -> bool:
    return product() == "fundus"


def product_info() -> dict:
    return PRODUCTS[product()]


def asset(rel: str | None) -> str | None:
    if not rel:
        return None
    p = _assets_dir() / rel
    return str(p) if p.is_file() else None
