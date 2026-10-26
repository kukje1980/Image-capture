"""OS별 동작(캡처 백엔드·데이터 폴더) 테스트 — macOS 지원."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import pytest

from app import paths
from app.capture.frame_utils import capture_api


def test_capture_api_per_os():
    assert capture_api("dshow", "win32") == cv2.CAP_DSHOW
    assert capture_api("dshow", "darwin") == cv2.CAP_AVFOUNDATION      # 맥은 자동으로 AVFoundation
    assert capture_api("avfoundation", "darwin") == cv2.CAP_AVFOUNDATION
    assert capture_api("dshow", "linux") == cv2.CAP_ANY
    assert capture_api("any", "win32") == cv2.CAP_ANY


def test_appdata_dir_on_macos(tmp_path, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    d = paths.get_appdata_dir()
    assert d == tmp_path / "Library" / "Application Support" / "SlitLampImaging" and d.is_dir()


def test_appdata_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.get_appdata_dir() == tmp_path / "SlitLampImaging"


def test_mac_bundle_files_present():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "build_mac.spec").read_text(encoding="utf-8")
    assert "NSCameraUsageDescription" in spec and "app.icns" in spec
    assert (root / "assets" / "icons" / "app.icns").stat().st_size > 1000
    # 실행 권한은 git 이 저장한 모드(100755)로 확인 — 윈도우 파일시스템엔 실행 비트가 없음
    import shutil
    import subprocess
    if shutil.which("git") is None:
        pytest.skip("git 없음")
    for f in ("build_mac.sh", "run_mac.command", "web/run_web.command", "web/run_web.sh"):
        out = subprocess.run(["git", "ls-files", "-s", f], cwd=root, capture_output=True, text=True).stdout
        assert out.startswith("100755"), f"{f} 실행 권한 없음 ({out.strip() or '추적 안 됨'})"


DSHOW_NEW = '''[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid_04f2"
[dshow @ 000001] "ZV-E10M2" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid_054c"
[dshow @ 000001] "Microphone (Realtek)" (audio)
'''
DSHOW_OLD = '''[dshow @ 0x1] DirectShow video devices (some may be both video and audio devices)
[dshow @ 0x1]  "USB Video"
[dshow @ 0x1]     Alternative name "@device_pnp_x"
[dshow @ 0x1]  "ILME-FX3"
[dshow @ 0x1] DirectShow audio devices
[dshow @ 0x1]  "Mic"
'''
# ffmpeg 7: 캡처보드는 (video, audio), 연결 전 가상 카메라는 (none) — 빠지면 뒤 장치 번호가 어긋난다
DSHOW_MIXED = '''[in#0 @ 000002] "AVerMedia HD Capture GC573" (video, audio)
[in#0 @ 000002]   Alternative name "@device_pnp_a"
[in#0 @ 000002] "Camera Sensor Front" (video)
[in#0 @ 000002]   Alternative name "@device_pnp_b"
[in#0 @ 000002] "Sony Camera (Imaging Edge)" (none)
[in#0 @ 000002]   Alternative name "@device_sw_{860BB310-5D01-11D0-BD3B-00A0C911CE86}"
[in#0 @ 000002] "Microphone Array (Realtek(R) Audio)" (audio)
[in#0 @ 000002] "Line In" (none)
'''
AVF = '''[AVFoundation indev @ 0x7f] AVFoundation video devices:
[AVFoundation indev @ 0x7f] [0] FaceTime HD Camera
[AVFoundation indev @ 0x7f] [1] ZV-E10M2
[AVFoundation indev @ 0x7f] [2] Capture screen 0
[AVFoundation indev @ 0x7f] AVFoundation audio devices:
[AVFoundation indev @ 0x7f] [0] MacBook Pro Microphone
'''


def test_device_name_parsing_and_sony_pick():
    from app.capture import frame_utils as fu
    assert fu.parse_dshow_devices(DSHOW_NEW) == ["Integrated Camera", "ZV-E10M2"]
    assert fu.parse_dshow_devices(DSHOW_OLD) == ["USB Video", "ILME-FX3"]
    assert fu.parse_dshow_devices(DSHOW_MIXED) == [
        "AVerMedia HD Capture GC573", "Camera Sensor Front", "Sony Camera (Imaging Edge)"]
    assert fu.find_sony_index(fu.parse_dshow_devices(DSHOW_MIXED)) == 2
    assert fu.parse_avfoundation_devices(AVF) == ["FaceTime HD Camera", "ZV-E10M2"]
    assert fu.find_sony_index(["FaceTime HD Camera", "ZV-E10M2"]) == 1
    assert fu.find_sony_index(["USB Video", "ILME-FX3"]) == 1
    assert fu.find_sony_index(["Integrated Camera"]) is None
    assert fu.device_names("linux") == []
