"""Microclear APOLLO (CSLO / CRO wide-field SLO) metadata.

The device (RTScan) stores captures as::

    PatientCapture/<PatientID>_<Name>/<YYYY_MM_DD>/<MODE>/
        <YYYY_MM_DD_HH_MM_SS.mmm>_<MODE>[_R|_G|_B][_OD_135°].jpg

and every JPEG carries a COM segment ``Description: {json}`` with
``ArchivedDT`` (capture time), ``Eye``, ``FieldAngle`` (scan angle, external
degrees; eye-centre angle = ×1.5 by Microclear's convention), ``DevModel``
(3007 = WA 135°, 3006 = UWA 165°, 4010 = RGB 2.0) and ``ImgType``. The
channel paths inside it repeat the ``<PatientID>_<Name>`` folder, so a file
copied out of its folder still names its patient. PNG exports carry the
same JSON hex-encoded (behind a small binary header) in a ``Description``
tEXt chunk.

Case export writes ``<PatientID>.json`` (id, name, birthDay, gender,
axialLen_OD/OS ...) — read when found next to / above the image.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

from ..models import ExtractedMeta
from .normalize import apply_field, norm_date, norm_sex, norm_time

SOURCE = "apollo"

DEV_MODELS = {
    3006: "Microclear APOLLO UWA",
    3007: "Microclear APOLLO WA",
    4006: "Microclear APOLLO UWA",
    4010: "Microclear APOLLO RGB 2.0",
}
# External scan angle -> nominal eye-centre angle (HD 90° / WA 135° / UWA 165°).
FIELD_ANGLE_INTERNAL = {112: 165.0, 110: 165.0, 90: 135.0, 60: 90.0, 30: 45.0, 15: 22.5}
# ``Eye`` values, confirmed against the burned-in "OD/OS Angle ..." text.
EYE_CODES = {1: "OD", 0: "OS"}
# ``ImgType`` values seen on device files (4 = ICGA alone is unconfirmed).
IMG_TYPES = {1: "ir", 2: "color", 3: "fa", 5: "redfree", 6: "af", 9: "icg"}

MODE_TOKENS = {
    "MCOLOR": "color", "COLOR": "color", "RF": "redfree", "IR": "ir", "AF": "af",
    "BAF": "af", "GAF": "af", "FFA": "fa", "FA": "fa", "ICGA": "icg", "ICG": "icg",
    "ICGA-FFA": "icg", "MOSAIC": "montage",
}

PATIENT_DIR = re.compile(r"PatientCapture[/\\](?P<pid>[^/\\_]+)_(?P<name>[^/\\]+)[/\\]")
FILENAME = re.compile(
    r"^(?P<date>\d{4}_\d{2}_\d{2})_(?P<time>\d{2}_\d{2}_\d{2})(?:\.\d{1,3})?"
    r"(?:_ART\([\d\-]+\))?"
    r"(?:_(?P<mode>Mosaic_[A-Za-z\-]+|[A-Za-z]+(?:-[A-Za-z]+)?))?(?:_(?P<chan>R|G|B|IR))?"
    r"(?:_(?P<eye>OD|OS))?(?:_(?P<angle>\d+)°?)?",
    re.IGNORECASE,
)


def _json_from_comment(text: str) -> dict | None:
    i = text.find("{")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except ValueError:
                    return None
    return None


def _png_header(raw: bytes) -> dict:
    """Binary header in front of the PNG ``Description`` JSON (big-endian):
    u32 version(=2) | u32 n | n-byte capture time | u16 eye | u16 ? | u32 FieldAngle."""
    try:
        version, n = struct.unpack(">II", raw[:8])
        if version != 2 or not 10 <= n <= 32:
            return {}
        when = raw[8:8 + n].decode("ascii")
        if not re.match(r"\d{4}-\d{2}-\d{2}", when):
            return {}
        eye, _ = struct.unpack(">HH", raw[8 + n:12 + n])
        (fov,) = struct.unpack(">I", raw[12 + n:16 + n])
    except (struct.error, UnicodeDecodeError):
        return {}
    out = {"ArchivedDT": when}
    if eye in EYE_CODES:
        out["Eye"] = eye
    if 0 < fov < 180:
        out["FieldAngle"] = fov
    return out


def description_json(img) -> dict | None:
    """The ``Description`` JSON of an opened PIL image, if present."""
    info = getattr(img, "info", {}) or {}
    comment = info.get("comment")
    if isinstance(comment, (bytes, bytearray)):
        comment = bytes(comment).decode("utf-8", errors="replace")
    if comment and "Description" in comment:
        return _json_from_comment(comment)
    desc = (getattr(img, "text", None) or {}).get("Description") or info.get("Description")
    if isinstance(desc, str) and re.fullmatch(r"[0-9a-fA-F]+", desc.strip() or "x"):
        try:
            raw = bytes.fromhex(desc.strip())
        except ValueError:
            return None
        d = _json_from_comment(raw.decode("utf-8", errors="replace")) or {}
        for k, v in _png_header(raw).items():
            d.setdefault(k, v)
        return d or None
    if isinstance(desc, str):
        return _json_from_comment(desc)
    return None


def looks_like_apollo(path: Path, img=None) -> bool:
    if "PatientCapture" in path.parts or FILENAME.match(path.stem):
        return True
    if img is not None:
        d = description_json(img)
        return bool(d and ("DevModel" in d or "FieldAngle" in d))
    return False


def _patient_json(path: Path, pid: str, stop: Path | None) -> dict | None:
    p = path.parent
    for _ in range(5):
        cand = p / f"{pid}.json"
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return None
        if (stop is not None and p == stop) or p == p.parent:
            break
        p = p.parent
    return None


def apollo_meta(path: Path, watch_root: Path | None = None) -> ExtractedMeta:
    from PIL import Image

    meta = ExtractedMeta()
    # The device's own folder PatientCapture/<id>_<name>/ is the current
    # record; the paths embedded in the JSON are the fallback for copies.
    m = PATIENT_DIR.search(str(path).replace("\\", "/"))
    if m:
        apply_field(meta, "patient_id", m.group("pid"), "folder")
        apply_field(meta, "name", m.group("name"), "folder")
    d = None
    try:
        with Image.open(path) as img:
            d = description_json(img)
    except Exception:
        pass
    if d:
        meta.raw["APOLLO Description"] = json.dumps(d, ensure_ascii=False)[:600]
        dt = str(d.get("ArchivedDT") or "")
        if dt:
            meta.set("exam_date", norm_date(dt[:10], min_year=1990), SOURCE)
            meta.set("exam_time", norm_time(dt[11:19]), SOURCE)
        eye = d.get("Eye")
        if isinstance(eye, int) and eye in EYE_CODES:
            meta.set("laterality", EYE_CODES[eye], SOURCE)
            meta.raw["APOLLO Eye"] = str(eye)
        model = d.get("DevModel")
        sw = str((d.get("ExtraInfo") or {}).get("SWVersion") or d.get("SWVersion") or "")
        if sw.endswith("110D"):  # the unit's maximum external angle
            meta.set("device", "Microclear APOLLO UWA", SOURCE)
        elif sw.endswith("90D") and model != 4010:
            meta.set("device", "Microclear APOLLO WA", SOURCE)
        elif isinstance(model, int) and model in DEV_MODELS:
            meta.set("device", DEV_MODELS[model], SOURCE)
        elif model:
            meta.set("device", f"Microclear {model}", SOURCE)
        if d.get("Mosaic"):
            meta.set("modality", "montage", SOURCE)
        elif isinstance(d.get("ImgType"), int):
            meta.set("modality", IMG_TYPES.get(d["ImgType"]), SOURCE)
        fa = d.get("FieldAngle")
        if isinstance(fa, (int, float)) and fa > 0:
            meta.set("fov_deg", FIELD_ANGLE_INTERNAL.get(int(fa), round(float(fa) * 1.5, 1)), SOURCE)
            meta.fov_type = "internal"
            meta.raw["APOLLO FieldAngle(외부각)"] = str(fa)
        # Patient folder repeated in the channel paths.
        blob = json.dumps(d, ensure_ascii=False)
        m = PATIENT_DIR.search(blob)
        if m:
            apply_field(meta, "patient_id", m.group("pid"), SOURCE)
            apply_field(meta, "name", m.group("name"), SOURCE)
    fm = FILENAME.match(path.stem)
    if fm:
        apply_field(meta, "exam_date", fm.group("date"), "filename")
        apply_field(meta, "exam_time", fm.group("time"), "filename")
        if fm.group("eye"):
            apply_field(meta, "laterality", fm.group("eye"), "filename")
        mode = (fm.group("mode") or "").upper()
        if mode.startswith("MOSAIC"):
            meta.set("modality", "montage", "filename")
        elif mode in MODE_TOKENS:
            meta.set("modality", MODE_TOKENS[mode], "filename")
        if fm.group("chan"):
            meta.raw["APOLLO 채널"] = fm.group("chan")
        if fm.group("angle") and not meta.fov_deg:
            meta.set("fov_deg", float(fm.group("angle")), "filename")
            meta.fov_type = "internal"
    # Case export JSON for demographics.
    if meta.patient_id:
        pj = _patient_json(path, meta.patient_id, watch_root)
        if pj:
            apply_field(meta, "name", str(pj.get("name") or ""), "apollo-json")
            apply_field(meta, "birth_date", str(pj.get("birthDay") or pj.get("birthday") or ""), "apollo-json")
            g = pj.get("gender")
            if isinstance(g, str):
                meta.set("sex", norm_sex(g), "apollo-json")
            for k in ("gender", "axialLen_OD", "axialLen_OS"):
                if pj.get(k):
                    meta.raw[k] = str(pj[k])
    return meta
