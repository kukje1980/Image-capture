# 효과음 후보 (실제 녹음) — 출처와 라이선스

공개 소프트웨어에 들어 있는 실제 카메라 소리를 44.1kHz 모노 WAV 로 변환하고, 앞뒤 무음을 잘라
최대 음량을 맞춘 것입니다 (`tools/fetch_real_sounds.sh` 로 다시 받을 수 있음). 고른 파일을
`assets/sounds/shutter.wav` 등으로 복사해 씁니다 (웹은 `web/static/sounds/` 에도 같은 파일).

| 파일 | 출처 | 라이선스 |
|------|------|----------|
| gnome_shutter.wav | freedesktop 사운드 테마 `stereo/camera-shutter.oga` (freesound 사용자 horsthorstensen 녹음, 필름 SLR) | CC BY-SA 3.0 — 출처 표기 필요 |
| android_classic.wav | AOSP `frameworks/base/data/sounds/effects/wav/CameraClick.wav` | Apache 2.0 |
| android1_click.wav | AOSP `frameworks/base/data/sounds/effects/camera_click.wav` | Apache 2.0 |
| android_material.wav | AOSP `.../effects/material/ogg/camera_click.ogg` | Apache 2.0 |
| android_rec_start/stop.wav | AOSP `.../effects/VideoRecord.wav`, `VideoStop.wav` | Apache 2.0 |
| android_material_rec_start/stop.wav | AOSP `.../effects/material/ogg/VideoRecord.ogg`, `VideoStop.ogg` | Apache 2.0 |
| chromeos_shutter.wav, chromeos_rec_start/stop.wav | Chromium `ash/webui/camera_app_ui/resources/sounds/` (shutter, record_start, record_end) | BSD-3 (Chromium OS) |
| firefoxos_shutter.wav, firefoxos_rec_start/stop.wav | Mozilla Gaia `disabled_apps/camera/resources/sounds/` (shutter, camcorder_start/end) | Apache 2.0 |
| deepin_shutter.wav | deepin-sound-theme `stereo/camera-shutter.wav` | GPL-3 — 배포용 앱에는 권하지 않음 |
