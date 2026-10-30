"""디자인 개편(Clinical Graphite) UI 구성 요소 테스트."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui import icons
from app.ui.control_bar import ControlBar
from app.ui.patient_panel import PatientPanel, age_of
from app.ui.theme import build_qss
from app.ui.thumbnail_panel import ThumbnailPanel, day_label


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_icons_render_all(qapp):
    assert len(icons.names()) >= 40
    for n in icons.names():
        assert not icons.pixmap(n, "#ffffff", 16).isNull(), n
    assert icons.gap("저장") == " 저장" and icons.gap("") == ""


def test_qss_both_themes(qapp):
    for mode in ("dark", "light"):
        qss = build_qss(mode)
        assert "QPushButton#Shutter" in qss and "QPushButton#EyeBtn" in qss
        qapp.setStyleSheet(qss)                               # 파싱 오류 없이 적용


def test_age_and_day_label():
    assert age_of("1968-03-15", date(2026, 3, 14)) == 57
    assert age_of("1968-03-15", date(2026, 3, 15)) == 58
    assert age_of("bad") is None and age_of(None) is None
    assert day_label("2026-10-23") == "2026.10.23 (금)"


def test_eye_segment_syncs_combo(qapp):
    bar = ControlBar()
    seen = []
    bar.eyeChanged.connect(seen.append)
    bar.eye_buttons["OS"].click()
    assert bar.current_eye() == "OS" and seen[-1] == "OS"
    bar.set_eye("OD")
    assert bar.eye_buttons["OD"].isChecked()
    bar.set_freeze_state(True)
    assert "라이브" in bar.btn_freeze.text()


def test_banner_shows_patient_summary(qapp, app_env):
    _config, db = app_env
    db.patients.insert(Patient(chart_no="C9", name="홍길동", sex="M", birth_date="1970-01-01",
                               diagnosis="각막염", doctor="이의사"))
    panel = PatientPanel(db)
    assert panel.lbl_name.text() == "홍길동"
    assert panel.lbl_chart.text() == "#C9"
    meta = panel.lbl_meta.text()
    assert "각막염" in meta and "이의사" in meta and "남" in meta
    assert panel.avatar.text() == "홍"


def test_thumbnail_filter_and_day_groups(qapp, app_env):
    config, db = app_env
    pid = db.patients.insert(Patient(chart_no="T1", name="썸네일"))
    p = db.patients.get(pid)
    svc = CaptureService(db, config)
    img = np.zeros((60, 80, 3), np.uint8)
    for e in ("OD", "OS", "OD"):
        svc.save_photo(img, p, eye=e)
    panel = ThumbnailPanel(db)
    panel.set_patient(pid)
    assert panel.count() == 3 and len(panel.visible_captures()) == 3
    panel.set_filter("OD")
    assert [c.eye for c in panel.visible_captures()] == ["OD", "OD"]
    panel.set_filter("video")
    assert panel.visible_captures() == []
    panel.set_filter("all")
    cap = svc.save_photo(img, p, eye="OS")
    panel.add_capture(cap)
    assert panel.count() == 4 and panel.visible_captures()[0].id == cap.id   # 최신이 위


def _three_photos(app_env):
    config, db = app_env
    pid = db.patients.insert(Patient(chart_no="SEL", name="선택"))
    p = db.patients.get(pid)
    svc = CaptureService(db, config)
    img = np.zeros((60, 80, 3), np.uint8)
    caps = [svc.save_photo(img, p, eye=e) for e in ("OD", "OS", "OD")]
    return config, db, p, svc, caps


def test_thumbnail_select_toggle_and_bar(qapp, app_env):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    config, db, p, svc, caps = _three_photos(app_env)
    panel = ThumbnailPanel(db)
    panel.set_patient(p.id)
    panel.resize(248, 700)
    panel.show()
    qapp.processEvents()
    seen = []
    panel.selectionChanged.connect(seen.append)
    assert panel.selected_count() == 0 and panel.select_bar.isHidden()

    w = panel._widgets[caps[0].id]
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))     # 왼쪽 클릭 → 선택
    assert panel.is_selected(caps[0]) and w.is_selected() and seen[-1] == 1
    assert panel.select_bar.isVisible() and "1장" in panel.lbl_selected.text()
    panel.toggle_selected(caps[1])
    assert [c.id for c in panel.selected_captures()] == [caps[1].id, caps[0].id]   # 목록 순서(최신 위)
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))     # 다시 클릭 → 해제
    assert not panel.is_selected(caps[0]) and panel.selected_count() == 1

    # 더블클릭은 크게 보기 신호
    opened = []
    panel.thumbnailClicked.connect(opened.append)
    QTest.mouseDClick(w, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert opened and opened[-1].id == caps[0].id

    # 필터를 바꿔 다시 그려도 선택은 유지, 환자가 바뀌면 해제
    panel.set_filter("OS")
    assert panel.is_selected(caps[1]) and panel._widgets[caps[1].id].is_selected()
    panel.select_all()
    assert panel.selected_count() == 1                   # 보이는 것(OS 1장)만 → 이미 선택됨
    panel.set_filter("all")
    panel.select_all()
    assert panel.selected_count() == 3
    panel.clear_selection()
    assert panel.selected_count() == 0 and panel.select_bar.isHidden()
    panel.set_selected(caps[0], True)
    panel.set_patient(None)
    assert panel.selected_count() == 0


def test_thumbnail_context_menu_send_delete(qapp, app_env):
    config, db, p, svc, caps = _three_photos(app_env)
    panel = ThumbnailPanel(db, delete_after_send=False)
    panel.set_patient(p.id)
    sent, deleted, toggled = [], [], []
    panel.sendRequested.connect(sent.append)
    panel.deleteRequested.connect(deleted.append)
    panel.deleteAfterSendToggled.connect(toggled.append)

    # 선택이 없을 때 빈 곳 오른쪽 클릭: 보내기/삭제는 비활성
    m = panel.build_menu()
    a = panel.menu_actions
    assert not a["send"].isEnabled() and not a["delete"].isEnabled() and a["select_all"].isEnabled()
    assert not a["send"].icon().isNull() and not a["delete"].icon().isNull()
    assert not a["delete_after_send"].isChecked()
    m.deleteLater()

    # 선택되지 않은 썸네일을 오른쪽 클릭 → 그 항목이 선택되고 메뉴 활성
    m = panel.build_menu(caps[1])
    a = panel.menu_actions
    assert panel.is_selected(caps[1]) and a["send"].isEnabled() and "(1장)" in a["send"].text()
    a["send"].trigger()
    assert sent and [c.id for c in sent[-1]] == [caps[1].id]
    a["delete"].trigger()
    assert deleted and [c.id for c in deleted[-1]] == [caps[1].id]
    a["delete_after_send"].trigger()
    assert toggled == [True] and panel.delete_after_send is True
    m.deleteLater()

    # 선택 막대 버튼도 같은 신호
    panel.set_selected(caps[0], True)
    panel.btn_send.click()
    assert len(sent[-1]) == 2
    panel.btn_clear.click()
    assert panel.selected_count() == 0

    # remove_captures 는 목록·선택에서 제거
    panel.set_selected(caps[2], True)
    panel.remove_captures([caps[2]])
    assert panel.count() == 2 and panel.selected_count() == 0 and caps[2].id not in panel._widgets


def test_main_window_send_and_delete_flow(qapp, app_env, monkeypatch):
    """메인 윈도우: 보내기(자동 삭제 켬/끔)와 삭제 확인까지 실제 파일·DB 로 검증."""
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from app.ui.main_window import MainWindow

    config, db = app_env
    config.source_mode = "synthetic"
    config.export_on_capture = False
    pid = db.patients.insert(Patient(chart_no="MW1", name="메인"))
    p = db.patients.get(pid)
    svc = CaptureService(db, config)
    img = np.zeros((60, 80, 3), np.uint8)
    caps = [svc.save_photo(img, p, eye="OD") for _ in range(3)]
    assert all(c.export_path is None for c in caps)

    win = MainWindow(config, db)
    try:
        win.thumbnail_panel.set_patient(pid)
        panel = win.thumbnail_panel
        assert panel.count() == 3

        # 1) 원본 남김
        config.send_delete_after = False
        panel.set_selected(caps[0], True)
        panel.btn_send.click()
        c0 = db.captures.get(caps[0].id)
        assert c0.export_path and Path(c0.export_path).exists() and Path(c0.file_path).exists()
        assert panel.count() == 3 and panel.selected_count() == 0

        # 2) 메뉴에서 '보내기 후 원본 삭제' 켬 → 설정에 저장되고, 보내면 원본·목록에서 사라짐
        m = panel.build_menu(caps[1])
        panel.menu_actions["delete_after_send"].trigger()
        m.deleteLater()
        assert config.send_delete_after is True
        from app.config import AppConfig
        assert AppConfig.load().send_delete_after is True
        panel.btn_send.click()
        assert db.captures.get(caps[1].id) is None
        assert not Path(caps[1].file_path).exists()
        exported = list(Path(config.export_root).rglob(Path(caps[1].file_path).name))
        assert len(exported) == 1
        assert panel.count() == 2

        # 3) 삭제: 취소 → 유지, 삭제 → 제거
        monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
        panel.set_selected(caps[2], True)
        panel.btn_delete.click()
        assert db.captures.get(caps[2].id) is not None and panel.count() == 2
        monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
        panel.btn_delete.click()
        assert db.captures.get(caps[2].id) is None and not Path(caps[2].file_path).exists()
        assert panel.count() == 1
    finally:
        win.close()
