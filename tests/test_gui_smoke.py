"""Headless smoke test of the main window (no OpenGL: the 3D tab is never shown)."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_imports_and_lists(tmp_path, demo_dir, wait_imports):
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
        wait_imports(app, w)
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
        # 세로 단면: the slider sets how far the section plane cuts (0 = through the axis)
        eye = w.eye3d
        w.c_view3d.setCurrentIndex(w.c_view3d.findData("section"))
        w._tween._finish()
        assert eye.half == 1.0 and eye.cut == 1.0 and (w.s_cut.minimum(), w.s_cut.value()) == (0, 0)
        w.s_cut.setValue(40)
        assert eye.half == pytest.approx(0.6)
        w.c_xray3d.setChecked(True)                    # 망막 투시
        w._tween._finish()
        assert eye.xray == 1.0 and eye.half == pytest.approx(0.6)
        w.c_view3d.setCurrentIndex(w.c_view3d.findData("front"))
        w._tween._finish()
        assert eye.half == 0.0 and eye.cut == pytest.approx(0.25) and w.s_cut.minimum() == -30
        w.c_view3d.setCurrentIndex(w.c_view3d.findData("section"))
        w._tween._finish()
        assert w.s_cut.value() == 40                   # each way keeps its own depth
        # the photo next to the eye, with its slit; after the presentation the controls follow the eye
        w.c_fov3d.setChecked(True)
        assert eye.fov_alpha == 1.0 and eye.fov_ring == 1.0
        w.c_side3d.setChecked(True)
        assert not w.scan_photo.isHidden() and eye.black
        w._update_3d()
        assert w.scan_photo.has_image()
        eye.half, eye.xray = w._show.END_HALF, 1.0
        w._on_scan_finished()
        assert w.c_view3d.currentData() == "section" and w.s_cut.value() == 38 and w.c_xray3d.isChecked()
        w._show.start()                                # the user changes things while it plays
        w._show._timer.stop()
        w._show._timer.start()
        w.c_xray3d.setChecked(False)
        w._tween._finish()
        assert not w._show.active() and not w.c_xray3d.isChecked() and eye.xray == 0.0
        w._show.start()
        w.s_cut.setValue(70)
        assert not w._show.active() and w.s_cut.value() == 70 and eye.half == pytest.approx(0.3)
        w.c_side3d.setChecked(False)
        assert w.scan_photo.isHidden() and not eye.black
        w._select_patient_ref(UNASSIGNED)
        assert w.thumbs.count() == 2
        w._set_compare(db.images_for_patient(ref)[0]["id"])
        assert all(v.has_image() for v in w.cmp_views)
    finally:
        w.close()
        db.close()
