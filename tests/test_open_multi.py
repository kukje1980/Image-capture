"""A patient opens with its newest OD and OS photo side by side on 다중 보기 (OD left, OS right),
and the multi view follows the clicks on the photo strip: a click adds a photo, a click on a
picked one takes it away, the layout fits the number picked (1 · 2 · 4 · 6 · 9 · 16), a double
click shows that photo large on 모두 보기."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_review import _library  # noqa: E402  (one patient seen three times, one once, one never)


@pytest.fixture
def win(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="")
    w = MainWindow(s, db)
    w.show()
    app.processEvents()
    yield app, w, db, refs, ids
    w.close()
    db.close()


def _open(app, w, ref):
    """Double click the patient on the patient list."""
    page = w.patient_page
    row = page.refs().index(ref)
    page.table.selectRow(row)
    page.table.doubleClicked.emit(page.table.model().index(row, 0))
    app.processEvents()


def _item(w, image_id):
    from PySide6.QtCore import Qt

    return next(w.thumbs.item(i) for i in range(w.thumbs.count())
                if w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) == image_id)


def _click(app, w, image_id, double=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    pos = w.thumbs.visualItemRect(_item(w, image_id)).center()
    if double:
        QTest.mouseDClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    else:
        QTest.mouseClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    app.processEvents()


def _cells(w):
    """The photos on the multi view's cells, in order (empty cells left out), and the selected one."""
    cells = [c for c in w.multi.cells if c.isVisible() and c.image_id is not None]
    sel = [c.image_id for c in cells if c.selected]
    return [c.image_id for c in cells], (sel[0] if sel else None)


def test_a_patient_opens_with_its_newest_od_and_os(win):
    from fundusview.ui.thumbs import PICK_ROLE

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    # the newest exam's OD | OS, side by side — OD on the left (as the patient faces you), selected
    assert w.page() == "work" and w._tab() == "multi" and w.view_buttons["multi"].isChecked()
    assert w.picks() == [ids["od3"], ids["os3"]] and w.multi.count == 2
    assert _cells(w) == ([ids["od3"], ids["os3"]], ids["od3"]) and w.current["id"] == ids["od3"]
    left, right = (c for c in w.multi.cells if c.isVisible())
    assert left.x() < right.x() and abs(left.y() - right.y()) < 3
    assert "OD" in left.label.text() and "OS" in right.label.text() and "고른 사진 2장" in w.multi.mode_label.text()
    assert all(c.view.has_image() for c in (left, right)) and not w.multi.empty.isVisible()
    # the strip lists all of the patient's photos; the two are numbered there
    assert w.thumbs.count() == 8
    assert _item(w, ids["od3"]).data(PICK_ROLE) == 1 and _item(w, ids["os3"]).data(PICK_ROLE) == 2
    assert _item(w, ids["od2"]).data(PICK_ROLE) == 0 and w.btn_multi.text() == "멀티 2"

    # an earlier exam checked on the patient list: that exam's OD | OS
    w.show_page("patients")
    w.patient_page.set_exam("2025-12-01")
    w.patient_page.btn_open.click()
    app.processEvents()
    assert w._tab() == "multi" and w.picks() == [ids["od2"], ids["os2"]] and w.current["id"] == ids["od2"]
    # an exam with one eye only: that eye alone, one photo on the whole view
    w.show_page("patients")
    w.patient_page.set_exam("2025-08-20")
    w.patient_page.btn_open.click()
    app.processEvents()
    assert w.picks() == [ids["od1"]] and w.multi.count == 1 and _cells(w)[0] == [ids["od1"]]
    # 3D: the checked exam's photo in 3D; the multi view is ready with the same two
    w.show_page("patients")
    w.patient_page.set_exam("2026-03-02")
    w.patient_page.btn_3d.click()
    app.processEvents()
    assert w._tab() == "3d" and w.current["id"] == ids["od3"] and w.picks() == [ids["od3"], ids["os3"]]

    # a patient seen for one eye: that photo; 미분류: its photos on 모두 보기 to be assigned
    _open(app, w, refs["park"])
    assert w._tab() == "multi" and w.picks() == [ids["p_od"]] and w.multi.count == 1
    from fundusview.ui.main_window import UNASSIGNED
    _open(app, w, UNASSIGNED)
    assert w._tab() == "all" and w.picks() == [] and w.current["id"] == ids["un"]

    # the eye filter of the strip is kept: OD only
    w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
    _open(app, w, refs["kim"])
    assert w.picks() == [ids["od3"]]
    w.f_eye.setCurrentIndex(0)

    # the workspace's patient pane: a click on a patient shows its newest OD | OS as well
    w._go("all")
    w.acts["list"].trigger()
    row = next(r for r in range(w.patients.rowCount()) if w._row_ref(r) == refs["park"])
    w.patients.selectRow(row)
    app.processEvents()
    assert w._patient_ref == refs["park"] and w._tab() == "multi" and w.picks() == [ids["p_od"]]


def test_the_multi_view_follows_the_clicks(win):
    from fundusview.ui.thumbs import PICK_ROLE

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2, od1 = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2", "od1"))

    # a click adds the photo, as the selected cell; the layout grows with the photos: 2 → 4 → 4 → 6
    _click(app, w, od2)
    assert w.picks() == [od3, os3, od2] and w.multi.count == 4
    assert _cells(w) == ([od3, os3, od2], od2) and w.current["id"] == od2
    assert _item(w, od2).data(PICK_ROLE) == 3 and "고른 사진 3장" in w.multi.mode_label.text()
    _click(app, w, os2)
    assert w.multi.count == 4 and _cells(w) == ([od3, os3, od2, os2], os2)
    _click(app, w, od1)
    assert w.multi.count == 6 and _cells(w) == ([od3, os3, od2, os2, od1], od1)
    # its processing is that photo's own: the cells of the others stay as they were
    before = {c.image_id: c.view._rgb.copy() for c in w.multi.cells if c.isVisible() and c.image_id}
    w._on_action("chan:redfree")
    after = {c.image_id: c.view._rgb for c in w.multi.cells if c.isVisible() and c.image_id}
    assert not (after[od1] == before[od1]).all()
    assert all((after[k] == before[k]).all() for k in before if k != od1)

    # a click on a picked photo takes it away; the layout shrinks; the selected cell stays
    _click(app, w, os3)
    assert w.picks() == [od3, od2, os2, od1] and w.multi.count == 4 and _cells(w) == ([od3, od2, os2, od1], od1)
    assert _item(w, os3).data(PICK_ROLE) == 0 and _item(w, od2).data(PICK_ROLE) == 2
    # … the selected one: the photo that comes into its place is selected (and keeps its own processing)
    _click(app, w, od1)
    assert w.picks() == [od3, od2, os2] and _cells(w) == ([od3, od2, os2], os2) and w._channel == "rgb"
    _click(app, w, od1)                                    # back: red-free as it was left
    assert _cells(w) == ([od3, od2, os2, od1], od1) and w._channel == "redfree"
    w._on_action("chan:redfree", False)
    _click(app, w, od1)
    _click(app, w, os2)
    assert w.picks() == [od3, od2] and w.multi.count == 2

    # a double click: that photo large on 모두 보기 — the picks stay as they were
    _click(app, w, od2, double=True)
    assert w._tab() == "all" and w.current["id"] == od2 and w.picks() == [od3, od2]
    _click(app, w, rf3, double=True)                       # (one not picked, too)
    assert w._tab() == "all" and w.current["id"] == rf3 and w.picks() == [od3, od2]
    # on 모두 보기 a click on a picked photo brings the multi view back with that photo selected …
    _click(app, w, od3)
    assert w._tab() == "multi" and w.picks() == [od3, od2] and _cells(w) == ([od3, od2], od3)
    # … and one not picked joins it (also from 3D)
    w._go("3d")
    _click(app, w, rf3)
    assert w._tab() == "multi" and w.picks() == [od3, od2, rf3] and _cells(w) == ([od3, od2, rf3], rf3)

    # all clicked away: the view says how to pick; the next click is the one photo on the view
    for k in (od3, od2, rf3):
        _click(app, w, k)
    assert w.picks() == [] and w.multi.count == 1 and w.multi.empty.isVisible()
    assert "클릭하면 여기에 모입니다" in w.multi.empty.text() and not any(c.isVisible() for c in w.multi.cells)
    _click(app, w, os2)
    assert w.picks() == [os2] and w.multi.count == 1 and _cells(w) == ([os2], os2) and not w.multi.empty.isVisible()
    _click(app, w, os3)
    assert w.multi.count == 2 and _cells(w) == ([os2, os3], os3)
    # 선택 해제: the same
    w.btn_clear_picks.click()
    app.processEvents()
    assert w.picks() == [] and w.multi.empty.isVisible() and w.btn_multi.text() == "멀티"
    # 다중 ▾ 4장 with nothing picked: VK-2's consecutive photos from the shown one
    w._on_action("multi:4")
    app.processEvents()
    assert w.multi.count == 4 and not w.multi.empty.isVisible() and len(_cells(w)[0]) == 4


def test_a_new_photo_takes_its_eyes_place(win):
    """새 영상 자동 표시 on 다중 보기: the newest OD | OS again, the new photo selected — unless the
    picks were changed by hand, then the new photo is shown large."""
    from fundusview.importer import ImportResult
    from fundusview.models import ExtractedMeta

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    assert w.picks() == [ids["od3"], ids["os3"]]
    folder = os.path.dirname(db.get_image(ids["od3"])["file_path"])
    assert db.upsert_patient(ExtractedMeta(patient_id="K001")) == refs["kim"]
    new = db.insert_image(patient_ref=refs["kim"], exam_date="2026-04-01", exam_time="09:00:00", laterality="OS",
                          modality="color", file_path=os.path.join(folder, "p2.png"), sha256="new")
    w._results.append(ImportResult("imported", "new.png", "김영수", image_id=new, patient_ref=refs["kim"]))
    w._flush_results()
    app.processEvents()
    assert w._tab() == "multi" and w.picks() == [ids["od3"], new] and _cells(w) == ([ids["od3"], new], new)
    # picks changed by hand: they stay; the new photo is shown large
    _click(app, w, ids["od2"])
    new2 = db.insert_image(patient_ref=refs["kim"], exam_date="2026-04-01", exam_time="09:05:00", laterality="OD",
                           modality="color", file_path=os.path.join(folder, "p3.png"), sha256="new2")
    w._results.append(ImportResult("imported", "new2.png", "김영수", image_id=new2, patient_ref=refs["kim"]))
    w._flush_results()
    app.processEvents()
    assert w._tab() == "all" and w.current["id"] == new2 and w.picks() == [ids["od3"], new, ids["od2"]]
