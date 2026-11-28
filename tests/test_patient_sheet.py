"""환자용 요약 (한 장) and 이 환자의 시야 (sight.py)."""
import os

import numpy as np
import pytest

from fundusview import pins, placement, sight


def test_the_retina_sees_upside_down_and_left_stays_left():
    cam = placement.Camera(500.0, 400.0, 380.0, 45.0, "external", "perspective")
    fovea, disc = (500.0, 400.0), (700.0, 395.0)

    def spot(x, y):
        return sight.spot_of(pins.where(x, y, cam, fovea=fovea, disc=disc), "1")
    up, right = spot(500, 250), spot(650, 400)
    assert up.x_deg == pytest.approx(0.0, abs=1e-6) and up.y_deg < -3          # above the fovea: the lower field
    assert right.y_deg == pytest.approx(0.0, abs=1e-6) and right.x_deg > 3     # right in the photo: right in the field
    here = spot(500, 400)
    assert (here.x_deg, here.y_deg) == (0.0, 0.0)                              # the fovea: the point looked at
    # the disc of an OD photo (on the right): the blind spot, about 15° to the temporal side (the right)
    blind = sight.spot_of(pins.where(*disc, cam, fovea=fovea, disc=disc))
    assert 10 < blind.x_deg < 20 and abs(blind.y_deg) < 2
    # a visual angle is smaller than the angle at the eye's centre, and grows with it
    assert sight.visual_angle(0) == 0 and 0 < sight.visual_angle(30) < 30 < sight.visual_angle(60) < 60
    # nothing to say: outside the photo, or no fovea to count from
    assert sight.spot_of(pins.where(5, 5, cam, fovea=fovea)) is None
    assert sight.spot_of(pins.where(500, 100, cam)) is None and sight.spot_of(None) is None


def test_a_patch_dims_the_scene_where_the_spot_is_and_far_spots_widen_it():
    scene = np.full((200, 300, 3), 200, np.uint8)
    near = sight.Spot(10.0, -5.0, "1")
    out = sight.simulate(scene, [near])
    x, y = sight.to_pixel(near, scene.shape)
    assert out[int(y), int(x)].mean() < 90 and out[5, 5].mean() > 190 and out.shape == scene.shape
    assert (sight.simulate(scene, []) == scene).all()
    assert sight.span_for([near], scene.shape) == sight.SPAN_DEG
    far = sight.Spot(-4.0, 44.0, "2")
    span = sight.span_for([near, far], scene.shape)
    assert span > 140
    x, y = sight.to_pixel(far, scene.shape, span)
    assert 0 <= x < 300 and 0 <= y < 200                                       # in the picture now
    assert sight.simulate(scene, [far], span_deg=span)[int(y), int(x)].mean() < 90


pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _photo(eye, pins_=()):
    from fundusview.demo import synth_fundus
    from fundusview.ui.patient_sheet import EyePhoto
    return EyePhoto(eye, synth_fundus(eye=eye, size=(400, 420)), list(pins_), "2026-01-15 · 컬러")


def test_the_page_grows_with_what_is_on_it_and_says_what_it_is(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview.ui import patient_sheet as PS

    QApplication.instance() or QApplication([])
    od = _photo("OD", [(120.0, 90.0, "11시 · 유두에서 9.2 mm"), (260.0, 300.0, "5시 · 유두에서 6.0 mm — 열공")])
    base = PS.Sheet(clinic="국제안과", patient="홍길동  ·  P1", exam="2026-01-15", photos=[od], device="촬영 장비: X")
    plain = PS.compose(base)
    assert (plain.width(), plain.height()) == (PS.W, PS.A4_H)                  # an A4 sheet at least
    assert PS.pin_rows(base) == [(1, "오른쪽 눈 — 11시 · 유두에서 9.2 mm"), (2, "오른쪽 눈 — 5시 · 유두에서 6.0 mm — 열공")]
    base.show_pins = False
    assert PS.pin_rows(base) and PS.compose(base).height() == PS.A4_H
    base.show_pins = True
    full = PS.Sheet(**{**base.__dict__, "photos": [od, _photo("OS", [(50.0, 60.0, "9시")])], "disease": "녹내장 (시신경 유두)",
                       "stage": 1, "memo": "여섯 달 뒤에 다시 봅니다. " * 12,
                       "field_eye": "OD", "field_spots": [sight.Spot(5.0, -30.0, "1"), sight.Spot(-8.0, 12.0, "2")]})
    img = PS.compose(full)
    assert img.height() > PS.A4_H and img.width() == PS.W                      # more on it: a longer page
    assert [n for n, _ in PS.pin_rows(full)] == [1, 2, 3] and PS.pin_rows(full)[2][1].startswith("왼쪽 눈 — ")
    assert img.pixelColor(4, 4).getRgb()[:3] == (255, 255, 255)                # paper
    pdf = tmp_path / "sheet.pdf"
    PS.save_pdf(img, str(pdf))
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 20000


def test_the_window_builds_the_page_from_the_photo_on_screen(tmp_path, monkeypatch):
    import time

    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.demo import write_demo_folder
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_on_startup=False, auto_detect=False, dicom_institution="국제안과")
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        assert w.build_patient_sheet() == (None, "사진을 고르세요.")
        write_demo_folder(tmp_path / "demo")
        w.service.import_paths([str(tmp_path / "demo")])
        t = time.time()
        while time.time() - t < 40 and db.find_patient("20260115001") is None:
            app.processEvents()
            time.sleep(0.02)
        for _ in range(150):
            app.processEvents()
            time.sleep(0.01)
        ref = db.find_patient("20260115001")["id"]                 # one OD and one OS photo
        w._select_patient_ref(ref)
        w.patient_list.hide()
        od = next(r for r in db.images_for_patient(ref) if r["laterality"] == "OD")
        w.open_large(od["id"])
        app.processEvents()
        cx, cy, r = od["circle_cx"], od["circle_cy"], od["circle_r"]
        w._add_pin(cx - 0.2 * r, cy - 0.5 * r)
        dlg, why = w.build_patient_sheet()
        assert why == "" and dlg is not None
        try:
            sheet = dlg.sheet()
            assert sheet.clinic == "국제안과" and "김민수" in sheet.patient and sheet.exam == od["exam_date"]
            assert [ph.eye for ph in sheet.photos] == ["OD", "OS"] and dlg.c_pair.isChecked()     # OD on the left
            assert len(sheet.photos[0].pins) == 1 and "유두에서" in sheet.photos[0].pins[0][2]
            assert max(sheet.photos[0].rgb.shape[:2]) <= w.SHEET_SIDE and "촬영 장비" in sheet.device
            assert sheet.field_spots == [] and dlg.c_field.isEnabled() and not dlg.c_field.isChecked()
            dlg.c_field.setChecked(True)
            spots = dlg.sheet().field_spots
            assert len(spots) == 1 and spots[0].label == "1" and spots[0].y_deg < 0     # above the fovea: lower field
            h0 = dlg.image.height()
            dlg.disease.setCurrentIndex(dlg.disease.findData("녹내장 (시신경 유두)"))
            assert dlg.stage.isEnabled() and dlg.stage.count() >= 2 and dlg.image.height() > h0
            dlg.c_pair.setChecked(False)
            assert [ph.eye for ph in dlg.sheet().photos] == ["OD"]
            dlg.c_pins.setChecked(False)
            assert dlg.sheet().field_spots == [] and not dlg.sheet().show_pins
            dlg.memo.setPlainText("다음에 다시 봅니다")
            assert dlg.sheet().memo == "다음에 다시 봅니다"
            dlg.save_pdf(str(tmp_path / "out.pdf"))
            dlg.save_png(str(tmp_path / "out.png"))
            assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF") and (tmp_path / "out.png").stat().st_size > 10000
            assert "저장했습니다" in dlg.status.text() and dlg.file_stem.startswith("20260115001_안저검사안내")
        finally:
            dlg.close()
        # the menu entry
        assert w.act_sheet.text() == "환자용 요약 (한 장)…"
    finally:
        w.close()
        db.close()
