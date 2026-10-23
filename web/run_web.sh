#!/usr/bin/env bash
# 슬릿램프 영상 시스템 (웹) - macOS/Linux 실행 런처
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[최초 1회] 가상환경 생성 및 의존성 설치 중..."
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "브라우저에서 http://localhost:8000 을 여세요. (종료: Ctrl+C)"
( sleep 3; (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || (command -v open >/dev/null && open http://localhost:8000) || true ) &

exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
