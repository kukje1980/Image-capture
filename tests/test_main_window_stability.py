"""메인 창 안정성 — 녹화 중지가 화면을 막지 않고 DB 에 기록, 카메라 오류 뒤 자동 재연결, 창이 먼저 뜸."""
from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from app.models.patient import Patient


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


@pytest.fixture()
def win(qapp, app_env):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 320, 240
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="S1", name="안정성"))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.show()
    assert w._last_frame is None                  # 카메라는 창이 뜬 뒤 이벤트 루프에서 열린다
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w
    w.close()


def test_record_stop_is_async_and_saves(qapp, win):
    n0 = win.thumbnail_panel.count()
    win.control_bar.btn_record.setChecked(True)
    assert win._recording
    _wait(qapp, lambda: False, 0.6)                 # 잠깐 녹화
    t0 = time.time()
    win.control_bar.btn_record.setChecked(False)
    assert time.time() - t0 < 0.3                   # 인코더 종료를 기다리지 않는다 (화면 안 멈춤)
    assert not win._recording and win._finishing is not None
    assert not win.control_bar.btn_record.isEnabled()
    assert _wait(qapp, lambda: win._finishing is None)
    assert win.thumbnail_panel.count() == n0 + 1
    vids = [c for c in win.db.captures.list_by_patient(win._current_patient.id) if c.media_type == "video"]
    assert len(vids) == 1 and vids[0].duration_ms > 0
    assert win.control_bar.btn_record.isEnabled()


def test_gui_acks_frames_so_nothing_queues(qapp, win):
    _wait(qapp, lambda: False, 0.5)
    w = win.worker
    assert w.frames > 5
    # 이벤트 루프가 도는 동안은 대기 프레임이 한 장 이하 — 드롭이 폭주하지 않는다
    assert w.dropped <= w.frames


def test_camera_error_schedules_reconnect(qapp, win):
    win.config.source_mode = "device"               # 재연결은 실제 장치 모드에서만
    win._on_camera_error("카메라 연결이 끊어졌습니다.")
    assert win._reconnect_timer.isActive() and win._reconnect_attempts == 1
    assert "자동 재연결" in win.video_view._placeholder
    win.config.source_mode = "synthetic"
    win._restart_camera()                           # 사용자가 직접 재연결하면 대기 취소
    assert not win._reconnect_timer.isActive() and win._reconnect_attempts == 0


def test_low_disk_space_refuses_recording(qapp, win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui import main_window as mw
    monkeypatch.setattr(mw, "_free_space_mb", lambda _p: 100.0)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    win.control_bar.btn_record.setChecked(True)
    assert not win._recording and not win.control_bar.btn_record.isChecked()
