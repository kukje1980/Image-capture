"""이 환자의 시야 시뮬레이션: where the places marked on the photo (병변 핀, pins.py) lie in what the
patient sees — a street scene with a blurred, dim patch for every pin.

The retina and the visual field are mirror images of each other, up ↔ down and left ↔ right: a lesion of
the upper retina takes the lower field, one of the nasal retina the temporal field. A fundus photo is
seen from the front, which turns left ↔ right once more — so, in the photo's own coordinates:

* **up ↔ down is turned**: a pin above the fovea is a patch *below* where the patient looks;
* **left ↔ right stays**: a pin on the right of the photo is a patch on the patient's right (the optic disc
  of a right eye is on the right of its photo, and its blind spot is on the right of that eye's field).

The distance from where the patient looks is the angle between the pin and the fovea (the photo's
geometry, ``placement.Camera``; without it a plain share of the photo's field of view).

A picture for explaining, not a measurement: the size and the depth of a patch are set by hand, and it
does not stand in for a visual field test. No Qt in here (``ui/patient_views.py`` shows it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from . import placement

NARROW_DEG = 30.0           # the scene's half width: the middle 60° …
WIDE_DEG = 60.0             # … or 120° where a pin lies further out
EDGE = 0.9                  # a pin beyond this share of the narrow scene: the wide one
SIZE_DEG = (2.0, 20.0, 6.0)  # radius of a patch: least, most, at first
GUESS_FOV_DEG = 45.0        # a photo without its geometry: the picture's width is taken for this
NOTE = "설명용 그림입니다. 실제 시야검사를 대신하지 않습니다."
NO_PINS = "이 사진에는 병변 핀이 없습니다 — 아래 툴바의 병변 핀을 켜고 병변 자리를 클릭한 뒤 다시 여세요."


@dataclass
class Spot:
    """A pin in the patient's view: degrees from where the eye looks (x right, y down), its number."""
    x: float
    y: float
    number: int = 0
    note: str = ""

    @property
    def away(self) -> float:
        return math.hypot(self.x, self.y)


def centre_of(cam: placement.Camera | None, *, fovea=None, disc=None, laterality: str | None = None,
              size: tuple[int, int] | None = None) -> tuple[tuple[float, float] | None, str]:
    """Where the patient looks, on the photo: ``((x, y), how)`` — the fovea found (``"fovea"``), the place
    it should be going by the disc (``"expected"``), else the middle of the picture (``"image"``)."""
    if fovea is not None:
        return (float(fovea[0]), float(fovea[1])), "fovea"
    if cam is not None and disc is not None:
        p = placement.expected_fovea(cam, disc, laterality)
        if p is not None:
            return (float(p[0]), float(p[1])), "expected"
    if cam is not None:
        return (cam.cx, cam.cy), "image"
    if size is not None:
        return (size[0] / 2.0, size[1] / 2.0), "image"
    return None, "image"


def spots(pins, cam: placement.Camera | None, centre, *, width: float | None = None) -> list[Spot]:
    """The pins (anything with ``x`` · ``y`` · ``note``) as places of the visual field. ``centre``: where
    the patient looks on the photo (``centre_of``); ``width``: the photo's width in pixels, for a photo
    without geometry. Pins outside the photo's field are left out (their numbers stay)."""
    out = []
    if centre is None:
        return out
    c = cam.direction(*centre) if cam is not None else None
    for n, pin in enumerate(pins, 1):
        dx, dy = float(pin.x) - centre[0], float(pin.y) - centre[1]
        d = math.hypot(dx, dy)
        if cam is not None and c is not None:
            q = cam.direction(pin.x, pin.y)
            if q is None:
                continue
            deg = placement.angle_between(q, c)
        else:
            deg = d / max(1.0, float(width or 1.0)) * GUESS_FOV_DEG
        if d < 1e-6:
            out.append(Spot(0.0, 0.0, n, getattr(pin, "note", "") or ""))
        else:
            out.append(Spot(dx / d * deg, -dy / d * deg, n, getattr(pin, "note", "") or ""))    # up ↔ down
    return out


def half_width(found: list[Spot]) -> float:
    """The scene's half width in degrees that shows all the patches (60° across, or 120°)."""
    far = max((max(abs(s.x), abs(s.y) * 1.5) for s in found), default=0.0)
    return NARROW_DEG if far <= NARROW_DEG * EDGE else WIDE_DEG


def _side(s: Spot) -> str:
    if s.away < 2.5:
        return "보는 곳 한가운데"
    lr = "오른쪽" if s.x > 0 else "왼쪽"
    ud = "아래" if s.y > 0 else "위"
    if abs(s.x) > 2.4 * abs(s.y):
        where = f"{lr}으로"
    elif abs(s.y) > 2.4 * abs(s.x):
        where = f"{ud}로"
    else:
        where = f"{lr} {ud}로"
    return f"보는 곳에서 {where} {s.away:.0f}°"


def describe(found: list[Spot]) -> list[str]:
    """One line a patch: "1  보는 곳에서 오른쪽 아래로 12° — 메모"."""
    return [f"{s.number}  {_side(s)}" + (f" — {s.note}" if s.note else "") for s in found]


def simulate(scene: np.ndarray, found: list[Spot], *, size_deg: float = SIZE_DEG[2], depth: float = 0.85,
             half_deg: float | None = None, numbers: bool = True) -> np.ndarray:
    """``scene`` (RGB) as the patient might see it: a blurred, dim patch of ``size_deg`` radius for every
    spot, a small cross where the eye looks. ``half_deg``: half the scene's width in degrees (None: as
    ``half_width`` gives)."""
    h, w = scene.shape[:2]
    half = float(half_deg or half_width(found))
    px = (w / 2.0) / half                                    # pixels a degree
    size_deg = float(min(SIZE_DEG[1], max(SIZE_DEG[0], size_deg)))
    depth = float(min(1.0, max(0.0, depth)))
    keep = np.ones((h, w), np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for s in found:
        cx, cy = w / 2.0 + s.x * px, h / 2.0 + s.y * px
        ang = np.arctan2(yy - cy, xx - cx)
        wob = 1.0 + 0.10 * np.sin(ang * 3 + s.number * 1.7) + 0.05 * np.sin(ang * 5 + s.number)
        rr = np.hypot(xx - cx, yy - cy) / np.maximum(1.0, size_deg * px * wob)
        keep = np.minimum(keep, 1.0 - depth * np.clip(1.35 - rr, 0.0, 1.0) ** 0.7)
    blur = cv2.GaussianBlur(scene, (0, 0), max(2.0, w / 50.0)).astype(np.float32)
    dark = blur * 0.22 + 22.0
    k = keep[..., None]
    out = np.clip(scene.astype(np.float32) * k + dark * (1.0 - k), 0, 255).astype(np.uint8)
    c = (int(w / 2), int(h / 2))
    arm = max(4, w // 90)
    for color, thick in (((20, 20, 20), 3), ((255, 255, 255), 1)):           # where the eye looks
        cv2.line(out, (c[0] - arm, c[1]), (c[0] + arm, c[1]), color, thick, cv2.LINE_AA)
        cv2.line(out, (c[0], c[1] - arm), (c[0], c[1] + arm), color, thick, cv2.LINE_AA)
    if numbers:
        for s in found:
            p = (int(w / 2.0 + s.x * px), int(h / 2.0 + s.y * px))
            if 0 <= p[0] < w and 0 <= p[1] < h:
                cv2.putText(out, str(s.number), (p[0] - 6, p[1] + 6), cv2.FONT_HERSHEY_SIMPLEX, max(0.5, w / 1100.0),
                            (255, 214, 10), max(1, w // 500), cv2.LINE_AA)
    return out
