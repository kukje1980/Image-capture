#!/usr/bin/env bash
# Build dist/FundusViewer.app and dist/FundusViewer-mac-<arch>.dmg on macOS 11+
# (Python 3.10+). The app is built for the architecture of this Mac:
# Apple Silicon (arm64) or Intel (x86_64).
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(uname)" != "Darwin" ]; then
  echo "Run this on macOS." >&2
  exit 1
fi
PY="${PYTHON:-python3}"
ARCH="$(uname -m)"
case "$ARCH" in
  arm64)  LABEL="AppleSilicon" ;;
  x86_64) LABEL="Intel" ;;
  *)      LABEL="$ARCH" ;;
esac

if [ -z "${VIRTUAL_ENV:-}" ] && [ -z "${CI:-}" ]; then
  "$PY" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PY=python
fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements.txt pyinstaller pytest
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q tests

rm -rf build/FundusViewer dist/FundusViewer dist/FundusViewer.app
"$PY" -m PyInstaller fundus_viewer.spec --noconfirm

# Ad-hoc signature: no developer certificate needed, and Apple Silicon
# refuses to start unsigned code.
codesign --force --deep --sign - dist/FundusViewer.app
codesign --verify --deep dist/FundusViewer.app

DMG="dist/FundusViewer-mac-$LABEL.dmg"
STAGE="dist/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R dist/FundusViewer.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
# hdiutil sometimes fails with "Resource busy": wait and retry
for try in 1 2 3 4 5; do
  if hdiutil create -volname "Fundus Viewer" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null; then
    break
  fi
  if [ "$try" = 5 ]; then echo "hdiutil failed" >&2; exit 1; fi
  echo "hdiutil retry $try/5"; sleep $((try * 5))
done
rm -rf "$STAGE"
echo
echo "Done: dist/FundusViewer.app and $DMG"
echo "Try it with: dist/FundusViewer.app/Contents/MacOS/FundusViewer --demo"
