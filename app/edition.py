"""에디션 — 같은 코드로 만드는 두 가지 프로그램.

    standard  슬릿램프 영상 시스템 (기본)
    agent     AI 에이전트 에디션 — 실시간 장면 인식·자동 촬영·전후 클립·추천 프레임·사용 데이터 수집

에디션은 앱 데이터 폴더(설정·DB·영상)를 분리하므로 두 프로그램을 같은 PC 에
나란히 설치해 쓸 수 있다.
선택 우선순위: 1) 실행 옵션 --edition agent
              2) 환경변수 SLITLAMP_EDITION (에이전트 설치본은 빌드 때 들어감)
config 를 읽기 전에 select() 해야 한다 (데이터 폴더 이름이 바뀌므로 — app/__main__.py 참고).
"""
from __future__ import annotations

import os
import sys

from app import paths

ENV_KEY = "SLITLAMP_EDITION"

EDITIONS: dict[str, dict] = {
    "standard": {
        "app_dir": "SlitLampImaging",
        "app_name_en": "SlitLampImaging",
        "title_suffix": "",
        "agent": False,
    },
    "agent": {
        "app_dir": "SlitLampAgent",
        "app_name_en": "SlitLampAgent",
        "title_suffix": " · AI 에이전트",
        "agent": True,
    },
}


def key_from(argv=None) -> str:
    argv = list(sys.argv if argv is None else argv)
    for i, a in enumerate(argv):
        if a == "--edition" and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        if a.startswith("--edition="):
            return a.split("=", 1)[1].strip().lower()
    return os.environ.get(ENV_KEY, "").strip().lower() or "standard"


def select(key: str) -> dict:
    """에디션을 정하고 데이터 폴더 이름을 바꾼다.

    이후 paths.get_appdata_dir() 가 그 폴더를 쓴다.
    """
    key = key if key in EDITIONS else "standard"
    os.environ[ENV_KEY] = key
    paths.APP_DIR_NAME = EDITIONS[key]["app_dir"]
    return current()


def current_key() -> str:
    key = os.environ.get(ENV_KEY, "").strip().lower()
    return key if key in EDITIONS else "standard"


def current() -> dict:
    return dict(EDITIONS[current_key()], key=current_key())


def is_agent() -> bool:
    return EDITIONS[current_key()]["agent"]
