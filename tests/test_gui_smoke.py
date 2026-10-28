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
        w.c_channel.setCurrentIndex(1)  # red-free
        w._apply_adjust()
        w._select_patient_ref(UNASSIGNED)
        assert w.thumbs.count() == 2
        w._set_compare(db.images_for_patient(ref)[0]["id"])
        assert all(v.has_image() for v in w.cmp_views)
    finally:
        w.close()
        db.close()
