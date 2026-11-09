"""Metadata extraction pipeline.

Sources are consulted from most to least trustworthy, each only filling
fields that are still empty:

    DICOM tags > vendor data (APOLLO JSON / folders) > sidecar files >
    embedded EXIF/XMP/comments > file / folder name patterns > profile defaults

The ``sources`` map of the result records where each value came from, so
the viewer can show it next to the field.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from ..models import ExtractedMeta
from ..profiles import AUTO, PROFILES, CameraProfile, get_profile, profile_for_device
from .apollo_meta import apollo_meta, looks_like_apollo
from .dicom_meta import dicom_meta, is_dicom
from .embedded_meta import embedded_meta, sidecar_meta
from .filename_meta import filename_meta, match_patterns
from .reticam_meta import looks_like_reticam, reticam_meta

__all__ = ["extract_metadata", "detect_profile", "is_dicom"]


def detect_profile(path: Path, meta: ExtractedMeta | None = None) -> CameraProfile:
    if looks_like_reticam(path):
        return PROFILES["reticam"]
    if looks_like_apollo(path):
        return PROFILES["apollo"]
    if meta is not None and meta.device:
        p = profile_for_device(meta.device)
        if p:
            return p
    for key in ("kowa_vk2",):
        tmp = ExtractedMeta()
        if match_patterns(path.stem, PROFILES[key].filename_patterns, tmp, "probe"):
            return PROFILES[key]
    if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        try:
            from PIL import Image
            with Image.open(path) as img:
                if looks_like_reticam(path, img):
                    return PROFILES["reticam"]
                if looks_like_apollo(path, img):
                    return PROFILES["apollo"]
        except Exception:
            pass
    return PROFILES["generic"]


def extract_metadata(path: Path, profile_key: str = AUTO, *, watch_root: Path | None = None,
                     custom_patterns: list[str] | tuple = ()) -> tuple[ExtractedMeta, CameraProfile]:
    path = Path(path)
    meta = ExtractedMeta()
    dicom = is_dicom(path)
    if dicom:
        try:
            meta.merge(dicom_meta(path))
        except Exception as exc:  # unreadable header: fall back to the name
            meta.raw["DICOM 오류"] = str(exc)[:200]

    profile = detect_profile(path, meta) if profile_key in (AUTO, "", None) else get_profile(profile_key)

    if profile.vendor == "apollo" and not dicom:
        meta.merge(apollo_meta(path, watch_root))
    elif profile.vendor == "reticam" and not dicom:
        meta.merge(reticam_meta(path))
    meta.merge(sidecar_meta(path))
    if not dicom:
        meta.merge(embedded_meta(path))
    meta.merge(filename_meta(path, list(custom_patterns) + list(profile.filename_patterns),
                             watch_root=watch_root, id_only=profile.id_only_filenames))

    if not meta.fov_deg:
        meta.fov_deg, meta.fov_type = profile.fov_deg, profile.fov_type
        meta.sources["fov_deg"] = "profile"
    elif not meta.fov_type:
        meta.fov_type = profile.fov_type
    meta.projection = meta.projection or profile.projection
    if not meta.exam_date:
        try:
            ts = datetime.fromtimestamp(os.path.getmtime(path))
            meta.set("exam_date", ts.date().isoformat(), "file-time")
            meta.set("exam_time", ts.strftime("%H:%M:%S"), "file-time")
        except OSError:
            pass
    if meta.patient_id:
        meta.patient_id = re.sub(r"[\x00-\x1f]", "", meta.patient_id).strip()
    return meta, profile
