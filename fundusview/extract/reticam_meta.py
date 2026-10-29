"""SYSEYE RetiCam (3100 Plus, 176° ultra-wide-field) metadata.

The capture software names files

    <Name>-<od|os|na>-<mode>-YYYYMMDD-HHMMSS-mmm.jpg      (local time)

— no patient id in the name — and writes the patient / exam record as JSON
in a **JPEG APP15 (0xFFEF) segment**: ``patientID``, ``patientName`` (2025
software) or ``patientFirstName`` / ``patientLastName`` (2023),
``patientBornDate`` (YYYY/MM/DD), ``patientSex`` (M/F/O), ``eyeLaterality``,
``dateTime`` (its hour can be off by the time-zone offset, so the file name's
time wins), ``modeID`` (1 = colour), mask / fixation geometry and
``extData`` (``isStitchIm`` for montages). Some exports are TIFF data with a
``.jpg`` extension; the JSON is then looked for in the TIFF tags.

The device's default patient (``#AnonymousID#`` / Anonymous / 1980-01-01 / O)
means "not registered" and is imported as 미분류.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import ExtractedMeta
from .normalize import apply_field, clean_name, has_hangul

SOURCE = "reticam"
ANONYMOUS_IDS = {"", "#ANONYMOUSID#", "ANONYMOUS"}
FILENAME = re.compile(
    r"^(?P<name>.+)-(?P<eye>od|os|na)-(?P<mode>[a-z]+)-(?P<date>\d{8})-(?P<time>\d{6})-\d{3}(?:\s*\(\d+\))?$",
    re.IGNORECASE,
)
MODE_IDS = {1: "color"}
PLUS_MIN_SIDE = 4500      # 3100 Plus frames are 5736×4304; the older 50° class ≈ 2700×2050
FOV_PLUS, FOV_MONTAGE, FOV_50 = 176.0, 220.0, 50.0


def _parse_json(raw) -> dict | None:
    if isinstance(raw, (bytes, bytearray)):
        b = bytes(raw)
        for enc in ("utf-8", "cp949"):
            try:
                raw = b.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raw = b.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(raw[i:j + 1])
    except ValueError:
        return None
    return d if isinstance(d, dict) and ("patientID" in d or "eyeLaterality" in d) else None


def reticam_json(img) -> dict | None:
    """The APP15 JSON of an opened PIL image (or JSON found in TIFF tags)."""
    for marker, data in getattr(img, "applist", None) or []:
        if marker == "APP15":
            d = _parse_json(data)
            if d:
                return d
    tags = getattr(img, "tag_v2", None)
    if tags:
        for v in tags.values():
            if isinstance(v, str):
                try:  # UTF-8 bytes that Pillow decoded as Latin-1
                    v = v.encode("latin-1")
                except UnicodeEncodeError:
                    pass
            if isinstance(v, (str, bytes)) and (b"patientID" in v if isinstance(v, bytes) else "patientID" in v):
                d = _parse_json(v)
                if d:
                    return d
    return None


def looks_like_reticam(path: Path, img=None) -> bool:
    if FILENAME.match(path.stem):
        return True
    return img is not None and reticam_json(img) is not None


def reticam_meta(path: Path) -> ExtractedMeta:
    from PIL import Image

    meta = ExtractedMeta()
    fm = FILENAME.match(path.stem)
    if fm:  # local wall-clock time — preferred over the JSON's dateTime
        apply_field(meta, "exam_date", fm.group("date"), "filename")
        apply_field(meta, "exam_time", fm.group("time"), "filename")
        apply_field(meta, "laterality", fm.group("eye"), "filename")
        apply_field(meta, "modality", fm.group("mode"), "filename")
    d, size = None, (0, 0)
    try:
        with Image.open(path) as img:
            d, size = reticam_json(img), img.size
    except Exception:
        pass
    if not d:
        return meta

    keep = ("dateTime", "eyeLaterality", "modeID", "picFormat", "version", "irisMaskRadius",
            "fixatInnerCoord", "fixatInnerCenter", "extData")
    meta.raw["RetiCam 데이터"] = json.dumps({k: d[k] for k in keep if k in d}, ensure_ascii=False)[:500]
    pid = str(d.get("patientID") or "").strip()
    anonymous = pid.upper() in ANONYMOUS_IDS
    if anonymous:
        meta.raw["RetiCam 환자"] = "등록되지 않은 기본 환자(#AnonymousID#) — 미분류"
    else:
        apply_field(meta, "patient_id", pid, SOURCE)
        name = d.get("patientName")
        if not name:
            last, first = str(d.get("patientLastName") or ""), str(d.get("patientFirstName") or "")
            name = (last + first) if has_hangul(last + first) else " ".join(p for p in (first, last) if p)
        apply_field(meta, "name", clean_name(str(name or "")) or "", SOURCE)
        apply_field(meta, "birth_date", str(d.get("patientBornDate") or ""), SOURCE)
        sex = str(d.get("patientSex") or "")
        if sex.upper() in ("M", "F"):
            apply_field(meta, "sex", sex, SOURCE)
    apply_field(meta, "laterality", str(d.get("eyeLaterality") or ""), SOURCE)
    when = str(d.get("dateTime") or "")
    if when:
        apply_field(meta, "exam_date", when[:10], SOURCE)
        apply_field(meta, "exam_time", when[11:19], SOURCE)

    ext = d.get("extData") if isinstance(d.get("extData"), dict) else {}
    plus = bool(ext.get("isStitchIm")) or "irisMaskEllipseLMaxis" in d or max(size) >= PLUS_MIN_SIDE \
        or max(int(ext.get("orgImWidth") or 0), int(ext.get("orgImHeight") or 0)) >= PLUS_MIN_SIDE
    if ext.get("isStitchIm"):  # the file name still says "color": override
        meta.modality, meta.sources["modality"] = "montage", SOURCE
        meta.set("fov_deg", FOV_MONTAGE, SOURCE)
        meta.fov_type, meta.projection = "internal", "radial"
    elif plus:
        meta.set("fov_deg", FOV_PLUS, SOURCE)
        meta.fov_type, meta.projection = "internal", "radial"
    else:  # older 50°-class RetiCam: an ordinary through-the-pupil camera
        meta.set("fov_deg", FOV_50, SOURCE)
        meta.fov_type, meta.projection = "external", "perspective"
    meta.set("device", "SYSEYE RetiCam 3100 Plus" if plus else "SYSEYE RetiCam (50°)", SOURCE)
    mode = d.get("modeID")
    if isinstance(mode, int):
        meta.set("modality", MODE_IDS.get(mode), SOURCE)
    return meta
