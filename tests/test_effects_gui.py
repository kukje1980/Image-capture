"""Main window: photos are read ahead while browsing, and the 3D effects (망막 입체 · 단순하게 보기 ·
입체 조명 · 자동 회전 · 들어가며 보기 · 슬릿 방향) and 보기 → 부드러운 움직임 do what their controls say."""
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_browsing_reads_ahead_and_effects_follow_their_controls(app, tmp_path, demo_dir, import_and_wait):
    from PySide6.QtCore import Qt

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui import motion
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    was = motion.enabled()
    try:
        w.resize(1500, 950)
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam"])
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        app.processEvents()
        ids = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.thumbs.count())]
        assert len(ids) == 3
        # -- reading ahead: showing the middle photo brings its two neighbours into memory
        w._go("2d")                                           # (모두 보기 reads its four photos itself)
        w.thumbs.setCurrentRow(0)
        app.processEvents()
        w._preload_timer.stop()
        _wait(app, lambda: not w._preloader._busy)
        w._cache.clear()
        w.thumbs.setCurrentRow(1)
        assert w.current["id"] == ids[1] and set(w._cache) == {ids[1]}
        assert _wait(app, lambda: {ids[0], ids[2]} <= set(w._cache))
        assert next(reversed(w._cache)) == ids[1]            # the photo on screen stays the newest
        before = {k: id(v) for k, v in w._cache.items()}
        w.thumbs.setCurrentRow(2)                             # stepping on: no file is read again
        assert id(w._load(db.get_image(ids[2]))) == before[ids[2]]
        # -- 3D effects
        eye = w.eye3d
        w._go("3d")
        app.processEvents()
        assert w.c_relief3d.isChecked() and eye.relief == w.RELIEF       # on from the start
        w.c_relief3d.setChecked(False)
        assert eye.relief == 0.0 and s.relief3d is False
        w.c_relief3d.setChecked(True)
        # 자동 회전: on from the start, turning in the 3D tab only
        assert w.c_spin3d.isChecked() and eye.auto_rotate == w.SPIN
        w.c_spin3d.setChecked(False)
        assert eye.auto_rotate == 0.0 and s.auto_rotate3d is False
        w.c_spin3d.setChecked(True)
        assert eye.auto_rotate == w.SPIN and s.auto_rotate3d is True
        w._go("2d")
        assert eye.auto_rotate == 0.0
        w._go("3d")
        assert eye.auto_rotate == w.SPIN
        w.c_spin3d.setChecked(False)
        # 공막 투명도: the glass sclera
        assert eye.glass == pytest.approx(0.8) and w.s_glass.value() == 80
        w.s_glass.setValue(0)
        assert eye.glass == 0.0 and s.glass3d == 0
        w.s_glass.setValue(60)
        assert eye.glass == pytest.approx(0.6) and s.glass3d == 60
        # the two opening modes are one choice, shown by its segments
        assert w._view_buttons["front"].isChecked() and w.c_view3d.currentData() == "front"
        w._view_buttons["section"].click()
        w._tween._finish()
        assert w.c_view3d.currentData() == "section" and eye.half > 0.0
        w._view_buttons["front"].click()
        w._tween._finish()
        assert w.c_view3d.currentData() == "front" and eye.half == 0.0
        # the settings beside the eye can be put away
        assert w.inspector.isVisible()
        w.b_inspector.click()
        assert not w.inspector.isVisible()
        w.b_inspector.click()
        # 망막 입체: 표면 높낮이 on from the start, its height on the slider
        assert w.c_surface3d.isChecked() and eye.relief_on and eye._hmap is not None      # (the heights, from the photo)
        assert eye.relief_amount == pytest.approx(s.surface_height3d / 100.0 * w.HEIGHT_MAX)
        w.s_height3d.setValue(80)
        assert eye.relief_amount == pytest.approx(0.8 * w.HEIGHT_MAX) and s.surface_height3d == 80
        w.c_surface3d.setChecked(False)
        assert not eye.relief_on and not eye.relief_sheet_on() and s.surface3d is False and not w.s_height3d.isEnabled()
        w.c_surface3d.setChecked(True)
        # 단순하게 보기 (motion off in tests: at once)
        motion.set_enabled(False)
        assert not w.c_simple3d.isChecked() and eye.simple == 0.0
        w.c_simple3d.setChecked(True)
        assert eye.simple == 1.0 and s.simple3d is True
        w.c_simple3d.setChecked(False)
        assert eye.simple == 0.0
        # 사진 펼치기 is gone
        assert not hasattr(w, "b_unwrap") and not hasattr(eye, "unwrap")
        # 들어가며 보기: in through the pupil to the retina, and back out (at once with motion off)
        assert w.b_journey.text() == "▶ 들어가기" and w.s_journey.value() == 0
        w.b_journey.click()
        assert eye.mode == "inside" and w.r_in.isChecked() and w.s_journey.value() == 100
        assert w.b_journey.text() == "◀ 나오기" and eye.dark == 0.0
        w.b_journey.click()
        assert eye.mode == "outside" and w.r_out.isChecked() and w.s_journey.value() == 0
        w.s_journey.setValue(62)                              # stopped in the anterior chamber
        assert eye.mode == "outside" and eye.journey_j == pytest.approx(0.62) and eye.dist < 1.12
        assert w._where.isVisible() and "앞방" in w._where.text()
        eye.reset_view(animate=True)                          # 처음 시점: an ordinary view takes over
        assert not eye.journey_on() and eye.out_fov == 38.0 and eye.cut == pytest.approx(0.25)
        # 슬릿 스캔: the way of the slit, remembered
        assert w._show.direction == "down" and w._slit_buttons["down"].isChecked()
        w._slit_buttons["right"].click()
        assert w._show.direction == "right" and s.slit_dir3d == "right" and "망막 위로" in w.lbl_slit.text()
        w._slit_buttons["all"].click()
        assert w._show.passes() == ("down", "up", "right", "left")
        w._slit_buttons["down"].click()
        motion.set_enabled(True)
        # -- 보기 → 부드러운 움직임
        assert w.act_smooth.isChecked() and s.smooth_motion is True
        w.act_smooth.setChecked(False)
        assert not motion.enabled() and s.smooth_motion is False
        w.act_smooth.setChecked(True)
        assert motion.enabled() and s.smooth_motion is True
        assert w.view2d.crossfade
    finally:
        motion.set_enabled(was)
        w.close()


def test_smooth_motion_setting_is_kept(tmp_path):
    from fundusview.config import Settings

    s = Settings(library_dir=str(tmp_path / "lib"))
    assert (s.smooth_motion, s.relief3d, s.auto_rotate3d, s.glass3d) == (True, True, True, 80)
    assert s.view3d_detail == "detailed"
