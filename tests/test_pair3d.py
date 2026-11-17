"""두 장 3D (pair3d.py): [3D] on Simple with two photos puts both photos on 3D eyes side by side,
which turn and zoom together; [3D] again goes back to the photos."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_3d_on_the_two_photo_view_shows_both_eyes(tmp_path, demo_dir, import_and_wait):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_on_startup=False, auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        import_and_wait(app, w, [demo_dir])
        ref = db.find_patient("20260115001")["id"]            # one OD and one OS photo
        w._select_patient_ref(ref)
        w.show_simple()
        app.processEvents()
        assert w._tab() == "multi" and len(w._picks) == 2
        b3d = w.tb_cmd.widgetForAction(w.acts["view3d"])      # [3D] on the command toolbar
        w.eye3d.glass = 0.4                                   # the look of the 3D tab is taken over
        b3d.click()
        app.processEvents()
        pair = w.pair3d
        assert w._tab() == "3d2" and b3d.isChecked() and pair.image_ids == w._picks
        assert all(c.isVisible() for c in pair.cells) and all(e._rgba is not None for e in pair.eyes)
        eyes = {e.laterality for e in pair.eyes}
        assert eyes == {"OD", "OS"} and all(e.glass == pytest.approx(0.4) for e in pair.eyes)
        assert all(e.wheel_mode == "zoom" and e.detail == w.eye3d.detail for e in pair.eyes)
        assert all(("OD" in t or "OS" in t) for t in (lab.text() for lab in pair.labels))
        assert w._last_view == "multi"                        # where the 3D icon goes back to

        # zooming / turning one eye moves the other the same way (함께 움직이기)
        a, b = pair.eyes
        start = b.magnification
        a.interacted.emit()
        a.set_magnification(2.5)
        a.yaw += 40
        pair._sync()
        assert b.magnification == pytest.approx(a.magnification) and b.magnification > start * 1.5
        assert b.yaw == pytest.approx(a.yaw) and b.pitch == pytest.approx(a.pitch)
        b.interacted.emit()                                   # … and the other way round
        b.set_magnification(1.2)
        pair._sync()
        assert a.magnification == pytest.approx(b.magnification)
        pair.c_link.setChecked(False)                         # off: each on its own
        assert not pair._follow.isActive()
        pair.c_link.setChecked(True)
        pair.b_home.click()
        assert all(e.magnification == pytest.approx(1.0) for e in pair.eyes)

        b3d.click()                                           # 3D again: the two photos
        app.processEvents()
        assert w._tab() == "multi" and len(w._picks) == 2 and not b3d.isChecked()
        assert pair.image_ids == [] and all(e._rgba is None for e in pair.eyes)

        # one photo on screen (Detail): the 3D icon opens the 3D tab as before
        w._go("all")
        b3d.click()
        app.processEvents()
        assert w._tab() == "3d"
    finally:
        w.close()
        db.close()
