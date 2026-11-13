"""환자 목록 화면 (첫 화면) · 검사 목록 · 검토 화면의 '현재' 검사 테스트."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.models.capture import Capture
from app.models.patient import Patient
from app.services import fundus_import
from app.services.capture_service import CaptureService
from app.services.fundus_import import ImportedImage


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _img(seed=0):
    img = np.zeros((90, 120, 3), dtype=np.uint8)
    cv2.circle(img, (60, 45), 40, (30, 70 + seed * 5, 200), -1)
    return img


def _ago(days: int, hhmmss="10:00:00") -> datetime:
    return datetime.fromisoformat(f"{(date.today() - timedelta(days=days)).isoformat()} {hhmmss}")


def _fundus(svc, patient, eye, when: datetime, seed=0):
    return fundus_import.import_image(svc, patient, ImportedImage(_img(seed), when, eye, f"{eye}.png"))


def _seed(app_env):
    """환자 5명: 검사 있는 환자 3명(오늘 / 3일 전 / 40일 전) + 세극등만 있는 환자 + 검사 없는 환자."""
    config, db = app_env
    svc = CaptureService(db, config)
    ps = {}
    for chart, name, sex, birth, dx in (("2024-0113", "김영수", "M", "1958-03-12", "당뇨망막병증"),
                                        ("2023-0871", "박정희", "F", "1949-11-02", "나이관련 황반변성"),
                                        ("2022-0456", "이상훈", "M", "1966-01-30", "망막정맥폐쇄"),
                                        ("2025-0034", "최민지", "F", None, "고도근시"),
                                        ("2026-0009", "정하늘", None, None, None)):
        p = Patient(chart_no=chart, name=name, sex=sex, birth_date=birth, diagnosis=dx, doctor="이준호")
        p.id = db.patients.insert(p)
        ps[name] = p
    kim, park, lee, choi = ps["김영수"], ps["박정희"], ps["이상훈"], ps["최민지"]
    for d in (0, 92, 190):                                   # 김영수: 검사 3회, 오늘 포함
        _fundus(svc, kim, "OD", _ago(d, "10:42:00"), d)
        _fundus(svc, kim, "OS", _ago(d, "10:43:00"), d)
    svc.save_photo(_img(), kim, eye="OD", captured_at=_ago(0, "11:00:00"))            # 오늘 세극등 1장
    db.captures.insert(Capture(patient_id=kim.id, media_type="video", file_path="/tmp/v.mp4",
                               captured_at=_ago(0, "11:05:00").strftime("%Y-%m-%d %H:%M:%S"), eye="OD",
                               duration_ms=3000))
    for d in (3, 64):                                        # 박정희: 2회, 최근 7일 안
        _fundus(svc, park, "OD", _ago(d), d)
    _fundus(svc, lee, "OD", _ago(40), 1)                     # 이상훈: 1회, 40일 전
    svc.save_photo(_img(), choi, eye="OS", captured_at=_ago(1))                         # 최민지: 세극등만
    return config, db, svc, ps


# ---------------- DAO ----------------
def test_list_with_stats(app_env):
    _, db, _, ps = _seed(app_env)
    stats = {s.patient.name: s for s in db.patients.list_with_stats()}
    assert len(stats) == 5
    assert (stats["김영수"].exam_count, stats["김영수"].last_exam) == (3, date.today().isoformat())
    assert (stats["박정희"].exam_count, stats["박정희"].last_exam) == (2, _ago(3).date().isoformat())
    assert stats["이상훈"].exam_count == 1 and stats["최민지"].exam_count == 1
    assert (stats["정하늘"].exam_count, stats["정하늘"].last_exam) == (0, None)
    assert stats["김영수"].patient.diagnosis == "당뇨망막병증"
    # 최근 검사가 있는 환자부터, 검사 없는 환자는 맨 뒤
    assert [s.patient.name for s in db.patients.list_with_stats()] == ["김영수", "최민지", "박정희", "이상훈", "정하늘"]


# ---------------- 표 · 검색 · 기간 ----------------
def test_table_rows_search_and_range(qapp, app_env):
    from app.ui.patient_list import COLUMNS, PatientListScreen
    _, db, _, ps = _seed(app_env)
    scr = PatientListScreen(db)
    assert [scr.table.horizontalHeaderItem(i).text() for i in range(6)] == COLUMNS
    rows = {r["name"]: r for r in scr.rows()}
    assert len(rows) == 5
    kim = rows["김영수"]
    assert kim["chart_no"] == "2024-0113" and kim["diagnosis"] == "당뇨망막병증" and kim["exam_count"] == 3
    assert kim["last_exam"] == date.today().isoformat().replace("-", ".")
    assert kim["sex_age"].startswith("남 · ") and kim["sex_age"].endswith("세")
    assert rows["정하늘"]["last_exam"] == "없음" and rows["정하늘"]["exam_count"] == 0
    assert rows["정하늘"]["sex_age"] == "—" and rows["정하늘"]["diagnosis"] == "—"

    scr.set_query("황반")                                     # 진단명
    assert [r["name"] for r in scr.rows()] == ["박정희"]
    scr.set_query("2022-04")                                  # 차트번호
    assert [r["name"] for r in scr.rows()] == ["이상훈"]
    scr.set_query("없는사람")
    assert scr.rows() == [] and not scr.lbl_rows_empty.isHidden() and scr.table.isHidden()
    scr.set_query("")
    scr.set_range("today")
    assert [r["name"] for r in scr.rows()] == ["김영수"]
    scr.set_range("week")
    assert [r["name"] for r in scr.rows()] == ["김영수", "최민지", "박정희"]
    scr.set_range("all")
    assert len(scr.rows()) == 5 and scr.range() == "all"


def test_selection_sets_current_patient_and_detail(qapp, app_env):
    from app.ui.patient_list import PatientListScreen
    _, db, _, ps = _seed(app_env)
    scr = PatientListScreen(db)
    seen = []
    scr.patientSelected.connect(seen.append)
    assert scr.current_patient().name == "김영수"            # 처음에는 맨 위 환자
    assert scr.table.currentRow() == 0

    # 검사 목록: 날짜별, 최신 먼저, 최신이 체크됨
    exams = scr.exams()
    assert [e.day for e in exams] == [_ago(d).date().isoformat() for d in (0, 92, 190)]
    assert exams[0].summary() == "안저 2장 · 슬릿램프 1장 · 동영상 1개" and exams[1].summary() == "안저 2장"
    assert scr.checked_exam() == exams[0].day
    assert [d for d, cb in scr.exam_checks.items() if cb.isChecked()] == [exams[0].day]
    assert scr.lbl_exams.text() == "검사 목록 · 3회" and scr.btn_open.isEnabled()
    assert scr.kv["진단명"].text() == "당뇨망막병증" and scr.kv["생년월일"].text().startswith("1958.03.12 (")
    scr.exam_checks[exams[2].day].click()                    # 한 번에 하나만 체크
    assert scr.checked_exam() == exams[2].day
    assert [d for d, cb in scr.exam_checks.items() if cb.isChecked()] == [exams[2].day]
    scr.reload()                                             # 다시 읽어도 고른 검사는 유지
    assert scr.checked_exam() == exams[2].day and seen == []

    scr.table.selectRow(4)                                   # 정하늘: 검사 없음
    assert seen[-1].name == "정하늘" and scr.current_patient().name == "정하늘"
    assert scr.exams() == [] and scr.checked_exam() is None and not scr.btn_open.isEnabled()
    assert scr.lbl_name.text() == "정하늘"
    scr.select_patient(ps["최민지"].id)                      # 세극등 사진만 → 검토 화면 열기 불가
    assert seen[-1].name == "최민지" and scr.exams()[0].summary() == "슬릿램프 1장"
    assert not scr.btn_open.isEnabled()

    # 검색으로 지금 환자가 안 보여도 지금 환자는 바뀌지 않는다
    n = len(seen)
    scr.set_query("김영수")
    assert scr.current_patient().name == "최민지" and len(seen) == n
    assert scr.table.selectedItems() == []


def test_double_click_enter_and_buttons(qapp, app_env):
    from app.ui.patient_list import PatientListScreen
    _, db, _, ps = _seed(app_env)
    scr = PatientListScreen(db)
    scr.resize(1200, 700)
    scr.show()
    qapp.processEvents()
    opened, sel, cap, imp = [], [], [], []
    scr.openReviewRequested.connect(lambda: opened.append(scr.current_patient().name))
    scr.patientSelected.connect(lambda p: sel.append(p.name))
    scr.captureRequested.connect(lambda: cap.append(1))
    scr.importRequested.connect(lambda: imp.append(1))

    def center(row):
        return scr.table.visualItemRect(scr.table.item(row, 1)).center()

    vp = scr.table.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=center(2))                 # 한 번: 선택만
    assert sel == ["박정희"] and opened == []
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, pos=center(3))
    QTest.mouseDClick(vp, Qt.MouseButton.LeftButton, pos=center(3))                # 두 번: 검토 화면
    assert sel[-1] == "이상훈" and opened == ["이상훈"]
    scr.table.setFocus()
    scr.table.selectRow(0)
    QTest.keyClick(scr.table, Qt.Key.Key_Return)                                   # Enter
    assert opened == ["이상훈", "김영수"]
    scr.table.selectRow(4)                                                         # 안저 사진 없는 환자는 열지 않음
    QTest.keyClick(scr.table, Qt.Key.Key_Return)
    assert len(opened) == 2

    scr.btn_capture.click()
    scr.btn_import.click()
    assert cap == [1] and imp == [1]
    scr.close()


def test_new_patient_is_listed_and_selected(qapp, app_env):
    from app.ui.patient_list import PatientListScreen
    _, db, _, ps = _seed(app_env)
    scr = PatientListScreen(db)
    scr.set_query("김영수")
    scr.set_range("today")
    pid = db.patients.insert(Patient(chart_no="NEW-1", name="새환자"))
    scr.add_patient_created(pid)
    assert scr.current_patient().name == "새환자" and len(scr.rows()) == 6
    assert scr.search.text() == "" and scr.range() == "all"
    assert scr.table.currentRow() == [r["name"] for r in scr.rows()].index("새환자")


# ---------------- 검토 화면: 체크한 검사 = 현재 ----------------
def test_review_current_day_drives_current_and_prior(qapp, app_env):
    from app.ui.fundus.fundus_review import FundusReview
    config, db, svc, ps = _seed(app_env)
    kim = ps["김영수"]
    d0, d92, d190 = (_ago(d).date().isoformat() for d in (0, 92, 190))
    w = FundusReview(db, config)
    w.resize(1200, 760)
    w.set_patient(kim)
    assert w.current_day() == d0 and w.prior_count() == 0 and w.timeline.current_day() == d0
    assert "김영수" in w.lbl_who.text() and "2024-0113" in w.lbl_who.text() and "당뇨망막병증" in w.lbl_who.text()

    w.set_current_day(d92)                                   # 92일 전 검사를 '현재'로
    assert w.current_day() == d92 and w.sessions() == [d92, d190]
    assert w.left.capture().captured_at.startswith(d92) and w.left.capture().eye == "OD"
    assert w.right.capture().captured_at.startswith(d92) and w.right.capture().eye == "OS"
    assert w.left.tag() == "" and w.timeline.current_day() == d92
    assert len(w.timeline.thumbs()) == 6                     # 타임라인에는 모든 검사가 보인다
    assert w.set_stage("od")
    assert w.right.capture().captured_at.startswith(d92) and w.right.tag() == "현재"
    assert w.left.capture().captured_at.startswith(d190) and w.left.tag() == "이전"
    assert w.prior_count() == 1
    newer = next(c for c in w.captures() if c.captured_at.startswith(d0) and c.eye == "OD")
    w.show_capture(newer)                                    # 현재보다 뒤 검사를 올리면 '이후'
    assert w.active_viewport().tag() == "이후"

    w.set_current_day(d190)                                  # 가장 오래된 검사 → 비교할 이전 검사 없음
    assert w.stage() == "ou" and not w.stage_enabled("od") and not w.stage_enabled("os")
    assert "이전 검사 없음" in w.c_stage.itemText(1)
    w.set_current_day(None)
    assert w.current_day() == d0 and w.stage_enabled("od") and w.prior_count() == 0
    w.set_stage("od")
    assert w.prior_count() == 2

    back = []
    w.backRequested.connect(lambda: back.append(1))
    w.b_back.click()
    assert back == [1]


def test_review_tool_extension_point(qapp, app_env):
    from app.ui.fundus.fundus_review import FundusReview
    config, db, svc, ps = _seed(app_env)
    w = FundusReview(db, config)
    calls = []
    btn = w.add_tool("demo", "도구", "예시 도구", lambda review, cap, img: calls.append((cap.id, img.shape)))
    assert w.tool_button("demo") is btn and not btn.isEnabled()          # 영상 없음
    assert w.run_tool("demo") is False
    w.set_patient(ps["김영수"])
    assert btn.isEnabled()
    assert w.tool_slot.indexOf(btn) == 0
    btn.click()
    assert calls == [(w.active_viewport().capture().id, (90, 120, 3))]
    assert w.run_tool("unknown") is False


# ---------------- 메인 윈도우 흐름 ----------------
def test_main_window_patient_list_flow(qapp, app_env):
    from app.ui import main_window as mw
    config, db, svc, ps = _seed(app_env)
    config.source_mode = "synthetic"
    config.save = lambda: None
    win = mw.MainWindow(config, db)
    win.show()
    end = time.time() + 5
    while time.time() < end and win._last_frame is None:
        qapp.processEvents()
        time.sleep(0.02)
    try:
        scr = win.patients_screen
        d0, d92 = (_ago(d).date().isoformat() for d in (0, 92))
        # 환자 목록에서 시작, 맨 위 환자가 지금 환자, 배너는 숨김
        assert win.mode_stack.currentIndex() == mw.SCREEN_PATIENTS and win.btn_mode_patients.isChecked()
        assert win._current_patient.name == "김영수" and win.patient_panel.isHidden()

        scr.select_patient(ps["박정희"].id)                   # 선택 → 앱 전체의 지금 환자
        assert win._current_patient.name == "박정희"
        assert win.patient_panel.current_patient().name == "박정희"
        assert win.thumbnail_panel.count() == 2 and win.control_bar.btn_capture.isEnabled()

        scr.btn_capture.click()                               # 촬영: 이 환자로 촬영 화면
        assert win.mode_stack.currentIndex() == mw.SCREEN_CAPTURE and win.btn_mode_capture.isChecked()
        assert not win.patient_panel.isHidden() and win.patient_panel.lbl_name.text() == "박정희"
        n0 = win.thumbnail_panel.count()
        QTest.keyClick(win, Qt.Key.Key_C)
        end = time.time() + 5
        while time.time() < end and win.thumbnail_panel.count() != n0 + 1:
            qapp.processEvents()
            time.sleep(0.02)
        assert db.captures.list_by_patient(ps["박정희"].id)[0].modality == "slit"

        win.patient_panel.btn_list.click()                    # 배너의 '환자 목록' → 통계가 새로 반영됨
        assert win.mode_stack.currentIndex() == mw.SCREEN_PATIENTS
        park = next(r for r in scr.rows() if r["name"] == "박정희")
        assert park["exam_count"] == 3 and park["last_exam"] == d0.replace("-", ".")

        scr.select_patient(ps["김영수"].id)                   # 예전 검사를 체크하고 검토 화면 열기
        scr.set_checked_exam(d92)
        scr.btn_open.click()
        assert win.mode_stack.currentIndex() == mw.SCREEN_FUNDUS and win.patient_panel.isHidden()
        assert win.fundus.patient().name == "김영수" and win.fundus.current_day() == d92
        assert win.fundus.right.capture().captured_at.startswith(d92)
        win.fundus.b_back.click()                             # ← 환자 목록
        assert win.mode_stack.currentIndex() == mw.SCREEN_PATIENTS
        assert scr.checked_exam() == d92                      # 고른 검사는 유지

        scr.table.selectRow([r["name"] for r in scr.rows()].index("이상훈"))
        scr.open_review()                                     # 다른 환자 → 가장 최근 검사가 현재
        assert win.fundus.patient().name == "이상훈" and win.fundus.current_day() == _ago(40).date().isoformat()

        win._set_screen(mw.SCREEN_PRO)
        assert not win.patient_panel.isHidden()
        QTest.keyClick(win, Qt.Key.Key_L)                     # L: 환자 목록 + 검색 칸
        assert win.mode_stack.currentIndex() == mw.SCREEN_PATIENTS and scr.search.hasFocus()
    finally:
        win.close()
