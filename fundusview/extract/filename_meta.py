"""Patient / exam fields from file and folder names.

Patterns are Python regexes matched against the file *stem* (name without
extension) using named groups:

    pid name last first birth sex date time eye mode seq

Profiles (``profiles.py``) supply camera-specific patterns, e.g. the Kowa
Export Tool styles ``ID_YYYYMMDD_HHMMSS_R_FUNDUS (COLOR)_1``. After the
patterns, a name written next to one number in any order (``홍길동_12345``,
``홍길동(12345)``, ``OD 12345 홍길동``) is read as the patient, and a
conservative token pass picks up an eye / mode / date found anywhere in the
name. A number alone is never a patient id, and neither is a date, a time or a
camera's serial prefix — filing a photo under the wrong patient is worse than
leaving it unassigned (미분류).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..models import ExtractedMeta
from .normalize import apply_field, clean_name, norm_date, norm_eye, norm_modality, norm_time

_EYE_ALT = r"OD|OS|OU|RE|LE|R|L|RIGHT|LEFT|우안|좌안"

_DATE_ALT = r"\d{8}|\d{4}[-.]\d{2}[-.]\d{2}"

# Tried for every profile, after the profile's own patterns.
GENERIC_PATTERNS = (
    # ID_이름_YYYYMMDD[_HHMMSS][_EYE][_...]
    rf"^(?P<pid>[A-Za-z0-9\-]{{2,20}})[_ ](?P<name>[^_\d][^_]{{0,40}}?)[_ ](?P<date>{_DATE_ALT})"
    rf"(?:[_ \-](?P<time>\d{{4,6}}))?(?:[_ \-](?P<eye>{_EYE_ALT}))?(?:[_ \-].*)?$",
    # ID_YYYYMMDD[_HHMMSS][_EYE][_...]
    rf"^(?P<pid>[A-Za-z0-9\-]{{2,20}})_(?P<date>{_DATE_ALT})(?:_(?P<time>\d{{4,6}}))?"
    rf"(?:_(?P<eye>{_EYE_ALT}))?(?:_.*)?$",
    # YYYYMMDD[_HHMMSS]_ID[_이름][_EYE][_...]
    rf"^(?P<date>{_DATE_ALT})(?:[_ ](?P<time>\d{{4,6}}))?[_ ](?P<pid>[A-Za-z0-9\-]{{2,20}})"
    rf"(?:[_ ](?P<name>[^_\d][^_]{{0,40}}?))?(?:[_ ](?P<eye>{_EYE_ALT}))?(?:_.*)?$",
    # 12345678_홍길동[_...] · 12345678(홍길동)
    r"^(?P<pid>\d{4,12})[_ \-(\[]+(?P<name>[가-힣]{2,6})(?:[^0-9A-Za-z가-힣].*)?$",
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


# Camera / phone / scanner / messenger file-name prefixes that look like an id but are not.
_NOT_AN_ID = re.compile(
    r"^(IMG|IMAGE|IMGP|DSC|DSCN|DSCF|PICT|PIC|PXL|MVIMG|SAM|SCAN|CAPTURE|PHOTO|SCREENSHOT|FUNDUS|EXPORT|"
    r"COLOR|MCOLOR|OD|OS|VK|KAKAOTALK|WIN|VID|MOV|RESIZED|SIGNAL|FB|WA|TEMP|TMP|NEW|TEST|COPY|UNTITLED|FILE|"
    r"DOC|PAGE|FIG|FIGURE|GOPR|DJI|CIMG|SDC|SANY)(?:[_\-]?\d*)$", re.IGNORECASE)

# Words that are written where a name could stand but are not a person's name.
_NOT_A_NAME = frozenset("""
    사진 검사 안저 촬영 영상 결과 관찰 수술 치료 주사 병원 안과 의원 센터 폴더 파일 복사 복사본 사본 원본 편집
    백업 자료 환자 이름 미분류 녹내장 백내장 황반 망막 시신경 유두 당뇨 변성 출혈 정상 소견 좌안 우안 양안 오른쪽
    왼쪽 컬러 형광 자가형광 적외선 몽타주 전안부 광각 초광각 초진 재진 술전 술후 전후 이전 이후 오전 오후 스캔
    캡처 화면 제목 무제 제목없음 바탕화면 문서 다운로드 가져오기 내보내기 전체 기타 임시 테스트 확인 완료 보관
    새폴더 익명 무명 미상 신환 구환 경과 추적 비교 최종 수정 수정본 진료 차트 기록 카메라 장비 이미지 그림
""".split())
# … and stems no name contains
_NOT_IN_A_NAME = ("사진", "검사", "안저", "촬영", "폴더", "파일", "병원", "안과", "녹내장", "백내장", "망막",
                  "시신경", "복사본", "가져오기", "내보내기", "미분류", "환자")
_NOT_A_NAME_EN = frozenset("""
    photo photos image images picture pictures backup data export exports files file copy new scan scans fundus
    drive disk folder temp tmp test final old raw jpg jpeg png dicom color colour od os ou eye eyes left right
    camera download downloads desktop documents usb share shared archive misc etc unknown anonymous noname
""".split())


def plausible_name(name: str | None) -> bool:
    """Not one of the words that stand where a name could (사진, 우안, backup …)."""
    n = (name or "").strip()
    if not n or not re.search(r"[^\W\d_]", n):      # a name has a letter in it
        return False
    if any(stem in n for stem in _NOT_IN_A_NAME):
        return False
    words = [w for w in re.split(r"[^0-9A-Za-z가-힣]+", n) if w]
    return not any(w in _NOT_A_NAME or w.lower() in _NOT_A_NAME_EN for w in words)


def date_like(token: str) -> bool:
    """Digits that read as a date: 20240305, 240305, a year, 2024-03, a 12/14-digit time stamp,
    the 13 digits of a clock in milliseconds (``FB_IMG_1709600000000``)."""
    if re.fullmatch(r"(19|20)\d{2}(?:[-.](?:0?[1-9]|1[0-2]))?", token):
        return True                                   # a year, or year-month
    if not token.isdigit():
        return False
    if len(token) in (6, 8):
        return norm_date(token) is not None
    if len(token) == 13 and token[0] == "1":
        return True
    return len(token) in (12, 14) and norm_date(token[:8], min_year=1990) is not None


def plausible_pid(pid: str | None) -> bool:
    """A patient id from a *name* must contain a digit and be neither a camera prefix nor a date."""
    if not pid or not any(c.isdigit() for c in pid) or _NOT_AN_ID.match(pid):
        return False
    return not (date_like(pid) and len(pid) != 6)     # (six digits: only a date where one is expected)


def _stamp_not_pid(m: re.Match) -> bool:
    """``20240305_101500``: the six digits after the date are the time, not a patient."""
    g = m.groupdict()
    pid = g.get("pid") or ""
    return bool(len(pid) == 6 and pid.isdigit() and norm_time(pid) and g.get("date") and not g.get("time")
                and m.start("pid") - m.end("date") == 1)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9A-Za-z가-힣@]+", text) if t]      # letters and digits; the rest separates


def name_id_pair(text: str) -> tuple[str, str] | None:
    """``(patient id, name)`` when ``text`` holds exactly one Korean name and one number that can
    be a chart number, in any order: ``홍길동_12345``, ``홍길동(12345)``, ``OD 12345 홍길동``.

    Dates (also a six-digit birth date next to the name), the time after a date, short serial
    numbers and camera prefixes are not chart numbers; with two candidates nothing is guessed.
    """
    text = re.sub(r"(?<!\d)\d{4}[-.]\d{1,2}[-.]\d{1,2}(?!\d)", " @date ", text)      # a written date
    text = re.sub(r"([가-힣])(?=[A-Za-z]{0,3}\d{4})", r"\1 ", text)                     # 홍길동12345
    text = re.sub(r"(\d)(?=[가-힣])", r"\1 ", text)                                     # 12345홍길동
    names, ids, after_date = [], [], False
    for t in _tokens(text):
        was_date, after_date = after_date, False
        if t == "@date" or (t.isdigit() and len(t) == 8 and date_like(t)):
            after_date = True
        elif re.fullmatch(r"[가-힣]{2,4}", t):
            if plausible_name(t) and not norm_eye(t) and not norm_modality(t):
                names.append(t)
        elif re.fullmatch(r"[A-Za-z]{0,3}\d{4,12}", t) and plausible_pid(t) and not date_like(t):
            if not (was_date and t.isdigit() and len(t) in (4, 6) and norm_time(t)):
                ids.append(t)
    if len(names) == 1 and len(ids) == 1:
        return ids[0], names[0]
    return None


def _apply_match(meta: ExtractedMeta, m: re.Match, source: str) -> None:
    g = {k: v for k, v in m.groupdict().items() if v}
    if g.get("name", "").strip().lower() in ("anonymous", "unknown", "noname", "no name", "익명"):
        g.pop("name")  # capture software placeholders (RetiCam default patient)
    if "name" in g and not plausible_name(g["name"]):
        g.pop("name")
        g.pop("pid", None)   # "2026_사진": neither a name nor an id
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
        except (re.error, TypeError):            # (TypeError: a pattern that is not text)
            continue
        if m and "pid" in m.groupdict() and m.group("pid") and (
                not plausible_pid(m.group("pid")) or _stamp_not_pid(m)
                or ("name" in m.groupdict() and m.group("name") and not plausible_name(m.group("name")))):
            continue  # e.g. IMG_20240305_101500, 20240305_101500, 2026_사진: try the next rule instead
        if m:
            _apply_match(meta, m, source)
            meta.raw.setdefault("파일명 규칙", pat if len(pat) < 120 else pat[:117] + "...")
            return True
    return False


def _token_pass(stem: str, meta: ExtractedMeta) -> None:
    written = re.search(r"(?<!\d)\d{4}[-.]\d{1,2}[-.]\d{1,2}(?!\d)", stem)      # 2024-03-05
    if written and not meta.exam_date:
        meta.set("exam_date", norm_date(written.group(0), min_year=1990), "filename")
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
        if not meta.name and re.fullmatch(r"[가-힣]{2,5}", t) and plausible_name(t):
            meta.set("name", clean_name(t), "filename")
        prev_was_date = False


def _resolved(p: Path) -> Path | None:
    try:
        return p.resolve()
    except OSError:
        return None


def filename_meta(path: Path, patterns=(), *, watch_root: Path | None = None,
                  id_only: bool = False, parent_levels: int | None = None) -> ExtractedMeta:
    """Extract from ``path``'s name, then its parent folders.

    The folders looked at are those below ``watch_root`` (at most 3 levels); without a watched
    root — photos picked by hand — the nearest ``parent_levels`` folders (none unless given).

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
    if not meta.patient_id:
        pair = name_id_pair(stem)
        if pair and (not meta.name or meta.name == pair[1]):
            meta.set("patient_id", pair[0], "filename")
            meta.set("name", clean_name(pair[1]), "filename")
    _token_pass(stem, meta)

    # Parent folders: within the watched root (at most 3 levels), or the nearest few of a
    # photo picked by hand.
    if parent_levels is None:
        parent_levels = 3 if watch_root is not None else 0
    root = _resolved(watch_root) if watch_root is not None else None
    parents = []
    p = path.parent
    while len(parents) < parent_levels and p != p.parent:
        if root is not None and (p == watch_root or _resolved(p) == root):
            break
        parents.append(unicodedata.normalize("NFC", p.name))
        p = p.parent
    for name in parents:
        if not meta.patient_id:
            if not match_patterns(name, FOLDER_PATTERNS, meta, "folder"):
                pair = name_id_pair(name)
                if pair and (not meta.name or meta.name == pair[1]):
                    meta.set("patient_id", pair[0], "folder")
                    meta.set("name", clean_name(pair[1]), "folder")
        if not meta.exam_date and re.fullmatch(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}", name):
            meta.set("exam_date", norm_date(name, min_year=1990), "folder")
        if not meta.laterality:
            meta.set("laterality", norm_eye(name), "folder")
    return meta
