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
