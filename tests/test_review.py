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
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="")
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
    assert w.thumbs.count() == 7 and ids["na3"] not in w._strip_ids()     # 8 photos, na3 (eye unknown) not listed
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
    # a double click on a cell: that photo large
    cell = next(c for c in w.multi.cells if c.image_id == ids["os2"])
    QTest.mouseDClick(cell.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    app.processEvents()
    assert w._tab() == "all" and w.current["id"] == ids["os2"]
    w._go("multi")
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
    pl.btn_open.click()                       # (no eye known: 모두 보기, to be given a patient)
    assert pl.isHidden() and w._tab() == "all" and w._patient_ref == UNASSIGNED and w.current["id"] == ids["un"]

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
    # a photo opened large, and back with [Multi]: 16장 보기 as it was
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


def _show_review(w):
    """The 검토 page is no longer shown in the window (v0.3.0); its code stays and is tested here."""
    w.tabs.setCurrentWidget(w.review)


def _open_review(app, w, refs, who="kim"):
    pl = w.patient_list
    row = pl.row_of(refs[who])
    pl.table.selectRow(row)
    pl.table.doubleClicked.emit(pl.table.model().index(row, 0))
    app.processEvents()
    _show_review(w)
    app.processEvents()
    return w.review


def test_double_click_opens_the_review_of_both_eyes(win):
    from PySide6.QtCore import QPoint

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    # the 검토 tab (the first tab), the photo strip away: the timeline lists the photos
    assert w.patient_list.isHidden() and w._tab() == "review" and w.tabs.tabText(w.tabs.currentIndex()) == "검토"
    assert w.tabs.indexOf(rv) == 0 and w.tb_cmd.isVisible() and w.tb_proc.isVisible() and w.acts["prev"].isEnabled()
    assert not w.strip_w.isVisible() and not w.f_date.isVisible() and rv.timeline.isVisible()
    # 양안: left = OD, right = OS — the newest colour photo of each eye in the checked (newest) exam
    assert rv.stage == "ou" and rv.current == "2026-03-02" and rv.slot_ids() == [ids["od3"], ids["os3"]]
    assert all(v.has_image() and v.tag == "" for v in rv.views) and rv.active == 0 and rv.views[0].active
    assert not rv.prior_nav.isVisible()
    # both compare stages are possible (earlier exams of both eyes)
    model = rv.c_stage.model()
    assert [rv.c_stage.itemText(i) for i in range(3)] == ["양안 (OD | OS)", "OD 비교* (이전 | 현재)", "OS 비교* (이전 | 현재)"]
    assert all(model.item(i).isEnabled() for i in range(3))
    # the timeline: exams newest first, the current one marked, the viewer's own sheet left out,
    # frames on the photos that are on show
    assert [b.text() for b in rv.timeline.dates] == ["2026-03-02 · 현재", "2025-12-01", "2025-08-20"]
    assert [t.image_id for t in rv.timeline.thumbs] == [ids[k] for k in ("od3", "os3", "rf3", "na3", "od2", "os2", "od1")]
    assert {t.image_id for t in rv.timeline.thumbs if t.shown} == {ids["od3"], ids["os3"]}
    assert rv.timeline.lbl_count.text() == "검사 3회 · 7장"
    # a click on a view makes it the active one
    rv.views[1].pressed.emit()
    assert rv.active == 1 and rv.views[1].active and not rv.views[0].active
    # folding the timeline away gives its height to the photos
    h = rv.views[0].height()
    rv.timeline.btn_fold.click()
    app.processEvents()
    app.processEvents()                                # (the page's layout settles one pass later)
    assert not rv.timeline.scroll.isVisible() and rv.views[0].height() > h and rv.timeline.btn_fold.text() == "▸ 타임라인"
    rv.timeline.btn_fold.click()
    app.processEvents()
    assert rv.timeline.scroll.isVisible()

    # the other tabs get the photo strip back; coming back keeps the review as it was
    rv.set_stage("od")
    w._go("all")
    assert w.strip_w.isVisible() and not w.f_date.isVisible() and w.view2d.has_image()
    _show_review(w)
    assert not w.strip_w.isVisible() and rv.stage == "od"
    # the patient list again, and the patient's photos again
    w.act_patients.trigger()
    assert w.patient_list.isVisible() and w.tb_cmd.isVisible()
    w.patient_list.btn_open.click()                    # 사진 보기: the newest OD | OS on 다중 보기 now
    assert w.patient_list.isHidden() and w._tab() == "multi" and w.picks() == [ids["od3"], ids["os3"]]
    _show_review(w)
    assert rv.views[0].mapTo(w, QPoint(0, 0)).x() < rv.views[1].mapTo(w, QPoint(0, 0)).x()


def test_checked_exam_is_the_current_one_and_stages_follow(win):
    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    # OD 비교: left = the latest earlier exam (이전), right = the current exam (현재); [ / ] step back and forth
    rv.set_stage("od")
    assert rv.slot_ids() == [ids["od2"], ids["od3"]] and [v.tag for v in rv.views] == ["이전", "현재"]
    assert rv.prior_nav.isVisible() and rv.lbl_prior.text() == "이전 검사 1/2"
    assert rv.btn_older.isEnabled() and not rv.btn_newer.isEnabled()
    rv.step_prior(1)
    assert rv.slot_ids() == [ids["od1"], ids["od3"]] and rv.lbl_prior.text() == "이전 검사 2/2"
    assert not rv.btn_older.isEnabled() and rv.btn_newer.isEnabled()
    rv.step_prior(1)                                   # no older exam: stays
    assert rv.slot_ids()[0] == ids["od1"]
    rv.btn_newer.click()
    assert rv.slot_ids()[0] == ids["od2"]
    rv.btn_older.click()
    assert rv.slot_ids()[0] == ids["od1"]
    # the stages are chosen in the 배치 list (the arrows page through photos now); a new stage starts
    # at the latest earlier exam
    rv.c_stage.activated.emit(2)
    assert rv.stage == "os" and rv.slot_ids() == [ids["os2"], ids["os3"]] and rv.lbl_prior.text() == "이전 검사 1/1"
    rv.c_stage.activated.emit(0)
    assert rv.stage == "ou" and not rv.prior_nav.isVisible()
    rv.set_stage("os")
    assert rv.stage == "os" and rv.c_stage.currentData() == "os"

    # another exam selected in the patient list: it is the current one, older exams are its priors
    w.show_patient_list()
    w.patient_list.set_exam("2025-12-01")
    w.patient_list.btn_open.click()
    _show_review(w)
    assert rv.current == "2025-12-01" and rv.timeline.dates[1].property("current")
    assert [b.text() for b in rv.timeline.dates] == ["2026-03-02 · 최근", "2025-12-01 · 현재", "2025-08-20"]
    # OS has no earlier exam than this one: its compare stage is switched off and says why
    assert rv.stage == "ou" and rv.slot_ids() == [ids["od2"], ids["os2"]]
    model = rv.c_stage.model()
    assert [model.item(i).isEnabled() for i in range(3)] == [True, True, False]
    assert rv.c_stage.itemText(2) == "OS 비교* (이전 | 현재) — 이전 검사 없음" and "이전 검사 없음" not in rv.c_stage.itemText(1)
    rv.set_stage("os")
    assert rv.stage == "ou"                             # not possible: falls back to 양안
    rv.set_stage("od")
    assert rv.stage == "od" and rv.slot_ids() == [ids["od1"], ids["od2"]] and rv.lbl_prior.text() == "이전 검사 1/1"
    rv.set_stage("ou")

    # the oldest exam: OS was not taken then — nothing earlier to fall back on; no compare stage at all
    w.patient_list.set_exam("2025-08-20")
    assert rv.current == "2025-08-20" and rv.slot_ids() == [ids["od1"], None]
    assert not rv.views[1].has_image() and rv.views[1].empty_text == "OS 좌안 사진이 없습니다"
    assert not rv.prior_nav.isVisible() and rv.prior_count() == 0
    rv.set_active(1)
    assert not rv.btn_2d.isEnabled() and not rv.btn_glaucoma.isEnabled()
    rv.set_active(0)
    assert rv.btn_2d.isEnabled()

    # a date of the timeline makes that exam the current one — in the patient list as well
    rv.timeline.dates[0].click()
    assert rv.current == "2026-03-02" and w.patient_list.current_exam() == "2026-03-02"
    assert w.patient_list.exams.selectionModel().selectedRows()[0].row() == 0

    # an eye missing from the current exam falls back to its newest earlier photo, tagged 이전
    db.delete_image(ids["os3"])
    w._fill_thumbs()
    assert rv.slot_ids() == [ids["od3"], ids["os2"]] and [v.tag for v in rv.views] == ["", "이전"]

    # another patient: one exam only, the stage falls back to 양안
    rv.set_stage("od")
    w._select_patient_ref(refs["park"])
    assert rv.stage == "ou" and rv.slot_ids()[0] == ids["p_od"] and rv.slot_ids()[1] is None
    assert [model.item(i).isEnabled() for i in range(3)] == [True, False, False]


def test_drop_puts_a_photo_on_a_cell(win):
    """A timeline photo dragged onto a cell goes to that cell (a click selects — see the multi-view tests)."""
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from fundusview.ui.review_view import MIME

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)

    def drop(view, image_id):
        mime = QMimeData()
        mime.setData(MIME, str(image_id).encode())
        enter = QDragEnterEvent(QPoint(30, 30), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
        view.dragEnterEvent(enter)
        assert enter.isAccepted() and view._drop
        view.dropEvent(QDropEvent(QPointF(30, 30), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                  Qt.KeyboardModifier.NoModifier))
        assert not view._drop

    # the stage's pair: the dropped photo takes that cell, whatever its eye; an earlier one is tagged 이전
    drop(rv.views[1], ids["od2"])
    assert rv.slot_ids() == [ids["od3"], ids["od2"]] and rv.active == 1 and rv.views[1].tag == "이전"
    assert rv.selection == [] and rv.preset and rv.layout_n == 2
    assert {t.image_id for t in rv.timeline.thumbs if t.shown} == {ids["od3"], ids["od2"]}
    drop(rv.views[0], ids["na3"])
    assert rv.slot_ids() == [ids["na3"], ids["od2"]] and rv.views[0].tag == ""
    rv.set_stage("od")
    drop(rv.views[0], ids["rf3"])
    assert rv.slot_ids()[0] == ids["rf3"] and rv.views[0].tag == "현재"
    # files are left to the window's import
    files = QMimeData()
    files.setUrls([])
    enter = QDragEnterEvent(QPoint(30, 30), Qt.DropAction.CopyAction, files, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    rv.views[1].dragEnterEvent(enter)
    assert not enter.isAccepted() and not rv.views[1]._drop
    # choosing the stage again puts the default photos back
    rv.set_stage("ou")
    assert rv.slot_ids() == [ids["od3"], ids["os3"]]
    # in a selection the dropped photo takes the place of that cell's photo
    for k in ("od3", "os3", "od2"):
        rv.timeline.photoClicked.emit(ids[k])
    _settle(app, rv)
    assert rv.layout_n == 4 and rv.selection == [ids["od3"], ids["os3"], ids["od2"]]
    drop(rv.views[1], ids["od1"])
    _settle(app, rv)
    assert rv.selection == [ids["od3"], ids["od1"], ids["od2"]] and rv.slot_ids()[:3] == rv.selection
    drop(rv.views[3], ids["os2"])                        # an empty cell: added at the end
    assert rv.selection[-1] == ids["os2"] and len(rv.selection) == 4
    drop(rv.views[0], ids["od2"])                        # already picked: it moves, nothing doubles
    assert rv.selection == [ids["od2"], ids["od1"], ids["os2"]]


def test_linked_views_view_modes_and_zoom(win):
    import numpy as np
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    from fundusview.ui.image_view import from_qimage

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    rv.set_stage("od")                                   # left 400 × 300, right 320 × 300: different sizes
    a, b = rv.views
    assert a._rgb.shape[:2] == (300, 400) and b._rgb.shape[:2] == (300, 320)
    assert rv.link and rv.sw_link.isChecked() and a.view_state()[3] and b.view_state()[3]

    def state(v):
        return v.view_state()

    # the wheel zooms at the cursor; the other view follows to the same place of its photo
    QTest.qWait(1)
    wheel_at = QPoint(a.viewport().width() // 3, a.viewport().height() // 3)
    under = a.mapToScene(wheel_at)
    a._wheel_at, a._wheel_scene = wheel_at, under
    a._wheel_part(8)                                     # eight notches: the photo is larger than the view
    assert a.zoomed_in() and (a.mapToScene(wheel_at) - under).manhattanLength() < 2.5      # the point stays put
    assert state(b)[0] == pytest.approx(state(a)[0], rel=1e-6) and not state(b)[3]
    assert state(b)[1] == pytest.approx(state(a)[1], abs=0.02) and state(b)[2] == pytest.approx(state(a)[2], abs=0.02)
    # dragging one view moves the other
    before = state(b)
    vp = a.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    QTest.mouseMove(vp, QPoint(150, 170))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=QPoint(150, 170))
    a.stop_motion()
    assert state(a)[1] > before[1] and state(b)[1] == pytest.approx(state(a)[1], abs=0.02)
    assert state(b)[2] == pytest.approx(state(a)[2], abs=0.02)
    # + / − on the bar zoom the active view (the other follows); 맞춤 shows both whole again
    rv.set_active(1)
    z = b.zoom
    rv.btn_in.click()
    assert b.zoom == pytest.approx(z * 1.25) and state(a)[0] == pytest.approx(state(b)[0], rel=1e-6)
    rv.btn_out.click()
    assert b.zoom == pytest.approx(z)
    rv.btn_fit.click()
    assert state(a)[3] and state(b)[3] and not a.zoomed_in() and not b.zoomed_in()
    # 맞춤 from the other cell as well (a double click is "this photo alone" now, not fit)
    b.zoom_to(b.zoom * 3)
    assert a.zoomed_in()
    rv.set_active(0)
    rv.fit()
    assert not a.zoomed_in() and not b.zoomed_in()
    # 연동 off: each view on its own; on again: the other joins the active view
    rv.sw_link.setChecked(False)
    a.zoom_to(a.zoom * 2)
    assert a.zoomed_in() and not b.zoomed_in() and state(b)[3]
    rv.set_active(0)
    rv.sw_link.setChecked(True)
    assert state(b)[0] == pytest.approx(state(a)[0], rel=1e-6) and b.zoomed_in()
    # stepping to another earlier exam keeps the place
    kept = state(a)
    rv.step_prior(1)
    assert rv.slot_ids()[0] == ids["od1"] and state(a)[0] == pytest.approx(kept[0], rel=1e-6)
    assert state(a)[1] == pytest.approx(kept[1], abs=0.02)
    rv.btn_fit.click()

    # 보기: 컬러 / 감각망막 = the green channel / 맥락막 = the red channel, on both views; the place is kept
    raw = w._load(db.get_image(ids["od3"]))
    assert [rv.c_view.itemText(i) for i in range(3)] == ["컬러", "감각망막 (적색 제거)", "맥락막 (녹색 제거)"]
    assert np.array_equal(b._rgb, raw)
    b.zoom_to(b.zoom * 2)
    kept = state(b)
    rv.c_view.setCurrentIndex(1)
    assert rv.view_mode == "retina" and np.array_equal(b._rgb[..., 0], raw[..., 1])
    assert np.array_equal(b._rgb[..., 0], b._rgb[..., 2]) and np.array_equal(a._rgb[..., 0], a._rgb[..., 1])
    assert state(b)[0] == pytest.approx(kept[0], rel=1e-6) and rv.slot_ids() == [ids["od1"], ids["od3"]]
    rv.c_view.setCurrentIndex(2)
    assert rv.view_mode == "choroid" and np.array_equal(b._rgb[..., 1], raw[..., 0])
    shown = from_qimage(b._pix.pixmap().toImage())
    assert np.array_equal(shown[..., 0], raw[..., 0]) and np.array_equal(shown[..., 2], raw[..., 0])
    # a photo put on a view while a channel is chosen is shown in that channel too
    rv.show_photo(ids["od2"], 0)
    assert np.array_equal(a._rgb[..., 0], a._rgb[..., 1])
    rv.c_view.setCurrentIndex(0)
    assert np.array_equal(b._rgb, raw)
    # the stored photo and the 2D view's own adjustments are untouched
    assert w._channel == "rgb" and np.array_equal(w._load(db.get_image(ids["od3"])), raw)


def test_magnifier(win):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    rv.set_stage("od")
    lens, (a, b) = rv.lens, rv.views
    assert not lens.isVisible() and not rv.sw_lens.isChecked()
    # the switch shows it over the active view
    rv.sw_lens.click()
    assert lens.isVisible() and lens.host() == 0 and lens.mag == 2.5
    assert lens.caption() == "2.5× · OD 2025-12-01"
    # what it shows: the photo under its centre, 2.5 times larger than the view shows it
    shown, rect = lens.source()
    centre = a.mapToScene(a.viewport().mapFrom(rv.stage_w, lens.geometry().center()))
    assert shown is a and rect.center().x() == pytest.approx(centre.x(), abs=0.6)
    assert rect.width() == pytest.approx(lens.SIDE / (a.zoom * 2.5))
    # dragging moves it (kept inside the two views); over the other view it shows that photo
    QTest.mousePress(lens, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    target = QPoint(b.x() + b.width() // 2, b.height() // 2)
    QTest.mouseMove(lens, lens.mapFromParent(target))
    QTest.mouseRelease(lens, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    assert lens.host() == 1 and lens.caption() == "2.5× · OD 2026-03-02"
    assert (lens.geometry().center() - target).manhattanLength() <= 2
    lens.move_to(QPoint(-500, 99999))
    assert rv.stage_w.rect().contains(lens.geometry())
    lens.move_to(target)
    # the wheel changes the magnification between 1.5× and 6×
    def wheel(delta):
        ev = QWheelEvent(QPointF(100, 100), QPointF(lens.mapToGlobal(QPoint(100, 100))), QPoint(0, 0),
                         QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        lens.wheelEvent(ev)
    wheel(120)
    assert lens.mag == pytest.approx(2.5 * 1.15) and lens.caption().startswith("2.9×")
    for _ in range(20):
        wheel(120)
    assert lens.mag == 6.0
    for _ in range(40):
        wheel(-120)
    assert lens.mag == 1.5
    zoom_before = b.zoom
    assert b.zoom == zoom_before                         # the wheel over the 확대창 does not zoom the photo
    # a right click shows the other view's photo at the same place of the photo
    QTest.mouseClick(lens, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert lens.other and lens.caption() == "1.5× · OD 2025-12-01 · 반대쪽"
    shown, rect = lens.source()
    here = b.mapToScene(b.viewport().mapFrom(rv.stage_w, lens.geometry().center()))
    assert shown is a
    assert rect.center().x() / 400 == pytest.approx(here.x() / 320, abs=0.01)      # the same fraction of the photo
    assert rect.center().y() / 300 == pytest.approx(here.y() / 300, abs=0.01)
    assert not lens.grab().toImage().isNull()
    QTest.mouseClick(lens, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert not lens.other
    # a middle click on a view switches it off / on there; on the 확대창 itself: off
    QTest.mouseClick(a.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(60, 80))
    assert not lens.isVisible() and not rv.sw_lens.isChecked()
    QTest.mouseClick(a.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(160, 180))
    assert lens.isVisible() and rv.sw_lens.isChecked() and lens.host() == 0
    assert (lens.geometry().center() - a.viewport().mapTo(rv.stage_w, QPoint(160, 180))).manhattanLength() <= 2
    QTest.mouseClick(lens, Qt.MouseButton.MiddleButton, pos=QPoint(100, 100))
    assert not lens.isVisible() and not rv.sw_lens.isChecked()
    # over a view without a photo it says where to go
    w.patient_list.set_exam("2025-08-20")                # OS not taken then
    rv.set_lens(True, QPoint(b.x() + 150, 150))
    assert lens.source() is None and lens.caption() == "사진 위로 옮기세요"


def test_hand_off_to_2d_3d_and_glaucoma(win):
    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    # 2D 보기: the active view's photo becomes the photo on screen, on 모두 보기 (whose big photo is the 2D view)
    rv.set_active(1)
    rv.btn_2d.click()
    assert w._tab() == "all" and w.current["id"] == ids["os3"] and w.view2d.has_image()
    assert w.thumbs.currentItem().data(0x0100) == ids["os3"] and w.strip_w.isVisible()
    # the 2D view's adjustments work as ever and do not reach the review
    w._on_action("chan:redfree")
    assert w._channel == "redfree"
    _show_review(w)
    assert rv.view_mode == "color" and rv.slot_ids() == [ids["od3"], ids["os3"]]
    w._on_action("chan:redfree", False)
    # 3D 안구
    rv.set_active(0)
    rv.btn_3d.click()
    assert w._tab() == "3d" and w.current["id"] == ids["od3"]
    # 녹내장: the existing window, through the existing entry point; in a compare stage with both photos
    opened = []
    w.open_glaucoma = lambda second=None: opened.append((w.current["id"], second))
    _show_review(w)
    rv.set_stage("ou")
    rv.set_active(1)
    rv.btn_glaucoma.click()
    assert opened == [(ids["os3"], None)] and w._tab() == "review"
    rv.set_stage("od")
    rv.set_active(1)
    rv.btn_glaucoma.click()
    assert opened[-1] == (ids["od3"], ids["od2"])
    rv.set_active(0)
    rv.hand_off("glaucoma")
    assert opened[-1] == (ids["od2"], ids["od3"])
    del w.open_glaucoma
    dlg, why = w._build_glaucoma(ids["od3"])               # the real window takes the pair
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
    # on the 검토 tab: a photo that is one of the two under review stays there …
    _show_review(w)
    w._results.append(res)
    w._flush_results()
    assert w._tab() == "review" and w.review.slot_ids()[0] == ids["p_od"]
    # … one that is not (unknown eye) is shown in the big view
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


def test_review_bar_wraps_instead_of_widening_the_window(win):
    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    lay = rv.bar_lay
    full = sum(lay.itemAt(i).sizeHint().width() + lay.spacing() for i in range(lay.count())) + 20
    w.resize(w.width() - rv.width() + full + 40, 960)       # room for every control: one line
    app.processEvents()
    assert rv.width() >= full and lay.rows() == 1
    assert rv.minimumSizeHint().width() < 420               # but the bar never asks for that width
    w.resize(w.minimumSizeHint().width(), 700)
    app.processEvents()
    assert rv.width() < full and lay.rows() >= 2 and all(v.width() > 100 for v in rv.views)
    last = rv.btn_glaucoma
    assert last.mapTo(rv, last.rect().bottomRight()).x() <= rv.width()      # nothing is cut off


def test_real_mouse_wheel_zooms_the_review_views(win):
    """A real wheel event over a photo (not the internal helper) zooms in and out at the cursor."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    a, b = rv.views
    vp = a.viewport()
    pos = QPoint(vp.width() // 2, vp.height() // 2)

    def wheel(delta):
        ev = QWheelEvent(QPointF(pos), QPointF(vp.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, delta),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(vp, ev)
        QTest.qWait(30)                                  # the view glides after the notches
        app.processEvents()

    z0, zb0 = a.view_state()[0], b.view_state()[0]
    for _ in range(8):                                   # right after opening: a late list refresh must not undo it
        wheel(120)
    z1 = a.view_state()[0]
    assert z1 > z0 * 1.3 and a.zoomed_in()               # wheel up = larger
    assert b.view_state()[0] > zb0 * 1.3                 # the linked view follows
    for _ in range(2):
        wheel(-120)
    assert z0 < a.view_state()[0] < z1                   # wheel down = smaller again
    # the same photos handed over again (list refresh) keep the zoom; a real change fits again
    z = a.view_state()[0]
    w._review_dirty = True
    w._fill_review()
    assert a.view_state()[0] == pytest.approx(z) and a.zoomed_in()


def test_timeline_eye_filter(win):
    """모두 / OD / OS on the timeline: only that eye's photos are listed; 모두 is the default."""
    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    tl = rv.timeline
    eye_of = {i: db.get_image(i)["laterality"] for i in ids.values()}
    everything = [t.image_id for t in tl.thumbs]
    assert tl.eye == "" and tl.eye_buttons[""].isChecked() and len(everything) == 7

    tl.eye_buttons["OD"].click()
    assert tl.eye == "OD" and [t.image_id for t in tl.thumbs] == [i for i in everything if eye_of[i] == "OD"]
    assert tl.thumbs and all(eye_of[t.image_id] == "OD" for t in tl.thumbs)
    assert [b.text() for b in tl.dates] == ["2026-03-02 · 현재", "2025-12-01", "2025-08-20"]
    assert tl.lbl_count.text() == f"검사 3회 · {len(tl.thumbs)}장"
    assert {t.image_id for t in tl.thumbs if t.shown} == {ids["od3"]}       # the frame stays on the photo on show

    tl.eye_buttons["OS"].click()
    assert [t.image_id for t in tl.thumbs] == [i for i in everything if eye_of[i] == "OS"]
    assert [b.text() for b in tl.dates] == ["2026-03-02 · 현재", "2025-12-01"]   # no OS photo in the oldest exam
    # the cells themselves are not filtered: the stage's pair stays, only the pool to page through changes
    assert rv.slot_ids() == [ids["od3"], ids["os3"]] and rv.preset
    assert [r["id"] for r in rv.pool()] == [i for i in everything if eye_of[i] == "OS"] and rv.position() == "2장 / 2"
    # the choice stays when the photos are handed over again, and 모두 brings everything back
    rv.set_photos(rv.rows, "2025-12-01")
    assert tl.eye == "OS" and all(eye_of[t.image_id] == "OS" for t in tl.thumbs)
    tl.set_eye("")
    assert tl.eye_buttons[""].isChecked() and len(tl.thumbs) == 7


# ---------------------------------------------------------------------------------------------
# 검토 as a multi-view: the cells show what is selected; layouts 1 – 32; paging; one photo alone
# ---------------------------------------------------------------------------------------------
def _pool_ids(rv):
    return [r["id"] for r in rv.pool()]


def test_review_opens_two_up_and_selection_sets_the_layout(win):
    from fundusview.ui.review_view import LAYOUTS, layout_for

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    tl = rv.timeline
    thumb = {t.image_id: t for t in tl.thumbs}
    assert list(LAYOUTS) == [1, 2, 4, 8, 16, 32]
    assert [LAYOUTS[n] for n in LAYOUTS] == [(1, 1), (2, 1), (2, 2), (4, 2), (4, 4), (8, 4)]     # columns × rows
    assert [layout_for(n) for n in (1, 2, 3, 4, 5, 8, 9, 16, 17, 40)] == [1, 2, 4, 4, 8, 8, 16, 16, 32, 32]
    # the first screen: the stage's pair on two cells, nothing selected
    assert rv.preset and rv.layout_n == 2 and len(rv.views) == 2 and rv.selection == []
    assert rv.slot_ids() == [ids["od3"], ids["os3"]] and rv.layout_buttons[2].isChecked()
    assert [b.text() for b in rv.seg_layout.buttons] == ["1", "2", "4", "8", "16", "32"]
    assert not rv.btn_clear.isVisible() and rv.lbl_pos.text() == "2장 / 7"
    assert all(t.rank == 0 for t in tl.thumbs)

    # a click selects (numbered in the order picked); the cells show the selected photos and the
    # layout is the smallest that holds them: 1 → 2 → 4 → 8
    thumb[ids["od2"]].click()
    assert rv.selection == [ids["od2"]] and not rv.preset and rv.layout_n == 1 and rv.slot_ids() == [ids["od2"]]
    assert thumb[ids["od2"]].rank == 1 and thumb[ids["od2"]].shown and rv.btn_clear.isVisible()
    assert rv.layout_buttons[1].isChecked() and rv.lbl_pos.text() == "1 / 1" and not rv.prior_nav.isVisible()
    thumb[ids["os2"]].click()
    assert rv.layout_n == 2 and rv.slot_ids() == [ids["od2"], ids["os2"]] and rv.lbl_pos.text() == "1–2 / 2"
    assert all(v.has_image() and v.tag == "" for v in rv.views)
    thumb[ids["od1"]].click()
    _settle(app, rv)
    assert rv.layout_n == 4 and rv.slot_ids() == [ids["od2"], ids["os2"], ids["od1"], None]
    assert [thumb[ids[k]].rank for k in ("od2", "os2", "od1", "od3")] == [1, 2, 3, 0]
    assert sum(v.isVisible() for v in rv.cells) == 4 and not rv.views[3].has_image()
    g = [rv.views[i].mapTo(rv.stage_w, rv.views[i].rect().topLeft()) for i in range(4)]
    assert g[0].y() == g[1].y() < g[2].y() == g[3].y() and g[0].x() == g[2].x() < g[1].x()        # 2 × 2
    thumb[ids["od3"]].click()
    thumb[ids["os3"]].click()
    _settle(app, rv)
    assert rv.layout_n == 8 and rv.slot_ids()[:5] == rv.selection and rv.slot_ids()[5:] == [None] * 3
    assert rv.lbl_pos.text() == "1–5 / 5" and not rv.btn_next.isEnabled() and not rv.btn_prev.isEnabled()
    g = [rv.views[i].mapTo(rv.stage_w, rv.views[i].rect().topLeft()) for i in range(8)]
    assert len({p.y() for p in g}) == 2 and len({p.x() for p in g}) == 4                          # 4 columns × 2 rows
    assert all(v.compact == 1 for v in rv.views)
    # the clicked photo's cell is the active one; hand-offs take the active cell (no pair outside a stage)
    assert rv.active == 4 and rv.active_row()["id"] == ids["os3"]
    sent = []
    w.open_glaucoma = lambda second=None: sent.append((w.current["id"], second))     # (the real window is modal)
    rv.hand_off("glaucoma")
    assert sent == [(ids["os3"], None)]
    del w.open_glaucoma

    # deselecting: the layout shrinks again; with nothing left the stage's pair is back
    thumb[ids["od1"]].click()
    _settle(app, rv)
    assert rv.layout_n == 4 and rv.selection == [ids["od2"], ids["os2"], ids["od3"], ids["os3"]]
    assert thumb[ids["od3"]].rank == 3 and thumb[ids["od1"]].rank == 0
    for k in ("od2", "os2", "od3"):
        thumb[ids[k]].click()
    assert rv.selection == [ids["os3"]] and rv.layout_n == 1
    thumb[ids["os3"]].click()
    assert rv.selection == [] and rv.preset and rv.layout_n == 2 and rv.slot_ids() == [ids["od3"], ids["os3"]]
    assert not rv.btn_clear.isVisible() and all(t.rank == 0 for t in tl.thumbs)
    # 선택 해제 and choosing a stage clear the selection as well
    thumb[ids["od1"]].click()
    thumb[ids["od2"]].click()
    rv.btn_clear.click()
    assert rv.selection == [] and rv.preset and rv.slot_ids() == [ids["od3"], ids["os3"]]
    thumb[ids["od1"]].click()
    rv.c_stage.activated.emit(1)
    assert rv.stage == "od" and rv.selection == [] and rv.preset and rv.slot_ids() == [ids["od2"], ids["od3"]]
    assert rv.prior_nav.isVisible()

    # the same photos handed over again (a list refresh): selection, layout and page stay
    thumb[ids["od1"]].click()
    thumb[ids["os2"]].click()
    thumb[ids["na3"]].click()
    _settle(app, rv)
    rv.views[0].zoom_to(rv.views[0].zoom * 2)
    zoom = rv.views[0].zoom
    w._fill_thumbs()
    w.refresh_patients()
    assert rv.selection == [ids["od1"], ids["os2"], ids["na3"]] and rv.layout_n == 4 and not rv.preset
    assert rv.slot_ids()[:3] == rv.selection and rv.views[0].zoom == pytest.approx(zoom)
    assert thumb[ids["os2"]].rank == 2


def test_layout_control_and_paging(win):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    pool = _pool_ids(rv)                                  # the timeline's photos, in its order
    assert pool == [ids[k] for k in ("od3", "os3", "rf3", "na3", "od2", "os2", "od1")]
    # choosing the layout the tab is already in changes nothing
    rv.layout_buttons[2].click()
    assert rv.preset and rv.slot_ids() == [ids["od3"], ids["os3"]]
    # 4: the cells are filled from the pool, starting at the first photo on screen
    rv.layout_buttons[4].click()
    _settle(app, rv)
    assert not rv.preset and rv.layout_n == 4 and rv.start == 0 and rv.slot_ids() == pool[0:4]
    assert rv.lbl_pos.text() == "1–4 / 7" and not rv.btn_prev.isEnabled() and rv.btn_next.isEnabled()
    assert not rv.prior_nav.isVisible() and rv.selection == []
    assert {t.image_id for t in rv.timeline.thumbs if t.shown} == set(pool[0:4])
    # ▶: the next four — the cells past the end are empty; clamped at both ends
    rv.btn_next.click()
    _settle(app, rv)
    assert rv.start == 4 and rv.slot_ids() == pool[4:7] + [None] and rv.lbl_pos.text() == "5–7 / 7"
    assert rv.btn_prev.isEnabled() and not rv.btn_next.isEnabled()
    rv.page(1)
    assert rv.start == 4
    rv.btn_prev.click()
    _settle(app, rv)
    assert rv.start == 0 and rv.slot_ids() == pool[0:4]
    rv.page(-1)
    assert rv.start == 0
    # the ← / → keys do the same
    rv.views[0].setFocus()
    QTest.keyClick(rv.views[0], Qt.Key.Key_Right)
    _settle(app, rv)
    assert rv.start == 4
    QTest.keyClick(rv.views[0], Qt.Key.Key_Left)
    _settle(app, rv)
    assert rv.start == 0
    # 2 from there: the page starts at the first photo on screen; ▶ moves by two
    rv.page(1)
    rv.layout_buttons[2].click()
    assert rv.layout_n == 2 and rv.start == 4 and rv.slot_ids() == pool[4:6] and rv.lbl_pos.text() == "5–6 / 7"
    rv.btn_next.click()
    assert rv.slot_ids() == [pool[6], None] and rv.lbl_pos.text() == "7 / 7"
    # 1: one photo, the arrows walk one at a time
    rv.layout_buttons[1].click()
    assert rv.layout_n == 1 and rv.slot_ids() == [pool[6]] and rv.lbl_pos.text() == "7 / 7"
    rv.btn_prev.click()
    assert rv.slot_ids() == [pool[5]] and rv.lbl_pos.text() == "6 / 7"
    rv.views[0].setFocus()
    QTest.keyClick(rv.views[0], Qt.Key.Key_Left)          # one key press = one step
    assert rv.lbl_pos.text() == "5 / 7"
    QTest.keyClick(rv.views[0], Qt.Key.Key_Right)
    assert rv.lbl_pos.text() == "6 / 7"
    # 16 and 32: every photo there is, the rest empty; small cells carry the eye and the date only
    rv.layout_buttons[16].click()
    _settle(app, rv)
    assert rv.layout_n == 16 and sum(v.isVisible() for v in rv.cells) == 16 and rv.start == 5
    assert rv.slot_ids()[:2] == pool[5:7] and rv.slot_ids()[2:] == [None] * 14
    rv.page(-1)
    rv.layout_buttons[32].click()
    _settle(app, rv)
    assert rv.layout_n == 32 and rv.start == 0 and rv.slot_ids()[:7] == pool and rv.lbl_pos.text() == "1–7 / 7"
    assert all(v.compact == 2 for v in rv.views) and sum(v.has_image() for v in rv.views) == 7
    g = [rv.views[i].mapTo(rv.stage_w, rv.views[i].rect().topLeft()) for i in range(32)]
    assert len({p.y() for p in g}) == 4 and len({p.x() for p in g}) == 8                          # 8 columns × 4 rows
    assert all(v.width() > 60 and v.height() > 40 for v in rv.views)
    # from the stage's pair the arrows start at the pair's place in the pool
    rv.set_stage("ou")
    assert rv.preset and rv.layout_n == 2 and not rv.btn_prev.isEnabled() and rv.btn_next.isEnabled()
    rv.btn_next.click()
    assert not rv.preset and rv.slot_ids() == pool[2:4] and rv.lbl_pos.text() == "3–4 / 7"
    # with a selection the pool is the selection
    for k in ("od1", "od2", "od3"):
        rv.timeline.photoClicked.emit(ids[k])
    rv.layout_buttons[2].click()
    assert rv.slot_ids() == [ids["od1"], ids["od2"]] and rv.lbl_pos.text() == "1–2 / 3"
    rv.btn_next.click()
    assert rv.slot_ids() == [ids["od3"], None] and rv.selection == [ids["od1"], ids["od2"], ids["od3"]]

    # the eye filter with nothing selected: another pool, but what is on screen stays until paged
    rv.btn_clear.click()
    rv.layout_buttons[2].click()
    rv.page(1)
    assert rv.slot_ids() == pool[2:4]                     # rf3 (OD), na3 (unknown eye)
    rv.timeline.set_eye("OD")
    od = _pool_ids(rv)
    assert od == [ids[k] for k in ("od3", "rf3", "od2", "od1")] and rv.slot_ids() == pool[2:4]
    assert rv.start == 1 and rv.lbl_pos.text() == "2–3 / 4"
    rv.btn_next.click()
    assert rv.slot_ids() == od[3:4] + [None]
    rv.timeline.set_eye("")


def test_double_click_shows_one_photo_and_back(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    pool = _pool_ids(rv)

    def dclick(i=0):
        QTest.mouseDClick(rv.views[i].viewport(), Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
        _settle(app, rv)

    # from a compare stage: the photo alone, whole; again: the stage exactly as it was (the prior too)
    rv.set_stage("od")
    rv.step_prior(1)
    assert rv.slot_ids() == [ids["od1"], ids["od3"]]
    rv.views[0].zoom_to(rv.views[0].zoom * 3)
    dclick(1)
    assert rv.layout_n == 1 and rv.slot_ids() == [ids["od3"]] and not rv.views[0].zoomed_in()      # not "fit"
    assert rv.layout_buttons[1].isChecked() and not rv.prior_nav.isVisible() and rv.lbl_pos.text() == "1 / 7"
    assert rv.views[0]._rgb.shape == w._load(db.get_image(ids["od3"])).shape                      # the full photo
    dclick()
    assert rv.preset and rv.stage == "od" and rv.layout_n == 2 and rv.prior == 1 and rv.active == 1
    assert rv.slot_ids() == [ids["od1"], ids["od3"]] and rv.prior_nav.isVisible()
    # walking with the arrows in the single view, then back: the page that holds the photo last seen
    dclick(1)
    rv.btn_next.click()
    rv.btn_next.click()
    rv.btn_next.click()
    assert rv.slot_ids() == [pool[3]] and rv.lbl_pos.text() == "4 / 7"
    dclick()
    assert not rv.preset and rv.layout_n == 2 and rv.start == 2 and rv.slot_ids() == pool[2:4] and rv.active == 1
    # from a page of four
    rv.layout_buttons[4].click()
    rv.page(-1)
    _settle(app, rv)
    assert rv.slot_ids() == pool[0:4]
    dclick(2)
    assert rv.layout_n == 1 and rv.slot_ids() == [pool[2]] and rv.lbl_pos.text() == "3 / 7"
    dclick()
    assert rv.layout_n == 4 and rv.start == 0 and rv.slot_ids() == pool[0:4] and rv.active == 2
    dclick(2)
    rv.page(1)
    rv.page(1)
    rv.page(1)
    dclick()
    assert rv.layout_n == 4 and rv.start == 4 and rv.slot_ids() == pool[4:7] + [None] and rv.active == 1
    # an empty cell and a single layout chosen with the control have nothing to go to / back to
    dclick(3)
    assert rv.layout_n == 4
    rv.layout_buttons[1].click()
    dclick()
    assert rv.layout_n == 1
    # in a selection as well
    rv.set_stage("ou")
    for k in ("od1", "os2", "od2"):
        rv.timeline.photoClicked.emit(ids[k])
    _settle(app, rv)
    dclick(1)
    assert rv.layout_n == 1 and rv.slot_ids() == [ids["os2"]] and rv.selection == [ids["od1"], ids["os2"], ids["od2"]]
    assert rv.lbl_pos.text() == "2 / 3"
    dclick()
    assert rv.layout_n == 4 and rv.slot_ids()[:3] == rv.selection and rv.active == 1


def test_link_and_magnifier_across_many_cells(win):
    from PySide6.QtCore import QPoint

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    for k in ("od3", "os3", "od2", "od1"):               # od2 is 400 × 300, the others 320 × 300
        rv.timeline.photoClicked.emit(ids[k])
    _settle(app, rv)
    cells = rv.views
    assert rv.layout_n == 4 and all(v.has_image() for v in cells) and all(v.view_state()[3] for v in cells)
    # 연동: zooming or moving one cell takes all the others to the same place of their photos
    v = cells[2]
    at = v.viewport().rect().center()                     # (near an edge a narrower photo cannot follow all the way)
    v._wheel_at, v._wheel_scene = at, v.mapToScene(at)
    v._wheel_part(8)
    ref = v.view_state()
    assert v.zoomed_in() and not ref[3]
    for other in cells:
        st = other.view_state()
        assert st[0] == pytest.approx(ref[0], rel=1e-6) and st[1] == pytest.approx(ref[1], abs=0.03)
        assert st[2] == pytest.approx(ref[2], abs=0.03)
    v.horizontalScrollBar().setValue(v.horizontalScrollBar().value() + 12)
    ref = v.view_state()
    assert all(o.view_state()[1] == pytest.approx(ref[1], abs=0.03) for o in cells)
    rv.set_active(0)
    rv.btn_fit.click()
    assert all(o.view_state()[3] and not o.zoomed_in() for o in cells)
    rv.sw_link.setChecked(False)
    cells[1].zoom_to(cells[1].zoom * 2)
    assert cells[1].zoomed_in() and not any(cells[i].zoomed_in() for i in (0, 2, 3))
    rv.sw_link.setChecked(True)
    rv.btn_fit.click()

    # 확대창: "반대쪽" is the next cell on screen (the last one wraps to the first)
    lens = rv.lens
    assert lens.views == cells
    rv.set_lens(True, cells[0].mapTo(rv.stage_w, cells[0].rect().center()))
    assert lens.host() == 0 and lens.source()[0] is cells[0]
    lens.toggle_other()
    assert lens.other and lens.source()[0] is cells[1] and lens.caption().endswith("· 반대쪽")
    lens.move_to(cells[3].mapTo(rv.stage_w, cells[3].rect().center()))
    assert lens.host() == 3 and lens.source()[0] is cells[0]
    lens.toggle_other()
    assert not lens.other and lens.source()[0] is cells[3]
    # one cell: there is no other photo — the toggle does nothing
    rv.layout_buttons[1].click()
    lens.move_to(rv.views[0].mapTo(rv.stage_w, rv.views[0].rect().center()))
    lens.toggle_other()
    assert not lens.other and lens.source()[0] is rv.views[0] and "반대쪽" not in lens.caption()
    assert lens.views == rv.views and len(lens.views) == 1


def test_many_cells_hold_reduced_photos(tmp_path):
    """Layouts of four and more read the photos reduced, in the background; one or two cells whole."""
    import numpy as np
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from fundusview import imaging
    from fundusview.ui.review_view import SIDES, ReviewPage

    app = QApplication.instance() or QApplication([])
    big = synth_fundus(eye="OD", size=(2000, 1500))
    jpg, png = tmp_path / "big.jpg", tmp_path / "big.png"
    Image.fromarray(big).save(jpg, quality=90)
    Image.fromarray(big[:600, :800]).save(png)
    small = imaging.load_reduced(jpg, 448)
    assert small.shape == (336, 448, 3) and small.dtype == np.uint8                 # the same shape, 448 at most
    assert abs(float(small.mean()) - float(big.mean())) < 3
    assert imaging.load_reduced(png, 448).shape == (336, 448, 3)                    # not a JPEG: read whole, then reduced
    assert imaging.load_reduced(png, 4000).shape == (600, 800, 3)                   # never enlarged
    assert SIDES[1] == 0 and SIDES[2] == 0 and 0 < SIDES[32] < SIDES[16] < SIDES[8] < SIDES[4]

    thumb = tmp_path / "t.png"
    Image.fromarray(big).resize((80, 60)).save(thumb)
    rows = [{"id": i, "exam_date": f"2026-01-{i:02d}", "exam_time": "10:00:00", "laterality": "OD" if i % 2 else "OS",
             "modality": "color", "thumb_path": str(thumb)} for i in range(1, 41)]
    loads = []
    rv = ReviewPage(lambda row: loads.append(row["id"]) or big, lambda row: str(jpg))
    try:
        rv.resize(1200, 800)
        rv.show()
        rv.set_photos(rows)
        assert rv.layout_n == 2 and rv.views[0]._rgb.shape == big.shape and len(loads) == 2      # two cells: whole photos
        rv.set_layout(32)
        # at once: every cell has its photo's thumbnail; nothing was read whole for it
        assert all(v.has_image() for v in rv.views) and rv.loading() and len(loads) == 2
        assert rv.views[5]._rgb.shape == (60, 80, 3) and len(rv.slot_ids()) == 32 and None not in rv.slot_ids()
        _settle(app, rv)
        assert all(v._rgb.shape == (336, 448, 3) for v in rv.views) and len(loads) == 2
        assert all(v.view_state()[3] for v in rv.views)
        # more than 32: the arrows page; photos seen before come from the cache at once
        # (the pair on screen was the newest exam's OD | OS: the page starts at its first photo, the 2nd of the pool)
        assert rv.start == 1 and rv.lbl_pos.text() == "2–33 / 40" and rv.btn_next.isEnabled()
        rv.page(1)
        _settle(app, rv)
        assert rv.start == 33 and rv.lbl_pos.text() == "34–40 / 40" and sum(v.has_image() for v in rv.views) == 7
        rv.page(-1)
        assert not rv.loading() and rv.views[0]._rgb.shape == (336, 448, 3)
        # four cells: a moderate size; a double click gives the cell's photo whole
        rv.set_layout(4)
        _settle(app, rv)
        assert max(rv.views[0]._rgb.shape[:2]) == SIDES[4]
        rv.open_single(1)
        assert rv.layout_n == 1 and rv.views[0]._rgb.shape == big.shape and len(loads) == 3
        # the channel view reaches the reduced photos as well
        rv.close_single()
        _settle(app, rv)
        rv.set_view_mode("retina")
        _settle(app, rv)
        assert all(np.array_equal(v._rgb[..., 0], v._rgb[..., 1]) for v in rv.views)
        # a selection beyond 32 pages to where the last pick is
        rv.set_view_mode("color")
        for r in rows[:34]:
            rv.toggle_select(r["id"])
        assert rv.layout_n == 32 and rv.start == 32 and rv.lbl_pos.text() == "33–34 / 34"
    finally:
        rv.shutdown()
        rv.close()


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
