"""효과음: 음원 파일 · 켜기/끄기 · 백엔드 오류 무시 · 촬영 동작과의 연결."""
from __future__ import annotations

import time
import wave

import pytest
from PySide6.QtWidgets import QApplication

from app import sounds
from app.config import AppConfig
from app.models.patient import Patient


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeBackend:
    name = "fake"

    def __init__(self, fail=False):
        self.played, self.fail = [], fail

    def play(self, path):
        if self.fail:
            raise RuntimeError("no audio device")
        self.played.append(path.stem)


@pytest.fixture()
def fake(monkeypatch):
    b = FakeBackend()
    monkeypatch.setattr(sounds, "_backend", b)
    monkeypatch.setattr(sounds, "_enabled", True)
    yield b
    sounds.reset_backend()


def test_wav_files_exist_and_are_short_mono_pcm():
    # 데스크탑(assets)과 웹(static) 에 같은 파일이 있어야 한다
    web_dir = sounds.assets_dir().parent / "web" / "static" / "sounds"
    for name in sounds.NAMES:
        p = sounds.sound_path(name)
        assert p.exists(), p
        with wave.open(str(p)) as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == 44100
            ms = w.getnframes() / w.getframerate() * 1000
            assert 100 <= ms <= 400, (name, ms)            # 짧은 효과음 — 촬영 흐름을 방해하지 않게
        assert (web_dir / p.name).read_bytes() == p.read_bytes(), name
    assert set(sounds.LABELS) == set(sounds.NAMES)


def test_shutter_has_two_clicks():
    """필름 카메라 '찰칵' — 미러('찰') 뒤 약 70ms 에 셔터막('칵') 두 번째 타격이 있어야 한다."""
    import numpy as np

    with wave.open(str(sounds.sound_path("shutter"))) as w:
        sr = w.getframerate()
        x = np.abs(np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float))
    win = int(sr * 0.005)
    env = np.convolve(x, np.ones(win) / win, mode="same")
    first = env[: int(sr * 0.05)].max()
    gap = env[int(sr * 0.05): int(sr * 0.065)].max()
    second = env[int(sr * 0.07): int(sr * 0.12)].max()
    assert gap < first * 0.4 and second > gap * 2


def test_play_respects_enabled_and_names(fake):
    assert sounds.play("shutter") and fake.played == ["shutter"]
    assert not sounds.play("bogus")
    sounds.set_enabled(False)
    assert not sounds.is_enabled() and not sounds.play("freeze")
    assert fake.played == ["shutter"]


def test_backend_errors_are_swallowed(monkeypatch):
    monkeypatch.setattr(sounds, "_backend", FakeBackend(fail=True))
    monkeypatch.setattr(sounds, "_enabled", True)
    assert sounds.play("rec_start") is False               # 예외 없이 False
    sounds.reset_backend()


def test_backend_selection_never_raises(qapp, monkeypatch):
    sounds.reset_backend()
    b = sounds.backend()
    assert hasattr(b, "play") and b.name in ("winsound", "qt", "command", "none")
    sounds.preload()                                        # 지원하지 않는 백엔드여도 조용히 지나감
    sounds.reset_backend()


def test_config_round_trip(app_env):
    config, _ = app_env
    assert config.sounds_enabled is True
    config.sounds_enabled = False
    config.save()
    assert AppConfig.load().sounds_enabled is False


def test_settings_dialog_toggles_sound(qapp, app_env):
    from app.ui.settings_dialog import SettingsDialog

    config, _ = app_env
    config.source_mode = "synthetic"
    dlg = SettingsDialog(config)
    assert dlg.sounds.isChecked()
    dlg.sounds.setChecked(False)
    dlg.apply_to_config()
    assert config.sounds_enabled is False


def _wait(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def test_capture_actions_play_sounds(qapp, app_env, fake, monkeypatch):
    """사진 캡처 = 찰칵, 정지영상 = freeze, 녹화 = rec_start/rec_stop, 4분할 저장 = 찰칵."""
    config, db = app_env
    config.source_mode = "synthetic"
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="S1", name="효과음"))
    from app.ui import main_window
    from app.ui.main_window import MainWindow

    w = MainWindow(config, db)
    w.show()
    try:
        assert _wait(qapp, lambda: w._last_frame is not None)
        w._current_patient = db.patients.list_all()[0]
        # 녹화 결과 경고창(프레임 0개 등)이 테스트를 막지 않게
        monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *a, **k: None)
        monkeypatch.setattr(main_window.QMessageBox, "information", lambda *a, **k: None)

        w._on_freeze()                                         # 단일 정지영상
        assert fake.played[-1] == "freeze"
        w._on_freeze()                                         # 라이브 복귀 — 소리 없음
        assert fake.played.count("freeze") == 1

        w._on_capture()
        assert fake.played[-1] == "shutter"

        w.control_bar.btn_quad.setChecked(True)
        assert _wait(qapp, lambda: w.quad_view._frames[0] is not None)   # 라이브 칸에 프레임 도착
        w._on_freeze()                                         # 4분할 칸 채우기
        assert fake.played[-1] == "freeze"
        w._on_save_quad()
        assert fake.played[-1] == "shutter"
        w.control_bar.btn_quad.setChecked(False)

        w._start_recording()
        assert fake.played[-1] == "rec_start"
        _wait(qapp, lambda: False, 0.6)                        # 프레임 몇 장 기록
        w._stop_recording()
        assert fake.played[-1] == "rec_stop"

        sounds.set_enabled(False)
        n = len(fake.played)
        w._on_capture()
        assert len(fake.played) == n                           # 꺼지면 조용
    finally:
        w.close()
