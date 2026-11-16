"""VK-2 style picking: the strip shows the photos by eye (OD row on top, OS row under it, newest
first) with the eye on every photo, a plain click puts the photo on the multi view at once
(numbered; the layout fits the number picked), [멀티] goes back to the picked photos and a
click on a cell lets the processing toolbar change that photo only."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_eye_badges():
    from fundusview.ui.thumbs import eye_badge, eye_badge_html

    assert [eye_badge(e)[0] for e in ("OD", "OS", "OU")] == ["OD", "OS", "OU"]
    assert eye_badge(None)[0] == "미상" and eye_badge("")[0] == "미상"
    assert len({eye_badge(e)[1] for e in ("OD", "OS", "OU", None)}) == 4
    assert "OD" in eye_badge_html("OD")


def test_strip_rows_by_eye(app):
    """OD row on top, OS row under it, OU / 미상 in a third row; the rows start at the left and
    scroll sideways together (no vertical scrolling: the wheel goes sideways)."""
    import time

    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QListWidgetItem

    from fundusview.ui.thumbs import EYE_ROLE, ThumbStrip, eye_row

    assert [eye_row(e) for e in ("OD", "OS", "OU", "", None)] == [0, 1, 2, 2, 2]
    t = ThumbStrip()
    t.setGridSize(QSize(96, 104))
    t.resize(5 * 96 + 20, 400)
    eyes = ["OD"] * 8 + ["OS"] * 3 + ["", "OU"]              # added in the strip's order: OD, OS, the rest
    for k, e in enumerate(eyes):
        it = QListWidgetItem(str(k))
        it.setSizeHint(QSize(92, 102))
        it.setData(EYE_ROLE, e)
        t.addItem(it)
    t.set_by_eye(True)
    t.show()
    app.processEvents()

    def check():
        assert t.grid_shape() == (3, 8)
        r = [t.visualItemRect(t.item(i)) for i in range(len(eyes))]
        top = r[0].top()
        assert [x.top() - top for x in r] == [0] * 8 + [104] * 3 + [208] * 2
        assert [x.left() for x in r[8:11]] == [x.left() for x in r[:3]]       # the rows line up
        assert [x.left() for x in r[11:]] == [x.left() for x in r[:2]]
        h = t.horizontalScrollBar()
        assert h.maximum() == 8 * 96 - t.viewport().width() and t.verticalScrollBar().maximum() == 0

    check()
    t.scrollToItem(t.item(7))                                 # the end of the OD row
    app.processEvents()
    assert t.horizontalScrollBar().value() > 0
    assert t.row(t.itemAt(t.visualItemRect(t.item(7)).center())) == 7
    t.horizontalScrollBar().setValue(0)
    assert t.row(t.itemAt(t.visualItemRect(t.item(12)).center())) == 12
    t.resize(4 * 96, 400)                                     # Qt lays the list out again: still by eye
    deadline = time.time() + 2
    while time.time() < deadline:
        app.processEvents()
    check()
    t.set_by_eye(False)                                       # one line, in the same order
    app.processEvents()
    assert t.grid_shape() == (1, len(eyes))
    assert len({t.visualItemRect(t.item(i)).top() for i in range(len(eyes))}) == 1
    lefts = [t.visualItemRect(t.item(i)).left() for i in range(len(eyes))]
    assert lefts == sorted(lefts)
    t.close()


def _click(w, item, double=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    pos = w.thumbs.visualItemRect(item).center()
    if double:
        QTest.mouseDClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    else:
        QTest.mouseClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def test_pick_photos_and_edit_each_in_multi(app, tmp_path, demo_dir, import_and_wait):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow
    from fundusview.ui.thumbs import EYE_ROLE, PICK_ROLE

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.resize(1600, 960)
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam", demo_dir / "VK2_Export"])
        pid = db.find_patient("PID20260310-0A1B2C3D")["id"]
        w._select_patient_ref(pid)
        app.processEvents()
        assert w.thumbs.count() == 3
        rows = db.images_for_patient(pid)                           # newest exam first (VK-2)
        # the patient comes with its newest OD and OS picked (OD first)
        eyes = {r["id"]: r["laterality"] for r in rows}
        assert [eyes[i] for i in w.picks()] == ["OD", "OS"] and w.current["id"] == w.picks()[0]
        ids = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)]
        by_eye = [r for e in ("OD", "OS") for r in rows if r["laterality"] == e]
        assert ids == [r["id"] for r in by_eye]                     # OD photos, then OS — each newest first
        assert [w.thumbs.item(i).data(EYE_ROLE) for i in range(3)] == ["OD", "OD", "OS"]
        assert all("°" not in w.thumbs.item(i).text() for i in range(3))     # the date and the kind, no angle

        # by eye: OD in the top row, OS in the row under it; the row button switches to one line and back
        # (remembered); one eye on the list = one row
        grid_h = w.thumbs.gridSize().height()

        def tops():
            return [w.thumbs.visualItemRect(w.thumbs.item(i)).top() for i in range(w.thumbs.count())]

        rects = [w.thumbs.visualItemRect(w.thumbs.item(i)) for i in range(3)]
        assert tops()[0] == tops()[1] and tops()[2] - tops()[0] == grid_h
        assert rects[0].left() == rects[2].left() < rects[1].left()   # each row starts at the left
        assert w.btn_rows.text().endswith("OD/OS") and w.thumbs.height() == 2 * grid_h + 10
        w.btn_rows.click()
        from fundusview.ui.main_window import THUMB_GRID
        assert s.thumb_rows == 1 and w.btn_rows.text().endswith("1줄") and w.thumbs.height() == THUMB_GRID[1] + 10
        assert len(set(tops())) == 1
        w.btn_rows.click()
        assert s.thumb_rows == 2 and tops()[2] - tops()[0] == grid_h
        w.f_eye.setCurrentIndex(w.f_eye.findData("OS"))
        app.processEvents()
        assert w.thumbs.count() == 1 and w.thumbs.height() == grid_h + 10
        w.f_eye.setCurrentIndex(0)
        app.processEvents()
        assert w.thumbs.count() == 3 and w.thumbs.height() == 2 * grid_h + 10

        # 미상 (eye unknown): not in the list — 눈 → 미상 shows them, and so does a patient with nothing else
        from fundusview.ui.main_window import UNKNOWN_EYE

        def strip_ids():
            return [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.thumbs.count())]

        eye_of = {r["id"]: r["laterality"] for r in rows}
        db.update_image(ids[1], laterality=None)
        w._fill_thumbs()
        app.processEvents()
        assert strip_ids() == [ids[0], ids[2]] and w.thumbs.grid_shape() == (2, 1)
        assert w.thumbs.height() == 2 * grid_h + 10                  # two rows: OD, OS
        w.f_eye.setCurrentIndex(w.f_eye.findData(UNKNOWN_EYE))
        app.processEvents()
        assert strip_ids() == [ids[1]]
        w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
        app.processEvents()
        assert strip_ids() == [ids[0]]
        w.f_eye.setCurrentIndex(0)
        for k in ids:
            db.update_image(k, laterality=None)
        w._fill_thumbs()
        app.processEvents()
        assert sorted(strip_ids()) == sorted(ids) and w.thumbs.grid_shape() == (1, 3)
        for k in ids:
            db.update_image(k, laterality=eye_of[k])
        w._fill_thumbs()
        app.processEvents()
        assert strip_ids() == ids

        # 선택 해제 starts from nothing
        w.clear_picks()
        assert w.picks() == [] and not w.btn_clear_picks.isVisible()

        # plain click = the photo on the multi view at once (numbered, selected); click again = it leaves
        _click(w, w.thumbs.item(2))
        app.processEvents()
        assert w._tab() == "multi" and w.picks() == [ids[2]] and w.multi.count == 1 and w.current["id"] == ids[2]
        _click(w, w.thumbs.item(0))
        assert w.picks() == [ids[2], ids[0]] and w.multi.count == 2 and w.current["id"] == ids[0]
        assert w.thumbs.item(2).data(PICK_ROLE) == 1 and w.thumbs.item(0).data(PICK_ROLE) == 2
        assert w.btn_multi.text() == "멀티 2" and w.btn_clear_picks.isVisible()
        _click(w, w.thumbs.item(2))
        assert w.picks() == [ids[0]] and w.thumbs.item(0).data(PICK_ROLE) == 1 and w.multi.count == 1
        _click(w, w.thumbs.item(1))
        assert w.picks() == [ids[0], ids[1]] and w.multi.count == 2

        # double click = that photo large (모두 보기, whose big photo is the 2D view), the picks stay as they were
        _click(w, w.thumbs.item(2), double=True)
        assert w.current["id"] == ids[2] and w._tab() == "all"
        assert w.picks() == [ids[0], ids[1]]

        # [멀티]: the picked photos, in pick order, the first one selected
        w.btn_multi.click()
        app.processEvents()
        assert w._tab() == "multi" and w.multi.count == 2
        cells = [c for c in w.multi.cells if c.isVisible()]
        assert [c.image_id for c in cells] == [ids[0], ids[1]]
        assert w.current["id"] == ids[0] and "고른 사진 2장" in w.multi.mode_text
        assert "OD" in cells[0].label.text() or "OS" in cells[0].label.text() or "미상" in cells[0].label.text()

        # processing applies to the selected cell's photo only
        before_second = cells[1].view._rgb.copy()
        w._on_action("chan:redfree")
        assert w._channel == "redfree"
        assert (cells[1].view._rgb == before_second).all()          # the other cell is untouched
        g = cells[0].view._rgb
        assert (g[..., 0] == g[..., 2]).all() and (g[..., 0] <= g[..., 1]).all()   # red-free = green-tinted grey
        QTest.mouseClick(cells[1].view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        assert w._tab() == "multi"                                   # a click selects the cell (it stays)
        assert w.current["id"] == ids[1] and w._channel == "rgb"    # its own (untouched) processing
        w._on_action("op:sharpen")
        assert w._ops == ["sharpen"]
        assert not (cells[1].view._rgb == before_second).all()      # sharpened, in its cell
        QTest.mouseClick(cells[0].view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        assert w.current["id"] == ids[0] and w._channel == "redfree" and w._ops == []
        # a photo opened large keeps its processing there, and back on [다중 보기] each has its own
        QTest.mouseDClick(cells[0].view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        assert w._tab() == "all" and w.current["id"] == ids[0] and w._channel == "redfree"
        w.view_buttons["multi"].click()
        app.processEvents()
        cells = [c for c in w.multi.cells if c.isVisible()]
        assert w._tab() == "multi" and [c.image_id for c in cells] == [ids[0], ids[1]]
        assert (cells[0].view._rgb[..., 0] == cells[0].view._rgb[..., 2]).all()      # still red-free
        w._on_action("undo")                                         # each photo keeps its own undo
        assert w._channel == "rgb"
        assert w._per_photo[ids[1]]["state"]["ops"] == ["sharpen"]

        # clearing the picks: the multi view says how to pick; 다중 ▾ N장 = VK-2's consecutive photos
        w.btn_clear_picks.click()
        app.processEvents()
        assert w.picks() == [] and w.multi.mode_text == "" and w.btn_multi.text() == "멀티"
        assert not w.btn_clear_picks.isVisible() and w.multi.empty.isVisible()
        w._on_action("multi:2")
        app.processEvents()
        assert not w.multi.empty.isVisible() and len([c for c in w.multi.cells if c.isVisible() and c.image_id]) == 2

        # another patient: the picks belong to the previous one — that patient's own newest OD | OS
        _click(w, w.thumbs.item(0))
        assert w.picks() == [ids[0]]
        other = next(p["id"] for p in db.list_patients() if p["id"] != pid)
        w._select_patient_ref(other)
        theirs = {r["id"] for r in db.images_for_patient(other)}
        assert set(w.picks()) <= theirs and w._per_photo == {}
    finally:
        w.close()
