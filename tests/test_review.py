"""환자 목록 (start screen) and the 검토 tab: which photos a review shows (review.py), the patient
list's rows · filters · exams, the selection shared with the workspace, the stages, earlier exams,
the timeline, linked views, view modes, the 확대창 and the hand-offs to 2D / 3D / 녹내장."""
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
    w.show()
    app.processEvents()
    yield app, w, db, refs, ids
    w.close()
    db.close()


def _texts(table, col):
    return [table.item(r, col).text() for r in range(table.rowCount())]


def test_start_screen_is_the_patient_list(win):
    from fundusview.ui.main_window import UNASSIGNED

    app, w, db, refs, ids = win
    page = w.patient_page
    # the window opens on the patient list; the VK-2 toolbars belong to the workspace
    assert w.page() == "patients" and w.stack.currentWidget() is page and page.isVisible()
    assert not w.split.isVisible() and w.tb_cmd.isHidden() and w.tb_proc.isHidden()
    assert not w.acts["prev"].isEnabled() and w.acts["search"].isEnabled() and w.acts["import"].isEnabled()
    # rows: 미분류 first, then the patients; ID · 이름 · 성별 · 나이 · 최근 검사 · 검사 수 · 영상
    hdr = [page.table.horizontalHeaderItem(c).text() for c in range(6)]
    assert hdr == ["환자 ID", "이름", "성별 · 나이", "최근 검사", "검사 수", "영상"]
    assert page.refs()[0] == UNASSIGNED and set(page.refs()[1:]) == set(refs.values())
    by_id = {page.table.item(r, 0).text(): [page.table.item(r, c).text() for c in range(6)]
             for r in range(page.table.rowCount())}
    age = date.today().year - 1958 - ((date.today().month, date.today().day) < (3, 12))
    assert by_id["K001"] == ["K001", "김영수", f"남 · {age}세", "2026-03-02", "3", "8"]
    assert by_id["P002"][3:] == ["2026-03-09", "1", "1"]
    assert by_id["J003"] == ["J003", "정하늘", "", "없음", "0", "0"]
    assert by_id["★ 미분류"][3:] == ["2026-02-01", "1", "1"]
    assert page.lbl_count.text() == "3명"
    # nothing is selected yet: no card, no way into a review
    assert page.current() is None and not page.btn_open.isEnabled() and not page.lbl_name.isVisible()
    assert page.lbl_detail_empty.isVisible() and "환자를 선택" in page.lbl_detail_empty.text()

    # search (ID · name · birth date) hides 미분류; no match → the empty state says so
    page.search.setText("영수")
    page.refresh()
    assert _texts(page.table, 0) == ["K001"] and page.lbl_count.text() == "1명 / 전체 3명"
    page.search.setText("1949")
    page.refresh()
    assert _texts(page.table, 0) == ["P002"]
    page.search.setText("없는사람")
    page.refresh()
    assert page.list_stack.currentWidget() is page.lbl_empty and page.lbl_empty.text() == "조건에 맞는 환자가 없습니다"
    page.search.setText("")
    page.refresh()
    assert page.list_stack.currentWidget() is page.table and page.table.rowCount() == 4

    # period, by the day of the last exam
    page.today = lambda: date(2026, 3, 9)
    page.period_buttons["today"].click()
    assert _texts(page.table, 0) == ["P002"]
    page.period_buttons["week"].click()
    assert set(_texts(page.table, 0)) == {"P002", "K001"}                 # 03-02 is the 7th day back
    page.today = lambda: date(2026, 3, 10)
    page.set_period("week")
    assert _texts(page.table, 0) == ["P002"]
    page.period_buttons["all"].click()
    assert page.table.rowCount() == 4

    # Ctrl+F goes to this screen's search box, Ctrl+0 is the way back from the workspace
    w._on_action("search")
    assert w.page() == "patients" and page.search.hasFocus()
    assert w.act_patients.shortcut().toString() == "Ctrl+0"


def test_patient_list_and_workspace_share_the_patient(win):
    from PySide6.QtCore import Qt

    from fundusview.ui.main_window import UNASSIGNED

    app, w, db, refs, ids = win
    page = w.patient_page

    def row_of(table, ref):
        return next(r for r in range(table.rowCount()) if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == ref)

    def selected(table):
        rows = table.selectionModel().selectedRows()
        return table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    # a click here selects the patient everywhere and stays on this screen
    page.table.selectRow(row_of(page.table, refs["kim"]))
    app.processEvents()
    assert w._patient_ref == refs["kim"] and selected(w.patients) == refs["kim"] and w.page() == "patients"
    assert "김영수" in w.banner.text() and w.thumbs.count() == 8
    # the card: name, ID, birth date (age), sex, and 정보 수정
    assert page.lbl_name.text() == "김영수" and page.lbl_id.text() == "K001" and page.avatar.text() == "김"
    assert page._kv_labels["생년월일"][1].text().startswith("1958-03-12 (") and page._kv_labels["성별"][1].text() == "남"
    assert page.btn_edit.isVisible() and page.btn_open.isEnabled()
    # the exams: newest first, one checked (the newest), what was taken, 최근 on the newest, thumbnails
    rows = page.exam_rows()
    assert [r.date for r in rows] == ["2026-03-02", "2025-12-01", "2025-08-20"]
    assert [r.check.isChecked() for r in rows] == [True, False, False] and page.current_exam() == "2026-03-02"
    from PySide6.QtWidgets import QLabel
    texts = [[lab.text() for lab in r.findChildren(QLabel) if lab.text()] for r in rows]
    assert texts[0] == ["2026-03-02", "컬러 3장 · Red-free 1장", "최근"]
    assert texts[2] == ["2025-08-20", "컬러 1장 · 디스크 2장 1장"]
    assert all(not lab.pixmap().isNull() for lab in rows[0].findChildren(QLabel, "examThumb"))
    assert page.lbl_exams.text() == "검사 목록 · 3회 · 사진 8장"
    # the check boxes are exclusive
    rows[1].check.click()
    assert [r.check.isChecked() for r in rows] == [False, True, False] and page.current_exam() == "2025-12-01"

    # the workspace's table selects here too
    w.show_page("work")
    w.patients.selectRow(row_of(w.patients, refs["park"]))
    app.processEvents()
    assert w._patient_ref == refs["park"] and page.current() == refs["park"]
    w.btn_patients.click()
    assert w.page() == "patients" and selected(page.table) == refs["park"] and page.lbl_name.text() == "박정희"
    assert [r.date for r in page.exam_rows()] == ["2026-03-09"]

    # a patient without photos: says so, nothing to open
    page.table.selectRow(row_of(page.table, refs["jung"]))
    assert page.lbl_detail_empty.isVisible() and "아직 가져온 사진이 없습니다" in page.lbl_detail_empty.text()
    assert not page.btn_open.isEnabled() and not page.btn_2d.isEnabled()
    page.table.doubleClicked.emit(page.table.model().index(row_of(page.table, refs["jung"]), 0))
    assert w.page() == "patients"
    # 미분류: its photos open in the workspace (모두 보기) to be assigned
    page.table.selectRow(row_of(page.table, UNASSIGNED))
    assert page.lbl_name.text() == "미분류" and not page.btn_edit.isVisible() and page.btn_open.text() == "사진 보기"
    page.btn_open.click()
    assert w.page() == "work" and w._tab() == "all" and w._patient_ref == UNASSIGNED and w.thumbs.count() == 1

    # the workspace's search hides the patient asked for from the list: it is cleared, not ignored
    w.search.setText("박")
    w.refresh_patients()
    w.show_page("patients")
    page.table.selectRow(row_of(page.table, refs["kim"]))
    assert w._patient_ref == refs["kim"] and selected(w.patients) == refs["kim"] and w.search.text() == ""

    # a new photo of the selected patient shows up in its exams; the checked exam stays
    page.set_exam("2025-12-01")
    from fundusview.models import ExtractedMeta
    assert db.upsert_patient(ExtractedMeta(patient_id="K001")) == refs["kim"]
    db.insert_image(patient_ref=refs["kim"], exam_date="2026-04-01", exam_time="09:00:00", laterality="OD",
                    modality="color", file_path="missing.png", sha256="new")
    w.refresh_patients(keep=True)
    assert [r.date for r in page.exam_rows()][0] == "2026-04-01" and page.current_exam() == "2025-12-01"
    assert page.table.item(row_of(page.table, refs["kim"]), 4).text() == "4"


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
        page = w.patient_page
        assert w.page() == "patients" and page.list_stack.currentWidget() is page.lbl_empty
        text = page.lbl_empty.text()
        assert "아직 환자가 없습니다" in text and "감시 폴더" in text and "끌어다 놓아도" in text
        assert page.btn_import.isEnabled() and not page.btn_open.isEnabled()
        called = []
        w._import_files = lambda: called.append(1)
        page.importRequested.disconnect()
        page.importRequested.connect(w._import_files)
        page.btn_import.click()
        assert called == [1]
        # dropping files on the window imports them from this screen as well
        assert w.acceptDrops()
    finally:
        w.close()
        db.close()


def _open_review(app, w, refs, who="kim"):
    page = w.patient_page
    row = next(r for r in range(page.table.rowCount()) if page.refs()[r] == refs[who])
    page.table.selectRow(row)
    page.table.doubleClicked.emit(page.table.model().index(row, 0))
    app.processEvents()
    return w.review


def test_double_click_opens_the_review_of_both_eyes(win):
    from PySide6.QtCore import QPoint

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    # the workspace on the 검토 tab (the first tab), toolbars back, the photo strip away: the timeline lists the photos
    assert w.page() == "work" and w._tab() == "review" and w.tabs.tabText(w.tabs.currentIndex()) == "검토"
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
    assert not rv.timeline.scroll.isVisible() and rv.views[0].height() > h and rv.timeline.btn_fold.text() == "▸ 타임라인"
    rv.timeline.btn_fold.click()
    app.processEvents()
    assert rv.timeline.scroll.isVisible()

    # the other tabs get the photo strip back; coming back keeps the review as it was
    rv.set_stage("od")
    w._go("all")
    assert w.strip_w.isVisible() and w.f_date.isVisible() and w.view2d.has_image()
    w._go("review")
    assert not w.strip_w.isVisible() and rv.stage == "od"
    # the way back to the patient list, and the patient's review again
    w.act_patients.trigger()
    assert w.page() == "patients" and w.tb_cmd.isHidden()
    w.patient_page.btn_open.click()
    assert w.page() == "work" and w._tab() == "review"
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
    # ◀ 이전 · 다음 ▶ go round the possible stages; a new stage starts at the latest earlier exam
    rv.btn_next.click()
    assert rv.stage == "os" and rv.slot_ids() == [ids["os2"], ids["os3"]] and rv.lbl_prior.text() == "이전 검사 1/1"
    rv.btn_next.click()
    assert rv.stage == "ou" and not rv.prior_nav.isVisible()
    rv.btn_prev.click()
    assert rv.stage == "os"

    # another exam checked in the patient list: it is the current one, older exams are its priors
    w.show_page("patients")
    w.patient_page.exam_rows()[1].check.click()        # 2025-12-01
    w.patient_page.btn_open.click()
    assert rv.current == "2025-12-01" and rv.timeline.dates[1].property("current")
    assert [b.text() for b in rv.timeline.dates] == ["2026-03-02 · 최근", "2025-12-01 · 현재", "2025-08-20"]
    # OS has no earlier exam than this one: its compare stage is switched off and says why
    assert rv.stage == "ou" and rv.slot_ids() == [ids["od2"], ids["os2"]]
    model = rv.c_stage.model()
    assert [model.item(i).isEnabled() for i in range(3)] == [True, True, False]
    assert rv.c_stage.itemText(2) == "OS 비교* (이전 | 현재) — 이전 검사 없음" and "이전 검사 없음" not in rv.c_stage.itemText(1)
    rv.set_stage("os")
    assert rv.stage == "ou"
    rv.btn_next.click()
    assert rv.stage == "od" and rv.slot_ids() == [ids["od1"], ids["od2"]] and rv.lbl_prior.text() == "이전 검사 1/1"
    rv.btn_next.click()
    assert rv.stage == "ou"                             # OS 비교 is skipped

    # the oldest exam: OS was not taken then — nothing earlier to fall back on; no compare stage at all
    w.patient_page.set_exam("2025-08-20")
    assert rv.current == "2025-08-20" and rv.slot_ids() == [ids["od1"], None]
    assert not rv.views[1].has_image() and rv.views[1].empty_text == "OS 좌안 사진이 없습니다"
    assert not rv.btn_next.isEnabled() and not rv.btn_prev.isEnabled()
    rv.set_active(1)
    assert not rv.btn_2d.isEnabled() and not rv.btn_glaucoma.isEnabled()
    rv.set_active(0)
    assert rv.btn_2d.isEnabled()

    # a date of the timeline makes that exam the current one — in the patient list as well
    rv.timeline.dates[0].click()
    assert rv.current == "2026-03-02" and w.patient_page.current_exam() == "2026-03-02"
    assert w.patient_page.exam_rows()[0].check.isChecked()

    # an eye missing from the current exam falls back to its newest earlier photo, tagged 이전
    db.delete_image(ids["os3"])
    w._fill_thumbs()
    assert rv.slot_ids() == [ids["od3"], ids["os2"]] and [v.tag for v in rv.views] == ["", "이전"]

    # another patient: one exam only, the stage falls back to 양안
    rv.set_stage("od")
    w._select_patient_ref(refs["park"])
    assert rv.stage == "ou" and rv.slot_ids()[0] == ids["p_od"] and rv.slot_ids()[1] is None
    assert [model.item(i).isEnabled() for i in range(3)] == [True, False, False]


def test_timeline_puts_photos_on_the_views(win):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from fundusview.ui.review_view import MIME

    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    thumb = {t.image_id: t for t in rv.timeline.thumbs}
    # 양안: a clicked photo goes to the view of its eye, whichever view is active
    rv.set_active(1)
    thumb[ids["od2"]].click()
    assert rv.slot_ids() == [ids["od2"], ids["os3"]] and rv.active == 0 and rv.views[0].tag == "이전"
    thumb[ids["os2"]].click()
    assert rv.slot_ids() == [ids["od2"], ids["os2"]] and rv.active == 1
    assert {t.image_id for t in rv.timeline.thumbs if t.shown} == {ids["od2"], ids["os2"]}
    # a photo of an unknown eye goes to the active view
    rv.set_active(0)
    thumb[ids["na3"]].click()
    assert rv.slot_ids() == [ids["na3"], ids["os2"]] and rv.views[0].tag == ""
    # compare stages: the clicked photo goes to the active view, whatever its eye
    rv.set_stage("od")
    rv.set_active(1)
    thumb[ids["os2"]].click()
    assert rv.slot_ids() == [ids["od2"], ids["os2"]]
    rv.set_active(0)
    thumb[ids["rf3"]].click()
    assert rv.slot_ids()[0] == ids["rf3"] and rv.views[0].tag == "현재"
    # drag & drop: on the view the photo is dropped on (files are left to the window's import)
    mime = QMimeData()
    mime.setData(MIME, str(ids["od1"]).encode())
    view = rv.views[1]
    pos = QPointF(30, 30)
    enter = QDragEnterEvent(QPoint(30, 30), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    view.dragEnterEvent(enter)
    assert enter.isAccepted() and view._drop
    drop = QDropEvent(pos, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    view.dropEvent(drop)
    assert rv.slot_ids()[1] == ids["od1"] and rv.active == 1 and not view._drop
    files = QMimeData()
    files.setUrls([])
    enter = QDragEnterEvent(QPoint(30, 30), Qt.DropAction.CopyAction, files, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    view.dragEnterEvent(enter)
    assert not enter.isAccepted() and not view._drop
    # choosing the stage again puts the default photos back
    rv.set_stage("ou")
    assert rv.slot_ids() == [ids["od3"], ids["os3"]]


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
    # a double click on a view fits as well
    b.zoom_to(b.zoom * 3)
    assert a.zoomed_in()
    QTest.mouseDClick(a.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
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
    w.patient_page.set_exam("2025-08-20")                # OS not taken then
    rv.set_lens(True, QPoint(b.x() + 150, 150))
    assert lens.source() is None and lens.caption() == "사진 위로 옮기세요"


def test_hand_off_to_2d_3d_and_glaucoma(win):
    app, w, db, refs, ids = win
    rv = _open_review(app, w, refs)
    # 2D 보기: the active view's photo becomes the photo on screen, in the 2D tab
    rv.set_active(1)
    rv.btn_2d.click()
    assert w._tab() == "2d" and w.current["id"] == ids["os3"] and w.view2d.has_image()
    assert w.thumbs.currentItem().data(0x0100) == ids["os3"] and w.strip_w.isVisible()
    # the 2D view's adjustments work as ever and do not reach the review
    w._on_action("chan:redfree")
    assert w._channel == "redfree"
    w._go("review")
    assert rv.view_mode == "color" and rv.slot_ids() == [ids["od3"], ids["os3"]]
    w._on_action("chan:redfree", False)
    # 3D 안구
    rv.set_active(0)
    rv.btn_3d.click()
    assert w._tab() == "3d" and w.current["id"] == ids["od3"]
    # 녹내장: the existing window, through the existing entry point; in a compare stage with both photos
    opened = []
    w.open_glaucoma = lambda second=None: opened.append((w.current["id"], second))
    w._go("review")
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
    # the patient list's shortcuts: the checked exam's photo in 2D / 3D
    w.show_page("patients")
    w.patient_page.set_exam("2025-12-01")
    w.patient_page.btn_2d.click()
    assert w.page() == "work" and w._tab() == "2d" and w.current["id"] == ids["od2"]
    w.show_page("patients")
    w.patient_page.btn_3d.click()
    assert w._tab() == "3d" and w.current["id"] == ids["od2"]


def test_new_photo_still_opens_its_patient(win):
    """새 영상 자동 표시: a photo arriving while the patient list is on screen shows in the workspace."""
    from fundusview.importer import ImportResult

    app, w, db, refs, ids = win
    assert w.page() == "patients" and w.act_follow.isChecked()
    res = ImportResult("imported", "new.png", "박정희", image_id=ids["p_od"], patient_ref=refs["park"])
    w._results.append(res)
    w._flush_results()
    assert w.page() == "work" and w._patient_ref == refs["park"] and w.current["id"] == ids["p_od"]
    assert w._tab() == "all" and w.view2d.has_image()
    # on the 검토 tab: a photo that is one of the two under review stays there …
    w._go("review")
    w._results.append(res)
    w._flush_results()
    assert w._tab() == "review" and w.review.slot_ids()[0] == ids["p_od"]
    # … one that is not (unknown eye) is shown in the big view
    w._results.append(ImportResult("imported", "x.png", "김영수", image_id=ids["na3"], patient_ref=refs["kim"]))
    w._flush_results()
    assert w._tab() == "all" and w.current["id"] == ids["na3"]
    # a bulk import at startup (--demo) is held back: the patient list stays
    w.show_page("patients")
    w.hold_follow()
    w._results.append(res)
    w._flush_results()
    assert w.page() == "patients"
    w._on_status("대기 중")
    w._results.append(res)
    w._flush_results()
    assert w.page() == "work"


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
