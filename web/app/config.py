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

# 저장 방식: choice(화면에서 선택) | local(항상 이 PC 에만 저장 — 서버엔 환자 정보·영상을 보내지 않음) | server
# Vercel 처럼 /tmp 임시 저장만 되는 곳은 서버 저장이 인스턴스마다 따로이고 곧 지워지므로 기본을 local 로 한다
_DEFAULT_POLICY = "local" if os.environ.get("VERCEL") and "SLITLAMP_DATA_DIR" not in os.environ else "choice"
STORAGE_POLICY = os.environ.get("SLITLAMP_STORAGE", _DEFAULT_POLICY).strip().lower()
if STORAGE_POLICY not in ("choice", "local", "server"):
    STORAGE_POLICY = _DEFAULT_POLICY

# 서버에 올릴 수 있는 파일 최대 크기 (MB)
MAX_UPLOAD_MB = int(os.environ.get("SLITLAMP_MAX_UPLOAD_MB", "1024") or 1024)

# 촬영 시각 기준 시간대 (클라우드 서버는 보통 UTC 라서 그대로 쓰면 9시간 어긋남)
TIMEZONE = os.environ.get("SLITLAMP_TZ", "Asia/Seoul")


def now():
    """설정한 시간대의 현재 시각 (시간대 정보 없는 datetime)."""
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(TIMEZONE)
    except Exception:                                   # 시간대 DB 가 없는 환경 (일부 Windows) → 한국 표준시
        tz = timezone(timedelta(hours=9))
    return datetime.now(tz).replace(tzinfo=None)

# 사진 저장 경로 규칙: <media>/<chart_no>_<patient_id>/<YYYY-MM-DD>/<파일>
SUBFOLDER_TEMPLATE = "{chart_no}_{patient_id}/{date}"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
