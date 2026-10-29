"""Patient / exam metadata from DICOM files (Ophthalmic Photography etc.).

Korean names: a properly written file declares ``Specific Character Set``
(e.g. ``ISO 2022 IR 149`` for KS X 1001) and pydicom decodes it. Files from
older capture stations sometimes carry CP949 bytes without declaring a
character set; those are re-decoded here so names are not garbled.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

from ..models import ExtractedMeta
from .normalize import clean_name, has_hangul, norm_date, norm_eye, norm_sex, norm_time

SOURCE = "dicom"


def is_dicom(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(132)
    except OSError:
        return False
    if len(head) >= 132 and head[128:132] == b"DICM":
        return True
    # Preamble-less (raw) DICOM: only trust it for .dcm files.
    return path.suffix.lower() in (".dcm", ".dicom")


_ISO2022_ESC = re.compile(rb"\x1b[\x20-\x2f]+[\x30-\x7e]")


def _decode_bytes(raw: bytes) -> str:
    """Undeclared PN bytes: strip ISO 2022 escapes (``ESC $ ) C``), undo 7-bit
    SO/SI shifting, then try UTF-8 / CP949 (KS X 1001)."""
    raw = _ISO2022_ESC.sub(b"", raw)
    if b"\x0e" in raw:
        out, shifted = bytearray(), False
        for b in raw:
            if b == 0x0E:
                shifted = True
            elif b == 0x0F:
                shifted = False
            else:
                out.append(b | 0x80 if shifted and 0x21 <= b <= 0x7E else b)
        raw = bytes(out)
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _person_name(ds) -> str | None:
    elem = ds.get("PatientName")
    if elem is None or not str(elem).strip():
        return None
    declared = "SpecificCharacterSet" in ds
    pn = elem
    original = getattr(pn, "original_string", None)
    if not declared and isinstance(original, (bytes, bytearray)) and any(b > 0x7F for b in original):
        text = _decode_bytes(bytes(original))
    else:
        text = str(pn)
    # Multi-group PN: Alphabetic=Ideographic=Phonetic. Prefer the Hangul one.
    groups = [g for g in text.split("=") if g.strip()]
    for g in groups:
        if has_hangul(g):
            return clean_name(g)
    return clean_name(groups[0]) if groups else None


def _str(ds, keyword: str) -> str | None:
    v = ds.get(keyword)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _modality_from_dicom(ds) -> str | None:
    desc = " ".join(filter(None, (_str(ds, "SeriesDescription"), _str(ds, "ImageComments"),
                                  _str(ds, "AcquisitionContextDescription")))).upper()
    for key, mod in (("RED", "redfree"), ("FAF", "af"), ("AUTOFLU", "af"), ("ICG", "icg"),
                     ("FLUORESCEIN", "fa"), ("FAG", "fa"), ("INFRARED", "ir"), (" IR", "ir"),
                     ("ANTERIOR", "anterior"), ("MONTAGE", "montage")):
        if key in desc:
            return mod
    if ds.get("SamplesPerPixel", 1) == 3:
        return "color"
    return None


def dicom_meta(path: Path) -> ExtractedMeta:
    import pydicom

    meta = ExtractedMeta()
    with warnings.catch_warnings():  # undeclared charsets are expected (VK-2); handled below
        warnings.simplefilter("ignore", UserWarning)
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        _ = str(ds.get("PatientName", ""))  # decode now, inside the filter
    meta.set("patient_id", (_str(ds, "PatientID") or "").replace(" ", "") or None, SOURCE)
    meta.set("name", _person_name(ds), SOURCE)
    meta.set("birth_date", norm_date(_str(ds, "PatientBirthDate")), SOURCE)
    meta.set("sex", norm_sex(_str(ds, "PatientSex")), SOURCE)
    for kw_d, kw_t in (("AcquisitionDateTime", None), ("ContentDate", "ContentTime"),
                       ("AcquisitionDate", "AcquisitionTime"), ("SeriesDate", "SeriesTime"),
                       ("StudyDate", "StudyTime")):
        d = _str(ds, kw_d)
        if not d:
            continue
        meta.set("exam_date", norm_date(d[:8], min_year=1990), SOURCE)
        t = d[8:14] if kw_t is None else _str(ds, kw_t)
        meta.set("exam_time", norm_time(t), SOURCE)
        if meta.exam_date:
            break
    # Ophthalmic Photography uses Image Laterality (0020,0062); some writers
    # put it in (Series) Laterality (0020,0060) instead.
    meta.set("laterality", norm_eye(_str(ds, "ImageLaterality") or _str(ds, "Laterality")), SOURCE)
    meta.set("modality", _modality_from_dicom(ds), SOURCE)
    device = " ".join(filter(None, (_str(ds, "Manufacturer"), _str(ds, "ManufacturerModelName"))))
    meta.set("device", device or None, SOURCE)
    fov = ds.get("HorizontalFieldOfView")
    if fov is not None:
        try:
            meta.set("fov_deg", float(fov), SOURCE)
            # Fundus-camera convention (VK-2 writes the camera's 45°/50°):
            # the angle at the pupil. Profiles may override for wide-field.
            meta.fov_type = "external"
        except (TypeError, ValueError):
            pass
    meta.set("study_uid", _str(ds, "StudyInstanceUID"), SOURCE)
    meta.set("description", _str(ds, "SeriesDescription") or _str(ds, "StudyDescription"), SOURCE)
    for kw in ("Modality", "SOPClassUID", "Manufacturer", "ManufacturerModelName", "SoftwareVersions",
               "SpecificCharacterSet", "PhotometricInterpretation", "StationName", "InstitutionName"):
        v = _str(ds, kw)
        if v:
            meta.raw[f"DICOM {kw}"] = v
    return meta
