"""카메라 각도 보정 — the lens curve of the wide-field camera from the photos in the library
(``calibrate.py``): what was found, what it changes, 적용 / 기본값으로."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import calibrate as cal
from .. import placement, profiles
from ..config import Settings


class CalibrationDialog(QDialog):
    def __init__(self, db, settings: Settings, parent=None, on_applied=None):
        super().__init__(parent)
        self.setWindowTitle("카메라 각도 보정")
        self.setMinimumWidth(560)
        self.db, self.settings, self._on_applied = db, settings, on_applied
        self.result: cal.Result | None = None
        lay = QVBoxLayout(self)
        intro = QLabel(
            "사진 한 장에는 크기를 아는 것이 하나 있습니다 — 황반과 시신경 유두 사이(약 4.5 mm, 안구 중심각 "
            f"{placement.DISC_FOVEA_DEG:g}°). 눈마다 조금씩 다르지만 같은 카메라로 찍은 여러 환자의 중앙값은 "
            "카메라의 값입니다. 저장된 사진에서 그 값을 구해 사진 중심부의 각도를 맞춥니다. "
            "사진 가장자리(화각)는 카메라의 값 그대로 둡니다.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("카메라"))
        self.c_camera = QComboBox()
        for p in profiles.PROFILES.values():
            if p.projection == "radial":
                self.c_camera.addItem(p.name, p.key)
        self.c_camera.currentIndexChanged.connect(self.measure)
        row.addWidget(self.c_camera, 1)
        lay.addLayout(row)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        self.b_again = QPushButton("다시 재기")
        self.b_again.clicked.connect(self.measure)
        self.b_reset = QPushButton("기본값으로")
        self.b_reset.setToolTip("보정한 값을 지우고 프로그램의 기본 렌즈 곡선으로 되돌립니다")
        self.b_reset.clicked.connect(self.reset)
        self.b_apply = QPushButton("적용")
        self.b_apply.setObjectName("primary")
        self.b_apply.clicked.connect(self.apply)
        b_close = QPushButton("닫기")
        b_close.clicked.connect(self.accept)
        row.addWidget(self.b_again)
        row.addWidget(self.b_reset)
        row.addStretch(1)
        row.addWidget(self.b_apply)
        row.addWidget(b_close)
        lay.addLayout(row)
        self.measure()

    def profile(self):
        return profiles.get_profile(self.c_camera.currentData())

    def measure(self, *_):
        prof = self.profile()
        self.b_reset.setEnabled(profiles.lens_curve(prof.key) is not None)
        samples = cal.samples_from_rows(cal.all_rows(self.db), prof)
        self.result = res = cal.fit_curve(samples, prof.fov_deg, prof.radial_c, fov_type=prof.fov_type,
                                          viewpoint=prof.viewpoint)
        if res is None:
            self.b_apply.setEnabled(False)
            self.lbl.setText(f"<b>아직 잴 수 없습니다.</b> 황반과 시신경 유두가 모두 표시된 이 카메라의 사진이 "
                             f"{len(samples)}장입니다 — {cal.MIN_PHOTOS}장 이상 필요하고, {cal.GOOD_PHOTOS}장 "
                             "이상이면 믿을 만합니다. 사진이 더 쌓인 뒤 다시 열어 주세요.")
            return
        now = "보정한 값" if profiles.lens_curve(prof.key) is not None else "기본값"
        s0 = cal.centre_scale(prof.fov_deg, res.old_c, prof.fov_type, prof.viewpoint)
        s1 = cal.centre_scale(prof.fov_deg, res.c, prof.fov_type, prof.viewpoint)
        lines = [
            f"<b>사용한 사진 {res.used}장</b> (황반 · 유두가 있는 {res.total}장 중 — 다른 사진들과 크게 다른 "
            f"{res.total - res.used}장은 뺌, 황반을 손으로 표시한 사진 {res.by_hand}장)",
            f"황반–유두 각도(중앙값): 지금 <b>{res.before_deg:.1f}°</b> → 보정하면 <b>{res.after_deg:.1f}°</b> "
            f"(기준 {placement.DISC_FOVEA_DEG:g}°)",
            f"사진 사이의 차이 ±{res.spread_deg:.1f}° · 중앙값의 오차 약 ±{res.error_deg:.1f}°",
            f"렌즈 곡선: 지금 {res.old_c:.3f} ({now}) → <b>{res.c:.3f}</b>",
            f"사진 가장자리는 {prof.fov_deg:g}° 그대로 · 중심부(반지름의 10%까지): {s0:.1f}° → {s1:.1f}°",
        ]
        if res.few:
            lines.append(f"<span style='color:#ff9f0a'>사진이 {res.used}장뿐이라 값이 대략적입니다 — "
                         f"{cal.GOOD_PHOTOS}장 이상 쌓이면 다시 재 보세요.</span>")
        if not res.changed:
            lines.append("지금 값과 같습니다 — 바꿀 것이 없습니다.")
        self.b_apply.setEnabled(res.changed)
        self.lbl.setText("<br>".join(lines))

    def _store(self, c: float | None) -> None:
        key = self.c_camera.currentData()
        curves = dict(self.settings.lens_curves)
        if c is None:
            curves.pop(key, None)
        else:
            curves[key] = c
        self.settings.lens_curves = curves
        self.settings.save()
        profiles.set_lens_curves(curves)
        if self._on_applied:
            self._on_applied()
        self.measure()

    def apply(self) -> None:
        if self.result is not None:
            self._store(self.result.c)

    def reset(self) -> None:
        self._store(None)
