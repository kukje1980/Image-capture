"""디스크 2장: disc crops sized in disc diameters, OD/OS order, the sheet and the main-window flow."""
import math
import os
import time

import numpy as np
import pytest

from fundusview import discpair, imaging, measure
from fundusview.demo import synth_fundus

CAMERAS = [(45, "external", "perspective", "OD"), (50, "external", "perspective", "OS"),
           (135, "internal", "equidistant", "OS"), (176, "internal", "radial", "OD")]


def _photo(fov, fov_type, projection, eye, size=(1200, 1200), circle=(600, 600, 560)):
    rgb = synth_fundus(eye=eye, fov_deg=fov, fov_type=fov_type, projection=projection, size=size,
                       circle=circle, seed=4)
    geo = measure.Geometry(*circle, fov_deg=fov, fov_type=fov_type, projection=projection)
    disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / max(math.degrees(geo.tmax), 5)))
    return rgb, geo, disc


@pytest.mark.parametrize("fov, fov_type, projection, eye", CAMERAS)
def test_crop_covers_the_same_retina_on_every_camera(fov, fov_type, projection, eye):
    rgb, geo, disc = _photo(fov, fov_type, projection, eye)
    assert disc is not None
    src = discpair.DiscSource(1, rgb, disc[:2], geo, eye)
    x0, y0, side = discpair.crop_box(src, "normal")
    # vertically through the disc the crop spans 3.5 disc diameters of retina, whatever the camera
    deg_mm = measure.retinal_distance((disc[0], y0), (disc[0], y0 + side), geo)
    assert deg_mm[1] == pytest.approx(3.5 * discpair.DISC_DIAMETER_MM, rel=0.1)
    assert (discpair.crop_box(src, "wide")[2] / side) == pytest.approx(5.0 / 3.5, rel=0.02)
    # the expected (anatomical) disc position is close to the detected one
    ex = discpair.expected_disc(geo, eye, (1200, 1200))
    assert math.hypot(ex[0] - disc[0], ex[1] - disc[1]) < 0.25 * side


def test_panel_is_centred_on_the_disc():
    rgb, geo, disc = _photo(45, "external", "perspective", "OD")
    out = discpair.panel(discpair.DiscSource(1, rgb, disc[:2], geo, "OD"), out_px=400)
    assert out.shape == (400, 400, 3) and out.dtype == np.uint8
    lum = imaging.luminance(out.astype(np.float32))
    iy, ix = np.unravel_index(np.argmax(imaging.gaussian_blur(lum, 6)), lum.shape)   # the pale cup
    assert abs(ix - 200) < 40 and abs(iy - 200) < 40


def test_crop_beyond_the_photo_is_black():
    rgb = np.full((300, 400, 3), 120, np.uint8)
    src = discpair.DiscSource(1, rgb, (5.0, 5.0), None, None)
    out = discpair.panel(src, out_px=200)
    assert out.shape == (200, 200, 3)
    assert out[5, 5].max() == 0 and out[-5, -5].min() == 120
    u, v = 0.75, 0.75
    x, y = discpair.to_source_point(src, "normal", u, v)
    x0, y0, side = discpair.crop_box(src, "normal")
    assert (x, y) == pytest.approx((x0 + u * side, y0 + v * side))


def test_order_pair_puts_od_left():
    rgb = np.zeros((10, 10, 3), np.uint8)

    def src(i, eye, when):
        return discpair.DiscSource(i, rgb, (5, 5), None, eye, when)

    od, os_ = src(1, "OD", "2026-01-15 10:22"), src(2, "OS", "2026-01-15 10:20")
    assert discpair.order_pair(os_, od) == (od, os_)
    old, new = src(3, "OD", "2025-01-02 09:00"), src(4, "OD", "2026-01-02 09:00")
    assert discpair.order_pair(new, old) == (old, new)          # same eye: older first
    assert od.eye_label.startswith("OD") and src(5, None, "").eye_label == "눈 미상"


def test_expected_disc_is_nasal():
    geo = measure.Geometry(500, 400, 380, fov_deg=45, fov_type="external", projection="perspective")
    assert discpair.expected_disc(geo, "OD", (1000, 800))[0] > 500 > discpair.expected_disc(geo, "OS", (1000, 800))[0]
    assert discpair.expected_disc(geo, None, (1000, 800)) == (500, 400)
    assert discpair.expected_disc(None, "OD", (1000, 800)) == (500, 400)


# -- main window ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_disc_pair_from_two_picked_photos(app, tmp_path, demo_dir):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        w.service.import_paths([str(demo_dir / "PatientCapture"), str(demo_dir / "RetiCam")])
        deadline = time.time() + 30
        while (db.find_patient("20260115001") is None or db.find_patient("PID20260310-0A1B2C3D") is None) \
                and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        settle = time.time() + 1.0          # results are coalesced on a 300 ms timer
        while time.time() < settle:
            app.processEvents()
            time.sleep(0.02)
        ref = db.find_patient("20260115001")["id"]       # 김민수: APOLLO OD + OS
        w._select_patient_ref(ref)
        assert w.thumbs.count() == 2
        dlg, why = w._build_disc_pair()
        assert dlg is None and "Ctrl+클릭" in why        # only one photo picked so far
        shown = w.current["id"]
        other = w.thumbs.item(1)
        other_id = other.data(Qt.ItemDataRole.UserRole)

        def ctrl_click(item):
            QTest.mouseClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                             w.thumbs.visualItemRect(item).center())
            app.processEvents()

        ctrl_click(other)                               # Ctrl+click: second photo, the shown one stays
        assert w.current["id"] == shown and w.compare["id"] == other_id
        assert other.text().startswith("②") and w.tabs.currentIndex() == 3
        assert all(v.has_image() for v in w.cmp_views)
        ctrl_click(other)                               # again: unpicked
        assert w.compare is None and not other.text().startswith("②")
        ctrl_click(other)
        w.thumbs.setCurrentItem(other)                  # clicking the ② photo swaps the two
        app.processEvents()
        assert w.current["id"] == other_id and w.compare["id"] == shown
        assert w.thumbs.item(0).text().startswith("②")

        dlg, why = w._build_disc_pair()
        assert why == "" and [src.eye for src in dlg.sources] == ["OD", "OS"]   # OD left whatever was clicked
        assert all(src.found == "saved" for src in dlg.sources)
        sheet = dlg.sheet()
        assert sheet.width() > 2 * discpair.PANEL_PX and sheet.height() > discpair.PANEL_PX
        assert "김민수" in dlg.patient_line and "20260115001" in dlg.patient_line
        dlg.field.setCurrentIndex(dlg.field.findData("near"))
        dlg.swap()
        assert [src.eye for src in dlg.sources] == ["OS", "OD"]
        dlg.swap()
        # clicking a panel re-centres it and stores that point as the photo's disc
        od = dlg.sources[0]
        before = od.disc
        dlg.recentre(od, 0.6, 0.5)
        assert od.disc[0] > before[0] and db.get_image(od.image_id)["disc_x"] == pytest.approx(od.disc[0])
        dlg.save_to_record()
        new = db.get_image(dlg.saved_id)
        assert (new["modality"], new["laterality"], new["patient_ref"]) == ("disc", "OU", ref)
        assert new["note"] == "디스크 2장 (OD · OS)" and new["width"] == sheet.width()
        assert w.thumbs.count() == 3
        dlg.close()
        # the sheet itself, an unassigned photo or another patient's photo cannot be paired
        assert "자를 수 없습니다" in w._build_disc_pair(dlg.saved_id)[1]
        other_patient = db.images_for_patient(db.find_patient("PID20260310-0A1B2C3D")["id"])[0]
        assert "다른 환자" in w._build_disc_pair(other_patient["id"])[1]
        anonymous = db.images_for_patient(None)[0]      # RetiCam default patient -> 미분류
        assert "미분류" in w._build_disc_pair(anonymous["id"])[1]
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        assert w.compare is None                        # a new patient starts without a second pick
    finally:
        w.close()
        db.close()
