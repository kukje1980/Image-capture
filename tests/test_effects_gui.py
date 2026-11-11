"""Main window: photos are read ahead while browsing, and the 3D effects (사진 펼치기 · 입체 조명 ·
자동 회전 · 들어가기) and 보기 → 부드러운 움직임 do what their controls say."""
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
        # 사진 펼치기 ↔ 망막에 감기 (motion is off in tests: the end state at once)
        assert w.b_unwrap.text() == "사진 펼치기" and eye.unwrap == 0.0
        w.b_unwrap.click()
        assert eye.unwrap == 1.0 and (eye.yaw, eye.pitch) == (0.0, 0.0) and w.b_unwrap.text() == "망막에 감기"
        assert eye.mode == "outside" and eye.half == 0.0 and eye.cut == 0.25
        w.b_unwrap.click()
        assert eye.unwrap == 0.0 and (eye.yaw, eye.pitch) == (38.0, 18.0) and w.b_unwrap.text() == "사진 펼치기"
        # another view takes the photo back onto the retina
        w.b_unwrap.click()
        w.r_in.setChecked(True)                               # 내부: in through the pupil
        assert eye.mode == "inside" and eye.unwrap == 0.0 and w.b_unwrap.text() == "사진 펼치기"
        w.r_out.setChecked(True)
        assert eye.mode == "outside" and eye.dark == 0.0
        w.b_unwrap.click()
        w.c_view3d.setCurrentIndex(w.c_view3d.findData("section"))
        w._tween._finish()                                    # (the glide to the section: its end, not its first step)
        assert eye.unwrap == 0.0 and eye.half > 0.0
        w.b_unwrap.click()                                    # from 세로 단면: back to the opened eye first
        assert eye.unwrap == 1.0 and eye.half == 0.0 and w.c_view3d.currentData() == "front"
        w.b_unwrap.click()
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
