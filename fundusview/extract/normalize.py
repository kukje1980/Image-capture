"""Normalisation of the many spellings capture software uses for dates, sex,
eye (laterality) and imaging mode, plus a tolerant ``key: value`` parser for
free text (EXIF comments, sidecar .txt/.ini/.xml files)."""
from __future__ import annotations

import re
from datetime import date, datetime

_HANGUL = re.compile(r"[가-힣]")


def has_hangul(s: str) -> bool:
    return bool(_HANGUL.search(s or ""))


def norm_date(s: str | None, *, min_year: int = 1900, max_year: int = 2100) -> str | None:
    """Return ``YYYY-MM-DD`` for the usual spellings, else ``None``.

    Accepts YYYYMMDD, YYYY-MM-DD / . / / / _ separators, EXIF
    ``YYYY:MM:DD[ hh:mm:ss]``, DICOM DA and ISO datetimes. Two-digit years
    (YYMMDD) are only accepted when ``min_year`` allows it.
    """
    if not s:
        return None
    s = str(s).strip()
    k = re.match(r"^(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?", s)   # 2024년 3월 5일
    m = re.match(r"^(\d{4})[-./:_ ]?(\d{1,2})[-./:_ ]?(\d{1,2})(?:$|[ T_\-]?\d)", s)
    if k:
        y, mo, d = (int(g) for g in k.groups())
    elif m and (len(s) >= 8 or re.match(r"^\d{4}\D", s)):
        y, mo, d = (int(g) for g in m.groups())
    else:
        # YYMMDD, and YY.MM.DD / YY-MM-DD as written by hand in Korea
        m = re.match(r"^(\d{2})(\d{2})(\d{2})$", s) or re.match(r"^(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\.?$", s)
        if not m:
            m2 = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", s)  # DD.MM.YYYY
            if not m2:
                return None
            d, mo, y = (int(g) for g in m2.groups())
        else:
            yy, mo, d = (int(g) for g in m.groups())
            y = 2000 + yy if yy <= (datetime.now().year % 100) else 1900 + yy
    if not (min_year <= y <= max_year):
        return None
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def norm_time(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{1,2})[:\-._]?(\d{2})(?:[:\-._]?(\d{2}))?", s)
    if not m:
        return None
    h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59 or se > 59:
        return None
    return f"{h:02d}:{mi:02d}:{se:02d}"


_SEX = {
    "M": "M", "MALE": "M", "남": "M", "남자": "M", "남성": "M",
    "F": "F", "FEMALE": "F", "W": "F", "여": "F", "여자": "F", "여성": "F",
    "O": "O", "OTHER": "O",
}


def norm_sex(s: str | None) -> str | None:
    if not s:
        return None
    return _SEX.get(str(s).strip().upper())


_EYE = {
    "OD": "OD", "R": "OD", "RE": "OD", "RIGHT": "OD", "RT": "OD", "우": "OD", "우안": "OD", "오른쪽": "OD",
    "OS": "OS", "L": "OS", "LE": "OS", "LEFT": "OS", "LT": "OS", "좌": "OS", "좌안": "OS", "왼쪽": "OS",
    "OU": "OU", "B": "OU", "BOTH": "OU", "양안": "OU",
}


def norm_eye(s: str | None) -> str | None:
    if not s:
        return None
    return _EYE.get(str(s).strip().upper())


_MODALITY = {
    "COLOR": "color", "COLOUR": "color", "COL": "color", "RGB": "color", "CF": "color", "컬러": "color",
    "MCOLOR": "color",
    "RF": "redfree", "REDFREE": "redfree", "RED-FREE": "redfree", "RED_FREE": "redfree", "GREEN": "redfree",
    "AF": "af", "FAF": "af", "AUTOFLUORESCENCE": "af", "자가형광": "af",
    "FA": "fa", "FAG": "fa", "FFA": "fa", "형광": "fa",
    "ICG": "icg", "ICGA": "icg",
    "IR": "ir", "NIR": "ir", "INFRARED": "ir", "적외선": "ir",
    "ANT": "anterior", "ANTERIOR": "anterior", "전안부": "anterior",
    "MONTAGE": "montage", "MOSAIC": "montage", "PANORAMA": "montage", "몽타주": "montage",
}


def norm_modality(s: str | None) -> str | None:
    if not s:
        return None
    return _MODALITY.get(str(s).strip().upper())


def clean_name(s: str | None) -> str | None:
    """DICOM-style ``Family^Given`` -> ``Family Given``; trims padding/odd chars."""
    if not s:
        return None
    s = str(s).replace("^", " ").replace("\x00", " ")
    s = re.sub(r"\s+", " ", s).strip(" _-.,")
    if re.fullmatch(r"[가-힣]{1,2} [가-힣]{1,4}", s):  # 박^지호 -> 박지호
        s = s.replace(" ", "")
    return s or None


# ---------------------------------------------------------------------------
# key: value text
# ---------------------------------------------------------------------------
_KEYMAP = {
    "patient_id": ("patientid", "pid", "id", "patid", "chartno", "chart", "chartnumber", "mrn",
                   "환자번호", "등록번호", "차트번호", "환자id", "patientno", "patientnumber"),
    "name": ("patientname", "name", "patient", "patname", "fullname", "이름", "성명", "환자명", "환자이름"),
    "_last": ("lastname", "familyname", "surname", "성"),
    "_first": ("firstname", "givenname", "이름(名)"),
    "birth_date": ("birthdate", "birthday", "dob", "dateofbirth", "birth", "patientbirthdate", "생년월일", "생일"),
    "sex": ("sex", "gender", "patientsex", "성별"),
    "exam_date": ("examdate", "studydate", "date", "capturedate", "acquisitiondate", "shootingdate",
                  "contentdate", "검사일", "촬영일", "검사일자", "촬영일자"),
    "exam_time": ("examtime", "studytime", "time", "capturetime", "acquisitiontime", "촬영시각", "검사시각", "촬영시간"),
    "laterality": ("eye", "laterality", "imagelaterality", "side", "lr", "눈", "좌우", "안"),
    "modality": ("mode", "modality", "type", "imagetype", "filter", "촬영종류", "촬영모드"),
    "device": ("device", "camera", "model", "equipment", "장비", "장비명"),
    "description": ("comment", "comments", "description", "memo", "note", "비고", "메모"),
}
_KEYLOOKUP = {alias: f for f, aliases in _KEYMAP.items() for alias in aliases}
# Words that also turn up in text that has nothing to do with a patient ("id=5" in a URL, an
# XMP packet's ``id``, "Name: Sunset", "Type: screenshot"). In free text inside a picture file
# (``strict``) they only count when the text reads as a patient record — see parse_key_values.
_GENERIC_KEYS = frozenset((
    "id", "pid", "name", "patient", "fullname", "chart", "birth", "date", "time", "side", "lr", "안", "성",
    "type", "mode", "filter", "model", "device", "camera", "equipment", "comment", "comments",
    "description", "memo", "note", "lastname", "firstname", "surname", "sex", "gender", "눈", "이름",
))
_PATIENT_FIELDS = ("patient_id", "name", "_last", "_first", "birth_date", "sex")
_KV = re.compile(r"(?P<key>[A-Za-z가-힣][A-Za-z가-힣0-9 _.()/-]{0,30}?)\s*[:=]\s*(?P<val>[^;\n\r|&]*)")


def canonical_key(key: str) -> str | None:
    k = re.sub(r"[\s_.\-/]", "", key).lower()
    return _KEYLOOKUP.get(k)


def is_generic_key(key: str) -> bool:
    return re.sub(r"[\s_.\-/]", "", key).lower() in _GENERIC_KEYS


def valid_patient_id(value: str | None) -> bool:
    """A value that can be a chart number: short, one word, no URL / path / sentence."""
    v = re.sub(r"\s+", "", value or "")
    return bool(v) and len(v) <= 32 and re.fullmatch(r"[\w\-.#+]+", v) is not None \
        and v.lower() not in ("none", "null", "unknown", "anonymous", "n/a", "na", "test", "0")


def valid_person_name(value: str | None) -> bool:
    """A value that can be a person's name: no digits-only, no ``key: value`` / URL remains."""
    v = (value or "").strip()
    return bool(v) and len(v) <= 40 and not re.search(r"[:=/\\@<>{}\[\]|;]|\d{3}", v) \
        and re.search(r"[^\W\d_]", v) is not None


def apply_field(meta, field: str, value: str, source: str) -> None:
    """Normalise ``value`` for ``field`` and store it on ``meta`` if empty."""
    value = (value or "").strip().strip('"').strip()
    if not value:
        return
    if field == "birth_date":
        meta.set(field, norm_date(value), source)
    elif field == "exam_date":
        meta.set(field, norm_date(value, min_year=1990), source)
        if not meta.exam_time:  # "2024-03-05 10:22:01"
            m = re.search(r"[ T](\d{1,2}:\d{2}(?::\d{2})?)", value)
            if m:
                meta.set("exam_time", norm_time(m.group(1)), source)
    elif field == "exam_time":
        meta.set(field, norm_time(value), source)
    elif field == "sex":
        meta.set(field, norm_sex(value), source)
    elif field == "laterality":
        meta.set(field, norm_eye(value), source)
    elif field == "modality":
        meta.set(field, norm_modality(value), source)
    elif field == "name":
        meta.set(field, clean_name(value), source)
    elif field == "patient_id":
        meta.set(field, re.sub(r"\s+", "", value), source)
    else:
        meta.set(field, value, source)


def parse_key_values(text: str, meta, source: str, *, strict: bool = False) -> int:
    """Pull recognised ``key: value`` / ``key=value`` pairs out of ``text``.

    Returns the number of fields filled. Split family/given names are joined.

    ``strict`` is for free text found *inside* a picture file (EXIF, comments, XMP), which is
    often not about a patient at all: a patient id or name has to look like one, and a common
    word used as the key ("id", "name" …) only counts when the text reads as a patient record —
    an unmistakable key (``PatientID``, ``환자번호`` …) or at least two different patient fields.
    """
    if not text:
        return 0
    before = sum(1 for v in meta.sources)
    parts: dict[str, str] = {}
    pairs = []
    for m in _KV.finditer(text):
        field = canonical_key(m.group("key"))
        if not field:
            continue
        val = m.group("val").strip().strip('"').strip()
        if strict and ((field == "patient_id" and not valid_patient_id(val))
                       or (field in ("name", "_last", "_first") and not valid_person_name(val))):
            continue
        pairs.append((field, val, is_generic_key(m.group("key"))))
    if strict:
        patient = {f for f, v, _ in pairs if f in _PATIENT_FIELDS and v}
        record = any(f in _PATIENT_FIELDS and not generic for f, _, generic in pairs) or len(patient) >= 2
        if not record:
            pairs = [(f, v, g) for f, v, g in pairs if f not in _PATIENT_FIELDS]
    for field, val, _generic in pairs:
        if field.startswith("_"):
            parts[field] = val
        else:
            apply_field(meta, field, val, source)
    if parts and not meta.name:
        apply_field(meta, "name", " ".join(p for p in (parts.get("_last"), parts.get("_first")) if p), source)
    return sum(1 for v in meta.sources) - before
