"""Metadata embedded in ordinary image files and in sidecar files.

* JPEG/TIFF EXIF — Make/Model, DateTimeOriginal, ImageDescription,
  UserComment and the Windows ``XP*`` tags (UTF-16, so Korean survives).
* JPEG COM segment, PNG tEXt/iTXt chunks, XMP packets.
* Sidecars next to the image with the same stem: ``.txt .ini .xml .json .csv``.

All free text goes through :func:`normalize.parse_key_values`, so any
``PatientID=...; Name=...`` style annotation is picked up regardless of the
container it was stored in.
"""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import ExtractedMeta
from .normalize import apply_field, canonical_key, norm_date, norm_time, parse_key_values

SIDECAR_EXTS = (".txt", ".ini", ".xml", ".json", ".csv", ".inf")

# EXIF tag ids
_IMAGE_DESCRIPTION, _MAKE, _MODEL, _DATETIME, _ARTIST = 270, 271, 272, 306, 315
_EXIF_IFD, _DATETIME_ORIGINAL, _USER_COMMENT = 0x8769, 36867, 37510
_XP_TITLE, _XP_COMMENT, _XP_AUTHOR, _XP_KEYWORDS, _XP_SUBJECT = 0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F


def _decode_text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, (tuple, list)):  # XP* tags as a tuple of byte values
        v = bytes(v)
    if isinstance(v, (bytes, bytearray)):
        b = bytes(v)
        if b[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00", b"JIS\x00\x00\x00\x00\x00", b"\x00" * 8):
            head, b = b[:8], b[8:]  # EXIF UserComment character-code prefix
            if head.startswith(b"UNICODE"):
                for enc in ("utf-16-le", "utf-16-be"):
                    try:
                        return b.decode(enc).strip("\x00")
                    except UnicodeDecodeError:
                        pass
        for enc in ("utf-8", "cp949", "utf-16-le"):
            try:
                return b.decode(enc).strip("\x00")
            except UnicodeDecodeError:
                continue
        return b.decode("latin-1", errors="replace")
    return str(v)


def _xp(v) -> str:
    if isinstance(v, (tuple, list)):
        v = bytes(v)
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-16-le", errors="ignore").strip("\x00")
    return str(v)


def embedded_meta(path: Path) -> ExtractedMeta:
    from PIL import Image

    meta = ExtractedMeta()
    try:
        img = Image.open(path)
    except Exception:
        return meta
    with img:
        texts: list[tuple[str, str]] = []
        try:
            exif = img.getexif()
        except Exception:
            exif = {}
        if exif:
            make = _decode_text(exif.get(_MAKE, "")).strip()
            model = _decode_text(exif.get(_MODEL, "")).strip()
            if make or model:
                meta.set("device", " ".join(p for p in (make, model) if p), "exif")
                meta.raw["EXIF Make/Model"] = f"{make} {model}".strip()
            for tag in (_IMAGE_DESCRIPTION, _ARTIST):
                if tag in exif:
                    texts.append(("exif", _decode_text(exif[tag])))
            for tag in (_XP_TITLE, _XP_COMMENT, _XP_AUTHOR, _XP_KEYWORDS, _XP_SUBJECT):
                if tag in exif:
                    texts.append(("exif", _xp(exif[tag])))
            try:
                sub = exif.get_ifd(_EXIF_IFD)
            except Exception:
                sub = {}
            dto = sub.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
            if dto:
                dto = _decode_text(dto)
                meta.set("exam_date", norm_date(dto, min_year=1990), "exif")
                m = re.search(r"\s(\d{1,2}:\d{2}:\d{2})", dto)
                if m:
                    meta.set("exam_time", norm_time(m.group(1)), "exif")
            if _USER_COMMENT in sub:
                texts.append(("exif", _decode_text(sub[_USER_COMMENT])))
        info = getattr(img, "info", {}) or {}
        if info.get("comment"):
            texts.append(("jpeg-comment", _decode_text(info["comment"])))
        for k, v in (getattr(img, "text", None) or {}).items():  # PNG chunks
            texts.append(("png-text", f"{k}: {v}" if canonical_key(k) else str(v)))
        xmp = info.get("xmp") or info.get("XML:com.adobe.xmp")
        if xmp:
            texts.append(("xmp", _xmp_to_text(_decode_text(xmp))))
    for source, text in texts:
        if not text:
            continue
        meta.raw.setdefault(f"{source} text", text[:300])
        body = re.sub(r"^\s*Description:\s*", "", text)
        if body.startswith("{") or re.fullmatch(r"[0-9a-fA-F\s]{64,}", body):
            continue  # vendor JSON / hex blob (Microclear) — parsed by apollo_meta
        parse_key_values(text, meta, source)
    return meta


def _xmp_to_text(xmp: str) -> str:
    """Flatten XMP to ``name: value`` lines (dc:description, custom tags ...)."""
    out = []
    for m in re.finditer(r"<(?:\w+:)?(\w+)[^>]*>([^<]{1,200})</", xmp):
        out.append(f"{m.group(1)}: {m.group(2).strip()}")
    for m in re.finditer(r"\s(?:\w+:)?(\w+)=\"([^\"]{1,200})\"", xmp):
        out.append(f"{m.group(1)}: {m.group(2).strip()}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# sidecar files
# ---------------------------------------------------------------------------
def find_sidecars(path: Path) -> list[Path]:
    out = []
    for ext in SIDECAR_EXTS:
        for cand in (path.with_suffix(ext), path.with_suffix(ext.upper()),
                     path.with_name(path.name + ext)):
            if cand.exists() and cand != path and cand not in out:
                out.append(cand)
    return out


def _read_text(p: Path) -> str:
    raw = p.read_bytes()[:256_000]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _flatten_json(obj, prefix="") -> list[tuple[str, str]]:
    items = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            items += _flatten_json(v, str(k))
    elif isinstance(obj, list):
        for v in obj[:50]:
            items += _flatten_json(v, prefix)
    elif obj is not None:
        items.append((prefix, str(obj)))
    return items


def sidecar_meta(path: Path) -> ExtractedMeta:
    meta = ExtractedMeta()
    for side in find_sidecars(path):
        src = f"sidecar{side.suffix.lower()}"
        try:
            text = _read_text(side)
        except OSError:
            continue
        meta.raw.setdefault(f"{side.name}", text[:300])
        ext = side.suffix.lower()
        pairs: list[tuple[str, str]] = []
        try:
            if ext == ".json":
                pairs = _flatten_json(json.loads(text))
            elif ext == ".xml":
                root = ET.fromstring(text)
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if el.text and el.text.strip():
                        pairs.append((tag, el.text.strip()))
                    pairs += list(el.attrib.items())
            elif ext == ".csv":
                rows = list(csv.reader(io.StringIO(text)))
                if len(rows) >= 2 and len(rows[0]) == len(rows[1]):
                    pairs = list(zip(rows[0], rows[1]))  # header row + value row
                else:
                    pairs = [(r[0], r[1]) for r in rows if len(r) >= 2]
        except (ValueError, ET.ParseError):
            pairs = []
        names: dict[str, str] = {}
        for k, v in pairs:
            field = canonical_key(k)
            if not field:
                continue
            if field.startswith("_"):  # JOIA XML: nsCommon:LastName / FirstName
                names.setdefault(field, v.strip())
            else:
                apply_field(meta, field, v, src)
        if names and not meta.name:
            apply_field(meta, "name", " ".join(n for n in (names.get("_last"), names.get("_first")) if n), src)
        if ext not in (".json", ".xml"):
            parse_key_values(text, meta, src)
    return meta
