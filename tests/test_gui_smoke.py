"""Headless smoke test of the main window (no OpenGL: the 3D tab is never shown)."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_imports_and_lists(tmp_path, demo_dir, import_and_wait, monkeypatch):
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
        import_and_wait(app, w, [demo_dir])
        assert w.patient_list.table.rowCount() == 7  # 6 patients + 미분류
        ref = db.find_patient("20260115001")["id"]
        w._select_patient_ref(ref)
        assert w.thumbs.count() == 2 and w.current is not None
        assert w.view2d.has_image()
        assert "김민수" in w.banner.text()
        # Red-free: the green channel with RNFL 강화 at 0.9 (광각 분석의 레드프리) — grey; it again: colour
        from fundusview import imaging
        from fundusview.ui.dialogs import SettingsDialog

        orig = w.view2d._rgb.copy()
        w._on_action("chan:redfree", True)
        assert w._channel == "redfree" and w.acts["chan:redfree"].isChecked() and not w.acts["chan:green"].isChecked()
        shown = w.view2d._rgb
        h, wd = shown.shape[:2]
        mid = shown[h // 3:2 * h // 3, wd // 3:2 * wd // 3]
        assert (mid[..., 0] == mid[..., 2]).all() and (mid[..., 0] == mid[..., 1]).all()   # grey on the retina
        assert imaging.RNFL_K == 0.9 and (shown == imaging.rnfl_green(orig, 0.9)).all()
        w._on_action("chan:redfree", False)                             # the lit Red-free clicked again
        assert w._channel == "rgb" and not w.acts["chan:redfree"].isChecked()
        # the G 필터: the green channel alone, as it is (no ▾, nothing in 설정 to turn it into another picture)
        assert "chan:green" not in w.menus and "RNFL" not in w.acts["chan:green"].toolTip()
        w._on_action("chan:green", True)
        assert w._channel == "green" and w.acts["chan:green"].isChecked() and not w.acts["chan:redfree"].isChecked()
        assert (w.view2d._rgb[..., 0] == orig[..., 1]).all() and (w.view2d._rgb != shown).any()
        w._on_action("chan:green", False)
        assert w._channel == "rgb"
        dlg = SettingsDialog(s, w)
        assert not hasattr(dlg, "green_filter") and not hasattr(dlg, "rnfl_strength")
        dlg.deleteLater()
        # 설정 → 일반 → 3D 입체 한 장 추정: 녹내장 분석 → 3D 입체 opens on it (처음 설정: 하이브리드)
        assert s.disc3d_method == "hybrid" and w._build_glaucoma()[0].surface.method == "hybrid"

        def disc3d_method(method):
            def ok(dlg):
                items = [dlg.disc3d_method.itemData(i) for i in range(dlg.disc3d_method.count())]
                assert items == ["hybrid", "vessels", "pallor"] and dlg.disc3d_method.currentData() == s.disc3d_method
                dlg.disc3d_method.setCurrentIndex(dlg.disc3d_method.findData(method))
                return True
            monkeypatch.setattr(SettingsDialog, "exec", ok)
            w._open_settings()

        try:
            disc3d_method("vessels")
            assert s.disc3d_method == "vessels" and Settings.load().disc3d_method == "vessels"
            dlg, _ = w._build_glaucoma()
            assert dlg.surface.method == "vessels" and dlg.surface.methods.key() == "vessels"
            dlg.close()
        finally:
            disc3d_method("hybrid")
        assert Settings.load().disc3d_method == "hybrid"
        # … 3D 입체 두 장 스테레오: the stereo depth opens on it (처음 설정: 시차 + 혈관 꺾임)
        assert s.disc3d_stereo_method == "parallax_vessels"
        assert w._build_glaucoma()[0].surface.stereo_method == "parallax_vessels"

        def stereo_method(method):
            def ok(dlg):
                items = [dlg.disc3d_stereo_method.itemData(i) for i in range(dlg.disc3d_stereo_method.count())]
                assert items == ["parallax_vessels", "parallax"]
                assert dlg.disc3d_stereo_method.currentData() == s.disc3d_stereo_method
                dlg.disc3d_stereo_method.setCurrentIndex(dlg.disc3d_stereo_method.findData(method))
                return True
            monkeypatch.setattr(SettingsDialog, "exec", ok)
            w._open_settings()

        try:
            stereo_method("parallax")
            assert s.disc3d_stereo_method == "parallax" and Settings.load().disc3d_stereo_method == "parallax"
            assert s.disc3d_method == "hybrid"                          # (the one-photo setting as it was)
            dlg, _ = w._build_glaucoma()
            assert dlg.surface.stereo_method == "parallax"
            dlg.close()
        finally:
            stereo_method("parallax_vessels")
        assert Settings.load().disc3d_stereo_method == "parallax_vessels"
        w._on_action("chan:redfree")
        # zooming: steps and wide-field regions from the 화면 맞춤 ▾ menu, the status-bar magnification
        w._on_action("zoom4")
        assert w.view2d.zoom == pytest.approx(4.0) and w.btn_zoom.text() == "배율 400%"
        w._on_action("region:posterior")
        assert w.view2d.zoomed_in() and w.view2d._nav.isVisible()
        w._on_action("fit")
        assert not w.view2d.zoomed_in() and w.btn_zoom.text().startswith("배율 맞춤")
        # 3D look: 자세히 from the start (with the glass sclera), as the web page; 간단히 | 자세히 in the bar
        assert w.eye3d.detail == "detailed" and w.c_muscle.isEnabled()
        assert w.eye3d.glass == pytest.approx(0.8) and not hasattr(w, "b_simple")
        w._set_3d_detail("simple")
        assert w.eye3d.detail == "simple" and not w.c_muscle.isEnabled()
        assert Settings.load().view3d_detail == "simple"
        w._set_3d_detail("detailed")
        assert w.eye3d.detail == "detailed" and Settings.load().view3d_detail == "detailed"
        w._set_3d_detail("simple")
        assert w.eye3d.detail == "simple" and Settings.load().view3d_detail == "simple"
        assert w._detail_buttons["simple"].isChecked()          # the bar shows the look, and sets it
        w._detail_buttons["detailed"].click()
        assert w.eye3d.detail == "detailed" and Settings.load().view3d_detail == "detailed"
        w._detail_buttons["simple"].click()
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
        assert len(w._listed) == 2                    # (the photo list: the newest exam's bookmark)
        w._set_compare(db.images_for_patient(ref)[0]["id"])
        tab = w._tab()
        assert w.compare is not None and w._tab() == tab             # the ② pick; the view stays
    finally:
        w.close()
        db.close()
