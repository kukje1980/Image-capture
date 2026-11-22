"""시간별 비교 — the optic disc of one eye over the years (녹내장 분석 → 시간별 비교).

Every photo of the eye is cut around its disc to the same retinal field (in disc diameters, so
that cameras of different fields compare — ``discpair.py``), laid onto the oldest one (a small turn,
size and shift from matched vessel points — ``glaucoma.find_turn``) and then shown either **side by
side in the order of time** (``sheet``) or **on top of each other** (``crossfade``: a time slider
that fades from each photo into the next).

This module is the arithmetic (no Qt): which photos to take, how to lay them out, how to say how
long after the first one a photo was taken. The window is ``ui/timeline_tab.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable

import cv2
import numpy as np

from . import glaucoma as G

MAX_PHOTOS = 12              # photos on screen at once (3 × 4)
FRAME_PX = 720               # side of a disc-centred frame
# what is shown of each photo: (key, label, width in disc diameters)
REGIONS = (("near", "유두", 3.0), ("disc", "유두 주변", 5.0), ("wide", "넓게", 10.0))
LIMIT = 60.0                 # the furthest a frame is moved to lie on the first one (px of the frame)


def common_eye(photos) -> str | None:
    """The one confirmed/resolved eye of every source, or None for mixed/unknown sources."""
    eyes = {photo.eye for photo in photos}
    return next(iter(eyes)) if len(eyes) == 1 and eyes <= {"OD", "OS"} else None


@dataclass
class Shot:
    """One photo that can go on the timeline. ``load()`` reads it (a ``glaucoma_dialog.Photo``, or
    None when the file cannot be read) — only the photos that are shown are read."""
    image_id: int
    when: str                          # "YYYY-MM-DD HH:MM:SS" ("" unknown)
    eye: str | None = None
    caption: str = ""                  # device · field · kind
    load: Callable[[], object] | None = None
    source_version: object | None = None     # immutable source metadata when this analysis was opened

    @property
    def day(self) -> str:
        return self.when[:10]


def in_order(shots) -> list:
    """Oldest first (photos without a date last)."""
    return sorted(shots, key=lambda s: (not s.when, s.when or "", s.image_id))


def _date(day: str) -> date | None:
    try:
        return date.fromisoformat(day[:10])
    except (TypeError, ValueError):
        return None


def days_between(first: str, day: str) -> int | None:
    a, b = _date(first), _date(day)
    return (b - a).days if a is not None and b is not None else None


def interval_text(first: str, day: str) -> str:
    """How long after ``first`` the photo of ``day`` was taken: "기준일", "+12일", "+3개월",
    "+1년 2개월" ("" when a date is missing)."""
    a, b = _date(first), _date(day)
    if a is None or b is None:
        return ""
    if a == b:
        return "기준일"
    sign = "+" if b > a else "−"
    lo, hi = (a, b) if b > a else (b, a)
    months = (hi.year - lo.year) * 12 + hi.month - lo.month - (1 if hi.day < lo.day else 0)
    if months < 1:
        return f"{sign}{(hi - lo).days}일"
    years, months = divmod(months, 12)
    if not years:
        return f"{sign}{months}개월"
    return f"{sign}{years}년" + (f" {months}개월" if months else "")


def spread(n: int, k: int, keep=()) -> list[int]:
    """``k`` of ``range(n)``, evenly spread, with both ends and the indexes of ``keep``."""
    if n <= k:
        return list(range(n))
    out = {i for i in keep if 0 <= i < n}
    out |= {0, n - 1}
    out = set(sorted(out)[:k]) if len(out) > k else out
    while len(out) < k:                                  # the widest gap gets its middle, again and again
        have = sorted(out)
        gap, i = max((b - a, a) for a, b in zip(have, have[1:]))
        if gap < 2:
            break
        out.add(i + gap // 2)
    return sorted(out)


def pick_default(shots, current_id: int | None = None, limit: int = MAX_PHOTOS, prefer=()) -> list[int]:
    """The photos shown at first, as image ids in the order of time: ``prefer`` (photos the user
    picked) when two or more of them are here; otherwise one photo of each exam day (the photo on
    screen for its day, else the day's first), thinned out evenly to ``limit`` — the oldest, the newest
    and the photo on screen always stay."""
    shots = in_order(shots)
    ids = [s.image_id for s in shots]
    chosen = [i for i in ids if i in set(prefer)]
    if len(chosen) >= 2:
        if current_id in ids and current_id not in chosen and len(chosen) < limit:
            chosen = [i for i in ids if i in set(chosen) | {current_id}]
        return chosen[:limit]
    per_day: dict[str, Shot] = {}
    for n, s in enumerate(shots):
        key = s.day or f"?{n}"
        if key not in per_day or s.image_id == current_id:
            per_day[key] = s
    days = list(per_day.values())
    keep = [i for i, s in enumerate(days) if s.image_id == current_id]
    return [days[i].image_id for i in spread(len(days), limit, keep)]


# -- frames ----------------------------------------------------------------------------------------
def frames_of(rgb: np.ndarray, disc, disc_px: float, px: int = FRAME_PX) -> dict[str, np.ndarray]:
    """The photo cut around its disc, once for each of ``REGIONS`` (``px`` square each)."""
    out = {}
    for key, _label, factor in REGIONS:
        crop, _, _ = G.crop_square(rgb, disc[0], disc[1], factor * disc_px)
        inter = cv2.INTER_AREA if crop.shape[0] > px else cv2.INTER_CUBIC
        out[key] = cv2.resize(crop, (px, px), interpolation=inter)
    return out


@dataclass
class Fit:
    """How a frame is laid onto the first one."""
    angle: float = 0.0
    scale: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    how: str = "none"                  # turn (matched vessel points) / shift / none (as it is)

    def text(self) -> str:
        if self.how == "none":
            return "맞추지 않음"
        s = f"좌우 {self.dx:+.1f} px · 상하 {self.dy:+.1f} px"
        if self.how == "turn":
            s += f" · 회전 {self.angle:+.1f}° · 크기 {self.scale * 100:.1f}%"
        return s


def register(ref: np.ndarray, frame: np.ndarray, limit: float = LIMIT) -> Fit:
    """The turn, size and shift that lay ``frame`` on ``ref`` (vessel points; a shift alone where too
    few agree)."""
    found = G.find_turn(ref, frame)
    if found is not None and abs(found[2]) <= limit and abs(found[3]) <= limit:
        return Fit(found[0], found[1], found[2], found[3], "turn")
    dx, dy = G.find_shift(ref, frame)
    return Fit(0.0, 1.0, float(dx), float(dy), "shift")


def applied(frame: np.ndarray, fit: Fit, nudge=(0.0, 0.0)) -> np.ndarray:
    """``frame`` as ``fit`` lays it, moved by ``nudge`` (the hand's correction) on top."""
    dx, dy = fit.dx + nudge[0], fit.dy + nudge[1]
    if abs(fit.angle) > 1e-6 or abs(fit.scale - 1.0) > 1e-6:
        return G.turned(frame, fit.angle, fit.scale, dx, dy)
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return frame
    return G.shifted(frame, dx, dy)


# -- side by side ----------------------------------------------------------------------------------
def grid_shape(n: int) -> tuple[int, int]:
    """``(rows, cols)`` for ``n`` photos in reading order: one row up to three, then as square as
    it gets (4: 2×2, 6: 2×3, 9: 3×3, 12: 3×4)."""
    if n <= 3:
        return 1, max(1, n)
    cols = math.ceil(math.sqrt(n))
    return math.ceil(n / cols), cols


def cell_px(n: int) -> int:
    """Side of one photo of the sheet (the sheet stays near 2000 px across)."""
    _rows, cols = grid_shape(n)
    return int(np.clip(2160 // cols, 320, FRAME_PX))


def sheet(frames, gap: int = 8) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """The frames in reading order on one picture, and each one's ``(x, y, w, h)`` there."""
    n = len(frames)
    rows, cols = grid_shape(n)
    c = cell_px(n)
    out = np.zeros((rows * c + (rows - 1) * gap, cols * c + (cols - 1) * gap, 3), np.uint8)
    cells = []
    for i, f in enumerate(frames):
        x, y = (i % cols) * (c + gap), (i // cols) * (c + gap)
        out[y:y + c, x:x + c] = f if f.shape[:2] == (c, c) else cv2.resize(f, (c, c), interpolation=cv2.INTER_AREA)
        cells.append((x, y, c, c))
    return out, cells


def cell_at(cells, x: float, y: float) -> int | None:
    for i, (cx, cy, w, h) in enumerate(cells):
        if cx <= x < cx + w and cy <= y < cy + h:
            return i
    return None


# -- on top of each other ----------------------------------------------------------------------------
def crossfade(frames, pos: float) -> np.ndarray:
    """The picture at ``pos`` of the time slider: 0 is the first frame, 1 the second …; in between,
    the two neighbours mixed."""
    n = len(frames)
    pos = float(np.clip(pos, 0, n - 1))
    i = min(int(math.floor(pos)), n - 1)
    t = pos - i
    if t < 1e-3 or i + 1 >= n:
        return frames[i]
    if t > 1 - 1e-3:
        return frames[i + 1]
    return G.blend(frames[i], frames[i + 1], t)


def time_marks(days) -> list[float]:
    """Where each photo sits on a time line from 0 (the first) to 1 (the last), by its date; evenly
    spaced when dates are missing or all the same."""
    n = len(days)
    if n < 2:
        return [0.0] * n
    ds = [_date(d) for d in days]
    if any(d is None for d in ds) or ds[-1] <= ds[0] or any(b < a for a, b in zip(ds, ds[1:])):
        return [i / (n - 1) for i in range(n)]
    span = (ds[-1] - ds[0]).days
    return [(d - ds[0]).days / span for d in ds]
