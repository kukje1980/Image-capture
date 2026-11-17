"""설정 → 일반 → 환자를 열면 Simple: a patient opens on its newest OD and OS photo side by side (OD
left, OS right), numbered 1 and 2 — and [Simple] puts them back whatever was picked. From there Simple
follows the clicks on the photo list: a click adds a photo, a click on a picked one takes it away, the
layout fits the number picked (1 · 2 · 4 · 6 · 9 · 16; none picked: all the photos). 16장 보기 (the
first setting, test_photo_grid): a click picks a photo there, [Multi] shows the picked ones only and
[Multi] again goes back to the 16. A double click shows a photo large (Detail), where a click on the
list shows that photo."""
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
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="",
                 open_view="odos", ui_version=MainWindow.UI_VERSION)      # (환자를 열면: Simple)
    w = MainWindow(s, db)
    w.patient_list.select_delay = 0          # a selection goes through at once (no key stepping here)
    w.show()
    app.processEvents()
    yield app, w, db, refs, ids
    w.close()
    db.close()


def _open(app, w, ref):
    """Double click the patient on the patient list (window)."""
    pl = w.patient_list
    if pl.isHidden():
        w.show_patient_list()
    row = pl.row_of(ref)
    pl.table.selectRow(row)
    pl.table.doubleClicked.emit(pl.table.model().index(row, 0))
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


def _press(w, key):
    """A button of the command toolbar (Simple · Multi · Detail · 3D …)."""
    w.tb_cmd.widgetForAction(w.acts[key]).click()


def _lit(w):
    return [k for k in ("view:simple", "view:multi", "view:all", "view3d") if w.acts[k].isChecked()]


def _cells(w):
    """The photos on the multi view's cells, in order (empty cells left out), and the selected one."""
    cells = [c for c in w.multi.cells if c.isVisible() and c.image_id is not None]
    sel = [c.image_id for c in cells if c.selected]
    return [c.image_id for c in cells], (sel[0] if sel else None)


def test_a_patient_opens_on_simple_with_its_newest_od_and_os(win):
    from fundusview.ui.thumbs import PICK_ROLE

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    # the newest exam's OD | OS, side by side — OD on the left (as the patient faces you), selected
    assert w.patient_list.isHidden() and w._tab() == "multi" and _lit(w) == ["view:simple"]
    assert w.picks() == [ids["od3"], ids["os3"]] and w.multi.count == 2
    assert _cells(w) == ([ids["od3"], ids["os3"]], ids["od3"]) and w.current["id"] == ids["od3"]
    left, right = (c for c in w.multi.cells if c.isVisible())
    assert left.x() < right.x() and abs(left.y() - right.y()) < 3
    assert "OD" in left.label.text() and "OS" in right.label.text() and "Simple — 최신 OD | OS" in w.multi.mode_text
    assert all(c.view.has_image() for c in (left, right)) and not w.multi.empty.isVisible()
    # 화면 분할 and the picks are in the menu bar's row on Simple
    assert w.multi_bar.isVisible() and w.lbl_picks.text() == "2장 선택" and w.btn_clear_picks.isVisible()
    # the strip lists the patient's photos of a known eye (미상 is under 눈 → 미상); the two shown are
    # numbered there
    assert w.thumbs.count() == 7
    assert _item(w, ids["od3"]).data(PICK_ROLE) == 1 and _item(w, ids["os3"]).data(PICK_ROLE) == 2
    assert _item(w, ids["od2"]).data(PICK_ROLE) == 0

    # an earlier exam checked on the patient list: that exam's OD | OS
    w.show_patient_list()
    w.patient_list.set_exam("2025-12-01")
    w.patient_list.btn_open.click()
    app.processEvents()
    assert w._tab() == "multi" and w.picks() == [ids["od2"], ids["os2"]] and w.current["id"] == ids["od2"]
    # … and [Simple] shows that exam's OD | OS, too
    _press(w, "view:simple")
    assert w.picks() == [ids["od2"], ids["os2"]]
    # an exam with one eye only: that eye alone, one photo on the whole view
    w.show_patient_list()
    w.patient_list.set_exam("2025-08-20")
    w.patient_list.btn_open.click()
    app.processEvents()
    assert w.picks() == [ids["od1"]] and w.multi.count == 1 and _cells(w)[0] == [ids["od1"]]
    # 3D: the checked exam's photo in 3D; Simple is ready with the same two …
    w.show_patient_list()
    w.patient_list.set_exam("2026-03-02")
    w.patient_list.btn_3d.click()
    app.processEvents()
    assert w._tab() == "3d" and w.current["id"] == ids["od3"] and w.picks() == [ids["od3"], ids["os3"]]
    assert _lit(w) == ["view3d"]
    # … a click on the list shows that photo in 3D (the two of Simple stay) and [3D] again goes back
    _click(app, w, ids["os2"])
    assert w._tab() == "3d" and w.current["id"] == ids["os2"] and w.picks() == [ids["od3"], ids["os3"]]
    _press(w, "view3d")
    assert w._tab() == "multi" and _lit(w) == ["view:simple"]
    assert _cells(w) == ([ids["od3"], ids["os3"]], ids["od3"])
    # from Simple [3D] puts both photos in 3D, side by side (두 장 3D — test_pair3d.py), and back again
    left, right = (c for c in w.multi.cells if c.isVisible())
    QTest_click(right.view.viewport())
    app.processEvents()
    assert w.current["id"] == ids["os3"]
    _press(w, "view3d")
    assert w._tab() == "3d2" and w.current["id"] == ids["os3"] and _lit(w) == ["view3d"]
    assert w.pair3d.image_ids == [ids["od3"], ids["os3"]]
    _press(w, "view3d")
    assert w._tab() == "multi" and _cells(w) == ([ids["od3"], ids["os3"]], ids["os3"])

    # a patient seen for one eye: that photo; 미분류: its photos large (Detail), to be assigned
    _open(app, w, refs["park"])
    assert w._tab() == "multi" and w.picks() == [ids["p_od"]] and w.multi.count == 1
    from fundusview.ui.main_window import UNASSIGNED
    _open(app, w, UNASSIGNED)
    assert w._tab() == "all" and w.picks() == [] and w.current["id"] == ids["un"]
    assert _lit(w) == ["view:all"]
    # … [Simple] there: the photo on screen alone (no OD | OS to go by)
    _press(w, "view:simple")
    assert w._tab() == "multi" and _cells(w) == ([ids["un"]], ids["un"])
    # the eye filter of the strip is kept: OD only
    w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
    _open(app, w, refs["kim"])
    assert w.picks() == [ids["od3"]]
    w.f_eye.setCurrentIndex(0)

    # one click on a patient in the patient list window: the main window shows its newest OD | OS as well
    w._go("all")
    w.show_patient_list()
    w.patient_list.table.selectRow(w.patient_list.row_of(refs["park"]))
    app.processEvents()
    assert w._patient_ref == refs["park"] and w._tab() == "multi" and w.picks() == [ids["p_od"]]


def QTest_click(widget):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))


def test_simple_follows_the_clicks_and_starts_again_from_the_newest_od_and_os(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from fundusview.ui.thumbs import PICK_ROLE

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2, od1 = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2", "od1"))
    assert w.picks() == [od3, os3] and w.multi.count == 2

    # a click adds the photo, numbered and selected; the layout grows with them (2 → 4)
    _click(app, w, od2)
    assert w.picks() == [od3, os3, od2] and w.multi.count == 4 and _cells(w) == ([od3, os3, od2], od2)
    assert _item(w, od2).data(PICK_ROLE) == 3 and "고른 사진 3장" in w.multi.mode_text
    assert w.lbl_picks.text() == "3장 선택" and _lit(w) == ["view:simple"]
    # a click on a picked one takes it away (the selected cell stays)
    _click(app, w, os3)
    assert w.picks() == [od3, od2] and w.multi.count == 2 and _cells(w) == ([od3, od2], od2)
    # each photo keeps its own processing: red-free on od2, not on od3 — and again when it is back
    w._on_action("chan:redfree")
    assert w._channel == "redfree"
    QTest_click(next(c for c in w.multi.cells if c.image_id == od3).view.viewport())
    app.processEvents()
    assert w.current["id"] == od3 and w._channel == "rgb"
    QTest_click(next(c for c in w.multi.cells if c.image_id == od2).view.viewport())
    app.processEvents()
    assert w.current["id"] == od2 and w._channel == "redfree"
    w._on_action("chan:redfree", False)

    # a double click: that photo large (Detail) — the picks stay as they were …
    _click(app, w, rf3, double=True)
    assert w._tab() == "all" and w.current["id"] == rf3 and w.picks() == [od3, od2] and _lit(w) == ["view:all"]
    # … on Detail a click on the list shows that photo there
    _click(app, w, od1)
    assert w._tab() == "all" and w.current["id"] == od1 and w.picks() == [od3, od2]
    # … and [Simple] starts again from the newest OD | OS, whatever was picked
    _press(w, "view:simple")
    assert w._tab() == "multi" and w.picks() == [od3, os3] and _cells(w) == ([od3, os3], od3)
    assert "Simple — 최신 OD | OS" in w.multi.mode_text
    # a double click on a cell: large as well
    cell = next(c for c in w.multi.cells if c.image_id == os3)
    QTest.mouseDClick(cell.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    app.processEvents()
    assert w._tab() == "all" and w.current["id"] == os3

    # a patient with one eye's photos: the one photo, and the clicks add to it
    w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
    _open(app, w, refs["kim"])
    assert w.picks() == [od3] and w.multi.count == 1
    _click(app, w, od2)
    assert w.picks() == [od3, od2] and w.multi.count == 2 and _cells(w) == ([od3, od2], od2)
    w.f_eye.setCurrentIndex(0)


def test_simple_with_nothing_picked_and_multi_is_16_photos(win):
    from fundusview.ui.thumbs import PICK_ROLE

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2, od1 = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2", "od1"))
    strip = w._strip_ids()
    assert len(strip) == 7
    montage = w.tb_cmd.widgetForAction(w.acts["montage"])

    # 선택 해제 on Simple: nothing picked — all the photos of the list, the layout fit to them (7 → 9)
    w.btn_clear_picks.click()
    app.processEvents()
    assert w._tab() == "multi" and w.picks() == [] and _lit(w) == ["view:simple"]
    assert w.multi.count == 9 and _cells(w) == (strip, od3) and w.multi_bar.isVisible()
    assert not w.btn_clear_picks.isVisible() and w.lbl_picks.text() == "" and not montage.isEnabled()
    assert all(w.thumbs.item(i).data(PICK_ROLE) == 0 for i in range(w.thumbs.count()))

    # a click picks the photo: only the picked ones are shown, the clicked one selected; the layout
    # grows with them: 1 → 2 → 4 → 4 → 6
    for k, (iid, count) in enumerate(((od3, 1), (os3, 2), (od2, 4), (os2, 4), (od1, 6))):
        _click(app, w, iid)
        assert w.multi.count == count and _cells(w) == ([od3, os3, od2, os2, od1][:k + 1], iid)
        assert _item(w, iid).data(PICK_ROLE) == k + 1
    assert w.current["id"] == od1 and "고른 사진 5장" in w.multi.mode_text
    assert w.lbl_picks.text() == "5장 선택" and w.btn_clear_picks.isVisible() and montage.isEnabled()
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

    # a double click: that photo large (Detail) — the picks stay as they were
    _click(app, w, od2, double=True)
    assert w._tab() == "all" and w.current["id"] == od2 and w.picks() == [od3, od2]
    _click(app, w, rf3, double=True)                       # (one not picked, too)
    assert w._tab() == "all" and w.current["id"] == rf3 and w.picks() == [od3, od2]

    # [Multi] (from Detail, photos picked): those photos only, Multi lit; [Multi] again: 16장 보기 — every
    # photo, the picked ones still numbered
    _press(w, "view:multi")
    assert w._tab() == "multi" and _lit(w) == ["view:multi"] and _cells(w)[0] == [od3, od2]
    assert w.multi_bar.isVisible() and "16장 보기로" in w.lbl_status.text()
    _press(w, "view:multi")
    assert w._tab() == "grid" and _lit(w) == [] and not w.multi_bar.isVisible()
    assert len(w.grid.items()) == 7 and w.grid._picks == {od3: 1, od2: 2}
    assert w.lbl_grid_picks.isVisible() and w.lbl_grid_picks.text().startswith("2장 선택") and montage.isEnabled()
    assert not hasattr(w, "btn_grid_open")                 # ([고른 사진 보기] was the same as [Multi]: gone)
    # a click on 16장 보기 picks there (numbered), again lets it go; [Multi]: the picked ones only
    w.grid.pressed.emit(os2)
    assert w.picks() == [od3, od2, os2] and w.grid._picks[os2] == 3 and w._tab() == "grid"
    w.grid.pressed.emit(od3)
    assert w.picks() == [od2, os2] and w.lbl_grid_picks.text().startswith("2장 선택")
    _press(w, "view:multi")
    assert w._tab() == "multi" and _lit(w) == ["view:multi"] and _cells(w)[0] == [od2, os2]
    _press(w, "view:multi")
    assert w._tab() == "grid" and w.picks() == [od2, os2]
    # 선택 해제 lets them all go; with nothing picked [Multi] says to pick first and 16장 보기 stays
    w.btn_grid_clear.click()
    assert w.picks() == [] and w.grid._picks == {} and not w.lbl_grid_picks.isVisible() and w._tab() == "grid"
    _press(w, "view:multi")
    assert w._tab() == "grid" and _lit(w) == [] and w.lbl_status.text() == w.PICK_FIRST_HINT
    # Simple's newest OD | OS are not picks of one's own: [Multi] on Simple is 16장 보기, nothing picked
    _press(w, "view:simple")
    assert w.picks() == [od3, os3] and _lit(w) == ["view:simple"]
    _press(w, "view:multi")
    assert w._tab() == "grid" and w.picks() == [] and w.grid._picks == {}
    _press(w, "view:simple")
    _click(app, w, od2)                                    # (changed by hand: they are picks, numbered on 16장)
    _press(w, "view:multi")
    assert w._tab() == "grid" and w.grid._picks == {od3: 1, os3: 2, od2: 3}
    _press(w, "view:multi")                                # … and [Multi] shows them
    assert w._tab() == "multi" and _lit(w) == ["view:multi"] and _cells(w)[0] == [od3, os3, od2]

    # 화면 분할 chosen by hand (보기 → Simple 화면 분할 4장) with nothing picked: VK-2's consecutive photos
    # from the shown one — and it stays so when Simple comes back from 3D
    _press(w, "view:simple")
    w.btn_clear_picks.click()
    w._on_action("multi:4")
    app.processEvents()
    assert w.multi.count == 4 and len(_cells(w)[0]) == 4
    _press(w, "view3d")
    assert w._tab() == "3d"
    _press(w, "view3d")
    assert w._tab() == "multi" and w.multi.count == 4 and len(_cells(w)[0]) == 4


def test_a_double_click_opens_detail_and_another_goes_back(win):
    """Detail: a double click on a photo opens it large, a double click on the big photo goes back to the
    view it came from, as it was — Simple with the photos picked there, Multi (16장), 3D."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, od2 = ids["od3"], ids["os3"], ids["od2"]

    def dclick(view):
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
        app.processEvents()

    # Simple with a photo added by hand: a cell double clicked — Detail; the big photo double clicked — back,
    # the three photos as they were, that photo selected
    _click(app, w, od2)
    assert w.picks() == [od3, os3, od2]
    dclick(next(c for c in w.multi.cells if c.image_id == os3).view)
    assert w._tab() == "all" and w.current["id"] == os3 and _lit(w) == ["view:all"]
    assert not w.view2d.loupe_on
    dclick(w.view2d)
    assert w._tab() == "multi" and _lit(w) == ["view:simple"] and w.picks() == [od3, os3, od2]
    assert _cells(w) == ([od3, os3, od2], os3) and not w.view2d.loupe_on
    # from the photo list the same; ◀ ▶ on Detail in between do not change where it goes back to
    _click(app, w, od2, double=True)
    assert w._tab() == "all" and w.current["id"] == od2
    w._step(1)
    dclick(w.view2d)
    assert w._tab() == "multi" and w.picks() == [od3, os3, od2]
    # 16장 보기 ([Multi] on Simple): a photo double clicked — Detail; double clicked again — 16장 보기
    _press(w, "view:multi")
    assert w._tab() == "grid"
    w.grid.activated.emit(od2)
    app.processEvents()
    assert w._tab() == "all" and w.current["id"] == od2
    dclick(w.view2d)
    assert w._tab() == "grid" and _lit(w) == []
    # Multi (the picked photos only): a cell double clicked — Detail; double clicked again — Multi, lit
    _press(w, "view:multi")
    assert w._tab() == "multi" and _lit(w) == ["view:multi"]
    dclick(next(c for c in w.multi.cells if c.image_id == od2).view)
    assert w._tab() == "all" and w.current["id"] == od2 and _lit(w) == ["view:all"]
    dclick(w.view2d)
    assert w._tab() == "multi" and _lit(w) == ["view:multi"] and _cells(w)[0] == [od3, os3, od2]
    # [Detail] pressed on 3D: back to 3D
    w._go("3d")
    _press(w, "view:all")
    assert w._tab() == "all"
    dclick(w.view2d)
    assert w._tab() == "3d"
    # with a measuring tool a double click is the tool's (Detail stays)
    _press(w, "view:all")
    w._on_action("tool:length")
    dclick(w.view2d)
    assert w._tab() == "all"
    w._on_action("tool:zoom")


def test_a_new_photo_takes_its_eyes_place(win):
    """새 영상 자동 표시 on Simple: the newest OD | OS again, the new photo selected — unless the photos
    there were changed by hand, then the new photo is shown large."""
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
    # while Simple shows all the photos (nothing picked): the new one is among them, selected — and
    # [Simple] puts the newest OD | OS on it again
    w.btn_clear_picks.click()
    new_od = db.insert_image(patient_ref=refs["kim"], exam_date="2026-04-01", exam_time="09:02:00", laterality="OD",
                             modality="color", file_path=os.path.join(folder, "p3.png"), sha256="new_od")
    w._results.append(ImportResult("imported", "new_od.png", "김영수", image_id=new_od, patient_ref=refs["kim"]))
    w._flush_results()
    app.processEvents()
    assert w._tab() == "multi" and w.picks() == [] and w.multi.count == 9 and w.thumbs.count() == 9
    assert _cells(w) == (w._strip_ids(), new_od)
    _press(w, "view:simple")
    assert w.picks() == [new_od, new]
    # a photo added by hand: they stay; the new photo is shown large
    _click(app, w, ids["od2"])
    assert w.picks() == [new_od, new, ids["od2"]]
    new2 = db.insert_image(patient_ref=refs["kim"], exam_date="2026-04-01", exam_time="09:05:00", laterality="OD",
                           modality="color", file_path=os.path.join(folder, "p3.png"), sha256="new2")
    w._results.append(ImportResult("imported", "new2.png", "김영수", image_id=new2, patient_ref=refs["kim"]))
    w._flush_results()
    app.processEvents()
    assert w._tab() == "all" and w.current["id"] == new2 and w.picks() == [new_od, new, ids["od2"]]


def test_arrows_at_the_sides_of_a_photo_and_the_arrow_keys(win):
    """◀ ▶ come up at the left / right side of a photo under the mouse and go to the photo before /
    after it, as ← / → do — Detail: of the photo list; Simple (and Multi): in a cell's place the photo of
    the same eye before / after it; ← / → on the photo list go through the photos on the page."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2, od1, sheet = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2", "od1", "sheet"))
    strip = w._strip_ids()
    assert strip == [rf3, od3, od2, sheet, od1, os3, os2]          # OD newest first, then OS

    def hover(view, side):
        vp = view.viewport()
        x = {"left": 20, "right": vp.width() - 20, "middle": vp.width() // 2}[side]
        QTest.mouseMove(vp, QPoint(x, vp.height() // 2))

    def press(button):
        assert button.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        app.processEvents()

    # -- Detail: through the photo list ----------------------------------------------------------------
    _click(app, w, od3, double=True)
    app.processEvents()
    nav = w.nav2d
    before, after = nav.buttons[-1], nav.buttons[1]
    assert w._tab() == "all" and w.current["id"] == od3 and nav.available() == (True, True)
    assert not before.isVisible() and not after.isVisible()      # not until the mouse is at a side
    hover(w.view2d, "right")
    assert after.isVisible() and not before.isVisible()
    assert after.x() > w.view2d.viewport().width() * 0.8          # at the right edge, half way up
    assert abs(after.geometry().center().y() - w.view2d.viewport().height() // 2) <= 2
    hover(w.view2d, "middle")
    assert not before.isVisible() and not after.isVisible()
    hover(w.view2d, "left")
    assert before.isVisible() and not after.isVisible() and before.x() < 40
    press(before)                                                 # ◀: the photo before it
    assert w._tab() == "all" and w.current["id"] == rf3 and w.thumbs.currentRow() == 0
    assert nav.available() == (False, True) and not before.isVisible()   # the first one: nothing before it
    hover(w.view2d, "left")
    assert not before.isVisible()
    hover(w.view2d, "right")
    press(after)
    press(after)
    assert w.current["id"] == od2
    # ← / → on the photo, and on the photo list
    QTest.keyClick(w.view2d, Qt.Key.Key_Right)
    assert w.current["id"] == sheet
    QTest.keyClick(w.view2d, Qt.Key.Key_Left)
    QTest.keyClick(w.view2d, Qt.Key.Key_Left)
    assert w.current["id"] == od3
    QTest.keyClick(w.thumbs, Qt.Key.Key_Right)
    assert w.current["id"] == od2 and w._tab() == "all"
    w._select_from_multi(os2)                                     # the last one: nothing after it
    assert nav.available() == (True, False)
    QTest.keyClick(w.view2d, Qt.Key.Key_Right)
    assert w.current["id"] == os2
    QTest.keyClick(w, Qt.Key.Key_Left)                            # (a key no control took: the window's)
    assert w.current["id"] == os3
    assert w.picks() == [od3, os3]                                # the two of Simple: as they were

    # -- Simple: ◀ ▶ on a cell — in its place the photo of the same eye before / after it (newer / older);
    #    ← / → in the cell the same; ← / → on the photo list go through the photos on it -------------------
    _press(w, "view:simple")
    assert _cells(w)[0] == [od3, os3]
    assert w._eye_ids(od3) == [rf3, od3, od2, sheet, od1] and w._eye_ids(os3) == [os3, os2]
    cells = [c for c in w.multi.cells if c.isVisible() and c.image_id]
    assert cells[0].nav.available() == (True, True)               # OD: rf3 before, od2 after
    assert cells[1].nav.available() == (False, True)              # OS: the newest — nothing before it
    hover(cells[0].view, "right")
    assert cells[0].nav.buttons[1].isVisible() and not cells[0].nav.buttons[-1].isVisible()
    press(cells[0].nav.buttons[1])                                # ▶ on OD: the older OD photo, in its place
    assert _cells(w) == ([od2, os3], od2) and w.picks() == [od2, os3]
    hover(cells[1].view, "right")
    press(cells[1].nav.buttons[1])                                # ▶ on OS
    assert _cells(w) == ([od2, os2], os2) and cells[1].nav.available() == (True, False)
    QTest.keyClick(cells[0].view, Qt.Key.Key_Left)                # ← in the OD cell: back to the newer one
    assert _cells(w) == ([od3, os2], od3)
    hover(cells[0].view, "left")
    press(cells[0].nav.buttons[-1])                               # ◀: the red-free of that day
    assert _cells(w) == ([rf3, os2], rf3) and cells[0].nav.available() == (False, True)
    QTest.keyClick(cells[0].view, Qt.Key.Key_Right)
    # a photo on another cell is passed over: od2 picked too, ▶ on od3 goes to the one after od2
    _click(app, w, od2)
    assert _cells(w) == ([od3, os2, od2], od2)
    cells = [c for c in w.multi.cells if c.isVisible() and c.image_id]
    w._step_cell(od3, 1)
    assert _cells(w) == ([sheet, os2, od2], sheet) and w.picks() == [sheet, os2, od2]
    w._step_cell(sheet, -1)
    assert _cells(w) == ([od3, os2, od2], od3)
    # ← / → on the photo list: through the photos on the page
    QTest.keyClick(w.thumbs, Qt.Key.Key_Right)
    assert _cells(w) == ([od3, os2, od2], os2)
    QTest.keyClick(w.thumbs, Qt.Key.Key_Left)
    assert _cells(w) == ([od3, os2, od2], od3) and w.picks() == [od3, os2, od2]
    w._on_action("next")                                          # 다음 (PageDown): the same
    assert w.current["id"] == os2 and w._tab() == "multi"


@pytest.mark.parametrize("way", ["grid", "odos"])
def test_the_last_patient_comes_back_on_16_photos_or_simple(tmp_path, way):
    """At the start the patient of the last session is behind the patient list — on 16장 보기 (the
    first setting: also for settings of before, once), or on Simple with its newest OD | OS when
    that was chosen — so that closing the list without picking a patient shows that first."""
    import time

    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="K001",
                 open_view="odos", ui_version=5 if way == "grid" else MainWindow.UI_VERSION)
    w = MainWindow(s, db)
    assert s.open_view == way and s.ui_version == MainWindow.UI_VERSION       # (5 → 6: 16장 보기, once)
    try:
        w.show()
        end = time.time() + 5
        while w._patient_ref is None and time.time() < end:      # (the start-up runs 200 ms after the window)
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert w._patient_ref == refs["kim"] and w.patient_list.isVisible()
        if way == "grid":
            assert w._tab() == "grid" and _lit(w) == [] and w.picks() == [] and len(w.grid.items()) == 7
        else:
            assert w._tab() == "multi" and _lit(w) == ["view:simple"]
            assert _cells(w) == ([ids["od3"], ids["os3"]], ids["od3"])
    finally:
        w.close()
        db.close()


def test_macula_and_disc_under_the_photos_of_simple(win):
    """[황반 · 디스크] on the Simple · Multi row: under each photo its macula and optic disc enlarged, as on
    Detail (a photo whose disc / macula is not known: its middle, said so) — with at most 4 cells;
    remembered for the next time."""
    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3 = ids["od3"], ids["os3"]
    assert w._tab() == "multi" and w.btn_closeups.isVisible() and not w.btn_closeups.isChecked()
    cells = [c for c in w.multi.cells if c.isVisible() and c.image_id]
    assert all(not c.closeups.isVisible() for c in cells)

    db.update_image(od3, disc_x=200.0, disc_y=150.0, fovea_x=120.0, fovea_y=160.0)   # (as found on import)
    w.btn_closeups.click()
    app.processEvents()
    assert w.settings.simple_closeups and w.multi.closeups_shown()
    assert all(c.closeups.isVisible() for c in cells)
    od_cell = next(c for c in cells if c.image_id == od3)
    os_cell = next(c for c in cells if c.image_id == os3)
    for c in (od_cell, os_cell):
        assert all(z.has_image() for z in c.zooms.values())
    assert od_cell.zoom_heads["disc"].text() == "시신경 유두" and od_cell.zoom_heads["macula"].text() == "황반"
    assert "찾지 못함" in os_cell.zoom_heads["disc"].text()
    # the disc pane looks at the disc: the middle of what it shows is the disc, in the photo's pixels
    z = od_cell.zooms["disc"]
    seen = z.mapToScene(z.viewport().rect()).boundingRect()
    d = 80.0                                                  # disc–fovea distance
    assert seen.width() == pytest.approx(0.85 * d, rel=0.35)
    assert w._tab() == "multi"
    # with the photo's processing: red-free on that photo, its panes red-free too
    w._select_from_multi(od3)
    w._on_action("chan:redfree")
    app.processEvents()
    g = od_cell.zooms["disc"]._rgb
    assert (g[..., 0] == g[..., 2]).all()
    w._on_action("chan:redfree", False)
    # a double click on a pane: that photo large (Detail)
    od_cell.zooms["macula"].activated.emit()
    assert w._tab() == "all" and w.current["id"] == od3
    _press(w, "view:simple")
    # more than 4 cells: no room — the panes go, and come back with fewer
    w._on_action("multi:9")
    app.processEvents()
    assert not w.multi.closeups_shown() and not any(c.closeups.isVisible() for c in w.multi.cells)
    w._on_action("multi:2")
    app.processEvents()
    assert w.multi.closeups_shown()
    # off: gone, and remembered
    w.btn_closeups.click()
    assert not w.settings.simple_closeups and not any(c.closeups.isVisible() for c in w.multi.cells)
