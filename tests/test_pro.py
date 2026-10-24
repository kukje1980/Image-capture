"""Pro 모드(전문가용) 테스트: 보정·진단명·마이그레이션·코멘트·작업공간 전체 흐름."""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from app.capture.image_process import Adjust, apply_adjust
from app.db.database import Database
from app.models.patient import Patient
from app.services.capture_service import CaptureService


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _img(v=100, h=60, w=80):
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[:] = (v, v // 2, 255 - v)
    return a


# ---------------- 이미지 보정 ----------------
def test_adjust_identity_and_negative():
    f = _img(100)
    assert np.array_equal(apply_adjust(f, Adjust()), f)
    neg = apply_adjust(f, Adjust(negative=True))
    assert np.array_equal(neg.astype(int), 255 - f.astype(int))


def test_adjust_brightness_and_channels():
    f = _img(100)
    assert apply_adjust(f, Adjust(brightness=40)).mean() > f.mean()
    g = apply_adjust(f, Adjust(channel="green"))
    assert np.array_equal(g[..., 0], g[..., 1]) and np.array_equal(g[..., 1], g[..., 2])
    assert int(g[0, 0, 0]) == int(f[0, 0, 1])           # Red-free = 녹색 채널
    gray = apply_adjust(f, Adjust(channel="gray"))
    assert np.array_equal(gray[..., 0], gray[..., 2])


# ---------------- 진단명·담당의 / 마이그레이션 ----------------
def test_patient_diagnosis_doctor_roundtrip(app_env):
    _, db = app_env
    pid = db.patients.insert(Patient(chart_no="D1", name="환자", diagnosis="백내장", doctor="김의사"))
    p = db.patients.get(pid)
    assert (p.diagnosis, p.doctor) == ("백내장", "김의사")
    p.diagnosis = "녹내장 의증"
    db.patients.update(p)
    assert db.patients.get(pid).diagnosis == "녹내장 의증"


def test_old_db_is_migrated(tmp_path):
    """진단명/담당의 컬럼이 없는 구버전 DB도 자동으로 컬럼이 추가되고 데이터가 보존된다."""
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT, chart_no TEXT UNIQUE,
            patient_id TEXT, name TEXT NOT NULL, birth_date TEXT, sex TEXT, phone TEXT,
            memo TEXT, symptoms TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        INSERT INTO patients (chart_no, name) VALUES ('OLD1', '기존환자');
    """)
    con.commit()
    con.close()
    db = Database(str(path)).init()
    try:
        p = db.patients.search("기존환자")[0]
        assert p.chart_no == "OLD1" and p.diagnosis is None
        p.diagnosis, p.doctor = "결막염", "이의사"
        db.patients.update(p)
        assert db.patients.get(p.id).doctor == "이의사"
    finally:
        db.close()


def test_capture_note_update(app_env):
    config, db = app_env
    pid = db.patients.insert(Patient(chart_no="N1", name="n"))
    cap = CaptureService(db, config).save_photo(_img(), db.patients.get(pid), eye="OD")
    db.captures.update_note(cap.id, "경과관찰")
    assert db.captures.get(cap.id).note == "경과관찰"


# ---------------- Pro 작업공간 전체 흐름 ----------------
def _workspace(app_env, n=5):
    from app.ui.pro.pro_workspace import ProWorkspace
    config, db = app_env
    svc = CaptureService(db, config)
    pid = db.patients.insert(Patient(chart_no="P1", name="김영희", sex="F",
                                     diagnosis="백내장", doctor="박원장"))
    patient = db.patients.get(pid)
    for k in range(n):
        svc.save_photo(_img(40 + k * 30), patient, eye="OD" if k % 2 else "OS")
    ws = ProWorkspace(db, svc, config, get_eye=lambda: "OD")
    ws.resize(1200, 800)
    ws.set_patient(patient)
    return ws, db, patient


def test_pro_multi_single_compare(qapp, app_env):
    ws, _, _ = _workspace(app_env, n=5)
    assert ws.mode() == "multi" and len(ws.captures()) == 5
    ws.set_per_page(36)
    assert ws.multi.per_page() == 36 and ws.multi.page_count() == 1

    ws.open_index(2)
    assert ws.mode() == "single" and ws.current_index() == 2
    ws.step(1)
    assert ws.current_index() == 3
    ws.step(10)                                    # 끝에서 멈춤
    assert ws.current_index() == 4
    ws.step(-1)
    assert ws.current_index() == 3

    ws.set_mode("multi")
    ws.select_for_compare(0, 4)
    ws.set_mode("compare")
    assert ws.mode() == "compare"
    assert ws.cmp_left.image() is not None and ws.cmp_right.image() is not None


def test_pro_adjust_annotate_save_edited(qapp, app_env):
    ws, db, patient = _workspace(app_env, n=3)
    ws.open_index(1)
    orig = ws.single_canvas.image().copy()
    ws.set_adjust(Adjust(negative=True))
    ws.single_canvas.add_text(5, 5, "병변")
    ws.single_canvas.add_arrow(QPointF(10, 40), QPointF(60, 20))
    assert ws.single_canvas.annotation_kinds() == ["text", "arrow"]
    rendered = ws.single_canvas.render_to_bgr()
    assert rendered.shape == orig.shape                  # 원본 해상도 유지
    assert not np.array_equal(rendered, orig)            # 보정·주석 반영

    saved = ws.save_edited()
    assert len(saved) == 1 and saved[0].note == "주석"
    assert len(ws.captures()) == 4                        # 원본 보존 + 새 영상
    assert db.captures.get(saved[0].id).file_path
    assert ws.adjust().is_identity()                      # 저장 후 이중 보정 방지

    ws.set_comment("2주 후 재검")
    assert db.captures.get(ws.captures()[ws.current_index()].id).note == "2주 후 재검"


def test_pro_pdf_report(qapp, app_env, tmp_path):
    ws, _, _ = _workspace(app_env, n=5)
    pdf = tmp_path / "report.pdf"
    assert ws.export_pdf(str(pdf)) == 2                   # MULTI 5장 → 4장/쪽 → 2쪽
    assert pdf.read_bytes()[:4] == b"%PDF"

    ws.select_for_compare(1, 3)
    ws.set_mode("compare")
    pdf2 = tmp_path / "compare.pdf"
    assert ws.export_pdf(str(pdf2)) == 1
    assert pdf2.stat().st_size > 1000


def test_pro_live_capture_save(qapp, app_env):
    ws, _, _ = _workspace(app_env, n=0)
    ws.set_mode("live")
    ws.set_live_frame(_img(10))
    ws.b_capture.setChecked(True)                          # 정지
    ws.set_live_frame(_img(250))                           # 정지 중 새 프레임은 무시
    cap = ws.save_live()
    assert cap is not None and cap.eye == "OD"
    assert len(ws.captures()) == 1
    assert not ws.b_capture.isChecked()                    # 저장 후 라이브 복귀


def test_pro_multi_real_mouse_click_and_double_click(qapp, app_env):
    """실제 마우스 이벤트: 클릭=선택 토글, 더블클릭=열기(선택은 원래대로 유지)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    ws, _, _ = _workspace(app_env, n=5)
    ws.show()
    qapp.processEvents()
    cells = {c.index: c for c in ws.multi._cells}
    QTest.mouseClick(cells[0], Qt.MouseButton.LeftButton)
    QTest.mouseClick(cells[2], Qt.MouseButton.LeftButton)
    assert ws.multi.selection() == [0, 2]
    assert ws.multi._cells[0] is cells[0]                 # 셀 위젯이 재생성되지 않음

    # 실제 더블클릭 순서: press/release(클릭) → double-click
    QTest.mouseClick(cells[3], Qt.MouseButton.LeftButton)
    QTest.mouseDClick(cells[3], Qt.MouseButton.LeftButton)
    assert ws.mode() == "single" and ws.current_index() == 3
    assert ws.multi.selection() == [0, 2]                  # 열기 전 선택 복원
    ws.close()
