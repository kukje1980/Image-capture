"""상단 메뉴 · 촬영 도크 버튼이 실제 마우스 클릭을 받는지, 설정 창 바로 실행, Smart 줄 숨기기, 4분할 초기화."""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.models.patient import Patient
from app.ui.icon_button import IconTextButton


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
def win(qapp, app_env, monkeypatch):
    config, db = app_env
    config.source_mode = "synthetic"
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="B1", name="버튼"))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.control_bar.count_chooser = lambda anchor: 4      # 테스트: 칸 수 고르기 창 대신 4칸
    w.resize(1400, 820)
    w.show()
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_icon_button_api_and_click(qapp):
    from app.ui import icons
    b = IconTextButton("녹화", icons.icon("rec", "#ff0000", 22), 22)
    b.setCheckable(True)
    hits = []
    b.clicked.connect(lambda *_: hits.append(1))
    b.resize(80, 56)
    b.show()
    qapp.processEvents()
    # 글자·아이콘 라벨 위를 눌러도 버튼이 받는다
    for lb in (b._ic, b._tx):
        QTest.mouseClick(b, Qt.MouseButton.LeftButton, pos=lb.geometry().center())
    assert len(hits) == 2 and b.isChecked() is False            # 두 번 눌러 켜졌다 꺼짐
    b.setText("녹화 중지")
    assert b.text() == "녹화 중지" and not b.icon().isNull()
    b.setEnabled(False)
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    assert len(hits) == 2
    b.close()


def test_top_menu_clicks_switch_screens(qapp, win):
    for name, mode in (("btn_mode_exam", "exam"), ("btn_mode_pro", "pro"), ("btn_mode_home", "home"),
                       ("btn_mode_capture", "capture")):
        QTest.mouseClick(getattr(win, name), Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert win.mode() == mode, name
    for gone in ("btn_camera", "btn_keys", "btn_samples", "btn_theme"):   # 설정 창 안으로 옮김
        assert not hasattr(win, gone)


def test_settings_holds_camera_shortcuts_samples_theme(qapp, win, monkeypatch):
    from app.ui import main_window as mw
    calls = []
    monkeypatch.setattr(win, "_restart_camera", lambda: calls.append("camera"))
    monkeypatch.setattr(win, "_open_shortcuts", lambda parent=None: calls.append(("shortcuts", type(parent).__name__)))
    monkeypatch.setattr(win, "_import_samples", lambda parent=None: calls.append(("samples", type(parent).__name__)))
    seen = {}

    def fake_exec(dlg):
        seen["dlg"] = dlg
        for b in (dlg.btn_camera, dlg.btn_shortcuts, dlg.btn_samples):
            assert b.isEnabled()
            QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        dlg.theme.setCurrentIndex(dlg.theme.findData("light"))
        dlg.smart_visible.setChecked(False)
        dlg.start_home.setChecked(False)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(mw.SettingsDialog, "exec", fake_exec)
    QTest.mouseClick(win.btn_settings, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert calls[0] == "camera"
    assert ("shortcuts", "SettingsDialog") in calls and ("samples", "SettingsDialog") in calls
    assert "카메라를 다시 연결" in seen["dlg"].quick_status.text()
    cfg = win.config
    assert cfg.theme == "light" and cfg.smart_bar_visible is False and cfg.start_screen == "capture"
    assert not win.smart_bar.isVisibleTo(win) and not win.control_bar.btn_smart.isChecked()
    assert win.home.chk_skip.isChecked()


def test_smart_bar_hide_and_show(qapp, win):
    assert win.smart_bar.isVisibleTo(win) and win.control_bar.btn_smart.isChecked()
    QTest.mouseClick(win.smart_bar.btn_hide, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert not win.smart_bar.isVisibleTo(win) and not win.control_bar.btn_smart.isChecked()
    assert win.config.smart_bar_visible is False
    QTest.mouseClick(win.control_bar.btn_smart, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert win.smart_bar.isVisibleTo(win) and win.config.smart_bar_visible is True
    win._set_fullscreen(True)                       # 전체 화면에서는 숨고, 나오면 설정대로
    assert not win.smart_bar.isVisibleTo(win)
    win._set_fullscreen(False)
    assert win.smart_bar.isVisibleTo(win)


def test_quad_full_then_start_over_and_reset_on_toggle(qapp, win):
    cb, qv = win.control_bar, win.quad_view
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)
    assert win._quad and cb.btn_clear_quad.isVisible()
    for _ in range(4):
        assert _wait(qapp, lambda: qv._active is not None and qv._frames[qv._active] is not None)
        QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)
    assert qv.is_full() and cb.btn_freeze.text() == "처음부터"
    QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)          # 다 찬 뒤 누르면 전체 초기화
    assert not qv.has_any() or not any(qv._frozen)
    assert cb.btn_freeze.text() == "정지영상" and qv._active == 0
    # 한 칸 채운 뒤 비우기
    assert _wait(qapp, lambda: qv._frames[0] is not None)
    QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)
    assert qv._frozen[0]
    QTest.mouseClick(cb.btn_clear_quad, Qt.MouseButton.LeftButton)
    assert not any(qv._frozen)
    # 채운 채로 4분할을 껐다 켜면 초기화
    assert _wait(qapp, lambda: qv._frames[0] is not None)
    QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)
    assert not win._quad
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)
    assert win._quad and not any(qv._frozen) and qv._active == 0
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)


def _photos(win, n, eyes=("OD", "OS")):
    import numpy as np
    from app.services.capture_service import CaptureService
    svc = CaptureService(win.db, win.config)
    p = win._current_patient
    caps = []
    for i in range(n):
        img = np.full((120, 160, 3), 40 + i * 30, np.uint8)
        caps.append(svc.save_photo(img, p, eye=eyes[i % len(eyes)]))
    win.thumbnail_panel.set_patient(p.id)
    qapp = QApplication.instance()
    for _ in range(5):
        qapp.processEvents()
    return caps


def test_thumbnail_click_selects_double_click_opens(qapp, win, monkeypatch):
    caps = _photos(win, 3)
    opened = []
    monkeypatch.setattr(win, "_on_thumbnail_clicked", lambda c: opened.append(c.id))
    win.thumbnail_panel.thumbnailClicked.disconnect()
    win.thumbnail_panel.thumbnailClicked.connect(win._on_thumbnail_clicked)
    w0 = win.thumbnail_panel._widgets[caps[0].id]
    w2 = win.thumbnail_panel._widgets[caps[2].id]
    QTest.mouseClick(w0, Qt.MouseButton.LeftButton)
    QTest.mouseClick(w2, Qt.MouseButton.LeftButton)
    assert [c.id for c in win.thumbnail_panel.selected_captures()] == [caps[0].id, caps[2].id]
    assert w0.rank() == 1 and w2.rank() == 2 and opened == []
    QTest.mouseClick(w0, Qt.MouseButton.LeftButton)                     # 다시 누르면 선택 해제
    assert w0.rank() == 0 and w2.rank() == 1
    QTest.qWait(QApplication.doubleClickInterval() + 400)               # 앞 클릭과 이어지지 않게
    QTest.mouseDClick(w0, Qt.MouseButton.LeftButton)                    # 두 번 클릭 = 크게 보기, 선택은 그대로
    assert opened == [caps[0].id] and w0.rank() == 0


def test_multi_view_select_save_and_reset(qapp, win):
    caps = _photos(win, 3)
    cb, panel = win.control_bar, win.thumbnail_panel
    QTest.mouseClick(cb.btn_multi, Qt.MouseButton.LeftButton)           # 고른 사진이 없으면 켜지지 않음
    assert not win._multi and not cb.btn_multi.isChecked()
    for c in caps:
        QTest.mouseClick(panel._widgets[c.id], Qt.MouseButton.LeftButton)
    QTest.mouseClick(cb.btn_multi, Qt.MouseButton.LeftButton)
    assert win._multi and win.view_stack.currentIndex() == 2 and win.multi_view.count() == 3
    assert cb.btn_save_multi.isVisible() and cb.btn_freeze.isVisible() and not cb.btn_freeze.isEnabled()
    comp = win.multi_view.composite()
    assert comp is not None and comp.shape[1] > comp.shape[0]          # 3장 → 2×2 격자
    n0 = panel.count()
    QTest.mouseClick(cb.btn_save_multi, Qt.MouseButton.LeftButton)      # 멀티 화면 저장
    assert panel.count() == n0 + 1
    saved = win.db.captures.list_by_patient(win._current_patient.id)[0]
    assert saved.note == "멀티 3장"
    assert [c.id for c in panel.selected_captures()] == [c.id for c in caps]   # 저장 후에도 선택 유지
    QTest.mouseClick(cb.btn_multi, Qt.MouseButton.LeftButton)           # 다시 누르면 초기화
    assert not win._multi and win.view_stack.currentIndex() == 0
    assert panel.selected_captures() == [] and win.multi_view.count() == 0


def test_dock_buttons_do_not_move_when_labels_change(qapp, win):
    cb = win.control_bar
    pos = {n: getattr(cb, n).geometry().topLeft() for n in ("btn_freeze", "btn_capture", "btn_record")}
    widths = {n: getattr(cb, n).width() for n in pos}
    QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)          # 정지영상 → 라이브
    qapp.processEvents()
    assert cb.btn_freeze.text() == "라이브"
    for n in pos:
        assert getattr(cb, n).geometry().topLeft() == pos[n] and getattr(cb, n).width() == widths[n], n
    QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)
    assert not cb.status.isVisible()                                     # 녹화 오른쪽 안내 글자 없음


def test_ou_removed_from_choices(qapp, win):
    from app import shortcuts
    assert set(win.control_bar.eye_buttons) == {"OD", "OS", "NA"}
    assert "eyeOU" not in shortcuts.defaults()
    assert [win.pro.c_eye.itemText(i) for i in range(win.pro.c_eye.count())] == ["안구 미지정", "OD 우안", "OS 좌안"]
    win.control_bar.set_eye("OU")                                        # 예전 값이 와도 무시
    assert win.control_bar.current_eye() in ("NA", "OD", "OS")


def test_patient_search_in_top_bar_and_list_screen(qapp, win):
    from app.models.patient import Patient
    db = win.db
    pid2 = db.patients.insert(Patient(chart_no="B2", name="두번째", sex="F", birth_date="1980-03-15", diagnosis="건성안"))
    win.patient_panel._reload()
    assert win.patient_panel.parentWidget().objectName() == "TopBar"
    assert not win.patient_panel.summary.isVisibleTo(win)
    # 홈 → 환자 목록 타일
    win.set_mode("home")
    QTest.mouseClick(win.home.tiles["patients"], Qt.MouseButton.LeftButton)
    qapp.processEvents()
    pl = win.patient_list
    assert win.mode() == "patients" and win.mode_stack.currentWidget() is pl
    assert pl.table.rowCount() == 2 and pl.badge.text() == "2"
    pl.search.setText("두번")
    assert pl.table.rowCount() == 1 and pl.table.item(0, 4).text() == "건성안"
    pl.table.selectRow(0)
    QTest.mouseClick(pl.btn_go, Qt.MouseButton.LeftButton)              # 촬영 시작
    assert win.mode() == "capture" and win._current_patient.id == pid2
    # 단축키 L 도 환자 목록 화면
    win._run_action("patients")
    assert win.mode() == "patients" and pl.selected_id() == pid2


def test_real_double_click_sequence_keeps_selection(qapp, win):
    """실제 OS 순서(누름 → 뗌 → 두 번 클릭 → 뗌)에서도 선택이 바뀌지 않는다."""
    caps = _photos(win, 2)
    panel = win.thumbnail_panel
    opened = []
    panel.thumbnailClicked.disconnect()
    panel.thumbnailClicked.connect(lambda c: opened.append(c.id))
    w = panel._widgets[caps[0].id]
    QTest.mousePress(w, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton)
    QTest.mouseDClick(w, Qt.MouseButton.LeftButton)
    assert opened == [caps[0].id] and panel.selected_captures() == []


def test_split_counts_and_saved_choice(qapp, win):
    cb, qv = win.control_bar, win.quad_view
    picks = iter([6, None, 16])
    cb.count_chooser = lambda anchor: next(picks)
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)            # 6분할 고름
    assert win._quad and qv.count() == 6 and cb.btn_quad.text() == "6분할"
    for _ in range(6):
        assert _wait(qapp, lambda: qv._active is not None and qv._frames[qv._active] is not None)
        QTest.mouseClick(cb.btn_freeze, Qt.MouseButton.LeftButton)
    assert qv.is_full() and qv.composite().shape[1] == qv._frames[0].shape[1] * 3     # 3×2
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)            # 끄기
    assert not win._quad and cb.btn_quad.text() == "분할"
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)            # 고르기 취소 → 켜지지 않음
    assert not win._quad and not cb.btn_quad.isChecked()
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)            # 16분할
    assert qv.count() == 16 and cb.btn_quad.text() == "16분할"
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)
    win.config.split_count = 8                                           # 저장된 칸 수로 단축키 Q
    win._run_action("quad")
    assert win._quad and qv.count() == 8
    win._run_action("quad")
    assert not win._quad


def test_split_choice_saved_by_menu(qapp, win, monkeypatch):
    monkeypatch.setattr(win, "_exec_menu", lambda menu, pos: menu.actions()[3])     # '8분할' 고름
    assert win._choose_split_count(win.control_bar.btn_quad) == 8 and win.config.split_count == 8
    from app.ui.quad_view import split_grid
    assert [split_grid(n) for n in (2, 4, 6, 8, 16)] == [(2, 1), (2, 2), (3, 2), (4, 2), (4, 4)]


def test_send_to_folder_all_formats(qapp, win, tmp_path, monkeypatch):
    from app.ui import main_window as mw
    from app.ui.send_dialog import SendDialog
    caps = _photos(win, 2)
    win.config.send_method = "folder"
    win.config.send_folder = str(tmp_path / "out")
    win.config.send_formats = ["original", "jpg", "pdf", "dicom"]
    infos = []
    monkeypatch.setattr(SendDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: infos.append(a[2]))
    monkeypatch.setattr(mw.QMessageBox, "exec", lambda self: (infos.append(self.text()), 0)[1])
    QTest.mouseClick(win.control_bar.btn_send, Qt.MouseButton.LeftButton)   # 고른 사진 없음 → 안내
    assert infos and "고른 뒤" in infos[-1]
    for c in caps:
        QTest.mouseClick(win.thumbnail_panel._widgets[c.id], Qt.MouseButton.LeftButton)
    QTest.mouseClick(win.control_bar.btn_send, Qt.MouseButton.LeftButton)
    assert "보냈습니다" in infos[-1]
    files = sorted(p.suffix for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert files.count(".dcm") == 2 and files.count(".jpg") == 2 and files.count(".png") == 2 and files.count(".pdf") == 1
    import pydicom
    dcm = next((tmp_path / "out").rglob("*.dcm"))
    ds = pydicom.dcmread(str(dcm))
    assert ds.Modality == "OP" and ds.PatientName == "버튼"


def test_send_service_pacs_with_local_scp(qapp, win, tmp_path):
    """PACS(DICOM C-STORE) 전송 — 이 PC 에 임시 PACS(Storage SCP)를 띄워 실제로 보내 본다."""
    from types import SimpleNamespace
    from pynetdicom import AE, evt
    from app.analysis import dicom_export
    from app.services import send_service as ss
    caps = _photos(win, 2)
    got = []

    def on_store(event):
        got.append(event.dataset.SOPInstanceUID)
        return 0x0000
    scp = AE(ae_title="TESTPACS")
    scp.add_supported_context(dicom_export.OP_8BIT, "1.2.840.10008.1.2.1")
    scp.add_supported_context("1.2.840.10008.1.1")
    server = scp.start_server(("127.0.0.1", 0), block=False, evt_handlers=[(evt.EVT_C_STORE, on_store)])
    try:
        port = server.server_address[1]
        cfg = SimpleNamespace(send_method="pacs", send_pacs_host="127.0.0.1", send_pacs_port=port,
                              send_pacs_ae="TESTPACS", send_pacs_calling_ae="SLITLAMP", clinic_name="")
        assert ss.test_pacs(cfg) == (True, "연결 성공")
        res = ss.send(caps, win._current_patient, cfg)
        assert res.ok and len(res.sent) == 2 and len(got) == 2
    finally:
        server.shutdown()
    bad = SimpleNamespace(send_method="pacs", send_pacs_host="127.0.0.1", send_pacs_port=1,
                          send_pacs_ae="X", send_pacs_calling_ae="Y", clinic_name="")
    assert ss.test_pacs(bad)[0] is False


def test_settings_send_tab_saves(qapp, app_env):
    from app.ui.settings_dialog import SettingsDialog
    config, _db = app_env
    config.save = lambda: None
    dlg = SettingsDialog(config)
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())][:3] == ["일반", "카메라 · 저장", "전송"]
    dlg.send_method.setCurrentIndex(dlg.send_method.findData("pacs"))
    assert not dlg.send_formats["jpg"].isEnabled() and dlg.send_formats["dicom"].isEnabled()
    dlg.pacs_host.setText("10.0.0.5")
    dlg.pacs_port.setValue(11112)
    dlg.send_formats["dicom"].setChecked(True)
    dlg.apply_to_config()
    assert config.send_method == "pacs" and config.send_pacs_host == "10.0.0.5" and config.send_pacs_port == 11112
    assert "dicom" in config.send_formats


def test_capture_presets_save_switch_and_live_props(qapp, win, monkeypatch):
    from app.capture import presets
    cfg = win.config
    assert win.control_bar.btn_preset.text() == "기본"                   # '기본 (자동)'
    # 지금 설정(피킹 켬 · 6분할 · 밝기 +60)을 '형광' 모드로 저장
    cfg.smart_peaking, cfg.split_count, cfg.camera_props = True, 6, {"brightness": 60}
    assert win._save_current_preset("형광")
    assert win.control_bar.btn_preset.text() == "형광" and cfg.active_preset == "형광"
    # 기본으로 바꾸면 밝기 자동 · 피킹 끔 · 4분할
    assert win.apply_preset(presets.DEFAULT_NAME)
    assert cfg.camera_props == {} and not cfg.smart_peaking and cfg.split_count == 4
    assert not win.smart_bar.btn_peaking.isChecked()
    # 도크 '모드' 메뉴에서 '형광' 고르기 → 카메라 값이 촬영 중에 바로 적용
    names = [p["name"] for p in presets.all_presets(cfg)]
    monkeypatch.setattr(win, "_exec_menu", lambda menu, pos: menu.actions()[names.index("형광")])
    QTest.mouseClick(win.control_bar.btn_preset, Qt.MouseButton.LeftButton)
    assert cfg.active_preset == "형광" and cfg.smart_peaking and cfg.split_count == 6
    assert win.smart_bar.btn_peaking.isChecked() and win.control_bar.split_count == 6
    assert _wait(qapp, lambda: win.worker._source.get_property("brightness") == 60)
    # 해상도가 다른 모드는 카메라를 다시 연다
    w0 = cfg.capture_width
    nw, nh = (1280, 720) if w0 != 1280 else (1920, 1080)
    presets.save(cfg, dict(presets.find(cfg, "형광"), name="다른 해상도", capture_width=nw, capture_height=nh))
    old_worker = win.worker
    assert win.apply_preset("다른 해상도") and win.worker is not old_worker
    assert _wait(qapp, lambda: win._last_frame is not None and win._last_frame.shape[1] == nw, 8)


def test_settings_preset_tab_edit(qapp, app_env):
    from app.capture import presets
    from app.ui.settings_dialog import SettingsDialog
    config, _db = app_env
    config.save = lambda: None
    previews = []
    dlg = SettingsDialog(config, actions={"camera_props": previews.append})
    dlg.show_tab("촬영 모드")
    assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "촬영 모드" and dlg.preset_list.count() == 1
    dlg.btn_p_add.click()                                               # 새 모드
    dlg.p_name.setText("세극 조명")
    dlg._preset_edited(rename=True)
    chk, spin = dlg.p_props["exposure"]
    chk.setChecked(True)
    spin.setValue(-7)
    dlg.p_split.setCurrentIndex(dlg.p_split.findData(8))
    dlg.btn_p_preview.click()
    assert previews == [{"exposure": -7.0}] and dlg.previewed
    dlg.btn_p_use.click()
    dlg.apply_to_config()
    p = presets.find(config, "세극 조명")
    assert p and p["camera_props"] == {"exposure": -7.0} and p["split_count"] == 8
    assert config.active_preset == "세극 조명"
    assert len(presets.all_presets(config)) == 2


def test_center_buttons_stay_put_in_every_mode(qapp, win):
    cb = win.control_bar
    def centers():
        qapp.processEvents()
        return [b.mapTo(cb, b.rect().center()).x() for b in (cb.btn_freeze, cb.btn_capture, cb.btn_record)]
    base = centers()
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)             # 분할: 저장 · 비우기 생김
    assert centers() == base
    QTest.mouseClick(cb.btn_quad, Qt.MouseButton.LeftButton)
    caps = _photos(win, 2)
    for c in caps:
        QTest.mouseClick(win.thumbnail_panel._widgets[c.id], Qt.MouseButton.LeftButton)
    QTest.mouseClick(cb.btn_multi, Qt.MouseButton.LeftButton)            # 멀티: 저장 생김
    assert centers() == base
