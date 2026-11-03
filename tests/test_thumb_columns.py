"""v1.19.3 촬영 화면 사진 목록: 여러 장(1 · 2 · 3열, 최신순) + 사진 위 큰 안구 배지(OD/OS/OU/미지정).

멀티(클릭 선택 → '멀티' → 멀티 화면에서 편집)는 v1.15 ~ v1.18 기능 그대로 — 여기서는 열 · 배지 · 좁은 창만 본다.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui.thumbnail_panel import PANEL_WIDTH, ThumbnailPanel
from app.ui.thumbnail_widget import eye_label
from tests.test_references import _make_window, _wait


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _photos(app_env, eyes=("OD", "OS", "OD", "NA", "OU")):
    config, db = app_env
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="TC1", name="열환자"))
    p = db.patients.get(pid)
    img = np.zeros((60, 80, 3), np.uint8)
    caps = [svc.save_photo(img + k * 20, p, eye=e) for k, e in enumerate(eyes)]
    return db, p, caps


def test_eye_label_on_every_photo():
    assert [eye_label(e)[0] for e in ("OD", "OS", "OU")] == ["OD", "OS", "OU"]
    assert eye_label("NA")[0] == "미지정" and eye_label(None)[0] == "미지정"     # 안 정한 사진도 표시
    assert len({eye_label(e)[1] for e in ("OD", "OS", "OU", "NA")}) == 4           # 색이 서로 다름


def test_columns_grid_newest_first(qapp, app_env):
    db, p, caps = _photos(app_env)
    panel = ThumbnailPanel(db, columns=2)
    panel.resize(PANEL_WIDTH[2], 900)
    panel.set_patient(p.id)
    panel.show()
    qapp.processEvents()
    assert panel.width() == PANEL_WIDTH[2] and panel.btn_cols.text() == "2열"
    shown = panel.visible_captures()
    assert [c.id for c in shown] == [c.id for c in reversed(caps)]                # 최신 사진부터
    w = [panel._widgets[c.id] for c in shown]
    assert w[0].y() == w[1].y() and w[0].x() < w[1].x() and w[2].y() > w[0].y()   # 한 줄에 2장

    # 열 버튼: 2 → 3 → 1 → 2, 패널 폭도 함께 · 고른 값을 알림(설정 저장용)
    seen = []
    panel.columnsChanged.connect(seen.append)
    panel.btn_cols.click()
    qapp.processEvents()
    assert panel.columns() == 3 and panel.width() == PANEL_WIDTH[3]
    w = [panel._widgets[c.id] for c in shown]
    assert w[0].y() == w[1].y() == w[2].y() and w[3].y() > w[0].y()               # 한 줄에 3장
    panel.btn_cols.click()
    assert panel.columns() == 1 and panel.width() == PANEL_WIDTH[1]
    panel.btn_cols.click()
    assert seen == [3, 1, 2]

    # 클릭 선택 · 번호는 여러 열에서도 그대로 (v1.15 멀티)
    QTest.mouseClick(panel._widgets[shown[3].id], Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel._widgets[shown[0].id], Qt.MouseButton.LeftButton)
    assert [c.id for c in panel.selected_captures()] == [shown[3].id, shown[0].id]
    assert panel._widgets[shown[3].id].rank() == 1
    panel.set_columns(3)                                                            # 다시 그려도 선택 유지
    assert panel._widgets[shown[0].id].rank() == 2

    # OD · OS 나눠 보기에서도 격자
    panel.set_split_eyes(True)
    panel.set_columns(2)
    qapp.processEvents()
    od = [c for c in shown if c.eye == "OD"]
    a, b = panel._widgets[od[0].id], panel._widgets[od[1].id]
    assert a.y() == b.y() and a.x() < b.x()
    panel.close()


def test_window_too_narrow_uses_fewer_columns(qapp, app_env):
    panel = ThumbnailPanel(app_env[1], columns=3)
    panel.set_max_columns(1)                                       # 좁은 창: 1열(예전 폭)로
    assert panel.columns() == 3 and panel.effective_columns() == 1 and panel.width() == PANEL_WIDTH[1]
    assert "창이 좁아" in panel.btn_cols.toolTip()
    panel.set_max_columns(3)
    assert panel.effective_columns() == 3 and panel.width() == PANEL_WIDTH[3]


def test_config_keeps_columns(app_env):
    config, _ = app_env
    config.thumb_columns = 3
    config.save()
    assert AppConfig.load().thumb_columns == 3
    config.thumb_columns = 7                                       # 쓸 수 없는 값은 기본값(2)으로
    config.save()
    assert AppConfig.load().thumb_columns == 2


def test_main_window_columns_follow_window_width(qapp, app_env, monkeypatch):
    w = _make_window(qapp, app_env, monkeypatch)
    try:
        tp = w.thumbnail_panel
        assert tp.columns() == 2                                   # 기본 2열
        w.thumbnail_panel.btn_cols.click()                         # → 3열, 설정에 저장
        assert w.config.thumb_columns == 3
        w.resize(1900, 1000)
        assert _wait(qapp, lambda: tp.effective_columns() == 3, 3.0)
        full = w._dock_scroll._full_w
        assert w.width() - tp.width() - w._dock_overhead >= full   # 넓혀도 도크는 제 크기 그대로
        w.resize(w.minimumSizeHint().width(), 760)                 # 가장 좁게 → 1열 (예전 폭)
        assert _wait(qapp, lambda: tp.effective_columns() == 1, 3.0)
        assert tp.width() == PANEL_WIDTH[1] and tp.columns() == 3  # 고른 값은 그대로
        w.resize(1900, 1000)
        assert _wait(qapp, lambda: tp.effective_columns() == 3, 3.0)
    finally:
        w.close()
