"""카메라 각도 보정: the lens curve of the wide-field camera from the disc–fovea distance of many photos."""
import json
import math
import os

import numpy as np
import pytest

from fundusview import calibrate as cal
from fundusview import placement, profiles
from fundusview import projection as proj

FOV = 176.0


def _photo(rng, c_true: float, *, apart=None, r=1000.0, image_id=None, by_hand=False) -> cal.Sample:
    """A photo of an eye whose disc and fovea lie ``apart``° apart (an eye of its own: ± 6 %), taken
    with a little off-centre gaze through a lens of curve ``c_true``."""
    apart = placement.DISC_FOVEA_DEG * (1.0 + 0.06 * rng.standard_normal()) if apart is None else apart
    cam = placement.Camera(r, r, r, FOV, "internal", "radial", radial_c=c_true)
    off, turn = math.radians(rng.uniform(0.0, 8.0)), rng.uniform(0.0, 2 * math.pi)
    fovea = np.array(proj.sphere_point(off, turn))
    side = rng.uniform(0.0, 2 * math.pi)
    disc = placement._axis_angle(fovea, side) @ placement._axis_angle(
        np.cross(fovea, [0.0, 1.0, 0.0]), math.radians(apart)) @ fovea
    return cal.Sample((r, r, r), cam.pixel(disc), cam.pixel(fovea), image_id, by_hand)


def test_the_lens_curve_comes_back_from_many_eyes():
    rng = np.random.default_rng(3)
    samples = [_photo(rng, 0.42) for _ in range(60)]
    res = cal.fit_curve(samples, FOV, proj.DEFAULT_RADIAL_C)
    assert res is not None and res.used >= 55 and not res.few and res.changed
    assert res.c == pytest.approx(0.42, abs=0.02)                 # the eyes differ, their median does not
    assert res.after_deg == pytest.approx(placement.DISC_FOVEA_DEG, abs=0.1)
    assert res.before_deg > res.after_deg + 2.0                   # the old curve made the centre too large
    assert 0.5 < res.spread_deg < 2.5 and res.error_deg < 0.4
    # one eye alone is a poor ruler: the single photos scatter far more than their median
    tmax = proj.theta_max(FOV, "internal")
    each = [cal.curve_of(s, tmax) for s in samples]
    assert max(each) - min(each) > 0.1


def test_wrong_marks_are_left_out_and_few_photos_are_said_to_be_few():
    rng = np.random.default_rng(5)
    good = [_photo(rng, 0.30, by_hand=k < 2) for k in range(12)]
    bad = [_photo(rng, 0.30, apart=35.0), _photo(rng, 0.30, apart=11.0)]       # a fovea found in the wrong place
    res = cal.fit_curve(good + bad, FOV, 0.30)
    assert res.total == 14 and res.used == 12 and res.by_hand == 2 and res.few
    assert res.c == pytest.approx(0.30, abs=0.03)
    assert cal.fit_curve(good[:4], FOV, 0.30) is None             # too few to say anything
    outside = cal.Sample((500.0, 500.0, 500.0), (1200.0, 500.0), (500.0, 500.0))
    assert cal.curve_of(outside, proj.theta_max(FOV, "internal")) is None


def test_the_measured_curve_replaces_the_cameras_own():
    try:
        profiles.set_lens_curves({"reticam": 0.4, "nobody": 0.3, "generic": "x"})
        assert profiles.get_profile("reticam").radial_c == 0.4 and profiles.lens_curve("reticam") == 0.4
        assert profiles.profile_for_device("SYSEYE RetiCam").radial_c == 0.4
        assert profiles.get_profile("generic").radial_c == proj.DEFAULT_RADIAL_C
        assert profiles.PROFILES["reticam"].radial_c == proj.DEFAULT_RADIAL_C      # the built-in one is kept
    finally:
        profiles.set_lens_curves({})
    assert profiles.get_profile("reticam").radial_c == proj.DEFAULT_RADIAL_C


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def list_patients(self):
        return [{"id": 1}]

    def images_for_patient(self, ref):
        return [r for r in self.rows if r["patient_ref"] == ref]


def _row(k, s: cal.Sample, **over):
    row = dict(id=k, patient_ref=1 if k % 3 else None, profile="reticam", modality="color", fov_deg=None,
               fov_type=None, projection=None, circle_cx=s.circle[0], circle_cy=s.circle[1], circle_r=s.circle[2],
               disc_x=s.disc[0], disc_y=s.disc[1], fovea_x=s.fovea[0], fovea_y=s.fovea[1],
               meta_json=json.dumps({"sources": {"fovea": "manual"}}) if k == 0 else None)
    row.update(over)
    return row


def test_only_the_cameras_own_photos_are_used():
    rng = np.random.default_rng(9)
    rows = [_row(k, _photo(rng, 0.4)) for k in range(8)]
    rows += [_row(20, _photo(rng, 0.4), profile="apollo"), _row(21, _photo(rng, 0.4), modality="montage"),
             _row(22, _photo(rng, 0.4), fovea_x=None), _row(23, _photo(rng, 0.4), fov_deg=120.0),
             _row(24, _photo(rng, 0.4), projection="equidistant")]
    samples = cal.samples_from_rows(cal.all_rows(_Db(rows)), profiles.PROFILES["reticam"])
    assert sorted(s.image_id for s in samples) == list(range(8)) and sum(s.by_hand for s in samples) == 1


def test_the_dialog_measures_applies_and_resets(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.calibrate_dialog import CalibrationDialog

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Settings, "save", lambda self, path=None: None)
    rng = np.random.default_rng(11)
    s, told = Settings(), []
    try:
        few = CalibrationDialog(_Db([_row(k, _photo(rng, 0.4)) for k in range(3)]), s)
        assert not few.b_apply.isEnabled() and "아직 잴 수 없습니다" in few.lbl.text()
        dlg = CalibrationDialog(_Db([_row(k, _photo(rng, 0.4)) for k in range(40)]), s,
                                on_applied=lambda: told.append(1))
        assert dlg.b_apply.isEnabled() and not dlg.b_reset.isEnabled() and "사용한 사진" in dlg.lbl.text()
        dlg.apply()
        c = s.lens_curves["reticam"]
        assert c == pytest.approx(0.4, abs=0.03) and profiles.get_profile("reticam").radial_c == c and told == [1]
        assert not dlg.b_apply.isEnabled() and dlg.b_reset.isEnabled()        # measured again: nothing to change
        assert "지금 값과 같습니다" in dlg.lbl.text()
        dlg.reset()
        assert s.lens_curves == {} and profiles.get_profile("reticam").radial_c == proj.DEFAULT_RADIAL_C
        assert dlg.b_apply.isEnabled()
    finally:
        profiles.set_lens_curves({})
        app.processEvents()
