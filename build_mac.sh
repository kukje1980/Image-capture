#!/usr/bin/env bash
# 슬릿램프 영상 시스템 - macOS 앱(.app) + 설치 디스크 이미지(.dmg) 빌드
#   사용:  ./build_mac.sh
#   결과:  dist/SlitLampImaging.app
#          dist/SlitLampImaging-<버전>-mac-<arm64|x86_64>.dmg
# 필요:   macOS 11 이상, Python 3.11 이상 (python.org 설치본 또는 Homebrew)
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(uname)" != "Darwin" ]; then
  echo "[오류] 이 스크립트는 macOS 에서 실행해야 합니다." >&2
  exit 1
fi

# Python 3.11+ 찾기
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[오류] Python 3.11 이상이 필요합니다. https://www.python.org/downloads/macos/ 에서 설치하세요." >&2
  exit 1
fi
VERSION="$("$PY" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
ARCH="$(uname -m)"

echo "===================================================="
echo " 슬릿램프 영상 시스템 - macOS 빌드  (v$VERSION, $ARCH, $("$PY" --version))"
echo "===================================================="

echo "[1/4] 빌드용 가상환경 + 의존성 설치..."
"$PY" -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt pyinstaller

echo "[2/4] PyInstaller 로 .app 번들 생성..."
rm -rf build/build_mac dist/SlitLampImaging dist/SlitLampImaging.app
pyinstaller --noconfirm build_mac.spec

echo "[3/4] 임시(ad-hoc) 서명..."
# 개발자 인증서가 없어도 Apple Silicon 에서 실행되도록 ad-hoc 서명
codesign --force --deep --sign - dist/SlitLampImaging.app

echo "[4/4] 설치 디스크 이미지(.dmg) 생성..."
STAGE="dist/dmg"
DMG="dist/SlitLampImaging-$VERSION-mac-$ARCH.dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R dist/SlitLampImaging.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "SlitLamp Imaging $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo
echo "===================================================="
echo " 완료!"
echo "   앱:   dist/SlitLampImaging.app"
echo "   설치: $DMG"
echo "   (dmg 를 열고 앱을 Applications 폴더로 끌어다 놓으세요)"
echo "===================================================="
