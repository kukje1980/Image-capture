"""모두 보기 (v0.3.0): the big 2D photo with its macula and optic disc enlarged beside it; no tab row —
the views (모두 보기 · 다중 보기 · 3D) are switched in the line under the photos; the patient line is
in the menu bar; the command toolbar at the left."""
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


def _shows(view, point) -> bool:
    return view.mapToScene(view.viewport().rect()).boundingRect().contains(point)


def test_overview_is_the_photo_with_its_macula_and_disc(tmp_path, demo_dir, import_and_wait):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w, db = _window(tmp_path, demo_dir)
    try:
        w.resize(1500, 950)
        w.show()
        app.processEvents()
        assert w.patient_list.isVisible() and w.tabs.isVisible()     # the patient list in front of the photos
        import_and_wait(app, w, [demo_dir])
        w._select_patient_ref(db.find_patient("20260115001")["id"])
        w.patient_list.hide()
        app.processEvents()
        assert w._tab() == "all"

        # -- the frame: no tab row; the view switch under the photos; patient line in the menu bar --
        assert w.tabs.tabBar().isHidden()
        assert [b.text() for b in w.view_buttons.values()] == ["모두 보기", "다중 보기", "3D"]
        assert w.view_buttons["all"].isChecked() and _inside(w.seg_views, w.strip_w) and w.seg_views.isVisible()
        assert w.thumbs.mapTo(w, QPoint(0, 0)).y() > w.view2d.mapTo(w, QPoint(0, 0)).y() + w.view2d.height() - 5
        assert w.menuBar().cornerWidget(Qt.Corner.TopRightCorner) is w.top_w
        assert w.btn_patients.isVisible() and _inside(w.btn_patients, w.top_w)
        assert "김민수" in w.banner.text() and "20260115001" in w.banner.text()
        assert w.toolBarArea(w.tb_cmd) == Qt.ToolBarArea.LeftToolBarArea
        assert w.thumbs.height() < 130                                   # one low line of photos

        # -- 모두 보기: the big photo, 황반 and 시신경 유두 enlarged; no 다중 · 3D panes --
        assert _inside(w.view2d, w.page_all) and w.view2d.has_image()
        assert list(w.ov_heads) == ["macula", "zoom"] and not w.ov_multi.isVisible()
        assert not w._ov_gl and _inside(w.split3d, w.page3d)
        row = w.current
        fovea, disc = QPointF(row["fovea_x"], row["fovea_y"]), QPointF(row["disc_x"], row["disc_y"])
        for v in (w.ov_macula, w.ov_zoom):
            assert v._rgb is w.view2d._rgb and v.zoomed_in()             # the same processed photo
        assert _shows(w.ov_macula, fovea) and not _shows(w.ov_macula, disc) or _shows(w.ov_macula, fovea)
        assert _shows(w.ov_zoom, disc) and not _shows(w.ov_zoom, fovea)
        assert w.ov_zoom.zoom > w.ov_macula.zoom                         # the disc closer than the macula
        # the frames on the big photo are where the panes look (macula light blue, disc yellow)
        roi_m, roi_d = w._ov_rois["macula"], w._ov_rois["zoom"]
        assert roi_m.isVisible() and roi_m.rect().contains(fovea)
        assert roi_d.isVisible() and roi_d.rect().contains(disc) and not roi_d.rect().contains(fovea)
        assert "찾지 못함" not in w.ov_heads["macula"].text() + w.ov_heads["zoom"].text()
        # a click on the big photo leaves the panes where they are (they show their own places)
        before = (roi_m.rect(), roi_d.rect())
        h, wd = w.view2d._rgb.shape[:2]
        QTest.mouseClick(w.view2d.viewport(), Qt.MouseButton.LeftButton,
                         pos=w.view2d.mapFromScene(QPointF(wd * 0.3, h * 0.6)))
        app.processEvents()
        assert (roi_m.rect(), roi_d.rect()) == before
        # processing (Red-free) reaches both panes; their places stay
        w._on_action("chan:redfree")
        _wait(app, lambda: not w._adjust_timer.isActive())
        assert w.ov_macula._rgb is w.view2d._rgb and w.ov_zoom._rgb is w.view2d._rgb
        assert roi_m.rect().contains(fovea) and roi_d.rect().contains(disc)
        w._on_action("chan:redfree", False)
        # the frames are never in a copy / saved / printed picture
        img = w._rendered()
        assert roi_m.isVisible() and roi_d.isVisible()
        roi_m.setVisible(False)
        roi_d.setVisible(False)
        assert img == w.view2d.render_image()
        w._ov_sync_roi()
        assert roi_m.isVisible() and roi_d.isVisible()
        # a pane's heading zooms the big photo to that place; double click on the big photo: all of it
        w._on_action("fit")
        assert not w.view2d.zoomed_in()
        w.ov_heads["zoom"].click()
        assert w.view2d.zoomed_in() and _shows(w.view2d, disc)
        w.ov_heads["macula"].click()
        assert w.view2d.zoomed_in() and _shows(w.view2d, fovea)
        w._on_action("fit")
        # the next photo: both panes on its own macula and disc
        w._on_action("next")
        app.processEvents()
        row = w.current
        assert roi_d.rect().contains(QPointF(row["disc_x"], row["disc_y"]))
        if row["fovea_x"] is not None:
            assert roi_m.rect().contains(QPointF(row["fovea_x"], row["fovea_y"]))

        # -- the view switch: 다중 보기 · 3D · back --
        w.view_buttons["multi"].click()
        assert w._tab() == "multi" and w.view_buttons["multi"].isChecked()
        w.view_buttons["3d"].click()
        assert w._tab() == "3d" and w.view_buttons["3d"].isChecked()
        w._on_action("view3d")                                           # the toolbar's 3D again: back
        assert w._tab() == "all" and w.view_buttons["all"].isChecked()
        assert _inside(w.view2d, w.page_all) and roi_d.isVisible()
        # whatever led to 검토 · 2D 보기 · 비교 stays on 모두 보기
        for key in ("review", "2d", "cmp"):
            w._go(key)
            assert w._tab() == "all"
        # 보기 menu: Ctrl+1~3 for the three views, Ctrl+0 the patient list
        acts = {a.text(): a.shortcut().toString() for a in w.findChildren(type(w.acts["fit"]))
                if a.text() in ("모두 보기", "다중 보기", "3D", "2D 보기", "비교", "검토", "3D 안구", "환자 목록")
                and not a.shortcut().isEmpty()}
        assert acts == {"모두 보기": "Ctrl+1", "다중 보기": "Ctrl+2", "3D": "Ctrl+3", "환자 목록": "Ctrl+0"}
        assert w.acts["view3d"].text() == "3D"
    finally:
        w.close()
        db.close()


def test_a_photo_without_macula_or_disc_says_so(tmp_path, demo_dir, import_and_wait):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w, db = _window(tmp_path, demo_dir)
    try:
        w.resize(1500, 950)
        w.show()
        import_and_wait(app, w, [demo_dir])
        row = db.images_for_patient(db.find_patient("20260115001")["id"])[0]
        db.update_image(row["id"], disc_x=None, disc_y=None, fovea_x=None, fovea_y=None)
        w._select_patient_ref(row["patient_ref"])
        w._go("all")
        w.thumbs.setCurrentRow(0)
        app.processEvents()
        if w.current["fovea_x"] is None:                       # (not found again when shown)
            assert "찾지 못함" in w.ov_heads["macula"].text()
        if w.current["disc_x"] is None:
            assert "찾지 못함" in w.ov_heads["zoom"].text()
        assert w.ov_macula.has_image() and w.ov_zoom.has_image()      # the centre of the photo instead
    finally:
        w.close()
        db.close()


def test_patient_line_in_a_narrow_window_settles(tmp_path, demo_dir):
    """A long patient line in a narrow window is cut to the room left by the menus, once: laying the
    menu bar out again must not set off another fit (it grew a pixel at a time and hung — Windows)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    w, db = _window(tmp_path, demo_dir)
    try:
        w.show()
        if not w._line_in_menubar:
            pytest.skip("the menu bar is the system's (macOS): the patient line is above the photo")
        calls = []
        fit = w._fit_banner
        w._fit_banner = lambda: (calls.append(1), len(calls) < 500 and fit())
        mb = w.menuBar()
        for width in (1500, 1100, 900, 800):
            calls.clear()
            w.resize(width, 800)
            app.processEvents()
            w.banner.setText("아주아주 긴 이름의 환자  ·  PID20260310-0A1B2C3D  ·  1960-01-01 (66세)  ·  남성")
            w._fit_banner()
            app.processEvents()
            assert len(calls) < 20, f"{width}: the patient line kept laying the menu bar out"
            menus = mb.actionGeometry([a for a in mb.actions() if a.isVisible()][-1]).right()
            assert w.top_w.geometry().right() <= mb.width()        # never past the window's edge
            if w.top_w.want <= mb.width() - menus - 40:
                assert w.top_w.geometry().left() >= menus         # cut to the room beside the menus
            else:   # not even the buttons fit beside the menus (wider fonts, 900 px): the line is at
                shortest = w.top_w.want                           # its smallest, no room for the name;
                w.banner.setText("")                              # the menus that do not fit go to »
                w._fit_banner()
                assert w.top_w.want == shortest
    finally:
        w.close()
        db.close()
