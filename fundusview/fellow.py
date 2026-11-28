"""OD · OS 비교: the two eyes' optic discs next to and over each other.

The two discs of one person are, as a rule, mirror images of each other — the same size, the same cup. A
cup clearly larger on one side is a clue of its own (glaucoma seldom takes both eyes at the same pace):
a difference of the vertical C/D of 0.2 or more is the figure usually given. So:

* **side by side** — OD on the left, OS on the right, as the examiner faces the patient, each as taken;
* **over each other** — the fellow eye turned left ↔ right, so nasal lies on nasal and the shapes can be
  compared by flicking or fading between them (the picture says that it is mirrored).

Both pictures are cut to the same number of disc diameters, so the discs have the same size on screen.
No Qt in here (``ui/fellow_tab.py`` is the tab of 녹내장 분석).
"""
from __future__ import annotations

import numpy as np

ASYMMETRY = 0.2             # vertical C/D of the two eyes further apart than this: said
GAP = 14                    # px between the two pictures side by side


def mirrored(rgb: np.ndarray) -> np.ndarray:
    """Left ↔ right (a contiguous copy)."""
    return np.ascontiguousarray(rgb[:, ::-1])


def other_eye(eye: str | None) -> str | None:
    return {"OD": "OS", "OS": "OD"}.get(eye or "")


def side_by_side(od: np.ndarray, os_: np.ndarray, gap: int = GAP) -> np.ndarray:
    """OD left, OS right (two pictures of one size), a dark strip between them."""
    h = max(od.shape[0], os_.shape[0])
    out = np.zeros((h, od.shape[1] + gap + os_.shape[1], 3), np.uint8)
    out[:od.shape[0], :od.shape[1]] = od
    out[:os_.shape[0], od.shape[1] + gap:] = os_
    return out


def blend(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """``a`` fading into ``b`` (0 … 1); two pictures of one size."""
    t = float(min(1.0, max(0.0, t)))
    if t <= 0.0:
        return a.copy()
    if t >= 1.0:
        return b.copy()
    return np.clip(a.astype(np.float32) * (1.0 - t) + b.astype(np.float32) * t + 0.5, 0, 255).astype(np.uint8)


def compare(cd_a: float | None, cd_b: float | None) -> tuple[float | None, bool]:
    """``(difference, said)`` of two vertical C/D: the difference (None where one is missing) and whether
    it reaches ``ASYMMETRY``."""
    if cd_a is None or cd_b is None:
        return None, False
    d = abs(float(cd_a) - float(cd_b))
    return d, d >= ASYMMETRY - 1e-9


def pick(rows, eye: str | None, day: str = "", *, eye_of, usable) -> object | None:
    """The fellow eye's photo to compare with: among ``rows`` (a patient's photos) one of the other eye
    that is ``usable`` — of the same day if there is one, else the nearest day; of those the newest."""
    want = other_eye(eye)
    if want is None:
        return None
    found = [r for r in rows if usable(r) and eye_of(r) == want]
    if not found:
        return None

    def far(r) -> tuple:
        d = (r["exam_date"] or "")
        same = 0 if (day and d == day) else 1
        try:
            from datetime import date
            gap = abs((date.fromisoformat(d) - date.fromisoformat(day)).days) if d and day else 10 ** 6
        except ValueError:
            gap = 10 ** 6
        return same, gap, -(r["id"] or 0)
    return min(found, key=far)
