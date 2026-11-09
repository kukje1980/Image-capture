"""안저 카메라 사진 파일 이름에서 환자 아이디·이름·촬영 날짜/시각·좌우(안구)를 읽는다.

데스크탑(app/services/fundus_filename.py)과 웹(web/app/fundus_filename.py)이 같은 파일을 쓴다.
고칠 때는 두 파일을 똑같이 맞춘다 (tests/test_folder_import.py 가 확인).

형식(template)을 정하면 그대로 읽고, 비우면 자동으로 알아낸다.
  토큰: {id} 아이디(차트번호)  {name} 이름  {date} 날짜  {time} 시각  {eye} 좌우  {*} 무시
  예)  {id}_{name}_{date}_{eye}     → 12345_홍길동_20261109_R.jpg
       {date}{time}_{id}_{eye}      → 20261109143015_12345_OD.jpg
       {id}-{eye}-{date}            → A0123-L-2026.11.09.jpg
  형식 뒤에 붙는 순번·기타 글자(_001, (2) 등)는 무시한다.
좌우: R·RE·RT·RIGHT·OD·우·우안 → OD,  L·LE·LT·LEFT·OS·좌·좌안 → OS,  B·BOTH·OU·양안 → OU
촬영 부위(어느 형식이든 이름 안에 있으면): DISC·ONH·유두 → 시신경유두 중심, MAC·MACULA·황반 → 황반 중심,
  PERI·주변 → 주변부
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

EYE_WORDS = {
    "OD": "OD", "R": "OD", "RE": "OD", "RT": "OD", "RIGHT": "OD", "우": "OD", "우안": "OD",
    "OS": "OS", "L": "OS", "LE": "OS", "LT": "OS", "LEFT": "OS", "좌": "OS", "좌안": "OS",
    "OU": "OU", "B": "OU", "BOTH": "OU", "양": "OU", "양안": "OU",
}
# 이름으로 오인하지 않을 흔한 단어 (카메라·촬영 종류 표시 등)
_NOISE = {
    "IMG", "IMAGE", "PIC", "PHOTO", "DSC", "DSCN", "CAPTURE", "SCAN", "EXPORT", "COPY",
    "FUNDUS", "COLOR", "COLOUR", "RF", "REDFREE", "RED", "FREE", "FA", "FAF", "ICG", "OCT", "IR",
    "NM", "MYD", "DISC", "MAC", "MACULA", "CENTER", "CENTRAL", "PERI", "WIDE",
    "안저", "사진", "촬영", "컬러", "적색", "무적색",
}
TOKENS = ("id", "name", "date", "time", "eye")
FIELDS = {"DISC": "시신경유두 중심", "ONH": "시신경유두 중심", "유두": "시신경유두 중심",
          "시신경유두": "시신경유두 중심", "MAC": "황반 중심", "MACULA": "황반 중심", "황반": "황반 중심",
          "PERI": "주변부", "주변": "주변부", "주변부": "주변부"}
_SEP = r"[_\-\s.,()\[\]^~+]+"

_DATE_RE = (r"(?P<y>(?:19|20)\d{2})[-._]?(?P<m>0[1-9]|1[0-2])[-._]?(?P<d>0[1-9]|[12]\d|3[01])")
_TIME_RE = r"(?P<H>[01]\d|2[0-3])[-.:]?(?P<M>[0-5]\d)(?:[-.:]?(?P<S>[0-5]\d))?"
# 날짜 바로 뒤(구분 없음·T·공백)에 붙은 시각까지 함께
_DATE_TIME_AUTO = re.compile(r"(?<!\d)" + _DATE_RE + r"(?:[T ]?" + _TIME_RE + r")?(?!\d)")


@dataclass
class ParsedName:
    id: str | None = None
    name: str | None = None
    date: str | None = None          # 'YYYY-MM-DD'
    time: str | None = None          # 'HH:MM:SS'
    eye: str = "NA"                  # OD | OS | OU | NA
    field: str | None = None         # 촬영 부위 (시신경유두 중심 · 황반 중심 · 주변부)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.id) and not self.error

    def summary(self) -> str:
        if not self.ok:
            return f"읽지 못함: {self.error or '아이디 없음'}"
        bits = [f"아이디 {self.id}", f"이름 {self.name or '-'}", f"날짜 {self.date or '-'}"]
        if self.time:
            bits.append(f"시각 {self.time}")
        bits.append(f"좌우 {self.eye if self.eye != 'NA' else '-'}")
        if self.field:
            bits.append(self.field)
        return " · ".join(bits)


def stem_of(filename: str) -> str:
    base = re.split(r"[\\/]", filename or "")[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def eye_code(word: str | None) -> str:
    return EYE_WORDS.get((word or "").strip().upper(), "NA")


def _valid_date(y: int, m: int, d: int) -> str | None:
    try:
        return datetime(y, m, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _norm_date(text: str) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 8:
        return _valid_date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
    if len(digits) == 6:                                      # YYMMDD
        return _valid_date(2000 + int(digits[:2]), int(digits[2:4]), int(digits[4:]))
    return None


def _norm_time(text: str) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) not in (4, 6):
        return None
    hh, mm = int(digits[:2]), int(digits[2:4])
    ss = int(digits[4:6]) if len(digits) == 6 else 0
    if hh > 23 or mm > 59 or ss > 59:
        return None
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _clean_name(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"[_^]+", " ", text).strip()
    return t or None


def template_regex(template: str) -> re.Pattern:
    """'{id}_{name}_{date}_{eye}' → 정규식 (뒤에 붙는 순번 등은 허용)."""
    parts = re.split(r"(\{[^{}]*\})", template.strip())
    rx = ""
    used = set()
    for p in parts:
        if not p:
            continue
        m = re.fullmatch(r"\{\s*([a-z*]+)\s*\}", p)
        if not m:
            rx += re.escape(p)
            continue
        tok = m.group(1)
        if tok == "*":
            rx += r".*?"
            continue
        if tok not in TOKENS:
            raise ValueError(f"알 수 없는 토큰: {{{tok}}} (쓸 수 있는 것: {{id}} {{name}} {{date}} {{time}} {{eye}} {{*}})")
        if tok in used:
            raise ValueError(f"{{{tok}}} 를 두 번 썼습니다")
        used.add(tok)
        rx += {
            "id": r"(?P<id>.+?)",
            "name": r"(?P<name>.+?)",
            "date": r"(?P<date>(?:19|20)\d{2}[-._]?\d{2}[-._]?\d{2}|\d{6})",
            "time": r"(?P<time>\d{2}[-.:]?\d{2}(?:[-.:]?\d{2})?)",
            "eye": r"(?P<eye>[A-Za-z가-힣]+)",
        }[tok]
    if "id" not in used:
        raise ValueError("형식에 {id} 가 있어야 합니다")
    return re.compile(r"^" + rx + r"(?:[_\-\s.(\[~+].*)?$", re.IGNORECASE)


def field_of(stem: str) -> str | None:
    for t in re.split(_SEP, stem):
        f = FIELDS.get(t.upper()) or FIELDS.get(t)
        if f:
            return f
    return None


def parse_filename(filename: str, template: str = "") -> ParsedName:
    """파일 이름 → ParsedName. template 이 비어 있으면 자동 인식."""
    stem = stem_of(filename)
    r = _parse_template(stem, template) if (template or "").strip() else _parse_auto(stem)
    if r.ok:
        r.field = field_of(stem)
    return r


def _parse_template(stem: str, template: str) -> ParsedName:
    try:
        rx = template_regex(template)
    except ValueError as e:
        return ParsedName(error=str(e))
    m = rx.match(stem)
    if not m:
        return ParsedName(error=f"형식({template})과 맞지 않음")
    g = m.groupdict()
    r = ParsedName(id=(g.get("id") or "").strip() or None, name=_clean_name(g.get("name")))
    if g.get("date"):
        r.date = _norm_date(g["date"])
        if r.date is None:
            r.error = f"날짜를 읽지 못함: {g['date']}"
    if g.get("time"):
        r.time = _norm_time(g["time"])
    if g.get("eye"):
        r.eye = eye_code(g["eye"])
    if not r.id and not r.error:
        r.error = "아이디 없음"
    return r


def _parse_auto(stem: str) -> ParsedName:
    r = ParsedName()
    rest = stem
    dm = _DATE_TIME_AUTO.search(rest)
    if dm:
        r.date = _valid_date(int(dm.group("y")), int(dm.group("m")), int(dm.group("d")))
        if r.date:
            if dm.group("H"):
                r.time = f"{dm.group('H')}:{dm.group('M')}:{dm.group('S') or '00'}"
            rest = rest[:dm.start()] + " \x00 " + rest[dm.end():]      # 날짜 자리 표시
    tokens = [t for t in re.split(_SEP, rest) if t]
    # 날짜 바로 뒤의 6자리 시각 (아이디 후보가 따로 있을 때만 — 6자리 아이디와 헷갈리지 않게)
    if r.date and not r.time and "\x00" in tokens:
        i = tokens.index("\x00")
        if i + 1 < len(tokens) and re.fullmatch(r"\d{6}", tokens[i + 1]) and _norm_time(tokens[i + 1]):
            others = [t for j, t in enumerate(tokens) if j not in (i, i + 1) and re.search(r"\d", t)]
            if others:
                r.time = _norm_time(tokens[i + 1])
                tokens.pop(i + 1)
    tokens = [t for t in tokens if t != "\x00"]
    # 좌우
    for t in tokens:
        if t.upper() in EYE_WORDS:
            r.eye = EYE_WORDS[t.upper()]
            tokens.remove(t)
            break
    # 아이디: 숫자가 들어간 첫 토큰 (두 글자 이상)
    for t in tokens:
        if len(t) >= 2 and re.search(r"\d", t):
            r.id = t
            tokens.remove(t)
            break
    # 이름: 한글 토큰이 먼저, 없으면 이어진 영문 토큰들
    words = [t for t in tokens if re.fullmatch(r"[A-Za-z가-힣]+", t) and t.upper() not in _NOISE
             and t.upper() not in EYE_WORDS and t not in FIELDS and t.upper() not in FIELDS]
    hangul = [t for t in words if re.search(r"[가-힣]", t)]
    if hangul:
        r.name = hangul[0]
    elif words:
        r.name = " ".join(w for w in words if re.fullmatch(r"[A-Za-z]+", w)) or None
    if not r.id:
        r.error = "아이디(숫자가 든 부분)를 찾지 못함"
    elif not (r.name or r.date or r.eye != "NA"):
        # IMG_0042 같은 카메라 기본 이름을 환자 아이디로 착각하지 않게
        r.error = "아이디 말고 이름·날짜·좌우가 하나도 없음 — 설정에서 파일 이름 형식을 지정하세요"
    return r


def captured_at(parsed: ParsedName, fallback: datetime) -> str:
    """'YYYY-MM-DD HH:MM:SS' — 파일 이름의 날짜/시각, 없는 부분은 fallback(사진 정보·파일 시각)으로."""
    d = parsed.date or fallback.strftime("%Y-%m-%d")
    t = parsed.time or (fallback.strftime("%H:%M:%S") if (parsed.date is None or
                                                          parsed.date == fallback.strftime("%Y-%m-%d"))
                        else "00:00:00")
    return f"{d} {t}"
