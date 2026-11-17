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


def test_3d_with_more_photos_picked_asks_one_or_all(tmp_path, demo_dir, import_and_wait, monkeypatch):
    """[3D] with several photos picked — on Multi (16장), or more than two on Simple — asks: the photo
    being looked at (the 3D view), or all of them, each on its own 3D eye (2 × 2, 2 × 3, 3 × 3 — up to
    nine), moving together. [3D] again goes back where it came from. Simple's two go to 3D at once."""
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow
    from fundusview.ui.pair3d import MAX_EYES, grid_shape

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_on_startup=False, auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    asked = []
    answer = ["all"]
    monkeypatch.setattr(w, "_ask_3d_which", lambda n: (asked.append(n), answer[0])[1])
    try:
        w.show()
        import_and_wait(app, w, [demo_dir])
        ref = max((p["id"] for p in db.list_patients()), key=lambda r: len(db.images_for_patient(r)))
        w._select_patient_ref(ref)
        app.processEvents()
        photos = [r["id"] for r in db.images_for_patient(ref)]
        assert len(photos) >= 3
        b3d = w.tb_cmd.widgetForAction(w.acts["view3d"])

        # Multi (16장) with three picked: asked; all — three eyes, 2 × 2, the picked ones in order
        w.tb_cmd.widgetForAction(w.acts["view:multi"]).click()
        for iid in photos[:3]:
            w.grid.pressed.emit(iid)
        assert w._tab() == "grid" and w.picks() == photos[:3]
        b3d.click()
        app.processEvents()
        pair = w.pair3d
        assert asked == [3] and w._tab() == "3d2" and pair.image_ids == photos[:3]
        assert all(c.isVisible() for c in pair.cells[:3]) and not any(c.isVisible() for c in pair.cells[3:])
        assert len(pair.eyes) == 3                                    # (eyes are made as photos come)
        assert all(e._rgba is not None for e in pair.eyes[:3]) and grid_shape(3) == (2, 2)
        # … moving together: the eye moved leads, the other two follow
        a, b, c = pair.eyes[:3]
        b.interacted.emit()
        b.set_magnification(2.0)
        b.yaw += 30
        pair._sync()
        assert a.yaw == pytest.approx(b.yaw) and c.yaw == pytest.approx(b.yaw)
        assert c.magnification == pytest.approx(b.magnification)
        b3d.click()                                                   # [3D] again: back to Multi
        app.processEvents()
        assert w._tab() == "grid" and pair.image_ids == [] and w.picks() == photos[:3]

        # the photo being looked at: the 3D view
        answer[0] = "one"
        b3d.click()
        app.processEvents()
        assert asked == [3, 3] and w._tab() == "3d" and w.current["id"] in photos
        b3d.click()
        assert w._tab() == "grid"
        # neither: nothing changes
        answer[0] = None
        b3d.click()
        assert w._tab() == "grid" and asked == [3, 3, 3]

        # Simple with its two: both at once, no question; with a third added: the question
        answer[0] = "all"
        w.tb_cmd.widgetForAction(w.acts["view:simple"]).click()
        if len(w.picks()) == 2:
            b3d.click()
            app.processEvents()
            assert w._tab() == "3d2" and len(asked) == 3 and pair.image_ids == w.picks()
            b3d.click()
            assert w._tab() == "multi"
        extra = next(i for i in photos if i not in w.picks())
        w._toggle_pick(extra)
        n = len(w.picks())
        b3d.click()
        app.processEvents()
        assert asked[-1] == n and w._tab() == "3d2" and pair.image_ids == w.picks()[:MAX_EYES]
        b3d.click()
        assert w._tab() == "multi" and w.picks()[-1] == extra

        # more than two: each eye gets the photo reduced, its marks scaled with it
        real = w._small_photo
        monkeypatch.setattr(w, "_small_photo", lambda row, side: real(row, side)[::2, ::2])
        w._open_pair3d(photos[:3])
        row = db.get_image(photos[0])
        k = pair.eyes[0]._rgba.shape[1] / row["width"]
        assert 0.4 < k < 0.6
        circle = pair.eyes[0]._marks[2]
        assert circle is None or circle[2] == pytest.approx(row["circle_r"] * k, rel=0.02)
    finally:
        w.close()
        db.close()


def test_the_3d_question_itself(tmp_path):
    """The question [3D] asks: the photo being looked at, all the photos picked (at most nine), or cancel."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow(Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False),
                   Database(tmp_path / "lib" / "fundus.db"))
    seen = []

    def answer(text):
        def press():
            box = QApplication.activeModalWidget()
            seen.append((box.text(), [b.text() for b in box.buttons()]))
            next(b for b in box.buttons() if b.text().startswith(text)).click()
        QTimer.singleShot(0, press)

    try:
        answer("고른 사진 모두")
        assert w._ask_3d_which(4) == "all"
        assert "4장" in seen[-1][0] and sorted(seen[-1][1]) == sorted(["보고 있는 사진만", "고른 사진 모두 (4장)", "취소"])
        answer("보고 있는 사진만")
        assert w._ask_3d_which(12) == "one"
        assert "9장까지" in seen[-1][0] and "고른 사진 모두 (9장)" in seen[-1][1]
        answer("취소")
        assert w._ask_3d_which(3) is None
    finally:
        w.close()
