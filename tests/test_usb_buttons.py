"""슬릿램프 USB 버튼 (Ctrl+Shift+Alt+F9 녹화 · Ctrl+Shift+Alt+F10 스틸) — 키 이벤트를 흉내 낸 검사.

실제 USB 장치(VID 04D9 / PID 1203)로는 시험하지 않았다: 장치가 보내는 것과 같은 키 조합의 누름 · 뗌 · 자동 반복
이벤트를 Qt 에 직접 넣어 확인한다.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from app import usb_buttons
from app.models.patient import Patient

M = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier
F9, F10 = Qt.Key.Key_F9, Qt.Key.Key_F10


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def _pump(qapp, t=0.1):
    end = time.time() + t
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def _key(target, key, press=True, mods=M, repeat=False):
    t = QEvent.Type.KeyPress if press else QEvent.Type.KeyRelease
    QApplication.sendEvent(target, QKeyEvent(t, key, mods, "", repeat))


def _click(target, key, mods=M):
    _key(target, key, True, mods)
    _key(target, key, False, mods)


# ---------------- 키 조합 · 설정값 ----------------
def test_defaults_and_bad_saved_values():
    class Cfg:
        usb_buttons = {}
    b = usb_buttons.load(Cfg())
    assert b == {"1": {"key": "Ctrl+Shift+Alt+F9", "action": "record"},
                 "2": {"key": "Ctrl+Shift+Alt+F10", "action": "freeze"}}
    Cfg.usb_buttons = {"1": {"key": "F8", "action": "없는동작"}, "2": "망가진 값", "9": {"key": "X"}}
    b = usb_buttons.load(Cfg())
    assert b["1"] == {"key": "F8", "action": "record"} and b["2"]["key"] == "Ctrl+Shift+Alt+F10"
    assert "9" not in b
    assert "capture" in [a for a, _ in usb_buttons.ACTIONS]          # 사진 캡처는 고를 수만 (기본 배정 없음)
    assert all(d["action"] != "capture" for d in usb_buttons.DEFAULTS.values())


def test_key_matching_any_modifier_order():
    k = "Ctrl+Shift+Alt+F9"
    assert usb_buttons.same_key(k, "ctrl+alt+shift+f9") and not usb_buttons.same_key(k, "Ctrl+Shift+Alt+F10")
    assert usb_buttons.matches(k, F9, M)
    assert not usb_buttons.matches(k, F9, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert not usb_buttons.matches(k, F9, Qt.KeyboardModifier.NoModifier)          # F9 만 = 다른 키
    assert not usb_buttons.matches(k, F10, M)
    assert usb_buttons.matches(k, F9, M | Qt.KeyboardModifier.KeypadModifier)     # 키패드 표시는 무시
    assert usb_buttons.key_of(k) == int(F9) and usb_buttons.key_of("") is None


# ---------------- 누름 · 뗌 · 자동 반복 (필터 단독) ----------------
class _Target:
    pass


def _filter(qapp, context=lambda: None, clock=None):
    runs, ignored = [], []
    now = [100.0]
    f = usb_buttons.UsbButtonFilter(usb_buttons.load(_Target()), run=lambda b, a: runs.append((b, a)),
                                    context=context, ignored=lambda b, r: ignored.append((b, r)),
                                    clock=clock or (lambda: now[0]))
    return f, runs, ignored, now


def _ev(f, key, press=True, mods=M, repeat=False):
    t = QEvent.Type.KeyPress if press else QEvent.Type.KeyRelease
    return f.eventFilter(None, QKeyEvent(t, key, mods, "", repeat))


def test_filter_runs_once_per_press_and_needs_release(qapp):
    f, runs, _ign, now = _filter(qapp)
    assert _ev(f, F9) is True                                  # 버튼 1 누름 → 가로채고 실행
    _pump(qapp)
    assert runs == [("1", "record")]
    for _ in range(5):                                         # 길게 누름: 자동 반복
        assert _ev(f, F9, repeat=True) is True
    assert _ev(f, F9) is True                                  # 뗌 없이 다시 온 누름 (중복 신호)
    _pump(qapp)
    assert runs == [("1", "record")] and f.held() == {"1"}
    now[0] += 1.0
    _ev(f, F9, press=False, mods=Qt.KeyboardModifier.NoModifier)   # 조합키를 먼저 놓고 F9 를 떼도 뗌으로
    assert f.held() == set()
    _ev(f, F9)
    _pump(qapp)
    assert runs == [("1", "record"), ("1", "record")]          # 뗀 뒤 다시 누르면 다음 동작
    _ev(f, F9, press=False)
    now[0] += 1.0
    _ev(f, F10)
    _pump(qapp)
    assert runs[-1] == ("2", "freeze")                         # 버튼 2 는 따로


def test_filter_debounce_and_deactivate(qapp):
    f, runs, _ign, now = _filter(qapp)
    _ev(f, F10)
    _ev(f, F10, press=False)
    now[0] += 0.05                                             # 접점 튐: 0.05초 만에 다시 누름
    assert _ev(f, F10) is True
    _pump(qapp)
    assert runs == [("2", "freeze")]
    _ev(f, F10, press=False)
    now[0] += 1.0
    _ev(f, F9)                                                 # 누른 채 다른 프로그램으로 → 뗌을 못 받음
    f.eventFilter(None, QEvent(QEvent.Type.ApplicationDeactivate))
    assert f.held() == set()
    now[0] += 1.0
    _ev(f, F9)
    _pump(qapp)
    assert runs.count(("1", "record")) == 2
    assert _ev(f, Qt.Key.Key_R, mods=Qt.KeyboardModifier.NoModifier) is False   # 다른 키는 그대로 흘려보냄


def test_filter_ignored_context_does_not_run_or_swallow(qapp):
    reason = ["text"]
    f, runs, ignored, now = _filter(qapp, context=lambda: reason[0])
    assert _ev(f, F9) is False                                 # 입력칸 · 다른 화면: 가로채지 않음
    _pump(qapp)
    assert runs == [] and ignored == [("1", "text")]
    _ev(f, F9, press=False)
    reason[0] = None
    now[0] += 1.0
    assert _ev(f, F9) is True
    _pump(qapp)
    assert runs == [("1", "record")]
    f.set_buttons({"1": {"key": "Ctrl+Shift+Alt+F9", "action": "none"}})
    now[0] += 1.0
    _ev(f, F9, press=False)
    _ev(f, F9)
    _pump(qapp)
    assert runs == [("1", "record")]                           # '사용 안 함' 이면 아무것도 안 함


# ---------------- 메인 창 ----------------
@pytest.fixture()
def win(qapp, app_env, monkeypatch):
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 160, 120
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="U1", name="버튼"))
    monkeypatch.setattr(usb_buttons, "MIN_INTERVAL", 0.0)      # 시험에서는 연달아 눌러도 되게 (간격 검사는 위에서)
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w.resize(1400, 820)
    w.show()
    w.activateWindow()
    assert _wait(qapp, lambda: w._last_frame is not None)
    _wait(qapp, lambda: QApplication.activeWindow() is w, 3)
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _target():
    return QApplication.focusWidget() or QApplication.activeWindow()


def test_capture_screen_focus_and_still_button_saves_nothing(qapp, win):
    assert QApplication.focusWidget() is win.video_view            # 시작하면 초점은 영상 (검색칸 아님)
    assert win._usb_context() is None
    n0 = len(win.db.captures.list_by_patient(win._current_patient.id))
    _key(_target(), F10)                                           # 버튼 2 누름 → 스틸 정지
    _pump(qapp)
    assert win._single_frozen
    for _ in range(4):                                             # 누르고 있는 동안 자동 반복 → 그대로
        _key(_target(), F10, repeat=True)
    _pump(qapp)
    assert win._single_frozen
    _key(_target(), F10, press=False)
    assert not win._smart_live()                                   # 정지 중에는 Smart 자동 저장 · 자동 정지가 쉼
    _click(_target(), F10)                                         # 다시 누름 → 라이브로
    _pump(qapp)
    assert not win._single_frozen
    assert len(win.db.captures.list_by_patient(win._current_patient.id)) == n0   # 사진 파일 저장 안 함
    assert "USB 버튼 2" in win.statusBar().currentMessage()


def test_record_button_and_still_during_recording_keeps_video(qapp, win):
    db = win.db
    _click(_target(), F9)                                          # 버튼 1 → 녹화 시작
    _pump(qapp)
    if not win._recording:
        pytest.skip("인코더 없음")
    assert win.control_bar.btn_record.isChecked()
    assert _wait(qapp, lambda: win.recorder.frame_count >= 3)
    _click(_target(), F10)                                         # 녹화 중 버튼 2 → 스틸 정지
    _pump(qapp)
    assert win._single_frozen and win._recording                    # 녹화는 끊기지 않음
    n = win.recorder.frame_count
    assert _wait(qapp, lambda: win.recorder.frame_count >= n + 5)  # 정지 화면 중에도 카메라 프레임은 계속 녹화
    _click(_target(), F10)                                         # 스틸 해제
    _pump(qapp)
    assert not win._single_frozen and win._recording
    _key(_target(), F9)                                            # 버튼 1 길게: 자동 반복이 와도 한 번만 정지
    for _ in range(3):
        _key(_target(), F9, repeat=True)
    _pump(qapp)
    assert not win._recording
    _key(_target(), F9, press=False)
    assert _wait(qapp, lambda: win._pending_video is None and not win.recorder.is_finalizing, 20)
    caps = [c for c in db.captures.list_by_patient(win._current_patient.id) if c.media_type == "video"]
    assert len(caps) == 1 and Path(caps[0].file_path).stat().st_size > 0
    import cv2
    vc = cv2.VideoCapture(caps[0].file_path)                       # 파일이 열리고 프레임이 읽힘 (손상 없음)
    ok, _frame = vc.read()
    frames = int(vc.get(cv2.CAP_PROP_FRAME_COUNT))
    vc.release()
    assert ok and frames >= 8
    assert not [c for c in db.captures.list_by_patient(win._current_patient.id) if c.media_type == "photo"]


def test_not_in_text_input_other_screens_or_dialogs(qapp, win):
    search = win.patient_panel.search
    search.setFocus()
    _pump(qapp)
    assert isinstance(QApplication.focusWidget(), QLineEdit) and win._usb_context() == "text"
    _click(search, F10)
    _pump(qapp)
    assert not win._single_frozen and "입력칸" in win.statusBar().currentMessage()
    QTest.keyClick(search, Qt.Key.Key_Return)                      # 검색 끝(Enter) → 초점이 영상으로
    _pump(qapp)
    assert QApplication.focusWidget() is win.video_view
    _click(_target(), F10)
    _pump(qapp)
    assert win._single_frozen
    _click(_target(), F10)
    _pump(qapp)
    assert not win._single_frozen
    win.set_mode("pro")                                            # 촬영 화면이 아니면 실행 안 함
    _pump(qapp)
    assert win._usb_context() == "screen"
    rec0 = win._recording
    _click(_target(), F9)
    _pump(qapp)
    assert win._recording == rec0 and "촬영 화면에서만" in win.statusBar().currentMessage()
    win.set_mode("capture")
    _pump(qapp)
    assert QApplication.focusWidget() is win.video_view and win._usb_context() is None
    from app.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.config, win)                         # 설정 창이 앞에 있으면 실행 안 함
    dlg.show()
    dlg.activateWindow()
    assert _wait(qapp, lambda: QApplication.activeWindow() is dlg, 3)
    assert win._usb_context() == "window"
    probe = dlg.usb_tab.probe                                      # 설정 창의 '신호 확인' 칸은 받은 신호를 보여 줌
    probe.setFocus()
    _click(probe, F10)
    _pump(qapp)
    assert not win._single_frozen
    assert "버튼 2" in probe.text() and "뗌 확인" in probe.text() and probe.presses == 1
    dlg.close()


def test_settings_tab_change_actions_and_conflicts(qapp, win, monkeypatch):
    from app.ui import main_window as mw
    from app.ui.settings_dialog import SettingsDialog
    from app.ui.shortcuts_dialog import ShortcutsDialog
    warned = []
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    from app.ui import settings_dialog as sd
    from app.ui import shortcuts_dialog as scd
    monkeypatch.setattr(sd.QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    monkeypatch.setattr(scd.QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))

    dlg = SettingsDialog(win.config, win)
    tab = dlg.usb_tab
    assert dlg.tabs.tabText(dlg.tabs.indexOf(tab)) == "USB 버튼"
    assert tab.values() == {"1": {"key": "Ctrl+Alt+Shift+F9", "action": "record"},
                            "2": {"key": "Ctrl+Alt+Shift+F10", "action": "freeze"}}
    tab.key_edits["2"].setKeySequence(tab.key_edits["1"].keySequence())     # 두 버튼에 같은 키 → 확인 막음
    dlg.accept()
    assert dlg.result() == 0 and warned and "같은 키" in warned[-1]
    tab.reset("2")
    win.config.shortcuts = {"record": "Ctrl+Shift+Alt+F9"}                    # 단축키와 같은 키 → 막음
    assert "단축키" in (tab.problem() or "")
    win.config.shortcuts = {}
    assert tab.problem() is None

    def fake_exec(self):                                                      # 설정 창: 버튼 2 를 '사용 안 함'으로
        self.usb_tab.action_combos["2"].setCurrentIndex(self.usb_tab.action_combos["2"].findData("none"))
        return 1
    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    other = dict(win.config.shortcuts or {}), win.config.theme
    win._open_settings()
    assert win.config.usb_buttons["2"]["action"] == "none"
    assert win.config.usb_buttons["1"] == {"key": "Ctrl+Alt+Shift+F9", "action": "record"}
    assert (dict(win.config.shortcuts or {}), win.config.theme) == other      # 다른 설정은 그대로
    assert win.usb_filter.buttons["2"]["action"] == "none"
    assert _wait(qapp, lambda: win._last_frame is not None)
    _wait(qapp, lambda: QApplication.activeWindow() is win, 3)
    win._focus_capture_view()
    _click(_target(), F10)
    _pump(qapp)
    assert not win._single_frozen                                             # 바꾼 기능이 바로 적용

    # 단축키 창: USB 버튼 키는 다른 동작에 지정할 수 없음
    taken = {"Ctrl+Shift+Alt+F9": "슬릿램프 USB 버튼 1"}
    sdlg = ShortcutsDialog({"record": "R"}, win, taken=taken)
    from PySide6.QtGui import QKeySequence
    sdlg.edits["capture"].setKeySequence(QKeySequence("Ctrl+Alt+Shift+F9"))
    sdlg._accept()
    assert sdlg.result() == 0 and "USB 버튼 1" in warned[-1]
    # 예전에 같은 키를 단축키로 저장해 둔 경우: USB 버튼이 먼저, 그 단축키는 쉼
    win.config.shortcuts = {"capture": "Ctrl+Shift+Alt+F9"}
    win._install_shortcuts()
    assert "capture" not in win._shortcut_objs and "record" in win._shortcut_objs
