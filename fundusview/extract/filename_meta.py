"""Patient / exam fields from file and folder names.

Patterns are Python regexes matched against the file *stem* (name without
extension) using named groups:

    pid name last first birth sex date time eye mode seq

Profiles (``profiles.py``) supply camera-specific patterns, e.g. the Kowa
Export Tool styles ``ID_YYYYMMDD_HHMMSS_R_FUNDUS (COLOR)_1``. After the
patterns, a conservative token pass picks up an eye / mode / date found
anywhere in the name — but never a patient id, because filing a photo under
the wrong patient is worse than leaving it unassigned (미분류).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..models import ExtractedMeta
from .normalize import apply_field, clean_name, has_hangul, norm_date, norm_eye, norm_modality, norm_time

_EYE_ALT = r"OD|OS|OU|RE|LE|R|L|RIGHT|LEFT|우안|좌안"

# Tried for every profile, after the profile's own patterns.
GENERIC_PATTERNS = (
    # ID_이름_YYYYMMDD[_HHMMSS][_EYE][_...]
    rf"^(?P<pid>[A-Za-z0-9\-]{{2,20}})[_ ](?P<name>[^_\d][^_]{{0,40}}?)[_ ](?P<date>\d{{8}})"
    rf"(?:[_ \-](?P<time>\d{{4,6}}))?(?:[_ \-](?P<eye>{_EYE_ALT}))?(?:[_ \-].*)?$",
    # ID_YYYYMMDD[_HHMMSS][_EYE][_...]
    rf"^(?P<pid>[A-Za-z0-9\-]{{2,20}})_(?P<date>\d{{8}})(?:_(?P<time>\d{{4,6}}))?"
    rf"(?:_(?P<eye>{_EYE_ALT}))?(?:_.*)?$",
    # YYYYMMDD[_HHMMSS]_ID[_이름][_EYE][_...]
    rf"^(?P<date>\d{{8}})(?:_(?P<time>\d{{4,6}}))?_(?P<pid>[A-Za-z0-9\-]{{2,20}})"
    rf"(?:_(?P<name>[^_\d][^_]{{0,40}}?))?(?:_(?P<eye>{_EYE_ALT}))?(?:_.*)?$",
    # 12345678_홍길동[_...]
    r"^(?P<pid>\d{4,12})[_ \-]+(?P<name>[가-힣]{2,6})(?:[_ \-].*)?$",
)

# Folder names (closest parent first), e.g. "12345_홍길동" or "12345 홍길동".
FOLDER_PATTERNS = (
    r"^(?P<pid>[A-Za-z0-9\-]{3,20})[_ ]+(?P<name>[^\d_ ][^_]{0,40})$",
)

_GROUP_FIELD = {
    "pid": "patient_id", "name": "name", "birth": "birth_date", "sex": "sex",
    "date": "exam_date", "time": "exam_time", "eye": "laterality", "mode": "modality",
}


def _mode_from_text(s: str) -> str | None:
    """Kowa capture-type labels: 'FUNDUS (COLOR)', 'RED FREE', 'FAF', ..."""
    u = s.upper()
    direct = norm_modality(re.sub(r"[\s()]", "", u))
    if direct:
        return direct
    for key, mod in (("FAF", "af"), ("AUTOF", "af"), ("RED", "redfree"), ("ICG", "icg"),
                     ("FA", "fa"), ("COLOR", "color"), ("COLOUR", "color"), ("IR", "ir"),
                     ("SLIT", "anterior"), ("ANTERIOR", "anterior"), ("MONTAGE", "montage"),
                     ("PANORAMA", "montage")):
        if re.search(rf"(?<![A-Z]){key}", u):
            return mod
    return None


# Camera / phone / scanner file-name prefixes that look like an id but are not.
_NOT_AN_ID = re.compile(r"^(IMG|IMAGE|DSC|DSCN|DSCF|PICT|PIC|PXL|MVIMG|SAM|SCAN|CAPTURE|PHOTO|SCREENSHOT|"
                        r"FUNDUS|EXPORT|COLOR|MCOLOR|OD|OS|VK)(?:[_\-]?\d*)$", re.IGNORECASE)


def plausible_pid(pid: str | None) -> bool:
    """A patient id from a *name* must contain a digit and not be a camera prefix."""
    return bool(pid) and any(c.isdigit() for c in pid) and not _NOT_AN_ID.match(pid)


def _apply_match(meta: ExtractedMeta, m: re.Match, source: str) -> None:
    g = {k: v for k, v in m.groupdict().items() if v}
    if g.get("name", "").strip().lower() in ("anonymous", "unknown", "noname", "no name", "익명"):
        g.pop("name")  # capture software placeholders (RetiCam default patient)
    if "pid" in g and not plausible_pid(g["pid"]):
        g.pop("pid")
        g.pop("name", None)  # the name next to a bogus id is just as unreliable
    for group, value in g.items():
        if group == "mode":
            meta.set("modality", _mode_from_text(value), source)
            meta.raw.setdefault("촬영 종류(파일명)", value)
        elif group == "seq":
            meta.raw.setdefault("일련번호", value)
        elif group in _GROUP_FIELD:
            apply_field(meta, _GROUP_FIELD[group], value, source)
    if not meta.name and ("last" in g or "first" in g):
        apply_field(meta, "name", " ".join(p for p in (g.get("last"), g.get("first")) if p), source)


def match_patterns(text: str, patterns, meta: ExtractedMeta, source: str) -> bool:
    for pat in patterns:
        try:
            m = re.match(pat, text, re.IGNORECASE)
        except re.error:
            continue
        if m and "pid" in m.groupdict() and m.group("pid") and not plausible_pid(m.group("pid")):
            continue  # e.g. IMG_20240305_101500: try the next rule instead
        if m:
            _apply_match(meta, m, source)
            meta.raw.setdefault("파일명 규칙", pat if len(pat) < 120 else pat[:117] + "...")
            return True
    return False


def _token_pass(stem: str, meta: ExtractedMeta) -> None:
    tokens = [t for t in re.split(r"[_\-\s.()\[\]]+", stem) if t]
    prev_was_date = False
    for t in tokens:
        if not meta.laterality and t.upper() in ("OD", "OS", "OU", "RE", "LE", "RIGHT", "LEFT", "우안", "좌안"):
            meta.set("laterality", norm_eye(t), "filename")
            continue
        if not meta.modality:
            mod = norm_modality(t)
            if mod:
                meta.set("modality", mod, "filename")
                continue
        if re.fullmatch(r"\d{8}", t) and not meta.exam_date:
            d = norm_date(t, min_year=1990)
            if d:
                meta.set("exam_date", d, "filename")
                prev_was_date = True
                continue
        if prev_was_date and re.fullmatch(r"\d{6}", t) and not meta.exam_time:
            meta.set("exam_time", norm_time(t), "filename")
        if not meta.name and has_hangul(t) and 2 <= len(t) <= 6 and re.fullmatch(r"[가-힣]+", t):
            meta.set("name", clean_name(t), "filename")
        prev_was_date = False


def filename_meta(path: Path, patterns=(), *, watch_root: Path | None = None,
                  id_only: bool = False) -> ExtractedMeta:
    """Extract from ``path``'s name, then its parent folders (below ``watch_root``).

    ``id_only`` accepts a bare ``<ID>.jpg`` / ``<ID>_<n>.jpg`` stem as the
    patient id (VK-2 "Copy Selected Images to Folder"); only enable it for a
    folder known to receive such files.
    """
    meta = ExtractedMeta()
    stem = unicodedata.normalize("NFC", path.stem)
    meta.raw["파일명"] = path.name
    matched = match_patterns(stem, list(patterns) + list(GENERIC_PATTERNS), meta, "filename")
    if not matched and id_only:
        m = re.match(r"^(?P<pid>[A-Za-z0-9][A-Za-z0-9\-]{1,30}?)(?:[ _(]+(?P<seq>\d{1,4})\)?)?$", stem)
        if m:
            _apply_match(meta, m, "filename")
    _token_pass(stem, meta)

    # Parent folders within the watched root (at most 3 levels).
    parents = []
    p = path.parent
    while watch_root is not None and len(parents) < 3:
        try:
            if p.resolve() == watch_root.resolve() or p == p.parent:
                break
        except OSError:
            break
        parents.append(unicodedata.normalize("NFC", p.name))
        p = p.parent
    for name in parents:
        if not meta.patient_id:
            match_patterns(name, FOLDER_PATTERNS, meta, "folder")
        if not meta.exam_date and re.fullmatch(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}", name):
            meta.set("exam_date", norm_date(name, min_year=1990), "folder")
        if not meta.laterality:
            meta.set("laterality", norm_eye(name), "folder")
    return meta
