"""VK-2 style picking: the strip shows several rows (newest first) with the eye on every photo,
a plain click picks photos (numbered), [멀티] shows the picked photos in the multi view and a
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
        rows = db.images_for_patient(pid)
        ids = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)]
        assert ids == [r["id"] for r in rows]                       # newest exam first (VK-2)
        assert [w.thumbs.item(i).data(EYE_ROLE) for i in range(3)] == [r["laterality"] or "" for r in rows]

        # several rows of photos; the row button cycles 2 → 3 → 1 and is remembered
        assert w.thumbs.isWrapping() and w.btn_rows.text().endswith("2줄")
        grid_h = w.thumbs.gridSize().height()
        assert w.thumbs.height() < 2 * grid_h                         # 3 photos fit in one row: no empty band
        w.btn_rows.click()
        assert s.thumb_rows == 3
        w.btn_rows.click()
        assert not w.thumbs.isWrapping() and s.thumb_rows == 1 and w.thumbs.height() == 182
        w.btn_rows.click()
        assert s.thumb_rows == 2
        w.thumbs.setFixedWidth(2 * w.thumbs.gridSize().width() + 30)  # narrow strip: 3 photos need 2 rows
        app.processEvents()
        w._fit_thumb_height()
        assert w.thumbs.height() == 2 * grid_h + 12
        w.thumbs.setMinimumWidth(0)
        w.thumbs.setMaximumWidth(16777215)
        app.processEvents()

        # plain click = pick (numbered), the shown photo stays; click again = unpick
        shown = w.current["id"]
        _click(w, w.thumbs.item(2))
        _click(w, w.thumbs.item(0))
        assert w.picks() == [ids[2], ids[0]] and w.current["id"] == shown
        assert w.thumbs.item(2).data(PICK_ROLE) == 1 and w.thumbs.item(0).data(PICK_ROLE) == 2
        assert w.btn_multi.text() == "멀티 2" and w.btn_clear_picks.isVisible()
        _click(w, w.thumbs.item(2))
        assert w.picks() == [ids[0]] and w.thumbs.item(0).data(PICK_ROLE) == 1
        _click(w, w.thumbs.item(1))
        assert w.picks() == [ids[0], ids[1]]

        # double click = open in 2D, the picks stay as they were
        w.tabs.setCurrentIndex(3)
        _click(w, w.thumbs.item(2), double=True)
        assert w.current["id"] == ids[2] and w.tabs.currentIndex() == 0
        assert w.picks() == [ids[0], ids[1]]

        # [멀티]: the picked photos, in pick order, the first one selected
        w.btn_multi.click()
        app.processEvents()
        assert w.tabs.currentIndex() == 2 and w.multi.count == 2
        cells = [c for c in w.multi.cells if c.isVisible()]
        assert [c.image_id for c in cells] == [ids[0], ids[1]]
        assert w.current["id"] == ids[0] and "고른 사진 2장" in w.multi.mode_label.text()
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
        assert w.current["id"] == ids[1] and w._channel == "rgb"    # its own (untouched) processing
        w._on_action("op:sharpen")
        assert w._ops == ["sharpen"]
        QTest.mouseClick(cells[0].view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        assert w.current["id"] == ids[0] and w._channel == "redfree" and w._ops == []
        w._on_action("undo")                                         # each photo keeps its own undo
        assert w._channel == "rgb"
        assert w._per_photo[ids[1]]["state"]["ops"] == ["sharpen"]

        # clearing the picks goes back to the VK-2 consecutive multi view
        w.btn_clear_picks.click()
        app.processEvents()
        assert w.picks() == [] and w.multi.mode_label.text() == "" and w.btn_multi.text() == "멀티"
        assert not w.btn_clear_picks.isVisible()

        # another patient: the picks belong to the previous one
        _click(w, w.thumbs.item(0))
        assert w.picks() == [ids[0]]
        other = next(p["id"] for p in db.list_patients() if p["id"] != pid)
        w._select_patient_ref(other)
        assert w.picks() == [] and w._per_photo == {}
    finally:
        w.close()
