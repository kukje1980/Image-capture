"""촬영 화면 보기 (큰 · 멀티 · 확대 · 3D) + 아래쪽 촬영 이미지 띠."""
from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QScrollArea

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui.surface_view import SurfaceModel, SurfaceView, _background, render_surface
from app.ui.thumbnail_panel import STRIP_H, ThumbnailPanel, day_chip
from app.ui.video_view import ZOOM_MAX, ZOOM_MIN, VideoView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def _eye(w=320, h=180):
    """어두운 배경 + 밝은 세로 띠(슬릿 빔)."""
    f = np.full((h, w, 3), 20, np.uint8)
    f[:, w // 2 - 6: w // 2 + 6] = 240
    return f


# ---- 3D 표면 ----
def test_surface_model_grid_limits():
    m = SurfaceModel(_eye(1920, 1080))
    assert (m.gw, m.gh) == (200, 112) and m.height.shape == (112, 200)
    assert 0.0 <= m.height.min() and m.height.max() <= 1.0
    p = SurfaceModel(_eye(720, 1280))                         # 세로 영상도 긴 변 200
    assert p.gh == 200 and p.gw < 200


def test_render_surface_draws_and_bright_is_higher():
    m = SurfaceModel(_eye())
    bg = _background(320, 180)
    flat = render_surface(m, 320, 180, scale=0.0)
    tall = render_surface(m, 320, 180, scale=0.8)
    assert flat.shape == (180, 320, 3) and flat.dtype == np.uint8
    assert (tall != bg).any(2).mean() > 0.15                  # 표면이 그려짐
    # 높이를 키우면 밝은 띠가 위로 솟아 더 위쪽 줄까지 그려진다
    def top_row(img):
        return int(np.argmax((np.abs(img.astype(int) - bg.astype(int)).sum(2) > 30).any(1)))
    assert top_row(tall) < top_row(flat) - 5
    cmap = render_surface(m, 320, 180, colormap=True)
    assert not np.array_equal(cmap, render_surface(m, 320, 180))


def test_render_surface_budget_keeps_size():
    m = SurfaceModel(_eye(640, 360))
    # 크게 확대 → 작게 그려 키움
    out = render_surface(m, 400, 240, zoom=0.35, pitch=1.2, scale=0.9, budget=20_000)
    assert out.shape == (240, 400, 3)


def test_surface_view_snapshot(qapp):
    v = SurfaceView()
    v.resize(640, 360)
    assert v.snapshot() is None                               # 아직 영상 없음
    v.set_frame(_eye())
    img = v.snapshot(width=640)
    assert img is not None and img.shape == (360, 640, 3)
    v.set_height(2.0)
    assert v.scale == 1.0                                     # 0~1 로 제한
    v.cam["yaw"] = 1.0
    v.reset_view()
    assert v.cam["yaw"] != 1.0


# ---- 확대 화면 ----
def test_zoom_clamp_steps_and_anchor(qapp):
    v = VideoView()
    v.resize(640, 360)
    v.set_frame(np.zeros((360, 640, 3), np.uint8))
    v.set_zoom_mode(True)
    v.set_zoom(100)
    assert v.zoom == ZOOM_MAX
    v.set_zoom(0.1)
    assert v.zoom == ZOOM_MIN
    v.set_zoom(2.0)
    v.step_zoom(1)
    assert v.zoom == 3.0
    v.step_zoom(-1)
    assert v.zoom == 2.0
    # 커서 위치의 영상 지점은 확대해도 그대로
    a = QPointF(480, 90)
    g = v._geom()

    def under(view):
        return (view.cx + (a.x() - g[0] / 2) / (view.zoom * g[4]),
                view.cy + (a.y() - g[1] / 2) / (view.zoom * g[5]))
    before = under(v)
    v.set_zoom(4.0, a)
    assert under(v) == pytest.approx(before)
    # 가장자리 밖으로는 못 나감
    v.cx, v.cy = 2.0, -1.0
    v._clamp_center(v._geom())
    assert v.cx == pytest.approx(1 - 1 / (2 * v.zoom)) and v.cy == pytest.approx(1 / (2 * v.zoom))
    assert v._minimap_rect() is not None
    v.set_zoom_mode(False)
    assert v._minimap_rect() is None


# ---- 아래쪽 촬영 이미지 띠 ----
def test_thumbnail_strip_horizontal_and_fold(qapp, app_env):
    config, db = app_env
    pid = db.patients.insert(Patient(chart_no="H1", name="가로띠"))
    svc = CaptureService(db, config)
    for e in ("OD", "OS"):
        svc.save_photo(np.zeros((60, 80, 3), np.uint8), db.patients.get(pid), eye=e)
    panel = ThumbnailPanel(db)
    panel.set_patient(pid)
    scroll = panel.findChild(QScrollArea)
    assert scroll.verticalScrollBarPolicy().name == "ScrollBarAlwaysOff"
    assert panel.height() == STRIP_H or panel.maximumHeight() == STRIP_H
    seen = []
    panel.foldedChanged.connect(seen.append)
    panel.set_folded(True)
    assert panel.is_folded() and panel.maximumHeight() < STRIP_H and seen == [True]
    panel.set_folded(False)
    assert panel.maximumHeight() == STRIP_H
    assert day_chip("2026-10-23", 5) == "2026\n10.23\n금 · 5장"


# ---- 메인 창: 보기 전환 · 3D 저장 · 확대에서도 원본 저장 ----
@pytest.fixture()
def win(qapp, app_env):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 640, 360
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="V1", name="보기"))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.resize(1100, 800)
    w.show()
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w
    w.close()


def test_layout_strip_below_video(qapp, win):
    """보기 막대 → 영상 → 도크 → 촬영 이미지 띠 (위에서 아래로)."""
    qapp.processEvents()
    parts = (win.view_bar, win.stage, win.control_bar, win.thumbnail_panel)
    y = [w.mapTo(win, w.rect().topLeft()).y() for w in parts]
    assert y == sorted(y)
    assert win.thumbnail_panel.width() > win.stage.width() * 0.9           # 띠가 화면 폭 전체


def test_views_capture_and_3d_save(qapp, win):
    n0 = win.thumbnail_panel.count()
    win._set_view("zoom")
    win.zoom_view.set_zoom(4.0)
    win._on_capture()                                 # 확대 화면에서도 원본 전체 프레임 저장
    assert _wait(qapp, lambda: win.thumbnail_panel.count() == n0 + 1)
    cap = win.thumbnail_panel._items[0]
    import cv2
    assert cv2.imread(cap.file_path).shape[:2] == win._last_frame.shape[:2]
    assert win.config.zoom_level == 4.0
    win._set_view("3d")
    assert _wait(qapp, lambda: win.surface_view.has_image())
    win._on_d3_save()
    assert win.thumbnail_panel.count() == n0 + 2
    assert win.thumbnail_panel._items[0].note == "3D"
    win._set_view("multi")
    assert win._quad and win.control_bar.btn_save_quad.isVisible()
    win._set_view("single")
    assert not win._quad and win.control_bar.btn_pause.isVisible()


def test_all_view_big_plus_three_panes(qapp, win):
    """모두 보기: 왼쪽 큰 화면(라이브) + 오른쪽 작은 화면 3개(멀티 · 확대 · 3D)가 함께."""
    win._set_view("all")
    assert _wait(qapp, lambda: win.surface_view.has_image()
                 and win.zoom_view.current_frame() is not None)
    qapp.processEvents()
    for w in (win.video_view, win.quad_view, win.zoom_view, win.surface_view):
        assert w.isVisible()
    big = win.video_view.mapTo(win, win.video_view.rect().topLeft())
    panes = (win.quad_view, win.zoom_view, win.surface_view)
    for w in panes:                                       # 작은 화면은 오른쪽에, 위에서 아래로
        assert w.mapTo(win, w.rect().topLeft()).x() > big.x() + win.video_view.width() * 0.9
        assert w.width() < win.video_view.width()
    ys = [w.mapTo(win, w.rect().topLeft()).y() for w in panes]
    assert ys == sorted(ys)
    assert win._quad and not win._paused              # 멀티 칸 채우기 + 큰 화면은 라이브
    # 큰 화면을 누른 곳이 확대 칸의 가운데로, 큰 화면에는 그 영역 표시
    win.zoom_view.set_zoom(4.0)
    win.video_view.pointed.emit(0.8, 0.3)
    x0, y0, x1, y1 = win.zoom_view.visible_rect()
    assert (x0 + x1) / 2 == pytest.approx(0.8, abs=0.02)
    assert (y0 + y1) / 2 == pytest.approx(0.3, abs=0.02)
    assert win.video_view._roi == pytest.approx((x0, y0, x1, y1))
    # 작은 화면 제목 → 그 화면 크게, 내용(4분할)은 이어짐
    win._on_freeze()
    filled = list(win.quad_view._frozen)
    win.stage.pane_head("multi").click()
    assert win.current_view() == "multi" and win.quad_view._frozen == filled
    win._set_view("all")
    assert win.config.capture_view == "all"
    win._set_view("single")
    assert win.video_view._roi is None and not win.quad_view.isVisible()
