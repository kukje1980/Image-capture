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
        # the wheel over the eye zooms from the start and leaves the depth alone (that is the 깊이 막대's)
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent

        def wheel(notches, mods=Qt.KeyboardModifier.NoModifier):
            pos = QPointF(eye.width() / 2, eye.height() / 2)
            eye.wheelEvent(QWheelEvent(pos, QPointF(eye.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                       QPoint(0, int(notches * 120)), Qt.MouseButton.NoButton, mods,
                                       Qt.ScrollPhase.NoScrollPhase, False))

        eye.reset_view()
        cut0, mag0 = w.s_cut.value(), eye.magnification
        assert s.wheel3d == "zoom" and eye.wheel_mode == "zoom"
        wheel(2)
        assert w.s_cut.value() == cut0 and eye.magnification > mag0
        eye.reset_view()
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
    assert new.wheel3d == "zoom"

    # UI version 4: the wheel was 깊이 — it zooms now (the depth has its bar), once; 망막 입체 as they had it
    v4 = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False,
                  ui_version=4, wheel3d="depth", surface3d=True, relief3d=True)
    assert open_window(v4) == (True, True, True, MainWindow.RELIEF, True)
    assert (v4.ui_version, v4.wheel3d) == (MainWindow.UI_VERSION, "zoom")
    v4.wheel3d = "depth"                                               # chosen again afterwards: kept
    open_window(v4)
    assert v4.wheel3d == "depth"


def test_3d_depth_bar_beside_the_eye(app, tmp_path, demo_dir, import_and_wait):
    """깊이 막대: a vertical bar over the eye's right edge sets the depth of the cut — drag it (top: 닫힘,
    down: deeper), press on it, or turn the wheel over it. It is the 깊이 slider of the settings panel shown
    where the eye is: one value, its range (세로 단면: down to 절반), and only while outside the eye."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui import depth_bar
    from fundusview.ui.main_window import MainWindow

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
        eye, bar = w.eye3d, w.depth_bar
        # on the eye, at its right edge, half way down; it says what the depth is
        assert bar.parentWidget() is eye and bar.isVisible()
        g = bar.geometry()
        assert g.right() == eye.width() - depth_bar.MARGIN - 1 and abs(g.center().y() - eye.height() // 2) <= 1
        assert w.s_cut.value() == 25 and bar.text() == f"{round(100 * 75 / 130)}%" and bar.bottom_text == "깊게"
        # dragged to the top: the closed eye; to the bottom: the deepest cut — the eye follows
        x = g.width() // 2
        y0, y1 = bar._track()
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, round(bar.handle_y())))
        QTest.mouseMove(bar, QPoint(x, int(y0) - 30))
        assert w.s_cut.value() == 100 and eye.cut == 1.0 and bar.text() == "닫힘"
        QTest.mouseMove(bar, QPoint(x, int(y1) + 30))
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, int(y1) + 30))
        assert w.s_cut.value() == -30 and eye.cut == pytest.approx(-0.3) and bar.text() == "100%"
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(x, round((y0 + y1) / 2)))          # a press half way: half the depth
        assert w.s_cut.value() == 35 and bar.handle_y() == pytest.approx((y0 + y1) / 2, abs=2)

        def wheel(notches):
            pos = QPointF(x, (y0 + y1) / 2)
            bar.wheelEvent(QWheelEvent(pos, QPointF(bar.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                       QPoint(0, int(notches * 120)), Qt.MouseButton.NoButton,
                                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))

        mag = eye.magnification
        wheel(-2)                                                    # down: deeper (the handle goes down)
        assert w.s_cut.value() == 27 and eye.magnification == pytest.approx(mag)
        wheel(3)
        assert w.s_cut.value() == 39
        w.s_cut.setValue(25)                                         # the panel's slider moves the bar
        assert bar.fraction() == pytest.approx(75 / 130)
        # 세로 단면: from closed down to through the axis (절반)
        w._view_buttons["section"].click()
        w._tween._finish()
        assert bar.bottom_text == "절반" and (w.s_cut.minimum(), w.s_cut.value()) == (0, 0) and bar.text() == "100%"
        w._view_buttons["front"].click()
        w._tween._finish()
        assert bar.bottom_text == "깊게" and w.s_cut.value() == 25
        # inside the eye there is no cut: no bar; outside again, the bar
        w.r_in.setChecked(True)
        app.processEvents()
        assert not bar.isVisible()
        w.r_out.setChecked(True)
        app.processEvents()
        assert bar.isVisible()
        # the window resized: the bar stays at the eye's right edge
        w.resize(1200, 800)
        app.processEvents()
        assert bar.geometry().right() == eye.width() - depth_bar.MARGIN - 1
    finally:
        w.close()
        db.close()


def test_3d_bars_float_lie_down_and_pick_the_wheel(app, tmp_path, demo_dir, import_and_wait):
    """깊이 막대 · 배율 막대 float over the 3D eye: a double click lays one down or stands it up, a drag by
    anything but its track moves it (remembered), the wheel over a bar does that bar's thing, and the bar
    whose ☑ 휠 is checked is what the wheel over the eye does (배율 at first)."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0, watch_on_startup=False,
                 auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier

    def wheel(widget, pos, notches):
        widget.wheelEvent(QWheelEvent(QPointF(pos), QPointF(widget.mapToGlobal(pos)), QPoint(0, 0),
                                      QPoint(0, int(notches * 120)), Qt.MouseButton.NoButton, none,
                                      Qt.ScrollPhase.NoScrollPhase, False))

    try:
        w.resize(1500, 950)
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam"])
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        w.patient_list.hide()
        w._go("3d")
        app.processEvents()
        eye, depth, zoom = w.eye3d, w.depth_bar, w.zoom_bar
        centre = QPoint(eye.width() // 2, eye.height() // 2)
        # at first: 배율 lying at the top left with its ☑ 휠 checked, 깊이 standing at the right
        assert zoom.parentWidget() is eye and zoom.isVisible() and not zoom.vertical() and depth.vertical()
        assert zoom.checked and not depth.checked and eye.wheel_mode == "zoom"
        assert zoom.width() > 3 * zoom.height() and zoom.geometry().left() < 40 and zoom.geometry().top() < 40
        # the wheel over the 배율 막대 magnifies, whatever the eye's wheel does; its handle drags too
        eye.reset_view()
        cut0 = w.s_cut.value()
        wheel(zoom, zoom.rect().center(), 2)
        assert eye.magnification > 1.1 and w.s_cut.value() == cut0 and zoom.text() == f"×{eye.magnification:.1f}"
        a, b = zoom._track()
        QTest.mouseClick(zoom, left, none, QPoint(int(b), zoom.height() // 2))       # its right end: the largest
        assert w.s_zoom3d.value() == w.s_zoom3d.maximum() and eye.magnification == pytest.approx(16.0, rel=0.03)
        eye.reset_view()
        # ☑ 휠 on the 깊이 막대: the wheel over the eye cuts deeper now — and it is remembered
        QTest.mouseClick(depth, left, none, depth._check_rect().center().toPoint())
        assert depth.checked and not zoom.checked and eye.wheel_mode == "depth" and s.wheel3d == "depth"
        assert w._wheel_buttons["depth"].isChecked()
        mag = eye.magnification
        wheel(eye, centre, 2)
        assert w.s_cut.value() < cut0 and eye.magnification == pytest.approx(mag)
        wheel(zoom, zoom.rect().center(), 1)                                         # (the 배율 막대 still magnifies)
        assert eye.magnification > mag
        QTest.mouseClick(zoom, left, none, zoom._check_rect().center().toPoint())    # back to 배율
        assert zoom.checked and not depth.checked and s.wheel3d == "zoom"
        QTest.mouseClick(zoom, left, none, zoom._check_rect().center().toPoint())    # (one of them stays checked)
        assert zoom.checked and eye.wheel_mode == "zoom"
        w._set_wheel3d("walk")                                                       # 들어가기: neither
        assert not zoom.checked and not depth.checked
        w._set_wheel3d("zoom")
        # a double click lays the 깊이 막대 down (the value as it was), another stands it up again
        cut = w.s_cut.value()
        QTest.mouseDClick(depth, left, none, QPoint(depth.width() // 2, 16))
        assert not depth.vertical() and depth.width() > 3 * depth.height() and s.depth_bar3d.startswith("h:")
        a, b = depth._track()
        QTest.mousePress(depth, left, none, QPoint(int(a) + 20, depth.height() // 2))       # on the track …
        QTest.mouseRelease(depth, left, none, QPoint(int(a) + 20, depth.height() // 2))
        assert w.s_cut.value() != cut
        w.s_cut.setValue(cut)
        QTest.mouseClick(depth, left, none, QPoint(int(b), depth.height() // 2))            # lying: the right end is 닫힘
        assert w.s_cut.value() == 100 and depth.text() == "닫힘"
        w.s_cut.setValue(cut)
        QTest.mouseDClick(depth, left, none, QPoint(int(a) + 20, depth.height() // 2))      # … a double click there
        assert depth.vertical() and w.s_cut.value() == cut                                  # leaves the depth alone
        # dragged by its title: it goes where it is put, stays inside the eye, and is remembered
        QTest.mousePress(zoom, left, none, QPoint(70, 14))
        QTest.mouseMove(zoom, QPoint(70 + 300, 14 + 200))
        QTest.mouseRelease(zoom, left, none, QPoint(70 + 300, 14 + 200))
        g = zoom.geometry()
        assert abs(g.left() - 314) <= 2 and abs(g.top() - 214) <= 2 and s.zoom_bar3d.startswith("h:")
        assert eye.rect().contains(g)
        QTest.mousePress(zoom, left, none, QPoint(70, 14))
        QTest.mouseMove(zoom, QPoint(70 + 5000, 14 + 5000))
        QTest.mouseRelease(zoom, left, none, QPoint(70 + 5000, 14 + 5000))
        assert eye.rect().contains(zoom.geometry()) and zoom.geometry().right() == eye.width() - 1
        w.resize(1200, 800)                                                          # still inside, at that corner
        app.processEvents()
        assert eye.rect().contains(zoom.geometry()) and zoom.geometry().right() == eye.width() - 1
        state = (s.depth_bar3d, s.zoom_bar3d)
    finally:
        w.close()
        db.close()
    # the next time: where they were left
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        assert (w.depth_bar.state(), w.zoom_bar.state()) == state and not w.zoom_bar.vertical()
    finally:
        w.close()
        db.close()


def test_3d_wheel_mode_is_chosen_in_the_settings(app, tmp_path, demo_dir, import_and_wait, monkeypatch):
    """마우스 휠 (3D 설정 · 설정 → 일반): what the wheel over the eye does — 확대 (toward the cursor, the
    first setting; the depth is on the 깊이 막대), 깊이 (the cut's depth) or 들어가기 (in from the cornea,
    without picking it first);
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

        # 확대: the first setting — the wheel zooms toward the cursor and leaves the depth alone (the 깊이 막대's)
        assert s.wheel3d == "zoom" and s.walk_click3d is True
        assert eye.wheel_mode == "zoom" and eye.pick_walk and w._wheel_buttons["zoom"].isChecked()
        assert w.c_walkclick3d.isEnabled() and w.c_walkclick3d.isChecked()
        assert "확대" in w.lbl_wheel3d.text() and "휠</b> 커서 쪽으로 확대" in w.keys3d.text()
        assert "깊이 막대" in eye.toolTip() and "각막 클릭" in eye.toolTip() and "깊이 막대" in w.keys3d.text()
        eye.reset_view()
        cut0, mag0 = w.s_cut.value(), eye.magnification
        wheel(2)
        assert w.s_cut.value() == cut0 and eye.magnification > mag0
        eye.reset_view()

        # 깊이: the wheel cuts deeper, Ctrl+wheel zooms
        w._wheel_buttons["depth"].click()
        assert s.wheel3d == "depth" and eye.wheel_mode == "depth" and w._wheel_buttons["depth"].isChecked()
        assert "자르는 깊이" in eye.toolTip() and "자르는 깊이" in w.keys3d.text()
        mag0 = eye.magnification
        wheel(2)
        assert w.s_cut.value() == cut0 - 8 and eye.magnification == pytest.approx(mag0)
        wheel(2, Qt.KeyboardModifier.ControlModifier)
        assert w.s_cut.value() == cut0 - 8 and eye.magnification > mag0
        wheel(-100)                                        # the end of the slider: the closed eye
        assert w.s_cut.value() == 100 and eye.cut == 1.0
        w.s_cut.setValue(cut0)
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

        # opened 15 % or more (the 깊이 막대 — the cornea, iris and lens left out): a click there is on the
        # retina — it picks no way in, the wheel goes on zooming; a way picked before is let go when opened
        front = _screen(eye, (0.0, 0.0, 0.6))
        w._wheel_buttons["zoom"].click()
        assert eye.opened() and not eye.anterior_at(front)
        eye._clicked(front)
        assert not eye.walk
        mag0 = eye.magnification
        wheel(2)
        assert eye.magnification > mag0 and not eye.walk
        eye.reset_view()
        w._wheel_buttons["depth"].click()
        w.s_cut.setValue(95)                                              # opened a little: the cornea is there
        assert not eye.opened()
        eye._clicked(front)
        assert eye.walk
        w.s_cut.setValue(cut0)                                            # opened far: let go
        assert not eye.walk and not w.b_walk.isChecked()
        w.s_cut.setValue(95)

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
        w.s_cut.setValue(cut0)

        # remembered — and 설정 → 일반 has the same two
        saved = Settings.load(config_dir() / "settings.json")
        assert saved.wheel3d == "depth" and saved.walk_click3d is False
        dlg = SettingsDialog(s, w)
        assert dlg.wheel3d.currentData() == "depth" and not dlg.walk_click3d.isChecked()
        assert [dlg.wheel3d.itemData(k) for k in range(dlg.wheel3d.count())] == ["zoom", "depth", "walk"]
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
