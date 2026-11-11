"""모두 보기 (first tab): the big 2D photo with 다중 · 확대 · 3D panes, photo list under the views."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _window(tmp_path, demo_dir):
    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    return MainWindow(s, db), db


def _wait(app, cond, timeout: float = 5.0) -> None:
    import time
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert cond()


def _inside(widget, ancestor) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def test_overview_panes_follow_the_photo(tmp_path, demo_dir, import_and_wait):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w, db = _window(tmp_path, demo_dir)
    try:
        w.resize(1500, 950)
        w.show()
        import_and_wait(app, w, [demo_dir])
        w._select_patient_ref(db.find_patient("20260115001")["id"])
        app.processEvents()
        # opens on 모두 보기 with the big 2D view in it; the photo list sits under the views
        assert w._tab() == "all" and w.tabs.tabText(0) == "모두 보기"
        assert _inside(w.view2d, w.page_all) and w.view2d.has_image()
        assert w.thumbs.mapTo(w, QPoint(0, 0)).y() > w.tabs.mapTo(w, QPoint(0, 0)).y() + w.tabs.height() - 5
        # 다중 (2 × 2): the patient's 2 photos; 확대: the same processed photo as the big view
        cells = [c for c in w.ov_multi.cells if c.isVisible()]
        assert len(cells) == 4 and sum(c.image_id is not None for c in cells) == 2
        assert not w.ov_multi.topbar.isVisible()
        assert w.ov_zoom._rgb is w.view2d._rgb and w.ov_zoom.zoomed_in()
        # the frame on the big photo shows what the 확대 화면 shows: first the optic disc
        row = w.current
        disc = QPointF(row["disc_x"], row["disc_y"])
        assert w._ov_roi.isVisible() and w._ov_roi.rect().contains(disc)
        # a click on the big photo moves the 확대 화면 there; a drag (zoom) does not
        h, wd = w.view2d._rgb.shape[:2]
        target = QPointF(wd * 0.3, h * 0.6)
        QTest.mouseClick(w.view2d.viewport(), Qt.MouseButton.LeftButton, pos=w.view2d.mapFromScene(target))
        app.processEvents()
        assert w._ov_roi.rect().contains(target) and not w._ov_roi.rect().contains(disc)
        before = w._ov_roi.rect()
        vp = w.view2d.viewport()
        a = w.view2d.mapFromScene(QPointF(wd * 0.7, h * 0.4))
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(vp, a + QPoint(0, 30))
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=a + QPoint(0, 30))
        app.processEvents()
        assert w._ov_roi.rect() == before
        w._on_action("fit")
        # processing (Red-free) reaches the 확대 화면 and keeps its place
        w._on_action("chan:redfree")
        _wait(app, lambda: not w._adjust_timer.isActive())
        assert w.ov_zoom._rgb is w.view2d._rgb and w._ov_roi.rect().contains(target)
        # the frame is never in a copy / saved / printed picture
        img = w._rendered()
        assert w._ov_roi.isVisible()
        w._ov_roi.setVisible(False)
        assert img == w.view2d.render_image()
        w._ov_roi.setVisible(True)
        # the next photo: 확대 화면 back on its disc, 다중 marks it
        w._on_action("next")
        app.processEvents()
        row = w.current
        assert w._ov_roi.rect().contains(QPointF(row["disc_x"], row["disc_y"]))
        from fundusview.ui.theme import ACCENT                     # the selected cell's frame
        assert any(c.image_id == row["id"] and ACCENT in c.styleSheet() for c in w.ov_multi.cells)
        # clicking a 다중 cell selects that photo
        other = next(c for c in w.ov_multi.cells if c.image_id not in (None, row["id"]))
        other.view.clicked.emit()
        app.processEvents()
        assert w.current["id"] == other.image_id
        # 2D 보기 gets the big view back (no frame there); pane headers open the big tabs
        w._go("2d")
        assert _inside(w.view2d, w.page2d) and not w._ov_roi.isVisible()
        w._go("all")
        assert _inside(w.view2d, w.page_all) and w._ov_roi.isVisible()
        w.ov_heads["multi"].click()
        assert w._tab() == "multi"
        w._go("all")
        w.ov_heads["zoom"].click()
        assert w._tab() == "2d"
        w._go("all")
        # no OpenGL offscreen: the 3D pane is a button to the 3D tab, the eye stays in its tab
        assert not w._ov_gl and _inside(w.split3d, w.page3d)
        btn = w.ov_3d.findChild(type(w.ov_heads["3d"]), "ovOpen3d")
        btn.click()
        assert w._tab() == "3d"
        # 보기 menu: tabs by name, Ctrl+1~4 as before and Ctrl+5 for 모두 보기
        acts = {a.text(): a.shortcut().toString() for a in w.findChildren(type(w.acts["fit"]))
                if a.text() in ("모두 보기", "2D 보기", "3D 안구", "다중 보기", "비교")}
        assert acts == {"모두 보기": "Ctrl+5", "2D 보기": "Ctrl+1", "3D 안구": "Ctrl+2", "다중 보기": "Ctrl+3",
                        "비교": "Ctrl+4"}
        for key in ("2d", "3d", "multi", "cmp", "all"):
            w._go(key)
            app.processEvents()
            assert w._tab() == key
    finally:
        w.close()
        db.close()

