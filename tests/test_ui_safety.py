"""Patient/eye identity and geometry stay consistent through failure and shared edits."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from fundusview import timeline as T
from fundusview.config import Settings
from fundusview.db import Database
from fundusview.models import ExtractedMeta
from fundusview.ui.glaucoma_dialog import DiscTab, Photo, ProgressTab, StereoTab, Surface3DTab
from fundusview.ui.main_window import MainWindow
from fundusview.ui.timeline_tab import TimelineTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_startup", lambda self: None)
    db = Database(tmp_path / "lib" / "fundus.db")
    a = db.upsert_patient(ExtractedMeta(patient_id="SYNTHETIC-A", name="Synthetic A"))
    b = db.upsert_patient(ExtractedMeta(patient_id="SYNTHETIC-B", name="Synthetic B"))
    rgb = np.full((200, 200, 3), [100, 60, 30], np.uint8)
    rgb[80:120, 110:150] = [210, 190, 130]
    path = tmp_path / "photo.png"
    Image.fromarray(rgb).save(path)
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"incomplete image")
    common = dict(patient_ref=a, exam_date="2026-10-22", exam_time="12:00:00", modality="color",
                  profile="generic", fov_deg=45, fov_type="external", projection="perspective",
                  width=200, height=200, circle_cx=100, circle_cy=100, circle_r=98,
                  disc_x=140, disc_y=100, fovea_x=100, fovea_y=100, meta_json={},
                  file_path=str(path), original_path=str(path))

    def image(key, **fields):
        return db.insert_image(**{**common, "sha256": key, **fields})

    ids = {"od": image("od", laterality="OD"),
           "od2": image("od2", laterality="OD", exam_date="2026-11-22"),
           "os": image("os", laterality="OS", disc_x=60, exam_date="2026-11-22"),
           "unknown": image("unknown", laterality=None, disc_x=None, disc_y=None),
           "missing": image("missing", patient_ref=b, laterality="OD", file_path=str(tmp_path / "missing.png"),
                            original_path=str(tmp_path / "missing.png")),
           "corrupt": image("corrupt", patient_ref=b, laterality="OD", file_path=str(corrupt),
                            original_path=str(corrupt))}
    settings = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False,
                        rescan_seconds=0, auto_detect=False, ui_version=MainWindow.UI_VERSION)
    w = MainWindow(settings, db)
    try:
        yield w, ids, (a, b), rgb
    finally:
        w.close()
        app.processEvents()
        w.deleteLater()
        db.close()


def _show(w, patient, image_id):
    w._set_patient(patient)
    w._show_image(image_id)
    w._update_3d()


def _assert_detail_empty(w):
    for view in (w.view2d, w.ov_macula, w.ov_zoom):
        assert not view.has_image()
        assert view.geometry is None
    assert w.eye3d._rgba is None and w.eye3d._marks == (None, None, None)
    assert not w.scan_photo.has_image() and w.scan_photo.scan is None
    assert w.photo3d._pix is None and w.photo3d.circle is None and w.photo3d.disc is None
    assert w.photo3d.fovea is None and w.photo3d.picking is None
    assert not w.pair3d.image_ids
    assert all(eye._rgba is None and eye._marks == (None, None, None) for eye in w.pair3d.eyes)
    assert w._ov_img is None and not w._ov_targets
    assert all(not roi.isVisible() for roi in w._ov_rois.values())
    assert not w.lbl_info.toolTip()
    assert not w.lbl_found3d.text() and w._marking3d is None
    assert not w.b_mark_fovea.isChecked() and not w.b_mark_disc.isChecked()
    assert not w.b_save_map.isEnabled() and not w.sp_fov.isEnabled()


@pytest.mark.parametrize("failure", ["missing", "corrupt", None])
def test_failed_or_empty_selection_clears_every_patient_panel(window, failure):
    w, ids, (a, b), rgb = window
    _show(w, a, ids["od"])
    w._set_marking3d("fovea")
    assert w._open_pair3d([ids["od"], ids["od2"]])
    for view in (w.ov_macula, w.ov_zoom):
        view.set_rgb(rgb)
        view.geometry = w.view2d.geometry
    w.multi.set_count(4, quiet=True)
    w.multi.populate([(ids["od"], "old", rgb)] * 4, ids["od"])
    w.multi.set_count(1, quiet=True)       # hidden cells must also lose the previous patient's pixels
    if failure is None:
        w._show_image(None)
    else:
        w._set_patient(b)
        w._show_image(ids[failure])
        assert w.current["id"] == ids[failure] and "Synthetic B" in w.banner.text()
    _assert_detail_empty(w)
    assert all(cell.image_id is None and not cell.view.has_image() for cell in w.multi.cells)
    assert all(not view.has_image() for cell in w.multi.cells for view in cell.zooms.values())


def test_3d_reload_failure_clears_the_previous_texture(window):
    w, ids, (a, _), _rgb = window
    _show(w, a, ids["od"])
    assert w.eye3d._rgba is not None
    w.current = w.db.get_image(ids["missing"])
    w._update_3d()
    _assert_detail_empty(w)


def _photo(image_id, eye="OD", day="2026-11-22"):
    rgb = np.full((160, 160, 3), [100, 60, 30], np.uint8)
    rgb[60:100, 60:100] = [230, 210, 160]
    return Photo(image_id, rgb, eye, (80, 80), 40, when=day)


@pytest.mark.parametrize("other_eye", ["OS", None])
def test_pair_tabs_require_the_same_known_eye_but_allow_individual_viewing(app, other_eye):
    first, other = _photo(1), _photo(2, other_eye)
    stereo, progress = StereoTab((first, other)), ProgressTab((first, other))
    surface = Surface3DTab(first, other)
    try:
        assert not stereo.has_image() and not progress.has_image()
        assert stereo.pair is None and progress.pair is None
        assert surface.has_image() and surface.source == "a"
        surface.set_source("stereo")
        assert surface.source == "a" and surface._surface("stereo") is None
        surface.set_source("b")
        assert surface.source == "b" and surface.has_image() and surface.eye() == other_eye
        assert surface.both() is None
        surface.sw_flick.setChecked(True)       # programmatic changes cannot bypass the disabled switch
        assert not surface._flickering()
    finally:
        for tab in (stereo, progress, surface):
            tab._timer.stop()
            tab.close()
            tab.deleteLater()


def test_timeline_filters_explicit_other_eye_and_unknown_sources(app):
    photos = [_photo(1, "OD", "2026-10-22"), _photo(2, "OS"), _photo(3, None), _photo(4, "OD")]
    shots = [T.Shot(p.image_id, p.when, p.eye, load=lambda p=p: p) for p in photos]
    tab = TimelineTab(shots, current_id=1, prefer=[1, 2, 3, 4])
    try:
        tab.set_checked([1, 2, 3, 4])
        tab.ensure_loaded()
        assert tab.image_ids() == [1, 4] and tab.eye() == "OD"
        assert tab.has_image()
    finally:
        tab.close()
        tab.deleteLater()
    unknown = TimelineTab(shots, current_id=3)
    try:
        unknown.ensure_loaded()
        assert not unknown.has_image() and unknown.image_ids() == []
    finally:
        unknown.close()
        unknown.deleteLater()


def test_individual_unknown_eye_is_not_silently_labelled_od(app):
    tab = DiscTab(_photo(1, None))
    try:
        assert tab.has_image() and tab.metrics() is not None and tab.eye() is None
        assert tab.eyes.key() == "" and "확인해야" in tab.lbl_rim.text()
        tab.set_eye("OS")
        assert tab.eye() == "OS" and "ISNT" in tab.lbl_rim.text()
    finally:
        tab.close()
        tab.deleteLater()


def test_explicit_odos_builder_keeps_individual_tools_and_only_same_eye_timeline(window):
    w, ids, (a, _), _rgb = window
    _show(w, a, ids["od"])
    dlg, why = w._build_glaucoma(ids["os"], start="timeline")
    try:
        assert not why and dlg.disc.has_image() and dlg.surface.has_image()
        assert not dlg.stereo.has_image() and not dlg.progress.has_image()
        dlg.timeline.ensure_loaded()
        assert {s.eye for s in dlg.timeline.shots} == {"OD"}
        assert ids["os"] not in dlg.timeline.image_ids()
        new_id = dlg.save_to_record()
        saved = w.db.get_image(new_id)
        assert saved["laterality"] == "OD"
        assert "시간별 비교" in saved["note"]
    finally:
        for tab in (dlg.stereo, dlg.progress, dlg.surface, dlg.timeline):
            tab._timer.stop()
        dlg.close()
        dlg.deleteLater()


def test_save_boundary_rejects_mixed_eyes_patients_and_unknown_comparisons(window):
    w, ids, (a, b), rgb = window
    _show(w, a, ids["od"])
    for second in (ids["os"], ids["unknown"], ids["missing"]):
        with pytest.raises(ValueError):
            w._save_glaucoma(rgb, "invalid", "OD", [ids["od"], second])
    with pytest.raises(ValueError):
        w._save_glaucoma(rgb, "invalid", None, [ids["od"], ids["od2"]])
    with pytest.raises(ValueError):
        w._save_glaucoma(rgb, "invalid", "OD", [])
    with pytest.raises(ValueError):
        w._save_glaucoma(rgb, "invalid", "OD", [ids["od"], 99999])
    # A single-eye image can be viewed/saved without inventing an OD label when the eye is unknown.
    saved = w._save_glaucoma(rgb, "individual unknown eye", None, [ids["unknown"]])
    assert w.db.get_image(saved)["laterality"] is None


def test_open_analysis_does_not_save_after_sources_move_to_another_patient(window):
    w, ids, (a, b), _rgb = window
    _show(w, a, ids["od"])
    dlg, _ = w._build_glaucoma()
    try:
        before = len(w.db.images_for_patient(b))
        w.db.update_image(ids["od"], patient_ref=b)
        assert dlg.save_to_record() is None
        assert "환자 소속" in dlg.status.text()
        assert len(w.db.images_for_patient(b)) == before + 1      # moved source only, no derived image
    finally:
        for tab in (dlg.stereo, dlg.progress, dlg.surface, dlg.timeline):
            tab._timer.stop()
        dlg.close()
        dlg.deleteLater()


def test_shared_geometry_and_patient_edits_refresh_the_current_views(window):
    w, ids, (a, _), rgb = window
    _show(w, a, ids["od"])
    w._go("all")
    w._share_sig = w._photo_sig()
    old_generation = w._preloader.generation
    w.db.update_patient(a, name="Synthetic A corrected")
    w.db.update_image(ids["od"], fov_deg=176, fov_type="internal", projection="radial",
                      disc_x=145, disc_y=98, fovea_x=88, fovea_y=102)
    w._on_shared_change()
    assert w.current["fov_deg"] == 176 and w.current["fovea_x"] == 88
    assert w.view2d.geometry.fov_deg == 176 and w.view2d.geometry.projection == "radial"
    assert w.eye3d._marks == ((145, 98), (88, 102), (100, 100, 98))
    assert w.photo3d.disc == (145, 98) and w.photo3d.fovea == (88, 102)
    assert "corrected" in w.banner.text()
    # A result queued before the shared refresh cannot repopulate an invalidated photo cache.
    w._cache.pop(ids["od2"], None)
    w._on_preloaded(ids["od2"], rgb, old_generation)
    assert ids["od2"] not in w._cache
    w._on_preloaded(ids["od2"], rgb, w._preloader.generation)
    assert ids["od2"] in w._cache


def test_shared_file_change_invalidates_cached_pixels(window, tmp_path):
    w, ids, (a, _), rgb = window
    _show(w, a, ids["od"])
    w._share_sig = w._photo_sig()
    changed = np.full_like(rgb, [20, 150, 50])
    path = tmp_path / "changed.png"
    Image.fromarray(changed).save(path)
    w.db.update_image(ids["od"], file_path=str(path), original_path=str(path), sha256="replacement")
    w._on_shared_change()
    assert np.array_equal(w.view2d._rgb, changed)


def _close_analysis(dlg):
    for tab in (dlg.stereo, dlg.progress, dlg.surface, dlg.timeline):
        tab._timer.stop()
    dlg.close()
    dlg.deleteLater()


@pytest.mark.parametrize("changed", [{"laterality": "OS"}, {"fov_deg": 176},
                                     {"disc_x": 120, "fovea_x": 90}, {"exam_date": "2026-11-21"}])
def test_single_analysis_rejects_source_metadata_changed_after_open(window, changed):
    w, ids, (a, _), _rgb = window
    _show(w, a, ids["od"])
    dlg, _ = w._build_glaucoma()
    try:
        before = len(w.db.images_for_patient(a))
        w.db.update_image(ids["od"], **changed)
        assert dlg.save_to_record() is None
        assert "원본 사진 정보" in dlg.status.text()
        assert len(w.db.images_for_patient(a)) == before
    finally:
        _close_analysis(dlg)


def test_single_analysis_allows_intentional_output_eye_correction(window):
    w, ids, (a, _), _rgb = window
    _show(w, a, ids["od"])
    dlg, _ = w._build_glaucoma()
    try:
        dlg.disc.set_eye("OS")              # output eye is the user's choice; the source has not changed
        result = dlg.save_to_record()
        assert result is not None and w.db.get_image(result)["laterality"] == "OS"
        assert w.db.get_image(ids["od"])["laterality"] == "OD"
    finally:
        _close_analysis(dlg)


def test_single_timeline_source_uses_its_original_metadata_snapshot(window):
    w, ids, (a, _), _rgb = window
    _show(w, a, ids["od"])
    dlg, _ = w._build_glaucoma(start="timeline")
    try:
        dlg.timeline.set_checked([ids["od2"]])    # lazy series source, not the initial explicit photo
        dlg.timeline.ensure_loaded()
        assert dlg.timeline.image_ids() == [ids["od2"]]
        before = len(w.db.images_for_patient(a))
        w.db.update_image(ids["od2"], fov_deg=176)
        assert dlg.save_to_record() is None and "원본 사진 정보" in dlg.status.text()
        assert len(w.db.images_for_patient(a)) == before
    finally:
        _close_analysis(dlg)


@pytest.mark.parametrize("change", ["move", "delete"])
def test_shared_refresh_drops_compare_that_no_longer_belongs_to_current_patient(window, change):
    w, ids, (a, b), _rgb = window
    _show(w, a, ids["od"])
    w.compare = w.db.get_image(ids["os"])
    w._share_sig = w._photo_sig()
    if change == "move":
        w.db.update_image(ids["os"], patient_ref=b)
    else:
        w.db.delete_image(ids["os"])
    w._on_shared_change()
    assert w.compare is None
    dlg, why = w._build_glaucoma()
    try:
        assert not why and dlg.disc.has_image() and not dlg.stereo.has_image()
    finally:
        _close_analysis(dlg)


