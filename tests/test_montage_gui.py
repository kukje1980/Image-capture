"""몽타주 in the main window: pick photos → [몽타주] → 자동 합치기 → 환자 기록에 저장 → 3D / 다시 편집,
and the editor's own tools (drag, roll, undo, 기준점, 포함 체크, 몽타주 화각)."""
import math
import os
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("cv2")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def montage_drop(tmp_path_factory):
    from fundusview.demo import write_demo_folder

    root = tmp_path_factory.mktemp("montage_drop")
    write_demo_folder(root, small=True, montage=True)
    return root


def _wait(app, cond, timeout=90.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def _sources(n=3, side=720):
    from fundusview import demo, imaging
    from fundusview.ui.montage_dialog import MontageSource

    out = []
    for k, rgb in enumerate(demo.montage_fields("OD", size=side)[:n]):
        c = imaging.detect_circle(rgb)
        out.append(MontageSource(k + 1, rgb, imaging.fundus_alpha(rgb, c), c, 45.0, "external", "perspective",
                                 label=f"#{k + 1}", laterality="OD"))
    return out


def test_editor_tools(app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    from fundusview import demo, montage as mt
    from fundusview.ui.montage_dialog import MontageDialog, PointPairDialog

    dlg = MontageDialog(_sources(), auto=False)
    try:
        dlg.resize(1300, 860)
        dlg.show()
        app.processEvents()
        dlg.canvas.fit()
        c = dlg.canvas
        assert dlg.included() == [0, 1, 2] and c.selected == 0
        # 수동: drag photo ② by its centre — it follows the mouse
        dlg.list.setCurrentRow(1)
        assert c.selected == 1
        x, y = c.to_screen(*mt.plane_xy(dlg.shots[1].centre()))
        start = QPoint(int(x), int(y))
        QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(c, start + QPoint(40, 0))
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(40, 0))
        nx, ny = c.to_screen(*mt.plane_xy(dlg.shots[1].centre()))
        assert float(nx) == pytest.approx(x + 40, abs=1.5) and float(ny) == pytest.approx(y, abs=1.5)
        assert len(dlg._undo) == 1
        dlg.undo()
        assert float(c.to_screen(*mt.plane_xy(dlg.shots[1].centre()))[0]) == pytest.approx(x, abs=0.5)
        # keys: nudge and turn the selected photo
        before = dlg.shots[1].centre()
        c.setFocus()
        QTest.keyClick(c, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        assert mt.angle_deg(before[None], dlg.shots[1].centre()[None])[0] == pytest.approx(1.0, abs=0.01)
        r0 = dlg.shots[1].R.copy()
        dlg._roll(1.0)
        assert np.allclose(dlg.shots[1].centre(), r0 @ [0, 0, -1]) and not np.allclose(dlg.shots[1].R, r0)
        # 기준점: true pairs of spots on ② and ① place ② where it belongs
        truth = [demo.gaze_rotation(*g) for g in demo.MONTAGE_GAZES[:2]]
        pd = PointPairDialog(dlg.shots, 1, [0], dlg)
        for xd, yd in ((14, 8), (16, -9), (20, 1)):
            d = mt.plane_dirs(math.radians(xd), math.radians(yd))
            pd._on_left(*[float(v) for v in dlg.shots[1].pixels(d @ truth[1])[:2]])
            assert not pd.b_ok.isEnabled()                       # waiting for the right-hand click
            pd._on_right(*[float(v) for v in dlg.shots[0].pixels(d @ truth[0])[:2]])
        assert pd.b_ok.isEnabled() and len(pd.pairs()[0]) == 3
        pd.undo()
        assert len(pd.pairs()[0]) == 2
        mu, au = pd.pairs()
        mt.align_points(dlg.shots[1], mu, dlg.shots[0], au)
        err = math.degrees(math.acos(min(1.0, (np.trace(dlg.shots[1].R.T @ truth[1]) - 1) / 2)))
        assert err < 0.2
        pd.close()
        # 포함 체크: an unchecked photo leaves the montage (and its 화각)
        full = dlg.auto_fov_deg()
        dlg.list.item(2).setCheckState(Qt.CheckState.Unchecked)
        assert dlg.included() == [0, 1] and 2 in c.hidden and dlg.auto_fov_deg() < full
        # 몽타주 화각: automatic, or set by hand for the 3D view
        assert dlg.montage_fov() == pytest.approx(dlg.auto_fov_deg())
        dlg.c_auto_fov.setChecked(False)
        dlg.sp_mfov.setValue(150.0)
        assert dlg.montage_fov() == 150.0 and "150°" in dlg.lbl_range.text()
        # 겹쳐 보기: the overlay follows the opacity / colour settings
        dlg.s_opacity.setValue(100)
        dlg.c_tint.setChecked(True)
        img = c._img
        assert img is not None and c.tint and c.opacity == 1.0
        QTest.mouseDClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))
        assert c.scale > 0 and isinstance(c.dir_at(QPointF(10, 10)), np.ndarray)
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_montage_from_the_main_window(app, tmp_path, montage_drop, import_and_wait, monkeypatch):
    from PySide6.QtCore import Qt

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui import montage_dialog
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(montage_drop))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    seen = []

    def run_editor(dlg):
        """Instead of the user: wait for 자동 합치기, save, look at 완성."""
        seen.append(dlg)
        _wait(app, lambda: dlg._job is None and not dlg._busy_on)
        if dlg.definition_loaded:
            return 1
        assert "5/5장" in dlg.status.text(), dlg.status.text()
        dlg.tabs.setCurrentIndex(1)
        _wait(app, lambda: dlg._preview is not None and dlg._render_job is None)
        assert dlg.done_view.has_image()
        dlg.save_to_record()
        _wait(app, lambda: dlg.saved_id is not None)
        return 1

    monkeypatch.setattr(montage_dialog.MontageDialog, "exec", run_editor)
    try:
        w.resize(1500, 960)
        w.show()
        import_and_wait(app, w, [montage_drop / "VK2_Export"])
        ref = db.find_patient("D0001240")["id"]
        w._select_patient_ref(ref)
        app.processEvents()
        assert w.thumbs.count() == 5 and not w.btn_montage.isEnabled()
        ids = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(5)]
        w._toggle_pick(ids[0])
        assert not w.btn_montage.isEnabled()                    # one photo is not a montage
        for i in ids[1:]:
            w._toggle_pick(i)
        assert w.btn_montage.isEnabled()
        w.btn_montage.click()
        dlg = seen[-1]
        assert len(dlg.shots) == 5 and dlg.laterality() == "OD"
        new = db.get_image(dlg.saved_id)
        assert (new["modality"], new["laterality"], new["patient_ref"]) == ("montage", "OD", ref)
        assert (new["fov_type"], new["projection"]) == ("internal", "equidistant")
        assert 100 < new["fov_deg"] < 160                        # 5 fields of 45° cover far more than one
        assert new["circle_r"] == pytest.approx(new["width"] / 2) and new["width"] == new["height"]
        d = w._montage_definition(new)
        assert d is not None and sorted(x["image_id"] for x in d["shots"]) == sorted(ids)
        assert w.thumbs.count() == 6
        # the montage in the 3D view and the measurements: its own eye geometry
        w._show_image(new["id"])
        app.processEvents()
        assert w.sp_fov.value() == pytest.approx(new["fov_deg"]) and w.c_proj.currentData() == "equidistant"
        assert w.eye3d.projection == "equidistant" and w.eye3d.fov_type == "internal"
        assert w.view2d.geometry is not None
        # 다시 편집: the saved arrangement comes back
        w.edit_montage(new["id"])
        again = seen[-1]
        assert again is not dlg and again._ref_chosen
        for a, b in zip(again.shots, dlg.shots):
            assert np.allclose(a.R, b.R, atol=1e-9) and a.fov_scale == pytest.approx(b.fov_scale)
        # photos of another patient or of the other eye are refused
        other = db.images_for_patient(db.find_patient("D0001234")["id"])[0]["id"]
        sources, why = w._montage_sources([ids[0], other])
        assert sources is None and "다른 환자" in why
        assert "두 장 이상" in w._montage_sources([ids[0]])[1]
    finally:
        w.close()
