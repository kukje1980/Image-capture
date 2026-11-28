"""0.13.20: 이 환자의 시야 시뮬레이션 (fieldsim.py) · 변화 지도 (changemap.py) · 환자용 한 장 요약 (handout.py)
and their windows (ui/patient_views.py)."""
import os
import time

import cv2
import numpy as np
import pytest

from fundusview import changemap as C
from fundusview import fieldsim as F
from fundusview import handout as H
from fundusview import glaucoma, pins, placement
from fundusview.demo import synth_fundus


def _cam(fov=45.0):
    return placement.Camera(500.0, 500.0, 480.0, fov)


# -- 시야 시뮬레이션 ---------------------------------------------------------------------------------------
def test_a_pin_above_the_fovea_is_below_where_the_patient_looks_and_left_right_stays():
    cam, fovea = _cam(), (500.0, 500.0)
    up, right, mid = pins.Pin(500, 300), pins.Pin(700, 500, "출혈"), pins.Pin(500, 500)
    a, b, c = F.spots([up, right, mid], cam, fovea)
    assert abs(a.x) < 1e-6 and a.y > 5                        # the upper retina: the lower field
    assert b.x > 5 and abs(b.y) < 1e-6                        # the photo's right: the patient's right
    assert c.away == 0 and (a.number, b.number, c.number) == (1, 2, 3)
    # the distance is the angle at the eye: 200 px of a 480 px, 45° circle
    assert a.away == pytest.approx(placement.angle_between(cam.direction(500, 300), cam.direction(500, 500)))
    assert 8 < a.away < 12
    lines = F.describe([a, b, c])
    assert "아래로" in lines[0] and "오른쪽으로" in lines[1] and lines[1].endswith("출혈") and "한가운데" in lines[2]


def test_where_the_patient_looks_fovea_then_the_place_by_the_disc_then_the_middle():
    cam = _cam()
    assert F.centre_of(cam, fovea=(480, 510)) == ((480.0, 510.0), "fovea")
    p, how = F.centre_of(cam, disc=(700, 500), laterality="OD")
    assert how == "expected" and p[0] < 700
    assert F.centre_of(cam) == ((500.0, 500.0), "image")
    assert F.centre_of(None, size=(800, 600)) == ((400.0, 300.0), "image")
    # without the photo's geometry: a share of the picture's width
    (s,) = F.spots([pins.Pin(600, 300)], None, (400.0, 300.0), width=800)
    assert s.x == pytest.approx(200 / 800 * F.GUESS_FOV_DEG) and s.y == 0
    # a pin outside the field is left out, the numbers of the others stay
    got = F.spots([pins.Pin(5, 5), pins.Pin(500, 400)], cam, (500.0, 500.0))
    assert [g.number for g in got] == [2]


def test_the_scene_is_dimmed_where_the_pins_are_and_nowhere_else():
    scene = glaucoma.sample_scene(600)
    h, w = scene.shape[:2]
    spot = F.Spot(15.0, 8.0, 1)
    out = F.simulate(scene, [spot], size_deg=5, numbers=False)
    assert out.shape == scene.shape and out.dtype == np.uint8
    px = (w / 2) / F.NARROW_DEG
    x, y = int(w / 2 + 15 * px), int(h / 2 + 8 * px)
    assert out[y - 4:y + 4, x - 4:x + 4].mean() < scene[y - 4:y + 4, x - 4:x + 4].mean() * 0.6
    assert np.array_equal(out[:40, :40], scene[:40, :40])                   # far from it: untouched
    assert np.array_equal(F.simulate(scene, [], numbers=False)[:h // 3], scene[:h // 3])
    # a pin far out: the scene shows 120°
    assert F.half_width([spot]) == F.NARROW_DEG and F.half_width([F.Spot(-40.0, 0.0)]) == F.WIDE_DEG
    # a larger patch takes more of the picture
    small = (F.simulate(scene, [spot], size_deg=3, numbers=False) != scene).any(axis=2).sum()
    large = (F.simulate(scene, [spot], size_deg=12, numbers=False) != scene).any(axis=2).sum()
    assert large > small * 3


# -- 변화 지도 ---------------------------------------------------------------------------------------------
def _pair():
    """Today's photo with a dark and a bright new spot, and the same fundus earlier: turned, shifted,
    a little larger and darker."""
    base = synth_fundus(size=(900, 900), circle=(450, 450, 430), fov_deg=45, seed=3)
    m = cv2.getRotationMatrix2D((450, 450), 4, 1.03)
    m[:, 2] += (12, -9)
    old = np.clip(cv2.warpAffine(base, m, (900, 900)).astype(np.float32) * 0.88 + 6, 0, 255).astype(np.uint8)
    new = base.copy()
    cv2.circle(new, (600, 500), 14, (95, 10, 10), -1)
    cv2.circle(new, (300, 300), 10, (250, 240, 170), -1)
    return old, cv2.GaussianBlur(new, (0, 0), 1.0), cv2.invertAffineTransform(m)


def test_the_earlier_photo_is_laid_on_todays_by_its_vessels():
    old, new, truth = _pair()
    fit = C.register(old, new, old_circle=(450, 450, 430), new_circle=(450, 450, 430))
    assert fit.how == "vessels" and fit.inliers >= C.MIN_INLIERS and "혈관" in fit.text
    corners = np.float64([[100, 100, 1], [800, 100, 1], [450, 800, 1]]).T
    assert np.abs(fit.matrix @ corners - truth @ corners).max() < 2.5          # within a few pixels
    warped, there = C.applied(old, fit, new.shape)
    assert warped.shape == new.shape and there[450, 450] == 255


def test_what_is_darker_and_what_is_brighter_today_are_marked_apart():
    old, new, _truth = _pair()
    fit = C.register(old, new)
    warped, there = C.applied(old, fit, new.shape)
    darker, brighter = C.difference(new, warped, there)
    ys, xs = np.nonzero(darker > 0.3)
    assert len(xs) > 50 and abs(xs.mean() - 600) < 6 and abs(ys.mean() - 500) < 6
    ys, xs = np.nonzero(brighter > 0.3)
    assert len(xs) > 30 and abs(xs.mean() - 300) < 6 and abs(ys.mean() - 300) < 6
    d, b = C.changed_share(darker, brighter, there)
    assert 0 < d < 0.01 and 0 < b < 0.01                    # the overall darkening is not a change
    # the same photo twice: nothing
    same = C.difference(new, new, there)
    assert C.changed_share(*same, there) == (0.0, 0.0)
    # the colours go on the photo; the line parts the two photos
    out = C.marked(new, darker, brighter)
    assert out[500, 600, 2] > new[500, 600, 2] + 40 and np.array_equal(out[100, 450], new[100, 450])
    cut = C.swipe(warped, new, 0.25)
    assert np.array_equal(cut[:, :225], warped[:, :225]) and np.array_equal(cut[:, 225:], new[:, 225:])
    # more sensitive: no less marked
    more = C.difference(new, warped, there, C.SENSITIVITY[1])
    assert (more[0] > 0.3).sum() >= (darker > 0.3).sum()


def test_without_vessels_the_landmarks_fit_and_without_them_only_the_size():
    blank = np.full((400, 600, 3), 90, np.uint8)
    fit = C.register(blank, blank, old_marks=((100, 200), (300, 200)), new_marks=((120, 210), (320, 210)))
    assert fit.how == "landmarks" and "유두" in fit.text
    assert fit.matrix @ np.float64([100, 200, 1]) == pytest.approx([120, 210])
    plain = C.register(blank, np.full((800, 1200, 3), 90, np.uint8))
    assert plain.how == "none" and plain.matrix[0, 0] == pytest.approx(2.0) and "못했습니다" in plain.text


# -- 환자용 한 장 요약 --------------------------------------------------------------------------------------
def test_the_doctors_note_is_trimmed_and_the_page_has_a_name():
    assert H.clean_memo("  3개월 뒤   다시 \n\n\n혈당 조절 ") == "3개월 뒤 다시\n혈당 조절"
    assert H.clean_memo(None) == ""
    assert len(H.clean_memo("가" * 1000)) == H.MEMO_MAX
    assert H.clean_memo("\n".join(str(i) for i in range(20))).count("\n") == H.MEMO_LINES - 1
    assert H.file_stem("1234", "2026-11-28") == "1234_설명자료_2026-11-28" and H.file_stem(None, None) == "설명자료"


pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _page_ink(img) -> float:
    from fundusview.ui.image_view import from_qimage
    return float((from_qimage(img).min(axis=2) < 200).mean())


def test_the_page_is_drawn_with_each_part_and_written_as_a_pdf(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview.ui.patient_views import handout_image, write_pdf

    app = QApplication.instance() or QApplication([])      # noqa: F841
    photo = synth_fundus(size=(400, 400), circle=(200, 200, 190), fov_deg=45, seed=2)
    plain = H.Handout(patient="홍길동 · ID 1", exam="검사일 2026-11-28", photos=[(photo, "OD")])
    sight = F.simulate(glaucoma.sample_scene(300), [F.Spot(10, 5, 1)])
    full = H.Handout(patient="홍길동 · ID 1", exam="검사일 2026-11-28", photos=[(photo, "OD"), (photo, "OS")],
                     disease="당뇨망막병증", stage=3, sight=sight, sight_lines=["1  보는 곳에서 오른쪽 아래로 11°"],
                     memo="3개월 뒤 다시 검사합니다.")
    a, b = handout_image(plain, 620), handout_image(full, 620)
    assert a.width() == 620 and abs(a.height() / a.width() - 297 / 210) < 0.01
    assert _page_ink(b) > _page_ink(a) > 0.02                # more on the page with the disease and the field
    assert _page_ink(handout_image(H.Handout(disease="없는 질환"), 300)) < 0.05     # an unknown disease: left out
    for d in ("녹내장 (시신경 유두)", "망막박리", "병적 근시"):        # the longest texts stay on the page
        handout_image(H.Handout(photos=[(photo, "OD")], disease=d, sight=sight, memo="가" * H.MEMO_MAX), 400)
    path = tmp_path / "page.pdf"
    write_pdf(path, full)
    data = path.read_bytes()
    assert data[:5] == b"%PDF-" and len(data) > 20_000
    with pytest.raises(OSError):
        write_pdf(tmp_path / "no" / "such" / "folder" / "page.pdf", full)


def test_the_three_windows_open_from_the_photo_on_screen(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.demo import write_demo_folder
    from fundusview.ui.main_window import MainWindow
    from fundusview.ui.patient_views import ChangeDialog, HandoutDialog, Shot, SightDialog
    from fundusview.ui.toolbars import MENUS

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
        t = time.time()
        while time.time() - t < 30 and not db.list_patients():
            app.processEvents()
            time.sleep(0.02)
        for _ in range(100):
            app.processEvents()
            time.sleep(0.01)
        patient = next(p for p in db.list_patients()
                       if {r["laterality"] for r in db.images_for_patient(p["id"])} >= {"OD", "OS"})
        w._select_patient_ref(patient["id"])
        w.patient_list.hide()
        rows = [r for r in db.images_for_patient(patient["id"]) if r["circle_r"] and r["disc_x"] is not None]
        row = next(r for r in rows if r["laterality"] == "OD")
        w.open_large(row["id"])
        app.processEvents()
        assert w.current["id"] == row["id"]
        # the menus have them
        assert ("pin_sight", "환자가 보는 모습 (시야 시뮬레이션)…") in MENUS["tool:pin"]
        labels = [a.text() for a in w._build_photo_menu(row["id"]).actions()]
        assert "변화 지도…" in labels and "환자용 한 장 요약…" in labels

        # 시야 시뮬레이션: needs a pin
        dlg, why = w._build_sight()
        assert dlg is None and "병변 핀" in why
        cx, cy, r = row["circle_cx"], row["circle_cy"], row["circle_r"]
        w._store_pins(w.current, [pins.Pin(cx + 0.2 * r, cy - 0.3 * r, "출혈"), pins.Pin(cx - 0.2 * r, cy + 0.2 * r)])
        dlg, why = w._build_sight()
        assert isinstance(dlg, SightDialog) and why == "" and len(dlg.spots) == 2
        before = dlg.scene().copy()
        dlg.s_size.slider.setValue(dlg.s_size.slider.maximum())
        assert (dlg.scene() != before).any() and dlg.picture().shape[1] > dlg.scene().shape[1]
        assert "출혈" in dlg.lbl_lines.text()
        dlg.deleteLater()

        # 환자용 한 장 요약: the photo with its pins, the other eye of the same day, the field of the pins
        dlg, why = w._build_handout()
        assert isinstance(dlg, HandoutDialog) and why == ""
        h = dlg.handout()
        assert len(h.photos) == 2 and h.photos[0][1].startswith("OD") and h.sight is not None and len(h.sight_lines) == 2
        assert patient["patient_id"] in h.patient and h.disease is None
        dlg.c_disease.setCurrentIndex(dlg.c_disease.findData("당뇨망막병증"))
        assert dlg.c_stage.count() > 1 and dlg.handout().disease == "당뇨망막병증"
        dlg.c_fellow.setChecked(False)
        dlg.c_sight.setChecked(False)
        dlg.memo.setPlainText("3개월 뒤 다시 검사합니다.")
        h = dlg.handout()
        assert len(h.photos) == 1 and h.sight is None and h.memo == "3개월 뒤 다시 검사합니다."
        assert dlg.view.has_image()
        dlg.deleteLater()
        w._store_pins(w.current, [])
        dlg, _why = w._build_handout(row["id"])
        assert dlg.handout().sight is None and not dlg.c_sight.isEnabled()
        dlg.deleteLater()

        # 변화 지도: needs a photo of the same eye of another day
        dlg, why = w._build_change_map()
        assert dlg is None and "다른 날짜" in why
        other = next(r for r in rows if r["laterality"] == "OS")     # the other eye's photo: the same eye, a month before
        db.update_image(other["id"], laterality="OD", exam_date="2025-12-15")
        dlg, why = w._build_change_map()
        assert isinstance(dlg, ChangeDialog) and why == "" and dlg.combo.count() == 1
        assert dlg.view.has_image() and dlg.fit is not None and "2025-12-15" in dlg.lbl_sides.text()
        dlg.set_at(0.2)
        assert dlg.at == 0.2 and dlg.picture() is not None
        dlg.c_mark.setChecked(False)
        dlg.s_sens.slider.setValue(dlg.s_sens.slider.maximum())
        dlg.deleteLater()
        # a photo that cannot be read: said, not raised
        gone = ChangeDialog(Shot(1, "2026-01-02", "", lambda: None), [Shot(2, "2026-01-01", "", lambda: None)])
        assert not gone.view.has_image() and "읽지 못했습니다" in gone.lbl_fit.text()
        gone.deleteLater()
    finally:
        w.close()
        w.deleteLater()
        app.processEvents()
