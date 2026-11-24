"""녹내장 분석 → 시간별 비교: several photos of one eye's disc in the order of time (timeline.py,
ui/timeline_tab.py) and the way there from the main window."""
import cv2
import numpy as np
import pytest

from fundusview import glaucoma as G
from fundusview import timeline as T
from fundusview.demo import synth_fundus


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _photo(image_id, when, shift=0, cup=0, eye="OD"):
    """The same eye framed ``shift`` px to the right, its cup ``cup`` px larger."""
    from fundusview import discpair, imaging, measure
    from fundusview.ui.glaucoma_dialog import Photo

    circle = (400, 400, 380)
    rgb = synth_fundus(eye=eye, fov_deg=45, size=(800, 800), circle=circle, seed=4)
    geo = measure.Geometry(*circle, fov_deg=45, fov_type="external", projection="perspective")
    disc = imaging.detect_disc(rgb, circle, disc_frac=0.085)
    assert disc is not None
    disc_px = discpair.disc_diameter_px(geo, disc[:2], (800, 800))
    if cup:
        rgb = rgb.copy()
        cv2.circle(rgb, (round(disc[0]), round(disc[1])), cup, (255, 240, 210), -1, cv2.LINE_AA)
    if shift:
        rgb = G.shifted(rgb, shift, 0)
    return Photo(image_id, rgb, eye, (disc[0] + shift, disc[1]), disc_px, None, True, when, "45°")


def _shots(n=4, reads=None):
    days = ["2019-03-02", "2021-06-15", "2023-01-10", "2024-09-30", "2025-02-01", "2026-03-01"][:n]
    out = []
    for i, day in enumerate(days):
        def load(i=i, day=day):
            if reads is not None:
                reads.append(i + 1)
            return _photo(i + 1, f"{day} 10:00:00", shift=3 * i, cup=4 + 3 * i)
        out.append(T.Shot(i + 1, f"{day} 10:00:00", "OD", "45° · 컬러", load))
    return out


def test_intervals_order_and_the_photos_shown_at_first():
    assert T.interval_text("2024-01-10", "2024-01-10") == "기준일"
    assert T.interval_text("2024-01-10", "2024-01-22") == "+12일"
    assert T.interval_text("2024-01-10", "2024-04-09") == "+2개월"
    assert T.interval_text("2024-01-10", "2025-01-10") == "+1년"
    assert T.interval_text("2019-03-02", "2026-03-01") == "+6년 11개월"
    assert T.interval_text("2024-04-10", "2024-01-10") == "−3개월" and T.interval_text("", "2024-01-10") == ""
    assert T.days_between("2024-01-10", "2024-01-22") == 12 and T.days_between("?", "2024-01-22") is None

    shots = [T.Shot(3, "2024-01-10 09:00:00"), T.Shot(1, ""), T.Shot(2, "2020-05-05 09:00:00")]
    assert [s.image_id for s in T.in_order(shots)] == [2, 3, 1]                 # no date: last

    many = [T.Shot(i, f"20{10 + i // 2:02d}-01-01 1{i % 2}:00:00") for i in range(40)]   # 20 days, two photos each
    first = T.pick_default(many, current_id=21, limit=12)
    assert len(first) == 12 and first == sorted(first) and 21 in first          # the photo on screen stands for its day
    assert first[0] in (0, 1) and first[-1] in (38, 39)                         # the oldest and the newest day stay
    assert len({i // 2 for i in first}) == 12                                   # one photo a day
    assert T.pick_default(many[:6], current_id=3) == [0, 3, 4]                  # three days: all of them
    assert T.pick_default(many, 21, 12, prefer=[30, 2, 8]) == [2, 8, 21, 30]    # picked by hand (and the one on screen)
    assert T.pick_default(many, 21, 12, prefer=[30]) == first                   # one picked photo is no series
    assert T.spread(5, 9) == [0, 1, 2, 3, 4] and T.spread(100, 5) == [0, 24, 49, 74, 99]
    assert T.spread(100, 4, keep=[3]) == [0, 3, 51, 99]


def test_sheet_crossfade_and_time_marks():
    assert [T.grid_shape(n) for n in (1, 2, 3, 4, 5, 6, 9, 10, 12)] == [
        (1, 1), (1, 2), (1, 3), (2, 2), (2, 3), (2, 3), (3, 3), (3, 4), (3, 4)]
    frames = [np.full((T.FRAME_PX, T.FRAME_PX, 3), 40 * i, np.uint8) for i in range(5)]
    img, cells = T.sheet(frames, gap=8)
    c = T.cell_px(5)
    assert c == T.FRAME_PX and img.shape == (2 * c + 8, 3 * c + 16, 3) and len(cells) == 5
    assert cells[3] == (0, c + 8, c, c) and int(img[c + 20, 10, 0]) == 120 and int(img[-5, -5, 0]) == 0
    assert T.cell_at(cells, c + 20, 10) == 1 and T.cell_at(cells, c + 4, 10) is None      # (the gap)
    assert T.cell_px(12) == 540 and T.sheet(frames * 2 + frames[:2])[0].shape[1] == 4 * 540 + 24

    assert T.crossfade(frames, 0) is frames[0] and T.crossfade(frames, 2) is frames[2]
    assert T.crossfade(frames, 9) is frames[4]
    assert int(T.crossfade(frames, 1.5)[0, 0, 0]) == 60                           # halfway from the 2nd to the 3rd
    assert T.time_marks(["2020-01-01", "2021-01-01", "2024-01-01"]) == pytest.approx([0, 0.2505, 1], abs=1e-3)
    assert T.time_marks(["2020-01-01", "", "2024-01-01"]) == [0, 0.5, 1] and T.time_marks(["2020-01-01"]) == [0.0]


def test_frames_are_laid_onto_the_first():
    a, b = _photo(1, "2020-01-01 10:00:00"), _photo(2, "2024-01-01 10:00:00", shift=9)
    fa, fb = T.frames_of(a.rgb, a.disc, a.disc_px), T.frames_of(b.rgb, b.disc, b.disc_px)
    assert set(fa) == {"near", "disc", "wide"} and fa["near"].shape == (T.FRAME_PX, T.FRAME_PX, 3)
    # the same disc cut around its own centre: already nearly on top of each other, and found so
    fit = T.register(fa["disc"], fb["disc"])
    assert fit.how in ("turn", "shift") and abs(fit.dx) < 4 and abs(fit.dy) < 4 and "좌우" in fit.text()
    moved = G.shifted(fb["disc"], 14, -6)                                         # … and moved away: brought back
    back = T.register(fa["disc"], moved)
    assert back.dx == pytest.approx(-14, abs=2.5) and back.dy == pytest.approx(6, abs=2.5)
    laid = T.applied(moved, back)
    core = (slice(80, -80), slice(80, -80))
    err = lambda x: float(np.abs(x[core].astype(int) - fa["disc"][core].astype(int)).mean())   # noqa: E731
    assert err(laid) < err(moved) * 0.6
    assert T.applied(fb["disc"], T.Fit()) is fb["disc"] and T.Fit().text() == "맞추지 않음"
    assert T.applied(fb["disc"], T.Fit(), (5, 0)).shape == fb["disc"].shape


def test_tab_shows_the_photos_side_by_side_and_on_top_of_each_other(app):
    from fundusview.ui.timeline_tab import TimelineTab

    reads = []
    tab = TimelineTab(_shots(4, reads), current_id=4)
    assert tab.checked == [1, 2, 3, 4] and not reads and not tab.has_image()      # nothing read before it is shown
    tab.ensure_loaded()
    assert sorted(reads) == [1, 2, 3, 4] and tab.has_image() and tab.selected == 4
    c = T.cell_px(4)
    assert tab.view.render_rgb().shape == (2 * c + 8, 2 * c + 8, 3) and len(tab._cells) == 4      # 나란히: 2 × 2
    assert tab.reference().image_id == 1 and tab.fit_of(1).how == "none" and tab.fit_of(3).how in ("turn", "shift")
    assert "2019-03-02 → 2024-09-30" in tab.lbl_span.text() and "5년 6개월" in tab.lbl_span.text()
    assert "+2년 3개월" in tab.list.item(1).text() and "기준일" in tab.list.item(0).text()
    assert tab.note() == "녹내장 분석 — 시간별 비교 나란히 (2019-03-02 → 2024-09-30, 4장)"
    assert tab.image_ids() == [1, 2, 3, 4] and tab.eye() == "OD"
    x, y, w, h = tab._cells[1]
    tab._press(x + w / 2, y + h / 2)                                              # a click on the second photo
    assert tab.selected == 2 and tab.list.currentRow() == 1 and tab.s_dx.isEnabled()
    tab._press(5, 5)
    assert tab.selected == 1 and not tab.s_dx.isEnabled() and "기준 사진" in tab.status.text()

    tab.select(3)
    tab.set_mode("overlay")                                                       # 겹치기: the time slider
    assert tab.pos == 2.0 and not tab.s_time.isHidden() and tab.speed.isHidden() is False
    assert tab.compose() is tab._laid[3] and tab.compose().shape == (T.FRAME_PX, T.FRAME_PX, 3)
    tab.set_pos(0.5)
    mix = tab.compose()
    want = G.blend(tab._laid[1], tab._laid[2], 0.5)
    assert np.array_equal(mix, want) and "2019-03-02 → 2021-06-15  50%" == tab._pos_text()
    tab.set_pos(2.6)
    assert tab.selected == 4                                                      # the nearest photo is the selected one
    tab.set_pos(99)
    assert tab.pos == 3.0 and tab._pos_text() == "2024-09-30"
    assert tab.view.render_rgb().shape == (T.FRAME_PX, T.FRAME_PX, 3)             # (with the date and the time line)

    tab.set_mode("flick")                                                         # 넘겨 보기: one after the other
    seen = []
    for _ in range(5):
        seen.append(next(i for i, f in tab._laid.items() if f is tab.compose()))
        tab._phase += 1
    assert seen == [1, 2, 3, 4, 1]
    tab.sw_two.setChecked(True)
    tab.select(3)
    tab._phase = 0
    assert tab.compose() is tab._laid[1]
    tab._phase = 1
    assert tab.compose() is tab._laid[3]

    tab.set_mode("diff")                                                          # 변화 지도: the first against the chosen
    d = tab.compose()
    assert d.shape == (T.FRAME_PX, T.FRAME_PX, 3)
    pink = (d[..., 0].astype(int) - d[..., 1] > 120).sum()
    assert pink > 200                                                             # the cup that grew
    assert tab.note().startswith("녹내장 분석 — 시간별 비교 변화 지도")


def test_tab_photos_are_chosen_moved_and_cut_wider(app):
    from PySide6.QtCore import Qt

    from fundusview.ui.timeline_tab import NEED, TimelineTab

    reads = []
    tab = TimelineTab(_shots(6, reads), current_id=6, prefer=[2, 5])
    assert tab.checked == [2, 5, 6]                                               # the picked ones, and the one on screen
    tab.ensure_loaded()
    assert sorted(reads) == [2, 5, 6] and tab.reference().image_id == 2
    tab.list.item(0).setCheckState(Qt.CheckState.Checked)                         # one more by its check mark
    assert tab.checked == [1, 2, 5, 6] and sorted(reads) == [1, 2, 5, 6] and tab.reference().image_id == 1
    tab.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert tab.image_ids() == [1, 5, 6] and len(reads) == 4
    tab.b_ends.click()
    assert tab.image_ids() == [1, 6] and tab.view.render_rgb().shape[1] == 2 * T.FRAME_PX + 8
    tab.reset_checked()
    assert tab.image_ids() == [2, 5, 6]

    tab.select(5)
    before = tab._laid[5].copy()
    tab.set_nudge(10, 0)                                                          # by hand, on top of the automatic fit
    assert not np.array_equal(tab._laid[5], before) and "손으로" in tab.status.text() and tab.s_dx.value() == 10
    tab.set_region("wide")                                                        # another field: its own fit, no nudge
    assert tab.region == "wide" and tab.s_dx.value() == 0 and (5, "wide", 2) in tab._fits
    tab.set_region("near")
    assert tab.s_dx.value() == 10
    tab.realign()
    assert tab.s_dx.value() == 0 and np.array_equal(tab._laid[5], before)
    tab.set_aligned(False)                                                        # as they are
    assert tab._laid[5] is tab._frames[5]["near"] and tab.fit_of(5).how == "none"

    full = TimelineTab(_shots(2) + [T.Shot(9, "2026-05-05 10:00:00", "OD", "", lambda: None)], current_id=1)
    full.ensure_loaded()                                                          # a file that cannot be read
    assert full.image_ids() == [1, 2] and "읽지 못함" in full.list.item(2).text()

    for empty in (TimelineTab(None), TimelineTab(_shots(1), current_id=1)):       # no series
        empty.ensure_loaded()
        assert not empty.has_image() and empty.compose() is None and empty.view._placeholder == NEED
        empty.set_mode("overlay")
        empty.set_pos(1)
        empty.set_nudge(1, 1)
        empty.realign()
        assert empty.image_ids() == [] and empty.eye() is None


def test_dialog_has_the_tab_and_saves_it(app):
    from fundusview.ui.glaucoma_dialog import GlaucomaDialog

    saved = []
    dlg = GlaucomaDialog(_photo(4, "2024-09-30 10:00:00"), series=_shots(4), start="timeline",
                         save_record=lambda *a: saved.append(a) or 31)
    assert dlg.tabs.currentWidget() is dlg.timeline and dlg.tabs.tabText(dlg.tabs.indexOf(dlg.timeline)) == "시간별 비교"
    dlg.timeline.ensure_loaded()
    assert dlg.save_to_record() == 31
    rgb, note, eye, ids = saved[-1]
    assert rgb.shape[2] == 3 and "시간별 비교" in note and eye == "OD" and ids == [1, 2, 3, 4]
    plain = GlaucomaDialog(_photo(4, "2024-09-30 10:00:00"))                      # no series: the tab says so
    assert plain.tabs.currentWidget() is plain.disc and not plain.timeline.has_image()


def test_main_window_collects_the_photos_of_the_eye(app, tmp_path, import_and_wait):
    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.demo import write_demo_folder
    from fundusview.ui.main_window import MainWindow

    demo_dir = tmp_path / "drop"
    write_demo_folder(demo_dir, small=True, history=True)           # the same eyes at two earlier visits too
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False)
    w = MainWindow(s, Database(tmp_path / "lib" / "fundus.db"))
    try:
        w.show()
        btn = w.tb_cmd.widgetForAction(w.acts["glaucoma"])
        assert [a.text() for a in btn.menu().actions()][2].startswith("시간별 비교")
        import_and_wait(app, w, [demo_dir / "PatientCapture", demo_dir / "RetiCam"])
        first = None
        for pt in w.db.list_patients():                             # a patient with two photos of one eye
            rows = [r for r in w.db.images_for_patient(pt["id"])
                    if r["disc_x"] is not None and r["laterality"] in ("OD", "OS") and r["modality"] == "color"]
            same = [r for r in rows if r["laterality"] == rows[0]["laterality"]] if rows else []
            if len(same) >= 2:
                first, others = same[0], same[1:]
                break
        assert first is not None and len({r["exam_date"] for r in [first] + others}) >= 2
        w._select_patient_ref(first["patient_ref"])
        w._show_image(first["id"])
        w.compare = None
        app.processEvents()
        dlg, why = w._build_glaucoma(start="timeline")
        assert why == "" and dlg.tabs.currentWidget() is dlg.timeline
        tab = dlg.timeline
        ids = {s.image_id for s in tab.shots}
        assert first["id"] in ids and all(o["id"] in ids for o in others)
        assert all(s.eye == first["laterality"] for s in tab.shots)               # this eye only
        tab.set_checked(ids)
        tab.ensure_loaded()
        assert set(tab.image_ids()) == ids and tab.has_image()
        n = len(w.db.images_for_patient(first["patient_ref"]))
        new_id = dlg.save_to_record()
        row = w.db.get_image(new_id)
        assert row["modality"] == "glaucoma" and "시간별 비교" in row["note"]
        assert len(w.db.images_for_patient(first["patient_ref"])) == n + 1
        again, _ = w._build_glaucoma(start="timeline")                            # the saved sheet is no photo of the eye
        assert {s.image_id for s in again.timeline.shots} == ids
    finally:
        w.close()
