"""메인 창 동작 안정성: 녹화 파일이 닫힌 뒤에만 DB 기록·export, 카메라 끊김 자동 재연결."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.models.patient import Patient


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


@pytest.fixture()
def win(qapp, app_env):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 160, 120
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="V1", name="녹화"))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.show()
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w
    w.close()


def test_video_record_saves_after_file_closed(qapp, win):
    _, db = win.config, win.db
    win.control_bar.btn_record.click()
    if not win._recording:
        pytest.skip("인코더 없음")
    assert _wait(qapp, lambda: win.recorder.frame_count >= 3)
    win.control_bar.btn_record.click()
    assert _wait(qapp, lambda: win._pending_video is None and not win.recorder.is_finalizing)
    caps = db.captures.list_by_patient(win._current_patient.id)
    assert len(caps) == 1 and caps[0].media_type == "video"
    assert Path(caps[0].file_path).stat().st_size > 0
    assert caps[0].export_path and Path(caps[0].export_path).stat().st_size == Path(caps[0].file_path).stat().st_size


def test_export_waits_for_slow_encoder(qapp, win, monkeypatch):
    """인코더가 파일을 늦게 닫아도 (stop 이 10초 안에 못 기다린 경우) export 복사·DB 기록은 닫힌 뒤에 한다."""
    db = win.db
    rec = win.recorder
    gate = threading.Event()
    real_close = rec._close_writer

    def slow_close():
        gate.wait(20)
        real_close()
    monkeypatch.setattr(rec, "_close_writer", slow_close)
    monkeypatch.setattr(rec, "stop", _patched_stop(rec, join_timeout=0.3))

    win.control_bar.btn_record.click()
    if not win._recording:
        pytest.skip("인코더 없음")
    assert _wait(qapp, lambda: rec.frame_count >= 3)
    win.control_bar.btn_record.click()
    assert win._pending_video is not None and rec.is_finalizing
    assert not win.control_bar.btn_record.isEnabled()
    qapp.processEvents()
    time.sleep(0.5)
    qapp.processEvents()
    assert db.captures.list_by_patient(win._current_patient.id) == []    # 아직 기록하지 않음
    gate.set()
    assert _wait(qapp, lambda: win._pending_video is None)
    caps = db.captures.list_by_patient(win._current_patient.id)
    assert len(caps) == 1 and Path(caps[0].export_path).stat().st_size == Path(caps[0].file_path).stat().st_size
    assert win.control_bar.btn_record.isEnabled()


def _patched_stop(rec, join_timeout):
    """VideoRecorder.stop 과 같지만 스레드 join 시간을 짧게 (테스트에서 10초를 기다리지 않게)."""
    import app.capture.video_recorder as vr

    def stop():
        if not rec._recording:
            return (rec._path or "", 0, 0)
        rec._recording = False
        stop_ts = time.time()
        rec._stop_evt.set()
        rec._queue.put(vr._SENTINEL, timeout=2)
        rec._thread.join(timeout=join_timeout)
        duration_ms = int((stop_ts - rec._start_ts) * 1000)
        return (rec._path or "", rec._count, duration_ms)
    return stop


def test_camera_error_schedules_reconnect_in_device_mode(qapp, win):
    win.config.source_mode = "device"
    win._on_camera_error("카메라 연결이 끊어졌습니다.")
    assert win._reconnect_timer.isActive() and win._reconnect_attempts == 1
    assert "재연결" in win.control_bar.status.text()
    win._on_camera_error("again")                      # 이미 예약돼 있으면 중복 예약하지 않는다
    assert win._reconnect_attempts == 1
    win.config.source_mode = "synthetic"               # (테스트 환경엔 장치가 없으므로 합성 소스로 다시 연다)
    win._restart_camera()                              # 수동 재연결은 자동 예약을 취소한다
    assert not win._reconnect_timer.isActive() and win._reconnect_attempts == 0
    assert _wait(qapp, lambda: win._camera_ok)


def test_camera_error_no_reconnect_for_synthetic(qapp, win):
    win._on_camera_error("x")
    assert not win._reconnect_timer.isActive()


def test_reconnect_backoff_and_reset_on_open(qapp, win):
    win.config.source_mode = "device"
    for _ in range(7):
        win._reconnect_timer.stop()
        win._schedule_reconnect()
    assert win._reconnect_timer.interval() == win._RECONNECT_DELAYS_MS[-1]
    win._reconnect_timer.stop()
    win._on_camera_opened(160, 120, 30.0)
    assert win._reconnect_attempts == 0 and win._camera_ok
    win.config.source_mode = "synthetic"
