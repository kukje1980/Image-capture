#!/usr/bin/env bash
# Build dist/FundusViewer.app and dist/FundusViewer-mac-<AppleSilicon|Intel>.dmg on a Mac
# (Python 3.10+). The app is built for the architecture of this Mac:
# Apple Silicon (arm64) or Intel (x86_64). It runs on the macOS its libraries are
# built for or newer (today macOS 14.4, from Qt 6.12); dist/mac-min-<label>.txt says
# which (e.g. "macOS 14.4 Sonoma") for the download page.
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
QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q -o faulthandler_timeout=180 tests

rm -rf build/FundusViewer dist/FundusViewer dist/FundusViewer.app
"$PY" -m PyInstaller fundus_viewer.spec --noconfirm

# Info.plist must name the newest macOS any bundled library needs (fails otherwise)
"$PY" macos_bundle.py dist/FundusViewer.app --notes-out "dist/mac-min-$LABEL.txt"

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
echo "Done: dist/FundusViewer.app and $DMG (runs on $(cat "dist/mac-min-$LABEL.txt") or newer)"
echo "Try it with: dist/FundusViewer.app/Contents/MacOS/FundusViewer --demo"
