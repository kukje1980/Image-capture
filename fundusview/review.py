"""Which photos a review shows: exams (one per exam date), the photo of each eye in an exam, and
the earlier exams of an eye that the current one is compared with.

The rows are ``images`` rows (``db.images_for_patient``). Nothing here touches Qt — the patient
list (검사 목록) and the 검토 tab (ui/review_view.py) both read their photos from these functions.

Rules
* An **exam** is one exam date. Photos without a date form one group at the end.
* Sheets the viewer made itself (디스크 2장, 녹내장 분석) are never review photos; anterior
  segment photos are not fundus photos and are never chosen for an eye either.
* The photo of an eye in an exam is its newest **colour** photo; without one, the newest photo
  of another kind (Red-free, FA …); a saved montage only when there is nothing else.
* Photos of an unknown eye (or OU) are never chosen by themselves — they can be put on a view
  by hand from the timeline.
"""
from __future__ import annotations

from .models import MODALITY_LABELS

SHEETS = ("disc", "glaucoma")          # made by the viewer: not photographs
EYES = ("OD", "OS")
NO_DATE = ""                           # key of the exam of the photos without a date


def _get(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def is_photo(row) -> bool:
    """A photograph that may be shown in a review (the timeline lists these)."""
    return (_get(row, "modality") or "") not in SHEETS


def _rank(row) -> int:
    """Preference of a photo for the place of its eye: colour, other kinds, montage."""
    mod = _get(row, "modality") or "color"
    return 0 if mod == "color" else 2 if mod == "montage" else 1


def _when(row) -> tuple:
    return (_get(row, "exam_time") or "", _get(row, "id") or 0)


def exams(rows) -> list[tuple[str, list]]:
    """``[(date, rows)]`` newest exam first; inside an exam the photos in the order taken."""
    by_date: dict[str, list] = {}
    for r in rows:
        by_date.setdefault(_get(r, "exam_date") or NO_DATE, []).append(r)
    dates = sorted((d for d in by_date if d != NO_DATE), reverse=True)
    if NO_DATE in by_date:
        dates.append(NO_DATE)
    return [(d, sorted(by_date[d], key=_when)) for d in dates]


def exam_dates(rows) -> list[str]:
    return [d for d, _ in exams(rows)]


def eye_photo(rows, eye: str):
    """The photo shown for ``eye`` out of one exam's ``rows`` (None: the eye was not taken)."""
    best = None
    for r in rows:
        if _get(r, "laterality") != eye or not is_photo(r) or _get(r, "modality") == "anterior":
            continue
        if best is None or _rank(r) < _rank(best) or (_rank(r) == _rank(best) and _when(r) > _when(best)):
            best = r
    return best


def eye_series(rows, eye: str, current: str | None = None) -> list:
    """The photo of ``eye`` in every exam that has one, newest first, starting at the exam
    ``current`` (later exams are left out; None = from the newest)."""
    out = []
    for d, group in exams(rows):
        if current and d != NO_DATE and d > current:
            continue
        if current == NO_DATE and d != NO_DATE:
            continue
        r = eye_photo(group, eye)
        if r is not None:
            out.append(r)
    return out


def summary(rows) -> str:
    """``컬러 4장 · Red-free 2장`` — the photos of an exam by kind."""
    counts: dict[str, int] = {}
    for r in rows:
        mod = _get(r, "modality") or ""
        counts[mod] = counts.get(mod, 0) + 1
    order = list(MODALITY_LABELS) + sorted(k for k in counts if k not in MODALITY_LABELS)
    return " · ".join(f"{MODALITY_LABELS.get(k, k or '사진')} {counts[k]}장" for k in order if k in counts)


def newest_photo(rows, date: str | None = None):
    """The photo a shortcut (2D 보기 / 3D 안구) opens: of the exam ``date`` (None: the newest
    exam) the right eye's photo, else the left eye's, else the newest photograph."""
    groups = exams(rows)
    if not groups:
        return None
    group = next((g for d, g in groups if d == date), groups[0][1])
    for eye in EYES:
        r = eye_photo(group, eye)
        if r is not None:
            return r
    shots = [r for r in group if is_photo(r)]
    return max(shots, key=lambda r: (-_rank(r), _when(r))) if shots else None
