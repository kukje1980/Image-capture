"""웹앱 설정. 환경변수로 오버라이드 가능, 데이터는 앱 폴더 하위에 저장."""
from __future__ import annotations

import os
from pathlib import Path

# web/ 디렉토리 기준
BASE_DIR = Path(__file__).resolve().parent.parent
# Vercel 같은 서버리스 호스팅은 /tmp 만 쓰기 가능 (인스턴스가 바뀌면 지워지는 임시 저장)
_DEFAULT_DATA = Path("/tmp/slitlamp") if os.environ.get("VERCEL") else BASE_DIR / "data"
DATA_DIR = Path(os.environ.get("SLITLAMP_DATA_DIR", _DEFAULT_DATA))
MEDIA_DIR = Path(os.environ.get("SLITLAMP_MEDIA_DIR", DATA_DIR / "media"))
DB_PATH = Path(os.environ.get("SLITLAMP_DB_PATH", DATA_DIR / "slitlamp.db"))

# 접속 비밀번호 (인터넷에 올릴 때 설정 권장). 비어 있으면 로그인 없이 열린다.
PASSWORD = os.environ.get("SLITLAMP_PASSWORD", "")

# 저장 방식: choice(화면에서 선택, 기본) | local(항상 이 PC 에만 저장 — 서버엔 환자 정보·영상을 보내지 않음) | server
STORAGE_POLICY = os.environ.get("SLITLAMP_STORAGE", "choice").strip().lower()
if STORAGE_POLICY not in ("choice", "local", "server"):
    STORAGE_POLICY = "choice"

# 사진 저장 경로 규칙: <media>/<chart_no>_<patient_id>/<YYYY-MM-DD>/<파일>
SUBFOLDER_TEMPLATE = "{chart_no}_{patient_id}/{date}"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
