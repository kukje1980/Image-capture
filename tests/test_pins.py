"""병변 핀 (pins.py): a place on a photo said as a clock hour and a distance from the disc — on the 2D
photo, on the 3D eye, kept with the photo."""
import json
import math
import os

import pytest

from fundusview import pins, placement


def _cam(fov=45.0):
    return placement.Camera(500.0, 400.0, 380.0, fov, "external", "perspective")


def test_clock_hours_are_as_the_examiner_sees_the_photo():
    cam, fovea = _cam(), (500.0, 400.0)
    for (dx, dy), hour in (((0, -200), 12), ((200, 0), 3), ((0, 200), 6), ((-200, 0), 9),
                           ((-100, -173), 11), ((100, -173), 1), ((173, 100), 4), ((-173, 100), 8)):
        w = pins.where(fovea[0] + dx, fovea[1] + dy, cam, fovea=fovea)
        assert w.hour == hour and w.about == "fovea" and w.inside
    # the same for either eye: the hour is of the photo, not of nasal / temporal
    assert pins.where(700, 400, cam, fovea=fovea, laterality="OS").hour == 3
    # at the fovea itself: no hour
    w = pins.where(505, 402, cam, fovea=fovea, disc=(700.0, 390.0))
    assert w.hour is None and w.short.startswith("황반 중심")


def test_distances_follow_the_eye_model_and_the_landmarks_there_are():
    cam = _cam()
    disc, fovea = (700.0, 390.0), (500.0, 400.0)
    w = pins.where(500, 150, cam, fovea=fovea, disc=disc)
    qa, qd, qf = cam.direction(500, 150), cam.direction(*disc), cam.direction(*fovea)
    assert w.disc_deg == pytest.approx(placement.angle_between(qa, qd))
    assert w.disc_mm == pytest.approx(math.radians(w.disc_deg) * 12.0)
    assert w.fovea_mm == pytest.approx(math.radians(placement.angle_between(qa, qf)) * 12.0)
    assert w.short == f"12시 · 유두에서 {w.disc_mm:.1f} mm" and "참고용" in w.long and "중심와에서" in w.long
    # no fovea in the photo: the hour round where it should be going by the disc
    w = pins.where(300, 400, cam, disc=disc, laterality="OD")
    assert w.about == "expected" and w.hour in (8, 9, 10) and w.fovea_mm is not None and w.disc_mm is not None
    # neither: round the middle of the picture, and said so
    w = pins.where(500, 100, cam)
    assert w.about == "image" and w.hour == 12 and w.disc_mm is None and "사진 가운데 기준" in w.long
    # outside the image circle
    w = pins.where(5, 5, cam, fovea=fovea)
    assert not w.inside and w.short == "사진 밖"
    # a photo without an image circle: no camera — nothing to count from
    assert pins.where(10, 10, None).hour is None


def test_pins_are_kept_in_the_photos_meta_and_bad_entries_are_left_out():
    meta = {"sources": {"laterality": "manual"}}
    kept = pins.to_meta(meta, [pins.Pin(10.26, 20.0), pins.Pin(5, 6, "열공")])
    assert kept["sources"] == meta["sources"] and "pins" not in meta
    assert kept["pins"] == [{"x": 10.3, "y": 20.0}, {"x": 5.0, "y": 6.0, "note": "열공"}]
    back = pins.from_meta(json.loads(json.dumps(kept)))
    assert [(p.x, p.y, p.note) for p in back] == [(10.3, 20.0, ""), (5.0, 6.0, "열공")]
    assert "pins" not in pins.to_meta(kept, [])
    assert pins.from_meta({"pins": [{"x": "a"}, {"y": 1}, None, {"x": float("nan"), "y": 1}, {"x": 1, "y": 2}]})[0].x == 1
    assert pins.from_meta(None) == [] and pins.from_meta({"pins": "junk"}) == []
    assert len(pins.from_meta({"pins": [{"x": i, "y": i} for i in range(100)]})) == pins.MAX_PINS
    assert pins.nearest(back, 6, 7, 5) == 1 and pins.nearest(back, 100, 100, 5) is None


pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_a_pin_is_put_on_the_photo_shown_on_the_3d_eye_and_kept(tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.demo import write_demo_folder
    from fundusview.ui.main_window import MainWindow
    from fundusview.ui.toolbars import MENUS, PROCBAR

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_on_startup=False, auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.resize(1500, 950)
        w.show()
        demo = tmp_path / "demo"
        write_demo_folder(demo)
        w.service.import_paths([str(demo / "RetiCam")])
        import time
        t = time.time()
        while time.time() - t < 30 and not db.list_patients():
            app.processEvents()
            time.sleep(0.02)
        for _ in range(100):
            app.processEvents()
            time.sleep(0.01)
        ref = db.list_patients()[0]["id"]
        w._select_patient_ref(ref)
        w.patient_list.hide()
        row = next(r for r in db.images_for_patient(ref) if r["circle_r"] and r["disc_x"] is not None)
        w.open_large(row["id"])
        app.processEvents()
        assert w._tab() == "all" and w.current["id"] == row["id"]
        # the button is on the 영상 처리 toolbar, with its ▾ entries
        assert any(sp and sp[0] == "tool:pin" for sp in PROCBAR) and len(MENUS["tool:pin"]) == 4
        w._on_action("tool:pin", True)
        v = w.view2d
        assert v.tool == "pin" and w.acts["tool:pin"].isChecked()

        def click(x, y):
            QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             v.mapFromScene(QPointF(x, y)))
            app.processEvents()

        cx, cy, r = row["circle_cx"], row["circle_cy"], row["circle_r"]
        click(cx, cy - 0.5 * r)
        click(cx + 0.4 * r, cy)
        kept = json.loads(db.get_image(row["id"])["meta_json"])["pins"]
        assert len(kept) == 2 and abs(kept[0]["x"] - cx) < 3 and abs(kept[0]["y"] - (cy - 0.5 * r)) < 3
        assert len(v._pins) == 2 and "시" in v._pins[0][2] and "유두에서" in v._pins[0][2]
        assert "핀 2:" in w.lbl_status.text() and "참고용" in w.lbl_status.text()
        # the measurements are cleared, the pins stay; they come back with the photo
        v.clear_annotations()
        assert len(v._pins) == 2
        other = next(r for r in db.images_for_patient(ref) if r["id"] != row["id"])
        w.open_large(other["id"])
        app.processEvents()
        assert v._pins == []
        w.open_large(row["id"])
        app.processEvents()
        assert len(v._pins) == 2
        # the same pins on the 3D eye, numbered alike, where the photo's pixels are on the retina
        eye = w.eye3d
        pts = eye.pin_points()
        assert len(pts) == 2 and pts[0][1].startswith("1  ") and pts[1][1].startswith("2  ")
        cam = eye.photo_camera((cx, cy, r))
        back = cam.pixel(eye.placement.matrix.T @ (pts[0][0] / (pts[0][0] @ pts[0][0]) ** 0.5))
        assert back == pytest.approx((kept[0]["x"], kept[0]["y"]), abs=1.0)
        # a memo on the last pin, a click on a pin takes it away, ▾ clears
        monkeypatch.setattr(w, "_ask_pin_note", lambda old="": "열공")
        w._on_action("pin_note")
        assert v._pins[1][2].endswith("— 열공") and json.loads(db.get_image(row["id"])["meta_json"])["pins"][1]["note"] == "열공"
        click(cx, cy - 0.5 * r)                                         # on pin 1
        assert len(v._pins) == 1 and v._pins[0][2].endswith("— 열공")
        w._on_action("pin_clear")
        assert v._pins == [] and "pins" not in json.loads(db.get_image(row["id"])["meta_json"])
        w._on_action("pin_undo")
        assert "핀이 없습니다" in w.lbl_status.text()
        # outside the image circle: none
        click(cx - 0.99 * r, cy - 0.99 * r) if (cx - 0.99 * r) > 0 and (cy - 0.99 * r) > 0 else w._add_pin(1, 1)
        assert v._pins == []

        # 3D: 병변 핀 on, a click on the retina of the eye seen from inside puts a pin at that pixel
        w._go("3d")
        app.processEvents()
        assert not eye.pin_mode
        w.b_pin3d.setChecked(True)
        assert eye.pin_mode
        eye.set_mode("inside")
        centre = QPointF(eye.width() / 2, eye.height() / 2)
        px = eye.photo_pixel_at(centre)
        assert px is not None
        eye._clicked(centre)
        app.processEvents()
        kept = json.loads(db.get_image(row["id"])["meta_json"])["pins"]
        assert len(kept) == 1 and (kept[0]["x"], kept[0]["y"]) == pytest.approx(px, abs=0.2)
        assert len(eye.pin_points()) == 1 and len(v._pins) == 1
        # from outside, on the closed eye: the sclera — no pin, and said so
        eye.set_mode("outside")
        w.s_cut.setValue(100)
        eye.reset_view()
        missed = []
        eye.pinMissed.connect(lambda: missed.append(1))
        eye._clicked(centre)
        assert missed and len(json.loads(db.get_image(row["id"])["meta_json"])["pins"]) == 1
    finally:
        w.close()
        db.close()
