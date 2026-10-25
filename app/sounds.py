"""효과음 — 사진 캡처(필름 카메라 '찰칵') · 정지영상(스틸 '틱') · 녹화 시작/중지('삐').

음원은 assets/sounds/*.wav (tools/generate_sounds.py 로 합성, 외부 저작물 없음).
재생 백엔드는 OS 에 맞춰 고른다. 어떤 경우에도 예외를 밖으로 내지 않는다
(소리가 촬영을 막아선 안 된다).

    Windows  → winsound (표준 라이브러리, 비동기, 지연 거의 없음)
    그 외    → QtMultimedia QSoundEffect → afplay(macOS) / paplay·aplay(Linux) → 없으면 조용히 생략

사용:  sounds.set_enabled(config.sounds_enabled);  sounds.play("shutter")
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

NAMES = ("shutter", "freeze", "rec_start", "rec_stop")
LABELS = {
    "shutter": "사진 캡처 (필름 카메라 찰칵)",
    "freeze": "정지영상 (스틸)",
    "rec_start": "녹화 시작",
    "rec_stop": "녹화 중지",
}

_enabled = True
_backend = None            # 처음 재생할 때 고른다 (import 시점엔 Qt 앱이 없을 수 있음)


def assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller 번들 안
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def sound_path(name: str) -> Path:
    return assets_dir() / "sounds" / f"{name}.wav"


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)


def is_enabled() -> bool:
    return _enabled


# ---------------------------------------------------------------- 백엔드
class _WinsoundBackend:
    name = "winsound"

    def __init__(self):
        import winsound  # Windows 전용 — 다른 OS 에선 ImportError

        self._ws = winsound

    def play(self, path: Path) -> None:
        ws = self._ws
        ws.PlaySound(str(path), ws.SND_FILENAME | ws.SND_ASYNC | ws.SND_NODEFAULT)


class _QtBackend:
    """QSoundEffect — WAV 를 직접 디코딩하므로 지연이 짧다. 효과 객체는 이름별로 한 번만 만든다."""

    name = "qt"

    def __init__(self):
        from PySide6.QtCore import QCoreApplication, QUrl
        from PySide6.QtMultimedia import QSoundEffect

        if QCoreApplication.instance() is None:
            raise RuntimeError("Qt 애플리케이션이 없습니다")
        self._QUrl, self._Effect = QUrl, QSoundEffect
        self._effects: dict[str, object] = {}

    def _effect(self, path: Path):
        key = str(path)
        eff = self._effects.get(key)
        if eff is None:
            eff = self._Effect()
            eff.setSource(self._QUrl.fromLocalFile(key))
            eff.setVolume(1.0)
            self._effects[key] = eff
        return eff

    def preload(self, paths) -> None:
        for p in paths:
            self._effect(p)

    def play(self, path: Path) -> None:
        self._effect(path).play()


class _CommandBackend:
    """외부 재생 명령 (afplay / paplay / aplay) 을 기다리지 않고 띄운다."""

    name = "command"

    def __init__(self):
        cands = ["afplay"] if sys.platform == "darwin" else ["paplay", "aplay"]
        self._cmd = next((shutil.which(c) for c in cands if shutil.which(c)), None)
        if not self._cmd:
            raise RuntimeError("재생 명령 없음")

    def play(self, path: Path) -> None:
        subprocess.Popen([self._cmd, str(path)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _NullBackend:
    name = "none"

    def play(self, path: Path) -> None:
        pass


def _select_backend():
    order = [_WinsoundBackend] if sys.platform.startswith("win") else []
    order += [_QtBackend, _CommandBackend]
    for cls in order:
        try:
            b = cls()
            log.info("효과음 백엔드: %s", b.name)
            return b
        except Exception as e:  # noqa: BLE001 — 다음 후보로
            log.debug("효과음 백엔드 %s 사용 불가: %s", cls.__name__, e)
    log.info("효과음 재생 수단이 없어 소리를 끕니다")
    return _NullBackend()


def backend():
    global _backend
    if _backend is None:
        _backend = _select_backend()
    return _backend


def reset_backend() -> None:
    """(테스트용) 다음 재생 때 백엔드를 다시 고른다."""
    global _backend
    _backend = None


def preload() -> None:
    """앱 시작 뒤 한 번 불러 첫 재생 지연을 줄인다 (백엔드가 지원할 때만)."""
    if not _enabled:
        return
    try:
        b = backend()
        pre = getattr(b, "preload", None)
        if pre is not None:
            pre([sound_path(n) for n in NAMES if sound_path(n).exists()])
    except Exception:  # noqa: BLE001
        log.debug("효과음 미리 읽기 실패", exc_info=True)


def play(name: str) -> bool:
    """효과음을 비동기로 재생한다. 실제로 재생을 시도했으면 True (꺼짐·파일 없음·오류면 False)."""
    if not _enabled or name not in NAMES:
        return False
    path = sound_path(name)
    if not path.exists():
        log.warning("효과음 파일이 없습니다: %s", path)
        return False
    try:
        backend().play(path)
        return True
    except Exception:  # noqa: BLE001
        log.warning("효과음 재생 실패: %s", name, exc_info=True)
        return False
