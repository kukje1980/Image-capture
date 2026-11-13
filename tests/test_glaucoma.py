"""녹내장 분석: the image work (glaucoma.py), the window's four tabs and the main-window flow."""
import os

import numpy as np
import pytest

from fundusview import glaucoma as G
from fundusview.demo import synth_fundus


def _texture(seed=0, size=(240, 320)):
    rng = np.random.default_rng(seed)
    import cv2
    g = cv2.GaussianBlur((rng.random(size) * 255).astype(np.float32), (0, 0), 3)
    g = ((g - g.min()) / (g.max() - g.min()) * 255).astype(np.uint8)
    return np.dstack([g, g // 2 + 60, 255 - g])


# -- image work -------------------------------------------------------------------------------------
def test_fit_and_crop():
    img = np.zeros((1000, 2000, 3), np.uint8)
    assert G.fit(img).shape[:2] == (450, 900) and G.fit_scale(img.shape) == pytest.approx(0.45)
    small = np.full((100, 120, 3), 7, np.uint8)
    assert G.fit(small).shape == small.shape and G.fit(small) is not small
    crop, x0, y0 = G.crop_square(small, 10, 10, 40)
    assert crop.shape == (40, 40, 3) and (x0, y0) == (-10, -10)
    assert crop[0, 0].max() == 0 and crop[-1, -1].min() == 7        # black outside the photo


def test_find_shift_recovers_a_translation():
    a = _texture()
    b = G.shifted(a, -9, 6)
    dx, dy = G.find_shift(a, b)
    assert (dx, dy) == pytest.approx((9, -6), abs=1.5)
    back = G.shifted(b, dx, dy)
    core = (slice(30, -30), slice(30, -30))
    assert np.abs(back[core].astype(int) - a[core].astype(int)).mean() < 12


def test_stereo_pictures():
    a, b = _texture(1), _texture(2)
    sbs = G.side_by_side(a, b)
    assert sbs.shape == (240, 650, 3) and (sbs[:, :320] == a).all() and (sbs[:, 330:] == b).all()
    ana = G.anaglyph(a, b)                                          # left eye red, right eye cyan (RGB)
    import cv2
    assert (ana[..., 0] == cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)).all()
    assert (ana[..., 1] == ana[..., 2]).all() and (ana[..., 1] == cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)).all()


def test_disparity_sees_a_shifted_patch_as_depth():
    left = _texture(3, (300, 400))
    right = left.copy()
    right[100:200, 150:250] = left[100:200, 140:240]                # the middle moved 10 px to the right
    disp = G.disparity(left, right)
    assert disp.shape[1] == 200
    centre, edge = disp[75, 100], disp[20, 30]
    assert abs(centre) > abs(edge) + 1.5
    deep, high = G.disparity_range(disp, 400)
    assert deep >= high
    over = G.depth_overlay(left, disp)
    assert over.shape == left.shape and over.dtype == np.uint8
    if centre > 0:      # deep = blue, raised = red
        assert over[150, 200, 2] > left[150, 200, 2] or over[150, 200, 0] < left[150, 200, 0]
    prof = G.depth_profile(disp, 150, 300, 400)
    assert prof.shape == (120, 400, 3)


def test_cdr_metrics_and_isnt():
    disc = {"cx": 100, "cy": 100, "rx": 50, "ry": 60}
    cup = {"cx": 100, "cy": 100, "rx": 25, "ry": 30}
    m = G.cdr_metrics(disc, cup, "OD")
    assert m["vertical"] == pytest.approx(0.5) and m["horizontal"] == pytest.approx(0.5)
    assert m["area"] == pytest.approx(0.25)
    assert m["rim"]["I"] == pytest.approx(0.25) and m["rim"]["S"] == pytest.approx(0.25)
    # healthy order I ≥ S ≥ N ≥ T: cup towards the temporal side (left in a right eye) and up
    cup2 = {"cx": 97, "cy": 98, "rx": 30, "ry": 30}
    ok = G.cdr_metrics(disc, cup2, "OD")
    assert ok["rim"]["I"] > ok["rim"]["S"] > ok["rim"]["N"] > ok["rim"]["T"] and ok["isnt"] == []
    # the same picture read as a left eye has nasal and temporal exchanged
    os_ = G.cdr_metrics(disc, cup2, "OS")
    assert os_["rim"]["N"] == pytest.approx(ok["rim"]["T"]) and "비측 림이 이측보다 얇음" in os_["isnt"]
    # inferior notch
    low = G.cdr_metrics(disc, {"cx": 100, "cy": 115, "rx": 25, "ry": 40}, "OD")
    assert "하측 림이 상측보다 얇음" in low["isnt"] and low["vertical"] == pytest.approx(40 / 60)


def test_sectors_and_clock_hours():
    disc, fovea = (600.0, 400.0), (340.0, 400.0)                    # right eye: the disc is right of the fovea
    ax = G.axes(disc, fovea)
    assert ax["od"] and ax["t"] == pytest.approx((-1, 0)) and ax["u"] == pytest.approx((0, -1))
    assert ax["rd"] == pytest.approx(50.0)
    up = G.sector_info(disc, fovea, (600, 300))
    assert up["hour"] == 12 and up["dd"] == pytest.approx(1.0)
    temporal = G.sector_info(disc, fovea, (500, 400))
    assert temporal["hour"] == 9 and temporal["sector"] == "이측"
    nasal = G.sector_info(disc, fovea, (700, 400))
    assert nasal["hour"] == 3 and nasal["sector"] == "비측"
    st = G.sector_info(disc, fovea, (550, 320))                     # up and temporal
    assert st["sector"] == "상이측" and "하측" in st["field"]
    it = G.sector_info(disc, fovea, (550, 480))
    assert it["sector"] == "하이측" and "상측" in it["field"]
    # left eye: mirrored — temporal is at 3 o'clock
    l_disc, l_fovea = (340.0, 400.0), (600.0, 400.0)
    assert not G.axes(l_disc, l_fovea)["od"]
    assert G.sector_info(l_disc, l_fovea, (440, 400))["hour"] == 3
    polys = G.sector_polygons(disc, fovea)
    assert [p[0] for p in polys] == [s[0] for s in G.SECTORS]
    for _name, _rgb, pts in polys:
        for x, y in pts:
            assert 1.2 * 50 <= np.hypot(x - 600, y - 400) <= 2.05 * 50
    assert G.disc_fovea_angle(disc, (340.0, 430.0)) > 0 > G.disc_fovea_angle(disc, (340.0, 370.0))


def test_visual_field_points():
    disc, fovea = (600.0, 400.0), (340.0, 400.0)
    pts = G.vf_points(disc, fovea)
    assert len(pts) == 54                                           # 24-2: 54 points (blind spot pair included)
    upper = [p for p in pts if p[2]]
    assert len(upper) == 27 and all(p[1] > 400 for p in upper)      # the upper field lies on the lower retina
    sc = 260 / 15.5
    xs = sorted({round((p[0] - 340) / sc) for p in pts})
    assert xs[0] == -27 and xs[-1] == 21        # 27° into the nasal field (temporal retina), 21° towards the disc


def test_enhance_and_change_map():
    rgb = synth_fundus(eye="OD", fov_deg=45, size=(400, 400), circle=(200, 200, 190), seed=2)
    out = G.enhance_wide(rgb)
    assert out.shape == rgb.shape and (out[..., 0] == out[..., 1]).all()       # red-free: grey
    assert (out[0, 0] == rgb[0, 0]).all()                                       # outside the circle untouched
    assert (G.enhance_wide(rgb, False, 0) == rgb).all()
    colour = G.enhance_wide(rgb, False, 2.0)
    assert not (colour[..., 0] == colour[..., 1]).all()
    same = G.diff_map(rgb, rgb)
    assert (same[..., 0] == same[..., 1]).all()                                 # no change: all grey
    changed = rgb.copy()
    changed[180:220, 180:220] = 255
    d = G.diff_map(rgb, changed)
    assert d[200, 200, 0] > d[200, 200, 1] + 80 and d[200, 200, 2] > d[200, 200, 1]   # pink where it changed
    assert (d[60, 200, 0] == d[60, 200, 1])
    assert (G.blend(rgb, changed, 0.0) == rgb).all()


# -- the window -------------------------------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _photo(image_id, eye="OD", seed=4, when="2026-01-05 10:00:00", shift=0):
    from fundusview import discpair, imaging, measure
    from fundusview.ui.glaucoma_dialog import Photo

    circle = (400, 400, 380)
    rgb = synth_fundus(eye=eye, fov_deg=45, size=(800, 800), circle=circle, seed=seed)
    geo = measure.Geometry(*circle, fov_deg=45, fov_type="external", projection="perspective")
    disc = imaging.detect_disc(rgb, circle, disc_frac=0.085)
    assert disc is not None
    disc_px = discpair.disc_diameter_px(geo, disc[:2], (800, 800))
    if shift:                                                       # the same photo, framed ``shift`` px to the right
        rgb = G.shifted(rgb, shift, 0)
    return Photo(image_id, rgb, eye, (disc[0] + shift, disc[1]), disc_px, (400.0 + shift, 400.0), True, when, "45°")


def test_disc_tab_cuts_around_the_disc_and_measures(app):
    from fundusview.ui.glaucoma_dialog import DiscTab

    tab = DiscTab(_photo(1))
    assert tab.has_image() and tab.img.shape[0] == tab.img.shape[1]
    side = tab.img.shape[0]
    # the ellipses start at the disc's own size: 3.5 disc diameters across the picture
    assert 2 * tab.disc["ry"] == pytest.approx(side / 3.5 * 1.05, rel=0.01)
    assert tab.metrics()["vertical"] == pytest.approx(0.50 / 1.05, abs=0.01)
    assert not tab.warn.isVisibleTo(tab)
    tab.set_field("wide")
    assert 2 * tab.disc["ry"] == pytest.approx(tab.img.shape[0] / 5.0 * 1.05, rel=0.01)
    # drag the cup's lower handle down: the vertical C/D grows, the eye decides nasal / temporal
    c = tab.cup
    tab._press(c["cx"], c["cy"] + c["ry"])
    tab._move(c["cx"], c["cy"] + 1.6 * c["ry"])
    assert tab.metrics()["vertical"] == pytest.approx(1.6 * 0.50 / 1.05, abs=0.02)
    assert tab.lbl_v.text() == f"{tab.metrics()['vertical']:.2f}"
    tab.set_ellipses(tab.disc, {**tab.cup, "cx": tab.cup["cx"] - 10})
    n_od = tab.metrics()["rim"]["N"]
    tab.set_eye("OS")
    assert tab.eye() == "OS" and tab.metrics()["rim"]["T"] == pytest.approx(n_od)
    out = tab.render()
    assert out.shape == tab.img.shape and (out != tab.img).any()                # the ellipses are drawn in
    assert "C/D" in tab.note()


def test_wide_tab_starts_from_the_photo_landmarks(app):
    from fundusview.ui.glaucoma_dialog import WideTab

    ph = _photo(1)
    tab = WideTab(ph)
    assert tab.disc == pytest.approx(ph.disc) and tab.fovea == pytest.approx((400, 400))
    assert tab.tool == "mark" and tab.eye() == "OD"                 # nothing to point at first
    dx, dy = tab.disc
    tab.click(dx, dy - 60)
    tab.c_kind.setCurrentText("디스크 출혈")
    tab.click(dx - 60, dy)
    f = tab.findings()
    assert [x["hour"] for x in f] == [12, 9] and f[1]["kind"] == "디스크 출혈" and f[1]["sector"] == "이측"
    assert "12시 방향" in tab.lbl_list.text() and "소견 2곳" in tab.note()
    grey = tab.render()
    tab.sw_rf.setChecked(False)
    assert not (tab.render() == grey).all()
    tab.clear_marks()
    assert tab.findings() == []
    # a photo without landmarks: point at the disc, then the fovea
    bare = WideTab(type(ph)(2, ph.rgb, None, ph.disc, ph.disc_px, None, False))
    assert bare.disc is None and bare.tool == "disc"
    bare.click(600, 400)
    assert bare.tool == "fovea"
    bare.click(340, 400)
    assert bare.tool == "mark" and bare.eye() == "OD" and "OD" in bare.lbl_geo.text()


def test_pair_tabs_register_and_compose(app):
    from fundusview.ui.glaucoma_dialog import PAIR_PX, ProgressTab, StereoTab

    a, b = _photo(1), _photo(2, shift=12, when="2026-03-01 09:00:00")
    st = StereoTab((a, b))
    assert st.a.shape == (PAIR_PX, PAIR_PX, 3) and st.b.shape == st.a.shape    # both cut around their discs
    assert abs(st.dx) < 6 and abs(st.dy) < 6                        # the discs are centred: nearly registered
    assert st.compose().shape == st.a.shape                         # wiggle: one photo at a time
    first = st.compose().copy()
    st._phase = 1
    assert st.compose() is st._bs and first.shape == st._bs.shape
    for mode, shape in (("sbs", (PAIR_PX, 2 * PAIR_PX + 10)), ("cross", (PAIR_PX, 2 * PAIR_PX + 10)),
                        ("ana", (PAIR_PX, PAIR_PX)), ("depth", (PAIR_PX + 120, PAIR_PX))):
        st.set_mode(mode)
        assert st.compose().shape[:2] == shape and not st._timer.isActive()
    assert "시차" in st.status.text() and st.note() == "스테레오 깊이 지도"
    st.set_mode("wiggle")
    assert st._timer.isActive()
    st.set_region("full")                                           # whole photos: the 12 px shift is found
    assert st.a.shape[:2] == (800, 800) and st.dx == pytest.approx(-12, abs=1.5)
    st.set_offset(100, -100)
    assert (st.dx, st.dy) == (60.0, -40.0)
    st.set_swap(True)
    assert st.eyes()[1] is st.a and st.sw_swap.isChecked()
    st._timer.stop()

    pg = ProgressTab((b, a))                                        # given later-first: the earlier is the baseline
    assert [p.image_id for p in pg.pair] == [1, 2] and "2026-01-05" in pg.lbl_dates.text()
    assert pg.mix.isHidden() and not pg.speed.isHidden()
    pg.set_mode("blend")
    assert not pg.mix.isHidden() and pg.speed.isHidden() and not pg._timer.isActive()
    assert pg.compose().shape == pg.a.shape
    pg.set_mode("diff")
    d = pg.compose()
    assert d.shape == pg.a.shape
    assert pg.note() == "녹내장 분석 — 경과 비교 (2026-01-05 → 2026-03-01)" and pg.eye() == "OD"

    empty = StereoTab(None)
    assert not empty.has_image() and empty.compose() is None and not empty._timer.isActive()
    empty.auto_align()
    empty.set_offset(3, 3)


def test_dialog_saves_what_it_shows(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    saved = []

    def save(rgb, note, eye, ids):
        saved.append((rgb.shape, note, eye, ids))
        return 77

    one = GlaucomaDialog(_photo(1), title_line="홍길동", save_record=save)
    assert one.tabs.currentWidget() is one.disc and not one.stereo.has_image()
    assert one.save_to_record() == 77 and saved[-1][2:] == ("OD", [1]) and "C/D" in saved[-1][1]
    one.tabs.setCurrentWidget(one.stereo)                           # no pair: nothing to save
    assert one.save_to_record() is None and len(saved) == 1 and "없습니다" in one.status.text()
    one.copy()
    assert "없습니다" in one.status.text()

    a, b = _photo(1), _photo(2, when="2026-03-01 09:00:00")
    two = GlaucomaDialog(a, b, save_record=save)
    assert two.tabs.currentWidget() is two.progress                 # two days: a follow-up
    two.progress._timer.stop()
    two.stereo._timer.stop()
    assert two.save_to_record() == 77 and saved[-1][3] == [1, 2] and saved[-1][0] == two.progress.a.shape
    same_day = GlaucomaDialog(a, _photo(3, seed=5))
    assert same_day.tabs.currentWidget() is same_day.stereo and not same_day.b_record.isEnabled()
    same_day.stereo._timer.stop()
    same_day.progress._timer.stop()

    out = tmp_path / "분석"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    two.tabs.setCurrentWidget(two.wide)
    two.save_file()
    assert (tmp_path / "분석.jpg").stat().st_size > 1000
    two.copy()
    assert not QApplication.clipboard().image().isNull() or "복사" in two.status.text()


def test_main_window_flow(app, demo_dir, tmp_path, monkeypatch, import_and_wait):
    from PySide6.QtWidgets import QMessageBox

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.models import MODALITY_LABELS
    from fundusview.ui.main_window import MainWindow

    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, title, text, *a, **k: said.append((title, text)))
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    w = MainWindow(s, Database(tmp_path / "lib" / "fundus.db"))
    try:
        w.show()
        assert w.btn_glaucoma.text() == "녹내장" and "glaucoma" in w.acts and "glaucoma" in MODALITY_LABELS
        w.open_glaucoma()                                           # no photo yet
        assert said and said[-1] == ("녹내장 분석", "사진을 고르세요.")
        import_and_wait(app, w, [demo_dir / "PatientCapture", demo_dir / "RetiCam"])
        by_patient = {}
        for pt in w.db.list_patients():
            rows = [r for r in w.db.images_for_patient(pt["id"]) if r["modality"] not in ("anterior", "disc")]
            if rows:
                by_patient[pt["id"]] = rows
        first, second = next(v for v in by_patient.values() if len(v) >= 2)[:2]
        w.current = w.db.get_image(first["id"])
        w.compare = None

        dlg, why = w._build_glaucoma()
        assert why == "" and dlg.disc.has_image() and dlg.wide.has_image() and not dlg.stereo.has_image()
        assert dlg.disc.photo.disc_px > 4
        n = len(w.db.images_for_patient(first["patient_ref"]))
        new_id = dlg.save_to_record()
        row = w.db.get_image(new_id)
        assert len(w.db.images_for_patient(first["patient_ref"])) == n + 1
        assert row["modality"] == "glaucoma" and row["patient_ref"] == first["patient_ref"]
        assert "C/D" in row["note"] and row["disc_x"] is None and row["fov_deg"] is None
        assert first["id"] in (__import__("json").loads(row["meta_json"])["derived_from"])
        assert dlg.save_to_record() == new_id                       # the same picture is stored once

        pair, why = w._build_glaucoma(second["id"])
        assert why == "" and pair.stereo.has_image() and pair.progress.has_image()
        assert pair.stereo.image_ids() == [first["id"], second["id"]]
        for t in (pair.stereo, pair.progress):
            t._timer.stop()

        w.current = row                                             # an analysis picture is not analysed again
        again, why = w._build_glaucoma()
        assert again is None and "녹내장 분석" in why
        other = next((v[0] for k, v in by_patient.items() if k != first["patient_ref"]), None)
        if other is not None:
            w.current = w.db.get_image(first["id"])
            assert w._build_glaucoma(other["id"]) == (None, "서로 다른 환자의 사진입니다.")
    finally:
        w.close()
