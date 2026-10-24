#!/usr/bin/env bash
# 슬릿램프 영상 시스템 (웹) - macOS/Linux 실행 런처
#   처음 실행 시 가상환경 생성 + 의존성 설치, 이후에는 바로 서버 시작.
#   서버가 실제로 응답하면 브라우저를 http://127.0.0.1:8000 으로 연다.
cd "$(dirname "$0")" || exit 1
URL="http://127.0.0.1:8000"

fail() {
  echo
  echo "[오류] $1"
  read -r -p "엔터를 누르면 닫힙니다..." _ || true
  exit 1
}

# Python 3.11 ~ 3.13 우선, 없으면 python3 (3.11 이상) — macOS 기본 python3 는 3.9 인 경우가 많다
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.11 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
echo "사용할 Python: $("$PY" --version)"

# 최초 설치 (끝까지 성공해야 .installed 표시가 생긴다)
if [ ! -f ".venv/.installed" ]; then
  echo "[최초 1회] 가상환경 생성 및 의존성 설치 중... 1~2분 걸립니다."
  rm -rf .venv
  "$PY" -m venv .venv || fail "가상환경 생성 실패"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt || fail "의존성 설치 실패. 인터넷 연결을 확인한 뒤 다시 실행하세요."
  touch .venv/.installed
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo
echo "서버를 시작합니다. 준비되면 브라우저가 자동으로 열립니다."
echo "  주소: $URL   (종료: 이 창에서 Ctrl+C 또는 창 닫기)"
echo

# 서버가 응답할 때까지(최대 60초) 기다렸다가 브라우저 열기
(
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "$URL/"; then
      if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
      break
    fi
    sleep 1
  done
) &

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo
echo "서버가 종료되었습니다. 위에 오류 메시지가 있으면 확인하세요."
echo "(이미 다른 창에서 실행 중이면 'address already in use' — 브라우저에서 $URL 을 열면 됩니다.)"
read -r -p "엔터를 누르면 닫힙니다..." _ || true
