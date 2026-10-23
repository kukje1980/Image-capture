"""OS별 동작(캡처 백엔드·데이터 폴더) 테스트 — macOS 지원."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

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
    for f in ("build_mac.sh", "run_mac.command", "web/run_web.command", "web/run_web.sh"):
        assert (root / f).stat().st_mode & 0o111, f"{f} 실행 권한 없음"
