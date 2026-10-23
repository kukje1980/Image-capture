#!/usr/bin/env bash
# 슬릿램프 영상 시스템 (웹) - macOS Finder 에서 더블클릭으로 실행
#   서버가 켜지고 브라우저가 http://localhost:8000 으로 열린다. 이 창을 닫으면 종료된다.
cd "$(dirname "$0")" || exit 1
exec ./run_web.sh
