"""실제 위치에 맞춤 in the window: the fovea found at import (or when an old photo is first shown),
the photo put on the eye by it, marks by hand in the 2D view, the size from the fovea–disc distance —
and no patient data written on the photo."""
import os

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_photo_is_placed_by_its_fovea_and_disc(app, tmp_path, demo_dir, import_and_wait):
    from fundusview import placement
    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.placement import POLE, angle_between
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.resize(1500, 950)
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam"])
        w._select_patient_ref(db.find_patient("PID20260310-0A1B2C3D")["id"])
        app.processEvents()
        rows = [r for r in db.images_for_patient(w.current["patient_ref"]) if r["modality"] != "montage"]
        od = next(r for r in rows if r["laterality"] == "OD")
        w._show_image(od["id"])
        row, eye = w.current, w.eye3d
        cx, cy, r = row["circle_cx"], row["circle_cy"], row["circle_r"]
        # -- found at import: the disc nasal (OD: right), the fovea at the centre of this fovea-centred photo
        assert row["disc_x"] > cx + 0.2 * r and row["fovea_x"] is not None
        assert np.hypot(row["fovea_x"] - cx, row["fovea_y"] - cy) < 0.04 * r
        cam = w._photo_camera(row)
        pl = eye.placement
        assert pl.by == "fovea" and pl.offset_deg < 3.0 and w.c_align3d.isChecked()
        assert angle_between(pl.matrix @ cam.direction(row["fovea_x"], row["fovea_y"]), POLE) < 1e-6
        assert eye.disc_dir[0] > 0.25 and pl.distance_deg == pytest.approx(placement.DISC_FOVEA_DEG, abs=3.0)
        text = w.lbl_3d.text()
        assert "황반을 안구 뒤쪽 한가운데" in text and "황반–유두" in text and "mm" in text
        assert w.view2d._fovea_px == (row["fovea_x"], row["fovea_y"]) and w.b_fit_fov.isEnabled()
        # -- 실제 위치에 맞춤 off: the photo's centre on the pole, as before
        w.c_align3d.setChecked(False)
        assert eye.placement.by == "off" and np.allclose(eye.placement.matrix, np.eye(3)) and s.align3d is False
        assert "꺼짐" in w.lbl_3d.text()
        w.c_align3d.setChecked(True)
        assert eye.placement.by == "fovea" and s.align3d is True
        # -- the fovea marked by hand in the 2D view: that point goes to the pole
        fx, fy = cx + 0.22 * r, cy - 0.10 * r
        w.view2d.foveaPicked.emit(fx, fy)
        row = w.current
        assert (row["fovea_x"], row["fovea_y"]) == (fx, fy) and w.view2d._fovea_px == (fx, fy)
        assert angle_between(eye.placement.matrix @ cam.direction(fx, fy), POLE) < 1e-6
        assert eye.placement.offset_deg > 8.0 and "사진 중심은 후극에서" in w.lbl_3d.text()
        assert "황반 위치를 저장" in w.lbl_status.text()
        # -- the disc moved far from that fovea: the fovea is looked for again beside the new disc
        w.view2d.discPicked.emit(od["disc_x"], od["disc_y"])                # (back where it was found)
        row = w.current
        assert row["fovea_x"] is not None and np.hypot(row["fovea_x"] - cx, row["fovea_y"] - cy) < 0.04 * r
        assert eye.placement.by == "fovea" and eye.placement.offset_deg < 3.0
        # -- a photo from an older library (no fovea stored): found when it is shown
        db.update_image(row["id"], fovea_x=None, fovea_y=None)
        w._fovea_tried.clear()
        w._show_image(row["id"])
        assert w.current["fovea_x"] is not None and row["id"] in w._fovea_tried
        assert np.hypot(w.current["fovea_x"] - cx, w.current["fovea_y"] - cy) < 0.04 * r
        # -- 황반–유두 거리로 크기 맞춤: a wrong field of view is set right by the eye's own scale
        w.sp_fov.setValue(120.0)
        assert eye.placement.distance_deg < 0.8 * placement.DISC_FOVEA_DEG and "다를 수 있습니다" in w.lbl_3d.text()
        w.b_fit_fov.click()
        assert eye.placement.distance_deg == pytest.approx(placement.DISC_FOVEA_DEG, abs=0.2)
        # (approximate: it rests on where the disc and the fovea were found, and eyes differ a little)
        assert w.sp_fov.value() == pytest.approx(176.0, rel=0.2) and "다를 수 있습니다" not in w.lbl_3d.text()
        # -- on the photo: its number and the eye only (no name, ID or date), and not in green
        from fundusview.ui import image_view
        assert w.view2d._captions[1] == "OD (R)" and w.view2d._captions[2:] == ("", "")
        assert image_view.CAPTION.green() - image_view.CAPTION.red() < 30
        # -- the OS photo: its disc on the other side
        w._show_image(next(r for r in rows if r["laterality"] == "OS")["id"])
        assert eye.placement.by == "fovea" and eye.disc_dir[0] < -0.25
        # -- a photo without a disc: nothing to go by, centred on the pole
        db.update_image(w.current["id"], disc_x=None, disc_y=None, fovea_x=None, fovea_y=None)
        w._show_image(w.current["id"])
        assert eye.placement.by == "centre" and not w.b_fit_fov.isEnabled() and "찾지 못해" in w.lbl_3d.text()
        assert eye.disc_dir[0] < -0.25                                       # the nerve: at its anatomical place
    finally:
        w.close()
        db.close()


def test_alignment_setting_is_kept(tmp_path):
    from fundusview.config import Settings

    assert Settings(library_dir=str(tmp_path / "lib")).align3d is True
