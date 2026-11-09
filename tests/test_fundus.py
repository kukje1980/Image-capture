"""안저 기능 (데스크탑): C/D 비 · 좌우 비교 · 촬영 부위 메모 · Red-free 보기 · 원형 가이드."""
from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui.pro.image_canvas import ImageCanvas, cdr_label, cdr_ratios


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def test_cdr_ratio_and_canvas(qapp):
    a = {"kind": "cdr", "x1": 100, "y1": 100, "x2": 200, "y2": 220, "x3": 130, "y3": 130, "x4": 170, "y4": 184}
    v, h = cdr_ratios(a)
    assert v == pytest.approx(54 / 120) and h == pytest.approx(40 / 100)
    assert cdr_label(a) == "C/D 수직 0.45 · 수평 0.40"
    cv = ImageCanvas()
    cv.set_image(np.zeros((300, 400, 3), np.uint8))
    cv.add_cdr({"x1": 100, "y1": 100, "x2": 200, "y2": 220}, {"x1": 130, "y1": 130, "x2": 170, "y2": 184})
    assert cv.annotation_kinds() == ["cdr"]
    assert cv.measurements() == [("cdr", "C/D 수직 0.45 · 수평 0.40")]
    cv.rotate(1)                                         # 90° 회전하면 수직·수평이 바뀜 (좌표가 따라감)
    assert cv.measurements() == [("cdr", "C/D 수직 0.40 · 수평 0.45")]
    assert cv.render_to_bgr() is not None


def test_cdr_tool_two_drags(qapp):
    """① 유두 드래그 → (유두는 남아 있음) ② 함몰 드래그 → C/D 주석 하나."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    cv = ImageCanvas()
    cv.resize(400, 300)
    cv.show()
    cv.set_image(np.zeros((300, 400, 3), np.uint8))
    cv.set_tool("cdr")
    qapp.processEvents()

    def drag(p0, p1):
        vp = cv.viewport()
        for typ, p, btns in ((QEvent.Type.MouseButtonPress, p0, Qt.MouseButton.LeftButton),
                             (QEvent.Type.MouseMove, p1, Qt.MouseButton.LeftButton),
                             (QEvent.Type.MouseButtonRelease, p1, Qt.MouseButton.NoButton)):
            vpos = cv.mapFromScene(QPointF(*p))
            ev = QMouseEvent(typ, QPointF(vpos), QPointF(vp.mapToGlobal(vpos)), Qt.MouseButton.LeftButton,
                             btns, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(vp, ev)
            qapp.processEvents()
    drag((100, 80), (220, 220))
    assert cv.annotation_kinds() == [] and cv._cdr_disc is not None
    drag((140, 120), (180, 180))
    assert cv.annotation_kinds() == ["cdr"] and cv._cdr_disc is None
    (kind, label), = cv.measurements()
    assert kind == "cdr" and label.startswith("C/D 수직 0.4")
    cv.close()


def test_pair_eyes_puts_right_eye_left(qapp, app_env):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    pid = db.patients.insert(Patient(chart_no="P1", name="좌우"))
    p = db.patients.get(pid)
    svc = CaptureService(db, config)
    img = np.zeros((60, 80, 3), np.uint8)
    for e in ("OS", "OD", "OS", "NA"):
        svc.save_photo(img, p, eye=e)
    pro = ProWorkspace(db, svc, config, get_eye=None)
    pro.set_patient(p)
    pro.reload(select_last=False)
    assert pro.pair_eyes()
    a, b = pro._pair
    assert (a.eye, b.eye) == ("OD", "OS") and pro._mode == "compare"
    assert b.id == max(c.id for c in pro._caps if c.eye == "OS")      # 가장 최근 좌안
    empty = db.patients.insert(Patient(chart_no="P2", name="한쪽만"))
    svc.save_photo(img, db.patients.get(empty), eye="OD")
    pro.set_patient(db.patients.get(empty))
    pro.reload(select_last=False)
    assert not pro.pair_eyes()


@pytest.fixture()
def win(qapp, app_env):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 320, 180
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="F1", name="안저"))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.show()
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w
    w.close()


def test_field_note_redfree_and_guide(qapp, win):
    cb = win.control_bar
    cb.field_buttons["황반 중심"].click()
    assert cb.current_field() == "황반 중심" and win.config.capture_field == "황반 중심"
    n0 = win.thumbnail_panel.count()
    win._on_capture()
    assert win.thumbnail_panel.count() == n0 + 1 and win.thumbnail_panel._items[0].note == "황반 중심"
    # Red-free: 화면은 녹색 채널(흑백), 저장 원본은 컬러 그대로
    cb.btn_redfree.click()
    assert win.config.redfree_view and win.video_view._redfree and win.zoom_view._redfree
    frame = np.dstack([np.full((10, 10), 200, np.uint8), np.full((10, 10), 100, np.uint8),
                       np.full((10, 10), 30, np.uint8)])
    shown = win.video_view._display(frame)
    assert (shown[..., 0] == shown[..., 1]).all() and shown[0, 0, 0] == 105     # 100 × 1.15 − 10
    assert frame[0, 0, 2] == 30                                                  # 원본은 그대로
    cb.btn_redfree.click()
    assert not win.config.redfree_view
    cb.btn_guide.setChecked(False)
    assert not win.video_view._guide and not win.config.fundus_guide
    cb.btn_guide.setChecked(True)
    assert win.video_view._guide
