#!/usr/bin/env bash
# 공개 소프트웨어에 들어 있는 실제 카메라 효과음을 받아 tools/sound_candidates/ 를 다시 만든다.
#   필요: apt-get(우분투), git, python3 + numpy + imageio-ffmpeg
# 출처·라이선스는 tools/sound_candidates/README.md 참고.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=$(mktemp -d)
OUT="$ROOT/tools/sound_candidates"
mkdir -p "$OUT"
FF=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
conv() { "$FF" -y -loglevel error -i "$1" -ac 1 -ar 44100 -sample_fmt s16 "$W/raw_$2.wav"; }

cd "$W"
apt-get download sound-theme-freedesktop deepin-sound-theme
for d in *.deb; do dpkg-deb -x "$d" x; done
conv x/usr/share/sounds/freedesktop/stereo/camera-shutter.oga gnome_shutter
conv x/usr/share/sounds/deepin/stereo/camera-shutter.wav deepin_shutter

git clone -q --depth 1 --filter=blob:none --sparse https://github.com/aosp-mirror/platform_frameworks_base aosp
(cd aosp && git sparse-checkout set data/sounds/effects)
A=aosp/data/sounds/effects
conv $A/wav/CameraClick.wav android_classic;            conv $A/camera_click.wav android1_click
conv $A/material/ogg/camera_click.ogg android_material
conv $A/VideoRecord.wav android_rec_start;              conv $A/VideoStop.wav android_rec_stop
conv $A/material/ogg/VideoRecord.ogg android_material_rec_start
conv $A/material/ogg/VideoStop.ogg android_material_rec_stop

git clone -q --depth 1 --filter=blob:none --sparse https://github.com/chromium/chromium chromium
(cd chromium && git sparse-checkout set ash/webui/camera_app_ui/resources/sounds)
C=chromium/ash/webui/camera_app_ui/resources/sounds
conv $C/shutter.ogg chromeos_shutter; conv $C/record_start.ogg chromeos_rec_start; conv $C/record_end.ogg chromeos_rec_stop

git clone -q --depth 1 --filter=blob:none --sparse https://github.com/mozilla-b2g/gaia gaia
(cd gaia && git sparse-checkout set disabled_apps/camera/resources/sounds)
G=gaia/disabled_apps/camera/resources/sounds
conv $G/shutter.opus firefoxos_shutter; conv $G/camcorder_start.opus firefoxos_rec_start; conv $G/camcorder_end.opus firefoxos_rec_stop

# 앞뒤 무음 제거 + 최대 음량 정규화 (셔터 0.9, 녹화 0.8)
python3 - "$W" "$OUT" <<'PY'
import sys, wave, glob, os, numpy as np
W, OUT = sys.argv[1], sys.argv[2]; SR = 44100
for f in glob.glob(os.path.join(W, "raw_*.wav")):
    k = os.path.basename(f)[4:-4]
    w = wave.open(f); x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float) / 32768
    a = np.abs(x); pk = a.max() or 1
    i0 = int(np.argmax(a > pk * 10 ** (-40 / 20))); i1 = len(a) - int(np.argmax(a[::-1] > pk * 10 ** (-50 / 20)))
    y = x[max(0, i0 - int(SR * .003)):min(len(x), i1 + int(SR * .04))].copy()
    n = min(int(SR * .008), len(y)); y[-n:] *= np.linspace(1, 0, n); m = min(int(SR * .001), len(y)); y[:m] *= np.linspace(0, 1, m)
    y = y / (np.abs(y).max() or 1) * (0.8 if "rec_" in k else (0.85 if k == "android1_click" else 0.9))
    with wave.open(os.path.join(OUT, k + ".wav"), "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(SR); o.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    print(k, f"{len(y) / SR * 1000:.0f} ms")
PY
rm -rf "$W"
