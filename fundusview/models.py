"""Plain data carried between the extractors, the importer and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field, fields

# Fields an extractor may fill, in the order shown in the UI.
META_FIELDS = (
    "patient_id", "name", "birth_date", "sex",
    "exam_date", "exam_time", "laterality", "modality",
    "device", "fov_deg", "study_uid", "description",
)

FIELD_LABELS = {
    "patient_id": "환자 ID", "name": "이름", "birth_date": "생년월일", "sex": "성별",
    "exam_date": "검사일", "exam_time": "검사 시각", "laterality": "눈 (OD/OS)",
    "modality": "촬영 종류", "device": "장비", "fov_deg": "화각(°)",
    "study_uid": "Study UID", "description": "설명",
}

MODALITY_LABELS = {
    "color": "컬러", "redfree": "Red-free", "af": "자가형광(AF)", "fa": "형광조영(FA)",
    "icg": "ICG", "ir": "적외선(IR)", "anterior": "전안부", "montage": "몽타주",
    "disc": "디스크 2장",   # optic disc pair sheet made by the viewer (discpair.py)
}


@dataclass
class ExtractedMeta:
    patient_id: str | None = None
    name: str | None = None
    birth_date: str | None = None   # YYYY-MM-DD
    sex: str | None = None          # M / F / O
    exam_date: str | None = None    # YYYY-MM-DD
    exam_time: str | None = None    # HH:MM:SS
    laterality: str | None = None   # OD / OS / OU
    modality: str | None = None     # key of MODALITY_LABELS
    device: str | None = None
    fov_deg: float | None = None
    fov_type: str | None = None     # "external" (angle at the pupil) / "internal" (eye centre)
    projection: str | None = None   # overrides the profile's projection for this file
    study_uid: str | None = None
    description: str | None = None
    # field name -> where the value came from ("dicom", "filename", "exif", ...)
    sources: dict[str, str] = field(default_factory=dict)
    # Selected raw tags / strings, kept for display and troubleshooting.
    raw: dict[str, str] = field(default_factory=dict)

    def merge(self, other: "ExtractedMeta", source: str | None = None) -> "ExtractedMeta":
        """Fill fields that are still empty from ``other`` (earlier sources win)."""
        for name in META_FIELDS:
            if getattr(self, name) in (None, "") and getattr(other, name) not in (None, ""):
                setattr(self, name, getattr(other, name))
                self.sources[name] = source or other.sources.get(name, "?")
                if name == "fov_deg":  # the angle, its reference and projection travel together
                    self.fov_type = other.fov_type
                    self.projection = self.projection or other.projection
        for k, v in other.raw.items():
            self.raw.setdefault(k, v)
        return self

    def set(self, name: str, value, source: str) -> None:
        if value in (None, ""):
            return
        if getattr(self, name) in (None, ""):
            setattr(self, name, value)
            self.sources[name] = source

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def has_patient(self) -> bool:
        return bool(self.patient_id)
