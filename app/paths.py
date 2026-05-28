"""경로/폴더 규칙 헬퍼.

%APPDATA%/SlitLampImaging (Windows) 또는 ~/.local/share/SlitLampImaging (그 외)를
앱 데이터 루트로 사용한다. 환자별 저장 하위 폴더 이름도 여기서 생성한다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

APP_DIR_NAME = "SlitLampImaging"

# 폴더/파일 이름에 허용할 문자만 남기고 나머지는 '_'로 치환 (한글 허용)
_UNSAFE = re.compile(r"[^0-9A-Za-z._가-힣-]+")


def get_appdata_dir() -> Path:
    """앱 데이터 루트 디렉토리(없으면 생성)."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".local" / "share"
    d = base / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_dir(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize(name: str) -> str:
    name = (name or "").strip()
    name = _UNSAFE.sub("_", name)
    return name or "_"


def patient_subdir(root, patient, template: str, ts) -> Path:
    """<root>/<template>를 환자/날짜 값으로 채운 경로를 만든다.

    template 예: "{chart_no}_{patient_id}/{date}"
    각 토큰 값은 미리 sanitize 하므로 경로 탈출(../ 등)이 발생하지 않는다.
    """
    chart = sanitize(patient.chart_no or "noChart")
    pid = sanitize(patient.patient_id or (str(patient.id) if patient.id else "0"))
    name = sanitize(patient.name or "")
    date = ts.strftime("%Y-%m-%d")
    rel = template.format(chart_no=chart, patient_id=pid, name=name, date=date)
    sub = Path(root)
    for seg in rel.split("/"):
        seg = seg.strip()
        if seg and seg not in (".", ".."):
            sub = sub / seg
    return sub
