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
        w._on_action("chan:redfree")
        assert w._channel == "redfree"
        # G 필터 ▾ 녹색 + RNFL 강화 (광각 분석의 레드프리 0.9): the G 필터 lit; it again: colour
        labels = [a.text() for a in w.menus["chan:green"].actions()]
        assert labels[0].startswith("녹색 성분만") and "RNFL" in labels[1]
        w._on_action("chan:rnfl")
        assert w._channel == "rnfl" and w.acts["chan:green"].isChecked() and not w.acts["chan:redfree"].isChecked()
        shown = w.view2d._rgb
        h, wd = shown.shape[:2]
        mid = shown[h // 3:2 * h // 3, wd // 3:2 * wd // 3]
        assert (mid[..., 0] == mid[..., 2]).all() and (mid[..., 0] == mid[..., 1]).all()   # grey on the retina
        w._on_action("chan:green", False)                               # the lit G 필터 clicked again
        assert w._channel == "rgb" and not w.acts["chan:green"].isChecked()
        # 설정 → 일반: the G 필터 button gives one of its two pictures (처음 설정: 녹색 성분만), and RNFL 강화
        # is as strong as set there (0.5 … 0.9) — the ▾ says it, a photo shown with it is drawn again
        from fundusview import imaging
        from fundusview.ui.dialogs import SettingsDialog

        def settings(mode, k):
            def ok(dlg):
                assert dlg.rnfl_strength.minimum() == 0.5 and dlg.rnfl_strength.maximum() == 0.9
                assert [dlg.green_filter.itemData(i) for i in range(dlg.green_filter.count())] == ["green", "rnfl"]
                dlg.green_filter.setCurrentIndex(dlg.green_filter.findData(mode))
                dlg.rnfl_strength.setValue(k)
                return True
            monkeypatch.setattr(SettingsDialog, "exec", ok)
            w._open_settings()

        assert s.green_filter == "green" and s.rnfl_strength == 0.9 and "(0.9)" in labels[1]
        w._on_action("chan:green", True)                                # the button: the green channel alone
        assert w._channel == "green"
        w._on_action("chan:green", False)
        try:
            settings("rnfl", 0.5)
            assert s.green_filter == "rnfl" and s.rnfl_strength == 0.5 and imaging.rnfl_k() == 0.5
            assert Settings.load().green_filter == "rnfl" and Settings.load().rnfl_strength == 0.5
            assert "(0.5)" in w.menus["chan:green"].actions()[1].text()
            w._on_action("chan:green", True)                            # the button now: RNFL 강화, at 0.5
            assert w._channel == "rnfl" and w.acts["chan:green"].isChecked()
            weak = w.view2d._rgb.copy()
            w._on_action("chan:green")                                  # (its ▾ still gives the plain green)
            assert w._channel == "green"
            w._on_action("chan:rnfl")
            settings("rnfl", 0.9)                                       # stronger: the photo shown is drawn again
            assert imaging.rnfl_k() == 0.9 and (w.view2d._rgb != weak).any()
            w._on_action("chan:green", False)                           # the lit button again: colour
            assert w._channel == "rgb"
            settings("green", 3.0)                                      # (never past 0.9)
            assert s.green_filter == "green" and s.rnfl_strength == 0.9
        finally:
            imaging.set_rnfl_k(imaging.RNFL_K)
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
