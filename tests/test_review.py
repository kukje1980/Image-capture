"""환자 목록 (a window of its own, shown first) and the 검토 tab: which photos a review shows
(review.py), the patient list's rows · order · search · exams · 16 photos, the patient shared with
the main window and its 16 to a screen, the stages, earlier exams, the timeline, linked views, view
modes, the 확대창 and the hand-offs to 2D / 3D / 녹내장."""
import os
from datetime import date

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fundusview import review  # noqa: E402
from fundusview.demo import synth_fundus  # noqa: E402


def _row(i, day, eye, modality="color", time="10:00:00"):
    return {"id": i, "exam_date": day, "exam_time": time, "laterality": eye, "modality": modality,
            "thumb_path": None}


def test_review_rules_pick_the_photo_of_each_eye():
    rows = [
        _row(1, "2026-03-01", "OD", time="09:00:00"), _row(2, "2026-03-01", "OD", time="09:05:00"),
        _row(3, "2026-03-01", "OD", "redfree", "09:09:00"), _row(4, "2026-03-01", "OS", "montage"),
        _row(5, "2026-03-01", "OS", "disc"), _row(6, "2026-03-01", "OD", "glaucoma", "09:30:00"),
        _row(7, "2026-03-01", None), _row(8, "2026-03-01", "OS", "anterior"),
        _row(9, "2025-12-01", "OD"), _row(10, "2025-12-01", "OS", "af"), _row(11, "2025-12-01", "OS", "montage"),
        _row(12, "2025-06-01", "OS"), _row(13, None, "OD"),
    ]
    groups = review.exams(rows)
    assert [d for d, _ in groups] == ["2026-03-01", "2025-12-01", "2025-06-01", ""]      # newest first, no date last
    assert [r["id"] for r in groups[0][1]][:3] == [1, 2, 3]                               # in the order taken
    day = groups[0][1]
    # the newest colour photo of the eye; viewer-made sheets and anterior photos never; montage only alone
    assert review.eye_photo(day, "OD")["id"] == 2
    assert review.eye_photo(day, "OS")["id"] == 4
    assert review.eye_photo(groups[1][1], "OS")["id"] == 10                               # AF before a montage
    assert review.eye_photo(groups[2][1], "OD") is None
    assert not review.is_photo(rows[4]) and not review.is_photo(rows[5]) and review.is_photo(rows[6])
    # an eye through the exams, from the current exam back (later exams are left out)
    assert [r["id"] for r in review.eye_series(rows, "OD")] == [2, 9, 13]
    assert [r["id"] for r in review.eye_series(rows, "OS")] == [4, 10, 12]
    assert [r["id"] for r in review.eye_series(rows, "OS", "2025-12-01")] == [10, 12]
    assert [r["id"] for r in review.eye_series(rows, "OD", "2025-06-01")] == [13]
    assert review.summary(day) == "컬러 3장 · Red-free 1장 · 전안부 1장 · 몽타주 1장 · 디스크 2장 1장 · 녹내장 분석 1장"
    assert review.summary([_row(1, "2026-01-01", "OD", None)]) == "사진 1장"
    assert review.newest_photo(rows)["id"] == 2 and review.newest_photo(rows, "2025-06-01")["id"] == 12
    assert review.newest_photo([]) is None


# ---------------------------------------------------------------------------------------------
# a library with a history: one patient seen three times, one seen once, one without photos
# ---------------------------------------------------------------------------------------------
def _library(tmp_path):
    from PIL import Image

    from fundusview.db import Database
    from fundusview.models import ExtractedMeta

    db = Database(tmp_path / "lib" / "fundus.db")
    folder = tmp_path / "photos"
    folder.mkdir()
    n = [0]

    def add(ref, day, time, eye, modality="color", seed=1, size=(320, 300)):
        n[0] += 1
        rgb = synth_fundus(eye=eye or "OD", size=size, seed=seed, tint=(0.80 - 0.01 * n[0], 0.42, 0.24))
        path = folder / f"p{n[0]}.png"
        Image.fromarray(rgb).save(path)
        thumb = folder / f"t{n[0]}.png"
        Image.fromarray(rgb).resize((80, 75)).save(thumb)
        return db.insert_image(patient_ref=ref, exam_date=day, exam_time=time, laterality=eye, modality=modality,
                               file_path=str(path), thumb_path=str(thumb), sha256=f"sha{n[0]}",
                               width=size[0], height=size[1])

    kim = db.upsert_patient(ExtractedMeta(patient_id="K001", name="김영수", birth_date="1958-03-12", sex="M"))
    park = db.upsert_patient(ExtractedMeta(patient_id="P002", name="박정희", birth_date="1949-11-02", sex="F"))
    jung = db.upsert_patient(ExtractedMeta(patient_id="J003", name="정하늘"))
    ids = {
        "od3": add(kim, "2026-03-02", "10:42:00", "OD"), "os3": add(kim, "2026-03-02", "10:43:00", "OS"),
        "rf3": add(kim, "2026-03-02", "10:45:00", "OD", "redfree"),
        "na3": add(kim, "2026-03-02", "10:50:00", None),
        "od2": add(kim, "2025-12-01", "09:15:00", "OD", size=(400, 300)),      # another size than today's
        "os2": add(kim, "2025-12-01", "09:16:00", "OS"),
        "od1": add(kim, "2025-08-20", "14:02:00", "OD"),
        "sheet": add(kim, "2025-08-20", "14:30:00", "OD", "disc"),
        "p_od": add(park, "2026-03-09", "11:20:00", "OD"),
        "un": add(None, "2026-02-01", "08:00:00", "OS"),
    }
    return db, {"kim": kim, "park": park, "jung": jung}, ids


@pytest.fixture
def win(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="",
                 open_view="odos", ui_version=MainWindow.UI_VERSION)      # (환자를 열면: Simple)
    w = MainWindow(s, db)
    assert (w.width(), w.height()) == (1600, 960)        # the size the program opens with
    w.patient_list.select_delay = 0                     # a selection goes through at once (no key stepping here)
    w.show()
    app.processEvents()
    yield app, w, db, refs, ids
    w.close()
    db.close()


def _texts(table, col):
    return [table.item(r, col).text() for r in range(table.rowCount())]


def _grid_ids(w):
    """The photos on the main window's 다중 보기, in order."""
    return [c.image_id for c in w.multi.cells if c.isVisible() and c.image_id is not None]


def test_patient_list_is_a_window_of_its_own_and_comes_first(win):
    from PySide6.QtWidgets import QDialog

    from fundusview.ui.main_window import UNASSIGNED

    app, w, db, refs, ids = win
    pl = w.patient_list
    # the program opens with the patient list in front: a window of its own over the main window,
    # whose photo screen (and VK-2 toolbars) are always there behind it
    assert pl.isVisible() and pl.isWindow() and isinstance(pl, QDialog) and not pl.isModal()
    assert pl.windowTitle() == "환자 목록" and pl.parent() is w and w.centralWidget() is not pl
    assert w.tabs.isVisible() and w.tb_cmd.isVisible() and w.tb_proc.isVisible() and w.acts["prev"].isEnabled()
    assert w.acts["list"].isChecked() and w.acts["list"].text() == "환자 목록"
    # one list of patients: the workspace's own patient pane is gone
    assert not hasattr(w, "left") and not hasattr(w, "patients") and not hasattr(w, "patient_page")
    # VK-2: ID · name · sex · birth date · age · last exam …, sorted by ID; 미분류 on top
    hdr = [pl.table.horizontalHeaderItem(c).text() for c in range(8)]
    assert hdr == ["환자 ID", "이름", "성별", "생년월일", "나이", "최근 검사", "검사 수", "영상"]
    assert pl.refs() == [UNASSIGNED, refs["jung"], refs["kim"], refs["park"]]       # J003 · K001 · P002
    assert pl.sort_order() == (0, True)
    by_id = {pl.table.item(r, 0).text(): [pl.table.item(r, c).text() for c in range(8)]
             for r in range(pl.table.rowCount())}
    age = date.today().year - 1958 - ((date.today().month, date.today().day) < (3, 12))
    assert by_id["K001"] == ["K001", "김영수", "남", "1958-03-12", str(age), "2026-03-02", "3", "8"]
    assert by_id["P002"][2:3] + by_id["P002"][5:] == ["여", "2026-03-09", "1", "1"]
    assert by_id["J003"] == ["J003", "정하늘", "", "", "", "", "0", "0"]
    assert by_id["★ 미분류"][5:] == ["2026-02-01", "1", "1"]
    assert pl.lbl_count.text() == "3명"
    # nothing is selected yet: no patient, no exams, nothing to open or edit
    assert pl.current() is None and not pl.btn_open.isEnabled() and not pl.btn_edit.isVisible()
    assert pl.lbl_exams.text() == "검사 목록" and pl.exams.rowCount() == 0
    assert pl.exam_stack.currentWidget() is pl.lbl_exam_empty and pl.lbl_exam_empty.isVisible()
    assert "환자를 선택" in pl.lbl_exam_empty.text() and "16장" not in pl.lbl_exam_empty.text()
    # no patient information panel on the right: the table and its exams take the whole width
    assert not hasattr(pl, "info_box") and not hasattr(pl, "detail") and not hasattr(pl, "info")
    assert pl.left.width() > pl.width() - 60

    # a click on a column title sorts by it, a second click the other way; empty values stay last
    pl.sort_by(5)                                                  # 최근 검사: the latest first
    assert pl.sort_order() == (5, False) and pl.refs() == [UNASSIGNED, refs["park"], refs["kim"], refs["jung"]]
    pl.table.horizontalHeader().sectionClicked.emit(5)
    assert pl.sort_order() == (5, True) and pl.refs() == [UNASSIGNED, refs["kim"], refs["park"], refs["jung"]]
    pl.table.horizontalHeader().sectionClicked.emit(1)             # 이름: 가나다
    assert _texts(pl.table, 1)[1:] == ["김영수", "박정희", "정하늘"]
    pl.table.horizontalHeader().sectionClicked.emit(0)
    assert pl.sort_order() == (0, True)

    # search: patient ID, name, birth date (any part); 미분류 only without a search
    pl.f_name.setText("영수")
    pl.refresh()
    assert _texts(pl.table, 0) == ["K001"] and pl.lbl_count.text() == "1명 / 전체 3명"
    pl.f_name.setText("")
    pl.f_birth.setText("1949")
    pl.refresh()
    assert _texts(pl.table, 0) == ["P002"]
    pl.f_birth.setText("1958.03.12")                                # written any way
    pl.refresh()
    assert _texts(pl.table, 0) == ["K001"]
    pl.f_birth.setText("")
    pl.f_id.setText("p0")
    pl.refresh()
    assert _texts(pl.table, 0) == ["P002"]
    pl.f_id.setText("없는번호")
    pl.refresh()
    assert pl.list_stack.currentWidget() is pl.lbl_empty and pl.lbl_empty.text() == "조건에 맞는 환자가 없습니다"
    pl.btn_clear.click()
    assert pl.f_id.text() == "" and pl.list_stack.currentWidget() is pl.table and pl.table.rowCount() == 4

    # 검사일: patients photographed in that time (오늘 · 최근 7일 · 기간)
    pl.today = lambda: date(2026, 3, 9)
    pl.period_buttons["today"].click()
    assert _texts(pl.table, 0) == ["P002"] and not pl.range_w.isVisible()
    pl.period_buttons["week"].click()
    assert set(_texts(pl.table, 0)) == {"P002", "K001"}                 # 03-02 is the 7th day back
    pl.today = lambda: date(2026, 3, 10)
    pl.set_period("week")
    assert _texts(pl.table, 0) == ["P002"]
    pl.set_range(date(2025, 8, 1), date(2025, 12, 31))                 # K001 was seen then (not last)
    assert pl.period_buttons["range"].isChecked() and pl.range_w.isVisible()
    assert _texts(pl.table, 0) == ["K001"]
    pl.set_range(date(2026, 2, 1), date(2026, 2, 1))                   # only the photo without a patient
    assert _texts(pl.table, 0) == ["★ 미분류"]
    pl.period_buttons["all"].click()
    assert pl.table.rowCount() == 4

    # Ctrl+F (환자 검색) brings the list up with the cursor in 환자 ID; Ctrl+0 / [환자 목록] bring it up
    pl.hide()
    assert not w.acts["list"].isChecked()
    w._on_action("search")
    app.processEvents()
    assert pl.isVisible() and pl.focusWidget() is pl.f_id and w.acts["list"].isChecked()
    assert w.act_patients.shortcut().toString() == "Ctrl+0"
    pl.btn_close.click()
    assert pl.isHidden()
    w.act_patients.trigger()
    assert pl.isVisible()
    w.act_patients.trigger()                       # Ctrl+0 again puts it away, as [환자 목록] does (0.13.14)
    assert pl.isHidden() and not w.acts["list"].isChecked()
    w.act_patients.trigger()
    assert pl.isVisible()
    w.acts["list"].trigger()                       # the command toolbar's [환자 목록] puts it away again
    assert pl.isHidden() and not w.acts["list"].isChecked()
    w.btn_patients.click()
    assert pl.isVisible() and w.btn_patients.text() == "환자 목록"


def test_click_a_patient_shows_its_exams_not_its_photos(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel

    from fundusview.ui.main_window import UNASSIGNED

    app, w, db, refs, ids = win
    pl = w.patient_list

    def selected(table):
        rows = table.selectionModel().selectedRows()
        return table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    # one click: the patient in both windows — its exams in the list (no photos there), its newest
    # OD | OS in the main window
    pl.table.selectRow(pl.row_of(refs["kim"]))
    app.processEvents()
    assert w._patient_ref == refs["kim"] and pl.isVisible() and "김영수" in w.banner.text()
    newest_first = [ids[k] for k in ("na3", "rf3", "os3", "od3", "os2", "od2", "sheet", "od1")]
    # 8 photos, na3 (eye unknown) not listed; the photo list: the newest exam's bookmark (3 of the 7)
    assert len(w._listed) == 7 and ids["na3"] not in [i for i, _eye, _day in w._listed]
    assert w.thumbs.count() == 3 and w._book == "2026-03-02"
    # the main window: its newest OD | OS on 다중 보기 (설정 → 일반 → 환자를 열면: 최신 OD | OS)
    assert w._tab() == "multi" and w.picks() == [ids["od3"], ids["os3"]] and w.multi.count == 2
    assert len(newest_first) == 8
    # no photo thumbnails in the list, and no patient information panel beside it (the table has it)
    assert not hasattr(pl, "photos") and not pl.findChildren(QLabel, "photoPic")
    assert not hasattr(pl, "photoRequested") and not hasattr(pl, "info_box") and not hasattr(pl, "lbl_name")
    assert not pl.findChildren(QLabel, "patientName")
    assert pl.left.width() > pl.width() - 60
    # the patient: its exams, 정보 수정 · 환자 삭제 (with the buttons at the bottom)
    assert pl.exam_stack.currentWidget() is pl.exams and not pl.lbl_exam_note.isVisible()
    assert pl.btn_edit.isVisible() and pl.btn_delete.isVisible()
    assert pl.btn_open.isEnabled() and pl.btn_open.text() == "사진 보기"
    # its exams: newest first, one selected (the newest), what was taken
    assert pl.exam_dates() == ["2026-03-02", "2025-12-01", "2025-08-20"] and pl.current_exam() == "2026-03-02"
    assert [pl.exams.item(r, 0).text() for r in range(3)] == ["2026-03-02  · 최근", "2025-12-01", "2025-08-20"]
    assert pl.exams.item(0, 3).text() == "컬러 3장 · Red-free 1장" and pl.exams.item(2, 3).text() == "컬러 1장 · 디스크 2장 1장"
    assert pl.exams.item(0, 1).text() == "OD · OS" and pl.exams.item(0, 2).text() == "4"
    assert pl.lbl_exams.text() == "검사 목록 · 3회 · 사진 8장"
    # another exam: it is the current one, the main window shows its OD | OS
    pl.set_exam("2025-12-01")
    assert pl.current_exam() == "2025-12-01" and pl.exams.selectionModel().selectedRows()[0].row() == 1
    assert w.picks() == [ids["od2"], ids["os2"]] and _grid_ids(w) == [ids["od2"], ids["os2"]]

    # a photo large in the main window (the list has none of its own)
    pl.hide()
    w.open_large(ids["od3"])
    assert w._tab() == "all" and w.current["id"] == ids["od3"] and w.view2d.has_image()
    # [Simple]: the newest OD | OS of the exam selected in the list
    w.tb_cmd.widgetForAction(w.acts["view:simple"]).click()
    assert w._tab() == "multi" and _grid_ids(w) == [ids["od2"], ids["os2"]]
    # a double click on a cell: that photo large (Detail, 0.13.12); the big photo double clicked: back
    cell = next(c for c in w.multi.cells if c.image_id == ids["os2"])
    QTest.mouseDClick(cell.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    app.processEvents()
    assert w._tab() == "all" and w.current["id"] == ids["os2"]
    QTest.mouseDClick(w.view2d.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    app.processEvents()
    assert w._tab() == "multi" and w.current["id"] == ids["os2"]
    assert _grid_ids(w) == [ids["od2"], ids["os2"]] and w.current["id"] == ids["os2"]
    # a drag moves that cell's photo and never opens it
    cell = next(c for c in w.multi.cells if c.image_id == ids["od2"])
    vp = cell.view.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=QPoint(30, 60))
    QTest.mouseMove(vp, QPoint(30, 20))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=QPoint(30, 20))
    app.processEvents()
    assert w._tab() == "multi" and w.current["id"] == ids["od2"]

    # the list again: double click (or Enter, or 사진 보기) opens the patient in the main window
    w.show_patient_list()
    assert pl.isVisible() and selected(pl.table) == refs["kim"]
    pl.table.selectRow(pl.row_of(refs["park"]))
    assert w._patient_ref == refs["park"] and _grid_ids(w) == [ids["p_od"]] and pl.current() == refs["park"]
    assert pl.lbl_exams.text() == "검사 목록 · 1회 · 사진 1장"
    pl.table.doubleClicked.emit(pl.table.model().index(pl.row_of(refs["park"]), 0))
    assert pl.isHidden() and w._tab() == "multi" and _grid_ids(w) == [ids["p_od"]]

    # a patient without photos: says so in place of its exams; nothing to open
    w.show_patient_list()
    pl.table.selectRow(pl.row_of(refs["jung"]))
    assert w._patient_ref == refs["jung"] and _grid_ids(w) == []
    assert pl.lbl_exams.text() == "검사 목록 · 0회 · 사진 0장" and pl.btn_edit.isVisible()
    assert pl.exam_stack.currentWidget() is pl.lbl_exam_empty and pl.lbl_exam_empty.isVisible()
    assert "아직 가져온 사진이 없습니다" in pl.lbl_exam_empty.text()
    assert not pl.btn_open.isEnabled() and not pl.btn_3d.isEnabled()
    pl.table.doubleClicked.emit(pl.table.model().index(pl.row_of(refs["jung"]), 0))
    assert pl.isVisible()
    # 미분류: its photos open as well, to be given a patient
    pl.table.selectRow(pl.row_of(UNASSIGNED))
    assert pl.current() == UNASSIGNED and pl.btn_open.isEnabled()
    assert not pl.btn_edit.isVisible() and not pl.btn_delete.isVisible()
    assert pl.lbl_exams.text() == "검사 목록 · 1회 · 사진 1장" and pl.exam_stack.currentWidget() is pl.exams
    assert "환자 ID를 찾지 못한" in pl.lbl_exam_note.text() and pl.lbl_exam_note.isVisible()
    pl.btn_open.click()                       # (its eye is known: on Simple, as a patient's)
    assert pl.isHidden() and w._tab() == "multi" and w._patient_ref == UNASSIGNED and w.current["id"] == ids["un"]

    # the list's search hides the patient on screen: it stays the patient, only not listed
    w.show_patient_list()
    pl.table.selectRow(pl.row_of(refs["kim"]))
    pl.f_name.setText("박")
    pl.refresh()
    assert pl.refs() == [refs["park"]] and selected(pl.table) is None and w._patient_ref == refs["kim"]
    assert pl.current() == refs["kim"] and pl.lbl_exams.text() == "검사 목록 · 3회 · 사진 8장"
    pl.btn_clear.click()
    assert selected(pl.table) == refs["kim"]

    # a new photo of the selected patient shows up in its exams; the selected exam stays
    pl.set_exam("2025-12-01")
    from fundusview.models import ExtractedMeta
    assert db.upsert_patient(ExtractedMeta(patient_id="K001")) == refs["kim"]
    db.insert_image(patient_ref=refs["kim"], exam_date="2026-04-01", exam_time="09:00:00", laterality="OD",
                    modality="color", file_path="missing.png", sha256="new")
    w.refresh_patients()
    assert pl.exam_dates()[0] == "2026-04-01" and pl.current_exam() == "2025-12-01"
    assert pl.table.item(pl.row_of(refs["kim"]), 7).text() == "9"
    assert pl.lbl_exams.text() == "검사 목록 · 4회 · 사진 9장"


def test_more_than_16_photos_page_by_16(win):
    """A patient with 33 photos: the patient list tells how many (it shows no photos). The VK-2 way
    (설정 → 일반 → 환자를 열면) shows them 16 to a screen in the main window (16장 보기), following the
    exam picked in the list."""
    app, w, db, refs, ids = win
    pl = w.patient_list
    src = db.get_image(ids["od3"])["file_path"]
    for k in range(32):
        day = f"2024-{1 + k // 4:02d}-{1 + k % 4:02d}"
        db.insert_image(patient_ref=refs["park"], exam_date=day, exam_time="10:00:00",
                        laterality="OD" if k % 2 else "OS", modality="color", file_path=src,
                        sha256=f"many{k}", width=320, height=300)
    w.refresh_patients()
    pl.table.selectRow(pl.row_of(refs["park"]))
    app.processEvents()
    order = [r["id"] for r in db.images_for_patient(refs["park"])]       # newest first
    assert len(order) == 33 and order[0] == ids["p_od"]
    assert pl.lbl_exams.text() == "검사 목록 · 33회 · 사진 33장" and pl.exam_dates()[-1] == "2024-01-01"
    # the first way: the main window shows the newest OD | OS (the OS of an earlier exam)
    assert w._tab() == "multi" and w.picks()[0] == ids["p_od"] and len(w.picks()) == 2
    # an exam picked in the list
    first_of = {d: next(i for i in order if db.get_image(i)["exam_date"] == d) for d in pl.exam_dates()}
    pl.set_exam("2024-02-01")
    assert pl.current_exam() == "2024-02-01" and order.index(first_of["2024-02-01"]) == 28

    # the VK-2 way: 사진 보기 opens 16장 보기 at the selected exam's photo, nothing picked
    w.settings.open_view = "grid"
    pl.btn_open.click()
    app.processEvents()
    assert pl.isHidden() and w._tab() == "grid" and w.picks() == []
    assert [g.image_id for g in w.grid.items()] == order                # newest first, both eyes
    assert w.current["id"] == first_of["2024-02-01"] and w.grid.visible_ids() == order[16:32]
    assert w.grid_bar.isVisible() and "17–32" in w.lbl_grid_page.text()
    w.btn_grid_prev.click()
    assert w.grid.visible_ids() == order[:16]
    # an exam picked in the list: 16장 보기 turns to its page
    w.show_patient_list()
    pl.set_exam("2024-01-01")
    assert w.grid.visible_ids() == order[32:] and w.grid.page() == 2
    pl.set_exam(pl.exam_dates()[0])
    assert w.grid.visible_ids() == order[:16]
    # a photo opened large, and back with [Multi] (nothing picked): 16장 보기 as it was
    w.open_large(order[5])
    assert w._tab() == "all" and w.current["id"] == order[5]
    w.tb_cmd.widgetForAction(w.acts["view:multi"]).click()
    assert w._tab() == "grid" and w.grid.visible_ids() == order[:16]


def test_empty_library_explains_how_photos_arrive(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False), db)
    try:
        w.show()
        app.processEvents()
        pl = w.patient_list
        assert pl.isVisible() and pl.list_stack.currentWidget() is pl.lbl_empty
        text = pl.lbl_empty.text()
        assert "아직 환자가 없습니다" in text and "감시 폴더" in text and "끌어다 놓아도" in text
        assert pl.btn_import.isEnabled() and not pl.btn_open.isEnabled()
        called = []
        w._import_files = lambda: called.append(1)
        pl.importRequested.disconnect()
        pl.importRequested.connect(w._import_files)
        pl.btn_import.click()
        assert called == [1]
        # dropping files on either window imports them
        assert w.acceptDrops() and pl.acceptDrops()
        dropped = []
        w.review_import = lambda paths: dropped.append(paths)
        pl.filesDropped.disconnect()
        pl.filesDropped.connect(w.review_import)
        pl.filesDropped.emit(["/x/a.jpg"])
        assert dropped == [["/x/a.jpg"]]
    finally:
        w.close()
        db.close()


def _settle(app, rv, timeout: float = 20.0):
    """Wait until the reduced photos of the larger layouts are on their cells."""
    import time
    end = time.time() + timeout
    while rv.loading() and time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not rv.loading()


def test_glaucoma_window_and_the_patient_lists_buttons(win):
    app, w, db, refs, ids = win
    w._select_patient_ref(refs["kim"])
    w._show_image(ids["od2"])
    dlg, why = w._build_glaucoma(ids["od3"])               # the window takes the pair
    assert dlg is not None and why == "" and dlg.progress.has_image()
    assert dlg.tabs.currentWidget() is dlg.progress       # two exam days: 경과 비교 comes first
    dlg.close()
    # the patient list: 사진 보기 (the selected exam's OD | OS on 다중 보기, OD selected) / 3D (that exam's photo)
    w.show_patient_list()
    w.patient_list.set_exam("2025-12-01")
    assert w.patient_list.btn_open.text() == "사진 보기"
    w.patient_list.btn_open.click()
    assert w.patient_list.isHidden() and w._tab() == "multi" and w.current["id"] == ids["od2"]
    assert w.picks() == [ids["od2"], ids["os2"]]
    w.show_patient_list()
    w.patient_list.btn_3d.click()
    assert w.patient_list.isHidden() and w._tab() == "3d" and w.current["id"] == ids["od2"]


def test_new_photo_still_opens_its_patient(win):
    """새 영상 자동 표시: a photo arriving while the patient list is on screen shows in the workspace."""
    from fundusview.importer import ImportResult

    app, w, db, refs, ids = win
    assert w.patient_list.isVisible() and w.act_follow.isChecked()
    res = ImportResult("imported", "new.png", "박정희", image_id=ids["p_od"], patient_ref=refs["park"])
    w._results.append(res)
    w._flush_results()
    # the patient list makes way for it: the new photo large
    assert w.patient_list.isHidden() and w._patient_ref == refs["park"] and w.current["id"] == ids["p_od"]
    assert w._tab() == "all" and w.view2d.has_image()
    assert w.patient_list.current() == refs["park"]                       # the list follows as well
    # on 다중 보기: the new photo is the newest OD of the OD | OS there — it stays on the multi view
    w._go("multi")
    w._results.append(res)
    w._flush_results()
    assert w._tab() == "multi" and ids["p_od"] in w.picks() and ids["p_od"] in _grid_ids(w)
    # a photo of unknown eye, not among Simple's: the big view
    w._results.append(ImportResult("imported", "x.png", "김영수", image_id=ids["na3"], patient_ref=refs["kim"]))
    w._flush_results()
    assert w._tab() == "all" and w.current["id"] == ids["na3"]
    # a bulk import at startup (--demo) is held back: the patient list stays
    w.show_patient_list()
    w.hold_follow()
    w._results.append(res)
    w._flush_results()
    assert w.patient_list.isVisible()
    w._on_status("대기 중")
    w._results.append(res)
    w._flush_results()
    assert w.patient_list.isHidden()


def test_one_patient_list_for_both_windows(win):
    """환자 목록 and the old 환자 창 are one: the window. The patient is the same whichever way it
    was chosen, and the photo screen keeps its whole width."""
    app, w, db, refs, ids = win
    pl = w.patient_list
    width = w.tabs.width()
    assert w.tabs.width() > 1300                                     # no patient pane beside the photos
    w.acts["list"].trigger()
    app.processEvents()
    assert pl.isHidden() and w.tabs.width() == width
    # chosen elsewhere (a new photo, the photo's 정보 수정 …): the list shows that patient when it comes up
    w._select_patient_ref(refs["park"])
    assert "박정희" in w.banner.text() and w.thumbs.count() == 1
    w.acts["list"].trigger()
    app.processEvents()
    assert pl.isVisible() and pl.current() == refs["park"] and pl.lbl_exams.text() == "검사 목록 · 1회 · 사진 1장"
    assert pl.refs()[pl.table.selectionModel().selectedRows()[0].row()] == refs["park"]
    # a deleted patient leaves both windows (its photos are 미분류 now)
    db.delete_patient(refs["park"])
    w.refresh_patients()
    assert w._patient_ref is None and pl.current() is None and w.thumbs.count() == 0
    assert w.banner.text() == "환자를 선택하세요"
    # keys stepping through the table: the photos follow once the stepping pauses (a click: at once)
    pl.select_delay = 60
    pl.table.selectRow(pl.row_of(refs["kim"]))
    assert w._patient_ref is None
    import time
    end = time.time() + 2
    while w._patient_ref != refs["kim"] and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert w._patient_ref == refs["kim"] and w.picks() == [ids["od3"], ids["os3"]]
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    r = pl.row_of(refs["jung"])
    QTest.mouseClick(pl.table.viewport(), Qt.MouseButton.LeftButton,
                     pos=pl.table.visualItemRect(pl.table.item(r, 1)).center())
    assert w._patient_ref == refs["jung"]                              # a click: at once
