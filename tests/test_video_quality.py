"""동영상 화질 모드 (일반 / 고화질) — 설정 → 녹화기 → 실제 파일까지."""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.capture import video_recorder as vr
from app.config import AppConfig


def test_encoder_options_per_mode_and_resolution():
    assert vr.encoder_options("normal", (1920, 1080)) == ["-preset", "veryfast", "-crf", "23"]
    assert vr.encoder_options("high", (1920, 1080)) == ["-preset", "veryfast", "-crf", "18"]
    # 4K 는 보통 PC 에서도 실시간이 되도록 가장 빠른 설정 — 화질 차이는 CRF 로만
    assert vr.encoder_options("normal", (3840, 2160)) == ["-preset", "ultrafast", "-crf", "23"]
    assert vr.encoder_options("high", (3840, 2160)) == ["-preset", "ultrafast", "-crf", "18"]
    assert vr.encoder_options("bogus", (1280, 720)) == vr.encoder_options("normal", (1280, 720))


def test_writer_receives_mode(tmp_path, monkeypatch):
    seen = {}

    class _W:
        def append_data(self, _):
            pass

        def close(self):
            pass

    def fake_writer(path, **kw):
        seen.update(kw)
        return _W()

    monkeypatch.setattr(vr.imageio, "get_writer", fake_writer)
    rec = vr.VideoRecorder()
    rec.start(tmp_path / "x.mp4", fps=30, size=(3840, 2160), quality="high")
    rec.stop()
    assert seen["quality"] is None                       # imageio 가 자체 CRF 를 덧붙이지 않게
    assert seen["ffmpeg_params"] == ["-preset", "ultrafast", "-crf", "18"]


def _noisy(i, h=240, w=320):
    rng = np.random.default_rng(i)
    return np.clip(rng.normal(90, 30, (h, w, 3)), 0, 255).astype(np.uint8)


def _record(tmp_path, quality, n=30):
    rec = vr.VideoRecorder()
    try:
        rec.start(tmp_path / f"{quality}.mp4", fps=30.0, size=(320, 240), quality=quality)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"인코더 없음: {e}")
    for i in range(n):
        rec.feed(_noisy(i))
        time.sleep(1 / 30)
    path, count, _ = rec.stop()
    assert rec.wait_finalized(30)
    return path, count


def test_both_modes_record_playable_files_and_high_is_finer(tmp_path):
    import imageio.v2 as iio
    sizes = {}
    for q in ("normal", "high"):
        path, count = _record(tmp_path, q)
        r = iio.get_reader(path)
        assert r.count_frames() == count > 0
        r.close()
        sizes[q] = os.path.getsize(path)
    assert sizes["high"] > sizes["normal"], sizes        # 고화질 = 덜 압축


def test_config_video_quality_validated(app_env):
    p = AppConfig.config_path()
    for v, want in (("high", "high"), ("normal", "normal"), ("ultra", "normal"), ("", "normal")):
        p.write_text(json.dumps({"video_quality": v}), encoding="utf-8")
        assert AppConfig.load().video_quality == want
    p.write_text("{}", encoding="utf-8")
    assert AppConfig.load().video_quality == "normal"   # 기본은 일반 (동영상은 보조 기록)


def test_settings_dialog_round_trip(qtbot, app_env):
    from app.ui.settings_dialog import SettingsDialog
    config, _ = app_env
    config.video_quality = "high"
    dlg = SettingsDialog(config)
    qtbot.addWidget(dlg)
    assert dlg.video_quality.currentData() == "high"
    dlg.video_quality.setCurrentIndex(dlg.video_quality.findData("normal"))
    dlg.apply_to_config()
    assert config.video_quality == "normal"


def test_main_window_records_in_chosen_mode(qtbot, app_env):
    from app.models.patient import Patient
    from app.ui.main_window import MainWindow
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 320, 240
    config.video_quality = "high"
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="VQ1", name="화질"))
    w = MainWindow(config, db)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitUntil(lambda: w._last_frame is not None, timeout=8000)
    p = db.patients.list_all()[0]
    w._on_patient_changed(p)
    w.control_bar.btn_record.setChecked(True)
    assert w.recorder._quality == "high"
    qtbot.wait(400)
    w.control_bar.btn_record.setChecked(False)
    qtbot.waitUntil(lambda: w._pending_video is None, timeout=20000)
    vids = [c for c in db.captures.list_by_patient(p.id) if c.media_type == "video"]
    assert len(vids) == 1
    w.close()
