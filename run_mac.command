#!/usr/bin/env bash
# 슬릿램프 영상 시스템 (macOS) - 소스에서 바로 실행 (Finder 에서 더블클릭)
#   처음 한 번은 가상환경을 만들고 의존성을 설치한다.
#   하드웨어 없이 확인하려면 터미널에서:  ./run_mac.command --source synthetic
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[오류] Python 3.11 이상이 필요합니다. https://www.python.org/downloads/macos/ 에서 설치한 뒤 다시 실행하세요."
  read -r -p "엔터를 누르면 닫힙니다..." _
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[최초 1회] 가상환경 생성 및 의존성 설치 중... 잠시만 기다려 주세요."
  "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt || { echo "[오류] 의존성 설치 실패"; read -r -p "엔터를 누르면 닫힙니다..." _; exit 1; }
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

exec python run.py "$@"
