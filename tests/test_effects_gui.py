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
        assert not w.c_relief3d.isChecked() and eye.relief == 0.0        # off from the start: the photo as taken
        w.c_relief3d.setChecked(True)
        assert eye.relief == w.RELIEF and s.relief3d is True
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
        # 망막 입체: 표면 높낮이 off from the start — the original photo, smooth on the retina
        assert not w.c_surface3d.isChecked() and not eye.relief_on and not eye.relief_sheet_on()
        assert not w.s_height3d.isEnabled() and s.surface3d is False
        w.c_surface3d.setChecked(True)                    # switched on: its height on the slider
        assert eye.relief_on and eye._hmap is not None and s.surface3d is True      # (the heights, from the photo)
        assert w.s_height3d.isEnabled()
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
        # 사진 card (as the web page): the photo with its disc and macula, where they came from
        row = w.current
        assert w.photo3d._pix is not None and w.photo3d.disc is not None
        assert "자동으로 찾음" in w.lbl_found3d.text() and w.c_autofind3d.isChecked()
        assert w.c_device3d.currentData() == "reticam" and w.c_eye3d.currentData() in ("OD", "OS", "auto")
        disc0 = (row["disc_x"], row["disc_y"])
        w.b_mark_disc.click()                                 # 유두 지정: a click on the photo marks it
        assert w.photo3d.picking == "disc" and w.lbl_mark3d.isVisible()
        p = w.photo3d.to_widget(disc0[0] + 30.0, disc0[1])
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(p), QPointF(p), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        w.photo3d.mousePressEvent(ev)
        assert w.photo3d.picking is None and not w.b_mark_disc.isChecked()
        assert w.current["disc_x"] == pytest.approx(disc0[0] + 30.0, abs=3.0) and "유두 직접 지정" in w.lbl_found3d.text()
        w.c_autofind3d.setChecked(False)                      # only marked places: the disc stays, the macula goes
        assert eye._marks[0] is not None and eye._marks[1] is None and s.autofind3d is False
        w.b_redetect3d.click()                                # 다시 찾기: the hand marks dropped, found again
        assert w.c_autofind3d.isChecked() and "유두 자동으로 찾음" in w.lbl_found3d.text()
        assert w.current["disc_x"] == pytest.approx(disc0[0], abs=4.0)
        w._on_device3d("generic")                             # 장비: its field of view and projection
        assert w.sp_fov.value() == 45.0 and w.c_proj.currentData() == "perspective"
        w._on_device3d("reticam")
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
    assert (s.smooth_motion, s.auto_rotate3d, s.glass3d) == (True, True, 80)
    assert (s.surface3d, s.relief3d) == (False, False)      # 3D: the photo as taken until 망막 입체 is switched on
    assert s.view3d_detail == "detailed"


def test_3d_shows_the_original_photo_until_relief_is_switched_on(app, tmp_path):
    """표면 높낮이 and 입체 조명 are off from the start. A settings file of the earlier look (they were on
    by default) adopts that once; switching them on afterwards is kept."""
    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    def open_window(s):
        w = MainWindow(s, Database(tmp_path / "lib" / "fundus.db"))
        try:
            return (w.c_surface3d.isChecked(), w.c_relief3d.isChecked(), w.eye3d.relief_on, w.eye3d.relief,
                    w.s_height3d.isEnabled())
        finally:
            w.close()

    # a settings file written by the look before (UI version 3: 표면 높낮이 · 입체 조명 on, 공막 투명도 chosen)
    old = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False,
                   ui_version=3, surface3d=True, relief3d=True, glass3d=40, view3d_detail="simple")
    assert open_window(old) == (False, False, False, 0.0, False)
    assert (old.ui_version, old.surface3d, old.relief3d) == (MainWindow.UI_VERSION, False, False)
    assert (old.glass3d, old.view3d_detail) == (40, "simple")          # nothing else of theirs is touched

    # switched on by the user afterwards: kept at the next start
    old.surface3d, old.relief3d = True, True
    assert open_window(old) == (True, True, True, MainWindow.RELIEF, True)
    assert (old.surface3d, old.relief3d) == (True, True)

    # a first start (no settings file yet)
    new = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False)
    assert open_window(new) == (False, False, False, 0.0, False)
    assert (new.view3d_detail, new.auto_rotate3d, new.glass3d, new.autofind3d) == ("detailed", True, 80, True)
