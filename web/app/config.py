"""웹앱 설정. 환경변수로 오버라이드 가능, 데이터는 앱 폴더 하위에 저장."""
from __future__ import annotations

import os
from pathlib import Path

# web/ 디렉토리 기준
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SLITLAMP_DATA_DIR", BASE_DIR / "data"))
MEDIA_DIR = Path(os.environ.get("SLITLAMP_MEDIA_DIR", DATA_DIR / "media"))
DB_PATH = Path(os.environ.get("SLITLAMP_DB_PATH", DATA_DIR / "slitlamp.db"))

# 사진 저장 경로 규칙: <media>/<chart_no>_<patient_id>/<YYYY-MM-DD>/<파일>
SUBFOLDER_TEMPLATE = "{chart_no}_{patient_id}/{date}"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
