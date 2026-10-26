"""Smart Capture 화면 연동: 분석 스레드 · 자동 정지 · 자동 저장 · Best Shot · 피킹 · ROI 지정."""
from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.capture.smart_capture import BestShot, FrameQuality
from app.capture.smart_worker import SmartCaptureWorker
from app.models.patient import Patient


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


@pytest.fixture()
def win(qapp, app_env):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 640, 360
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="S1", name="스마트"))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.show()
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w
    w.close()


def _shot(value: int = 77, pct: float = 96.0) -> BestShot:
    frame = np.full((360, 640, 3), value, np.uint8)
    q = FrameQuality(t=0.0, focus=50.0, focus_pct=pct, usable=True, in_focus=True)
    return BestShot(frame=frame, quality=q, reason="peak")


def test_worker_analyzes_off_thread(qapp):
    w = SmartCaptureWorker()
    got = []
    w.analyzed.connect(got.append)
    w.update(peaking=True)
    w.start()
    try:
        rng = np.random.default_rng(0)
        for i in range(5):
            w.submit((rng.random((360, 640, 3)) * 255).astype(np.uint8), i / 30)
            time.sleep(0.03)
        assert _wait(qapp, lambda: len(got) > 0)
        a = got[-1]
        assert a.quality.focus > 0 and a.peaking is not None and a.peaking.shape == (360, 640, 4)
    finally:
        w.stop()
    assert w._thread is None


def test_auto_freeze_holds_best_frame(qapp, win):
    win.smart_bar.set_mode("freeze")
    assert win.config.smart_mode == "freeze"
    shot = _shot(77)
    win._on_smart_best_shot(shot)
    assert win._single_frozen and win._freeze_frame is shot.frame
    assert "자동 정지" in win.control_bar.status.text()
    qapp.processEvents()
    assert win._freeze_frame is shot.frame                 # 라이브 프레임이 와도 정지 유지
    # 의사가 확인 후 '사진 캡처' → 그 원본 프레임이 저장됨
    win.patient_panel.combo.setCurrentIndex(win.patient_panel.combo.count() - 1)
    n0 = win.thumbnail_panel.count()
    win._on_capture()
    assert win.thumbnail_panel.count() == n0 + 1
    # 이미 정지 중이면 다음 자동 정지는 무시
    win._on_smart_best_shot(_shot(10))
    assert win._freeze_frame is shot.frame
    win._on_freeze()                                       # 라이브로 복귀
    assert not win._single_frozen


def test_auto_freeze_fills_quad_cell(qapp, win):
    win.smart_bar.set_mode("freeze")
    win.control_bar.btn_quad.setChecked(True)
    shot = _shot(55)
    win._on_smart_best_shot(shot)
    assert win.quad_view._frozen[0] and win.quad_view._frames[0] is shot.frame


def test_auto_snapshot_saves_with_note(qapp, win):
    win.smart_bar.set_mode("snapshot")
    win.patient_panel.combo.setCurrentIndex(win.patient_panel.combo.count() - 1)
    assert win._current_patient is not None
    n0 = win.thumbnail_panel.count()
    win._on_smart_best_shot(_shot(90, pct=97))
    assert win.thumbnail_panel.count() == n0 + 1
    caps = win.db.captures.list_by_patient(win._current_patient.id)
    assert any("Smart 자동 저장" in (c.note or "") for c in caps)
    assert not win._single_frozen                          # 자동 저장은 화면을 멈추지 않는다


def test_auto_snapshot_needs_patient(qapp, win):
    win.smart_bar.set_mode("snapshot")
    win._current_patient = None
    win._on_smart_best_shot(_shot())
    assert "환자" in win.control_bar.status.text()


def test_off_mode_ignores_events(qapp, win):
    win.smart_bar.set_mode("off")
    win._on_smart_best_shot(_shot())
    assert not win._single_frozen


def test_manual_capture_uses_best_shot(qapp, win):
    win.config.smart_best_shot = True
    win.patient_panel.combo.setCurrentIndex(win.patient_panel.combo.count() - 1)
    best = _shot(123)
    win.smart.best_recent = lambda seconds=0.6: best
    n0 = win.thumbnail_panel.count()
    win._on_capture()
    assert win.thumbnail_panel.count() == n0 + 1
    caps = win.db.captures.list_by_patient(win._current_patient.id)
    assert any((c.note or "").startswith("Best Shot") for c in caps)


def test_live_analysis_updates_meters_and_peaking(qapp, win):
    win.smart_bar.btn_peaking.setChecked(True)
    assert win.config.smart_peaking
    assert _wait(qapp, lambda: win.video_view._overlay is not None, 8)
    assert _wait(qapp, lambda: "--" not in win.smart_bar.meters["focus"].text(), 8)
    assert win.video_view._roi is not None
    win.smart_bar.btn_peaking.setChecked(False)
    assert win.video_view._overlay is None


def test_roi_drag_sets_config(qapp, win):
    win.smart_bar.btn_roi.setChecked(True)
    v = win.video_view
    qapp.processEvents()
    v.repaint()
    r = v._img_rect
    a = QPointF(r.x() + r.width() * 0.1, r.y() + r.height() * 0.2)
    b = QPointF(r.x() + r.width() * 0.5, r.y() + r.height() * 0.7)
    QTest.mousePress(v, Qt.MouseButton.LeftButton, pos=a.toPoint())
    QTest.mouseMove(v, b.toPoint())
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, pos=b.toPoint())
    roi = win.config.smart_roi
    assert len(roi) == 4 and roi[0] == pytest.approx(0.1, abs=0.02) and roi[2] == pytest.approx(0.4, abs=0.02)
    assert not win.smart_bar.btn_roi.isChecked() and not v._roi_selecting
    assert win.smart.settings().roi == pytest.approx(tuple(roi))


def test_shortcuts_cycle_mode_and_peaking(qapp, win):
    win.smart_bar.set_mode("off")
    QTest.keyClick(win, Qt.Key.Key_S)
    assert win.config.smart_mode == "freeze"
    QTest.keyClick(win, Qt.Key.Key_S)
    assert win.config.smart_mode == "snapshot"
    QTest.keyClick(win, Qt.Key.Key_P)
    assert win.smart_bar.btn_peaking.isChecked()
