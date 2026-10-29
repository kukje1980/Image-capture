"""Headless smoke test of the main window (no OpenGL: the 3D tab is never shown)."""
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_imports_and_lists(tmp_path, demo_dir):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import UNASSIGNED, MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        w.service.import_paths([str(demo_dir)])
        deadline = time.time() + 30
        while (len(db.list_patients()) < 6 or db.count_unassigned() < 2) and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        settle = time.time() + 1.0  # results are coalesced on a 300 ms timer
        while time.time() < settle:
            app.processEvents()
            time.sleep(0.02)
        assert w.patients.rowCount() == 7  # 6 patients + 미분류
        ref = db.find_patient("20260115001")["id"]
        w._select_patient_ref(ref)
        assert w.thumbs.count() == 2 and w.current is not None
        assert w.view2d.has_image()
        assert "김민수" in w.banner.text()
        w._on_action("chan:redfree")
        assert w._channel == "redfree"
        # zooming: steps and wide-field regions from the 화면 맞춤 ▾ menu, the status-bar magnification
        w._on_action("zoom4")
        assert w.view2d.zoom == pytest.approx(4.0) and w.btn_zoom.text() == "배율 400%"
        w._on_action("region:posterior")
        assert w.view2d.zoomed_in() and w.view2d._nav.isVisible()
        w._on_action("fit")
        assert not w.view2d.zoomed_in() and w.btn_zoom.text().startswith("배율 맞춤")
        # 3D look: 간단히 by default, 자세히 remembered in the settings
        assert w.eye3d.detail == "simple" and not w.c_muscle.isEnabled()
        w.b_detailed.click()
        assert w.eye3d.detail == "detailed" and w.c_muscle.isEnabled()
        assert Settings.load().view3d_detail == "detailed"
        w.b_simple.click()
        assert w.eye3d.detail == "simple" and Settings.load().view3d_detail == "simple"
        w._select_patient_ref(UNASSIGNED)
        assert w.thumbs.count() == 2
        w._set_compare(db.images_for_patient(ref)[0]["id"])
        assert all(v.has_image() for v in w.cmp_views)
    finally:
        w.close()
        db.close()
