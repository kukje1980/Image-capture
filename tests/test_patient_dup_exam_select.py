"""v1.17.3 — 같은 차트번호(아이디)로 신규 환자를 넣으면 중복을 알리고 기존 환자에 이어서 할지 묻기,
검사 기록 화면에서 사진을 골라(한 번 누르기) 고른 사진만 저장하기."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.ui.exam_screen import ExamScreen
from app.ui.patient_dialog import PatientDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------- 차트번호 중복 ----------------
def _fill(dlg, chart, name):
    dlg.chart.setText(chart)
    dlg.name.setText(name)


def test_dao_find_by_chart(app_env):
    _config, db = app_env
    pid = db.patients.insert(Patient(chart_no="1111", name="홍길동"))
    assert db.patients.find_by_chart(" 1111 ").id == pid
    assert db.patients.find_by_chart("9999") is None and db.patients.find_by_chart("") is None


def test_duplicate_message_names(qapp):
    other = Patient(id=1, chart_no="1111", name="홍길동", birth_date="1980-03-15", sex="M")
    text, hint = PatientDialog.duplicate_message(other, "1111", "test")
    assert "중복" in text and "홍길동" in text and "test" in text and "이어서" in text
    assert "차트번호 다시 입력" in hint
    text2, _ = PatientDialog.duplicate_message(other, "1111", "홍길동")   # 같은 이름이면 '이미 등록됨'
    assert "이미 등록" in text2 and "입력한 이름" not in text2


def test_new_patient_duplicate_continue_existing(qapp, app_env, monkeypatch):
    _config, db = app_env
    pid = db.patients.insert(Patient(chart_no="1111", name="홍길동"))
    asked = []
    dlg = PatientDialog(db=db)
    monkeypatch.setattr(dlg, "_ask_continue", lambda other, chart, name: asked.append((other.name, chart, name)) or True)
    _fill(dlg, "1111", "test")
    dlg._on_ok()
    assert asked == [("홍길동", "1111", "test")]
    assert dlg.result() == PatientDialog.DialogCode.Accepted and dlg.existing.id == pid
    dlg.close()


def test_new_patient_duplicate_reenter(qapp, app_env, monkeypatch):
    _config, db = app_env
    db.patients.insert(Patient(chart_no="1111", name="홍길동"))
    dlg = PatientDialog(db=db)
    monkeypatch.setattr(dlg, "_ask_continue", lambda *a: False)        # '차트번호 다시 입력'
    _fill(dlg, "1111", "test")
    dlg._on_ok()
    assert dlg.result() != PatientDialog.DialogCode.Accepted and dlg.existing is None
    _fill(dlg, "2222", "test")                                          # 다른 번호 → 그대로 저장
    dlg._on_ok()
    assert dlg.result() == PatientDialog.DialogCode.Accepted and dlg.existing is None
    assert dlg.get_patient().chart_no == "2222"
    dlg.close()


def test_edit_patient_to_used_chart_blocked(qapp, app_env, monkeypatch):
    _config, db = app_env
    db.patients.insert(Patient(chart_no="1111", name="홍길동"))
    me = db.patients.get(db.patients.insert(Patient(chart_no="3333", name="나")))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]) or QMessageBox.StandardButton.Ok)
    dlg = PatientDialog(patient=me, db=db)
    dlg.chart.setText("1111")
    dlg._on_ok()
    assert dlg.result() != PatientDialog.DialogCode.Accepted and "홍길동" in warned[-1]
    dlg.chart.setText("3333")                                           # 자기 번호는 그대로 저장 가능
    dlg._on_ok()
    assert dlg.result() == PatientDialog.DialogCode.Accepted
    dlg.close()


def test_main_window_new_patient_duplicate_selects_existing(qapp, app_env, monkeypatch):
    """기본판·Keeler 판 상단 '신규 환자' 에서 같은 차트번호 → 기존 환자가 선택되고 새로 등록되지 않는다."""
    from app.ui.patient_panel import PatientPanel
    _config, db = app_env
    pid = db.patients.insert(Patient(chart_no="1111", name="홍길동"))
    db.patients.insert(Patient(chart_no="2000", name="다른 환자"))
    panel = PatientPanel(db)

    def fake_exec(self):
        _fill(self, "1111", "test")
        self.existing = db.patients.get(pid)
        return True
    monkeypatch.setattr(PatientDialog, "exec", fake_exec)
    n = len(db.patients.list_all())
    assert panel.new_patient()
    assert len(db.patients.list_all()) == n and panel.current_patient().id == pid
    panel.deleteLater()


# ---------------- 검사 기록: 사진 고르기 · 고른 사진만 저장 ----------------
def _patient_with_photos(config, db, n=3):
    p = db.patients.get(db.patients.insert(Patient(chart_no="E7", name="선택")))
    svc = CaptureService(db, config)
    img = np.zeros((60, 80, 3), np.uint8)
    caps = [svc.save_photo(img + i * 40, p, eye=("OD", "OS", "NA")[i % 3]) for i in range(n)]
    return p, caps


def test_exam_select_and_save_selected(qapp, app_env, tmp_path, monkeypatch):
    config, db = app_env
    p, caps = _patient_with_photos(config, db)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    scr = ExamScreen(db, config)
    opened = []
    scr.openCapture.connect(opened.append)
    scr.set_patient(p)
    scr.show()
    qapp.processEvents()
    assert not scr.btn_save_sel.isEnabled() and scr.btn_save_sel.text() == "선택 저장"
    w0, w2 = scr._thumbs[caps[0].id], scr._thumbs[caps[2].id]
    QTest.mouseClick(w2, Qt.MouseButton.LeftButton)                     # 한 번 누르면 선택 (크게 보기 아님)
    QTest.mouseClick(w0, Qt.MouseButton.LeftButton)
    assert opened == [] and [c.id for c in scr.selected_captures()] == [caps[2].id, caps[0].id]
    assert w2.rank() == 1 and w0.rank() == 2 and scr.btn_save_sel.text() == "저장 (2)"
    assert "선택 2장" in scr.lbl_day_meta.text()
    QTest.mouseClick(w2, Qt.MouseButton.LeftButton)                     # 다시 누르면 해제
    assert [c.id for c in scr.selected_captures()] == [caps[0].id] and w0.rank() == 1
    QTest.mouseDClick(w0, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    assert [c.id for c in opened] == [caps[0].id]                       # 두 번 누르면 크게 보기
    assert [c.id for c in scr.selected_captures()] == [caps[0].id]      # 선택은 그대로
    # 실제 PC 의 두 번 누르기 순서(누름 → 두 번 누름): 첫 누름이 바꾼 선택도 되돌린다
    scr._on_thumb_click(caps[1])
    scr._on_thumb_double(caps[1])
    assert [c.id for c in scr.selected_captures()] == [caps[0].id] and len(opened) == 2
    scr._on_thumb_click(caps[0])                                        # 선택된 사진을 두 번 눌러도 선택 유지
    scr._on_thumb_double(caps[0])
    assert [c.id for c in scr.selected_captures()] == [caps[0].id]
    QTest.mouseClick(w2, Qt.MouseButton.LeftButton)
    out = tmp_path / "내보내기"
    saved = scr.save_selected(str(out))                                 # 고른 2장만
    assert len(saved) == 2 and all(Path(s).is_file() for s in saved)
    assert sorted(Path(s).name.split("_")[0] for s in saved) == ["E7", "E7"]
    assert {Path(s).stat().st_size for s in saved} == {Path(caps[0].file_path).stat().st_size,
                                                       Path(caps[2].file_path).stat().st_size}
    assert len(list(out.iterdir())) == 2
    again = scr.save_selected(str(out))                                 # 같은 폴더에 또 저장해도 덮어쓰지 않음
    assert len(again) == 2 and len(list(out.iterdir())) == 4
    assert len(scr.report_items()) == 2                                 # 인쇄 · PDF 도 고른 사진만
    scr.toggle_select_all()
    assert len(scr.selected_captures()) == 3 and scr.btn_select_all.text() == "선택 해제"
    assert len(scr.report_items()) == 3
    scr.toggle_select_all()
    assert scr.selected_captures() == [] and not scr.btn_save_sel.isEnabled()
    assert len(scr.report_items()) == 3                                 # 아무것도 안 고르면 이 날 전부
    scr.deleteLater()
    qapp.processEvents()


def test_exam_save_selected_requires_selection(qapp, app_env, monkeypatch):
    config, db = app_env
    p, _caps = _patient_with_photos(config, db, n=1)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[2]) or QMessageBox.StandardButton.Ok)
    scr = ExamScreen(db, config)
    scr.set_patient(p)
    assert scr.save_selected("/tmp/never") == [] and "고르세요" in told[-1]
    scr.deleteLater()
    qapp.processEvents()


def test_exam_selection_reset_on_other_patient(qapp, app_env):
    config, db = app_env
    p, caps = _patient_with_photos(config, db, n=2)
    q = db.patients.get(db.patients.insert(Patient(chart_no="E8", name="다른")))
    scr = ExamScreen(db, config)
    scr.set_patient(p)
    scr.toggle_select(caps[0])
    assert len(scr.selected_captures()) == 1
    scr.reload()                                                        # 같은 환자 다시 읽기 → 선택 유지
    assert len(scr.selected_captures()) == 1
    scr.set_patient(q)
    assert scr._selected == [] and not scr.btn_save_sel.isEnabled()
    scr.deleteLater()
    qapp.processEvents()
