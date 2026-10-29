"""경로/폴더 규칙 헬퍼.

%APPDATA%/SlitLampImaging (Windows), ~/Library/Application Support/SlitLampImaging (macOS),
~/.local/share/SlitLampImaging (그 외)를 앱 데이터 루트로 사용한다. 환자별 저장 하위 폴더 이름도 여기서 생성한다.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

APP_DIR_NAME = "SlitLampImaging"
DEFAULT_TEMPLATE = "{chart_no}_{patient_id}/{date}"
log = logging.getLogger(__name__)

# 폴더/파일 이름에 허용할 문자만 남기고 나머지는 '_'로 치환 (한글 허용)
_UNSAFE = re.compile(r"[^0-9A-Za-z._가-힣-]+")
# 윈도우가 파일 이름으로 쓰지 못하는 장치 이름 (CON, NUL.txt 등)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
# 이름 한 칸 최대 길이 — 윈도우 전체 경로 260자, 맥·리눅스 이름 255바이트(한글 1자 = 3바이트) 안에 들도록
# (차트번호·이름은 보통 훨씬 짧다). 토큰 두 개를 이어 붙인 기본 규칙도 한 칸 한도 안에 든다.
_MAX_TOKEN = (48, 90)            # (글자, UTF-8 바이트)
_MAX_SEGMENT = (100, 200)


def get_appdata_dir() -> Path:
    """앱 데이터 루트 디렉토리(없으면 생성)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata)
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    d = base / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_dir(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize(name: str, max_len=_MAX_TOKEN) -> str:
    """어느 OS 에서나 그대로 쓸 수 있는 폴더/파일 이름 한 칸.

    '..'·앞뒤 점(윈도우는 끝의 점을 몰래 지워 다른 이름과 겹침)·장치 이름(CON 등)·지나치게 긴 이름을 막는다.
    max_len: 최대 (글자 수, UTF-8 바이트 수) 또는 글자 수.
    """
    chars, nbytes = max_len if isinstance(max_len, tuple) else (max_len, max_len * 3)
    name = _UNSAFE.sub("_", (name or "").strip())[:chars]
    name = name.encode("utf-8")[:nbytes].decode("utf-8", "ignore").strip(".")
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name or "_"


def patient_subdir(root, patient, template: str, ts) -> Path:
    """<root>/<template>를 환자/날짜 값으로 채운 경로를 만든다.

    template 예: "{chart_no}_{patient_id}/{date}"
    각 토큰 값과 결과의 각 칸을 sanitize 하므로 경로 탈출(../, C:\\ 등)이 발생하지 않는다.
    규칙이 잘못돼 있으면(오타 토큰 등) 촬영이 실패하지 않도록 기본 규칙을 쓴다.
    """
    values = dict(
        chart_no=sanitize(patient.chart_no or "noChart"),
        patient_id=sanitize(patient.patient_id or (str(patient.id) if patient.id else "0")),
        name=sanitize(patient.name or ""),
        date=ts.strftime("%Y-%m-%d"),
    )
    try:
        rel = (template or "").format(**values)
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        log.warning("저장 폴더 규칙이 잘못되어 기본 규칙을 씁니다: %r", template)
        rel = ""
    segs = [s.strip() for s in re.split(r"[/\\]", rel)]
    segs = [sanitize(s, _MAX_SEGMENT) for s in segs if s and s.strip(". ")]
    if not segs:
        segs = [sanitize(s, _MAX_SEGMENT) for s in DEFAULT_TEMPLATE.format(**values).split("/")]
    return Path(root).joinpath(*segs)
