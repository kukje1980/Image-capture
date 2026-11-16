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
        # the settings beside the eye are put away until [설정] (or 설정 → 3D 보기 설정…) opens them
        assert not w.inspector.isVisible() and s.panel3d is False
        w.b_inspector.click()
        assert w.inspector.isVisible() and s.panel3d is True
        w.b_inspector.click()
        assert not w.inspector.isVisible() and s.panel3d is False
        w._open_3d_settings()
        assert w.inspector.isVisible() and w.b_inspector.isChecked()
        # the wheel over the eye (outside) sets 깊이 — forward cuts deeper — and leaves the zoom alone
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent

        def wheel(notches, mods=Qt.KeyboardModifier.NoModifier):
            pos = QPointF(eye.width() / 2, eye.height() / 2)
            eye.wheelEvent(QWheelEvent(pos, QPointF(eye.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                       QPoint(0, int(notches * 120)), Qt.MouseButton.NoButton, mods,
                                       Qt.ScrollPhase.NoScrollPhase, False))

        eye.reset_view()
        cut0, mag0 = w.s_cut.value(), eye.magnification
        wheel(2)
        assert w.s_cut.value() == cut0 - 8 and eye.cut == pytest.approx((cut0 - 8) / 100.0)
        wheel(-3)
        assert w.s_cut.value() == cut0 + 4 and eye.magnification == pytest.approx(mag0)
        wheel(-100)                                        # the end of the slider: the closed eye
        assert w.s_cut.value() == 100 and eye.cut == 1.0
        w.s_cut.setValue(cut0)
        # 확대 바: the magnification on a logarithmic bar, both ways
        assert w.s_zoom3d.value() == 0 and w.lbl_zoom3d.text() == "배율 ×1.0"
        w.s_zoom3d.setValue(100)
        assert eye.magnification == pytest.approx(2.0, rel=0.02) and w.lbl_zoom3d.text() == "배율 ×2.0"
        w.s_zoom3d.setValue(-100)
        assert eye.magnification == pytest.approx(0.5, rel=0.02)
        eye.reset_view()
        assert w.s_zoom3d.value() == 0
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
        # 휠로 들어가기: [전안부 선택] (or a click on the cornea) — the wheel walks in, the chip says how
        look = s.view3d_detail
        w._set_3d_detail("simple", save=False)
        assert not w.b_walk.isChecked() and not eye.walk
        w.b_walk.click()
        assert eye.walk and eye.detail == "detailed" and s.view3d_detail == look   # (not saved as the look)
        assert w._where.isVisible() and w._where.text() == w.WALK_HINT
        eye.walk_by(15)                                       # (motion off: at once) in the anterior chamber
        assert w.s_journey.value() == 60 and "앞방" in w._where.text() and w.r_out.isChecked()
        eye.walk_by(20)                                       # to the retina: 내부
        assert eye.mode == "inside" and w.r_in.isChecked() and w.s_journey.value() == 100
        assert "망막" in w._where.text() and "휠" in w._where.text()
        eye.walk_by(-40)                                      # all the way out: still picked
        assert eye.mode == "outside" and w.s_journey.value() == 0 and w._where.text() == w.WALK_HINT
        assert eye.walk and w.b_walk.isChecked()
        w.b_walk.click()                                      # let go: the wheel zooms again
        assert not eye.walk and not w._where.isVisible()
        eye.set_walk(True)                                    # (a click on the cornea) the button follows
        assert w.b_walk.isChecked()
        eye.reset_view(animate=True)                          # another view lets it go
        assert not eye.walk and not w.b_walk.isChecked()
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


def test_3d_wheel_mode_is_chosen_in_the_settings(app, tmp_path, demo_dir, import_and_wait, monkeypatch):
    """마우스 휠 (3D 설정 · 설정 → 일반): what the wheel over the eye does — 깊이 (the cut's depth, the
    first setting), 확대 (toward the cursor) or 들어가기 (in from the cornea, without picking it first);
    Ctrl+wheel zooms in all of them. Whether a click on the cornea picks the way in (the wheel then walks
    in meanwhile) is a switch of its own. Both are remembered."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    from fundusview.config import Settings, config_dir
    from fundusview.db import Database
    from fundusview.ui.dialogs import SettingsDialog
    from fundusview.ui.main_window import MainWindow
    from test_motion import _screen

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0, watch_on_startup=False,
                 auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.resize(1500, 950)
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam"])
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        w.patient_list.hide()
        w._go("3d")
        app.processEvents()
        eye = w.eye3d

        def wheel(notches, mods=Qt.KeyboardModifier.NoModifier):
            pos = QPointF(eye.width() / 2, eye.height() / 2)
            eye.wheelEvent(QWheelEvent(pos, QPointF(eye.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                       QPoint(0, int(notches * 120)), Qt.MouseButton.NoButton, mods,
                                       Qt.ScrollPhase.NoScrollPhase, False))

        # 깊이: the first setting — the wheel cuts deeper, Ctrl+wheel zooms
        assert s.wheel3d == "depth" and s.walk_click3d is True
        assert eye.wheel_mode == "depth" and eye.pick_walk and w._wheel_buttons["depth"].isChecked()
        assert w.c_walkclick3d.isEnabled() and w.c_walkclick3d.isChecked()
        assert "자르는 깊이" in eye.toolTip() and "각막 클릭" in eye.toolTip() and "자르는 깊이" in w.keys3d.text()
        eye.reset_view()
        cut0, mag0 = w.s_cut.value(), eye.magnification
        wheel(2)
        assert w.s_cut.value() == cut0 - 8 and eye.magnification == pytest.approx(mag0)
        wheel(2, Qt.KeyboardModifier.ControlModifier)
        assert w.s_cut.value() == cut0 - 8 and eye.magnification > mag0
        w.s_cut.setValue(cut0)
        eye.reset_view()

        # 확대: the wheel zooms toward the cursor and leaves the depth alone
        w._wheel_buttons["zoom"].click()
        assert s.wheel3d == "zoom" and eye.wheel_mode == "zoom" and w._wheel_buttons["zoom"].isChecked()
        assert "확대" in w.lbl_wheel3d.text() and "휠</b> 커서 쪽으로 확대" in w.keys3d.text()
        mag0 = eye.magnification
        wheel(2)
        assert w.s_cut.value() == cut0 and eye.magnification > mag0
        eye.reset_view()

        # 들어가기: the wheel goes in from the cornea at once (no pick first), and back out; Ctrl+wheel zooms
        w._wheel_buttons["walk"].click()
        assert s.wheel3d == "walk" and eye.wheel_mode == "walk" and eye.pick_walk
        assert not w.c_walkclick3d.isEnabled() and not eye.walk          # (the switch does not matter here)
        assert "들어가기" in eye.toolTip() and "각막 클릭" not in eye.toolTip()
        mag0 = eye.magnification
        wheel(2, Qt.KeyboardModifier.ControlModifier)                     # Ctrl+wheel: zoom, no way in
        assert eye.magnification > mag0 and not eye.walk
        eye.reset_view()
        wheel(3)
        assert eye.walk and w.b_walk.isChecked() and eye.journey_j == pytest.approx(3 * eye.WALK_STEP)
        assert w.s_cut.value() == cut0                                    # (not the depth slider)
        wheel(-3)
        assert eye.journey_j == pytest.approx(0.0, abs=1e-6)
        # back to 깊이: the way picked by the wheel itself is let go — the wheel cuts again
        w._wheel_buttons["depth"].click()
        assert not eye.walk and not w.b_walk.isChecked() and eye.wheel_mode == "depth"
        eye.reset_view(animate=True)

        # 각막을 누르면 휠로 들어가기 — off: a click on the cornea picks nothing; on: it picks the way in
        front = _screen(eye, (0.0, 0.0, 0.6))
        assert eye.anterior_at(front)
        w.c_walkclick3d.setChecked(False)
        assert s.walk_click3d is False and not eye.pick_walk and "각막 클릭" not in eye.toolTip()
        eye._clicked(front)
        assert not eye.walk
        w.c_walkclick3d.setChecked(True)
        assert s.walk_click3d is True and eye.pick_walk
        eye._clicked(front)
        assert eye.walk and w.b_walk.isChecked()
        w.c_walkclick3d.setChecked(False)                                 # off while picked: let go
        assert not eye.walk

        # remembered — and 설정 → 일반 has the same two
        saved = Settings.load(config_dir() / "settings.json")
        assert saved.wheel3d == "depth" and saved.walk_click3d is False
        dlg = SettingsDialog(s, w)
        assert dlg.wheel3d.currentData() == "depth" and not dlg.walk_click3d.isChecked()
        assert [dlg.wheel3d.itemData(k) for k in range(dlg.wheel3d.count())] == ["depth", "zoom", "walk"]
        dlg.wheel3d.setCurrentIndex(dlg.wheel3d.findData("walk"))         # (들어가기: the switch does not matter)
        assert not dlg.walk_click3d.isEnabled()
        dlg.wheel3d.setCurrentIndex(dlg.wheel3d.findData("depth"))
        assert dlg.walk_click3d.isEnabled()

        def choose(self):
            self.wheel3d.setCurrentIndex(self.wheel3d.findData("zoom"))
            self.walk_click3d.setChecked(True)
            return 1

        monkeypatch.setattr(SettingsDialog, "exec", choose)
        w._open_settings()
        assert s.wheel3d == "zoom" and s.walk_click3d is True
        assert eye.wheel_mode == "zoom" and eye.pick_walk and w._wheel_buttons["zoom"].isChecked()
        assert w.c_walkclick3d.isChecked()
        # a window opened later starts with them
        w2 = MainWindow(Settings.load(config_dir() / "settings.json"), db)
        try:
            assert w2.eye3d.wheel_mode == "zoom" and w2._wheel_buttons["zoom"].isChecked()
        finally:
            w2.close()
    finally:
        w.close()
        db.close()
