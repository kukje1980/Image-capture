#!/usr/bin/env bash
# 슬릿램프 영상 시스템 (웹) - macOS/Linux 실행 런처
set -e
cd "$(dirname "$0")"

# Python 3.11 이상 찾기 (macOS 기본 python3 는 3.9 인 경우가 많다)
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[오류] Python 3.11 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[최초 1회] 가상환경 생성 및 의존성 설치 중..."
  "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "브라우저가 곧 http://localhost:8000 으로 열립니다. (종료: 이 창에서 Ctrl+C 또는 창 닫기)"
( sleep 3; (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || (command -v open >/dev/null && open http://localhost:8000) || true ) &

exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
