"""병변 핀: a place on the retina marked on a photo and said the way it is said at the slit lamp —
"11시 방향, 유두에서 9 mm".

A pin is a pixel of the photo (it stays with the photo: ``images.meta_json["pins"]``) and an optional
note. What is said about it comes from the photo's geometry (its image circle, field of view and
projection — the same eye model the 3D view and the length tool use, ``placement.Camera``):

* **clock hour** — as the examiner sees the fundus (the photo as taken): 12 is up, 3 is at the right of
  the photo, for either eye. Counted round the fovea (the middle of the fundus); without a fovea, round
  the place it should be going by the disc; without either, round the middle of the picture.
* **from the disc / from the fovea** — along the retina, in mm (a 12 mm eye) and degrees at the eye's
  centre.

The 3D mapping is a first-order optical model (not a calibrated measurement): the figures are for
explaining and noting, and are labelled 참고용 where shown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import placement

EYE_RADIUS_MM = placement.EYE_RADIUS_MM
CENTRAL_DEG = 2.5           # nearer the fovea than this: "황반 중심" (a clock hour says nothing there)
MAX_PINS = 30               # on one photo
NOTE_MAX = 60


@dataclass
class Pin:
    x: float
    y: float
    note: str = ""

    def as_dict(self) -> dict:
        d = {"x": round(float(self.x), 1), "y": round(float(self.y), 1)}
        if self.note:
            d["note"] = self.note[:NOTE_MAX]
        return d


def from_meta(meta: dict | None) -> list[Pin]:
    """The pins kept with a photo (anything that is not a pin is left out)."""
    out = []
    for d in (meta or {}).get("pins") or []:
        try:
            x, y = float(d["x"]), float(d["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            out.append(Pin(x, y, str(d.get("note") or "")[:NOTE_MAX]))
    return out[:MAX_PINS]


def to_meta(meta: dict, pins: list[Pin]) -> dict:
    """``meta`` with these pins (none: no ``pins`` entry)."""
    meta = dict(meta or {})
    if pins:
        meta["pins"] = [p.as_dict() for p in pins[:MAX_PINS]]
    else:
        meta.pop("pins", None)
    return meta


@dataclass
class Where:
    hour: int | None = None           # 1 … 12, None at the centre
    about: str = ""                   # what the hour is counted round: "fovea" · "expected" · "image"
    disc_mm: float | None = None      # from the disc centre, along the retina
    disc_deg: float | None = None
    fovea_mm: float | None = None
    fovea_deg: float | None = None
    inside: bool = True               # in the photo's field

    @property
    def short(self) -> str:
        """As on the photo: "11시 · 유두에서 9.2 mm"."""
        if not self.inside:
            return "사진 밖"
        bits = ["황반 중심" if self.hour is None else f"{self.hour}시"]
        if self.disc_mm is not None:
            bits.append(f"유두에서 {self.disc_mm:.1f} mm")
        elif self.fovea_mm is not None and self.hour is not None:
            bits.append(f"중심와에서 {self.fovea_mm:.1f} mm")
        return " · ".join(bits)

    @property
    def long(self) -> str:
        """As in the status line: all of it, and that it is an estimate."""
        if not self.inside:
            return "사진의 시야 밖입니다"
        bits = ["황반 중심" if self.hour is None else f"{self.hour}시 방향"]
        if self.disc_mm is not None:
            bits.append(f"유두에서 {self.disc_mm:.1f} mm ({self.disc_deg:.0f}°)")
        if self.fovea_mm is not None:
            bits.append(f"중심와에서 {self.fovea_mm:.1f} mm ({self.fovea_deg:.0f}°)")
        if self.about == "image":
            bits.append("황반 · 유두 위치를 몰라 사진 가운데 기준")
        return " · ".join(bits) + " — 참고용 (12 mm 안구 모형)"


def _hour(dx: float, dy: float) -> int:
    """Clock hour of the direction ``(dx, dy)`` in picture coordinates (y down): 12 up, 3 right."""
    a = math.degrees(math.atan2(dx, -dy)) % 360.0          # 0 up, clockwise
    h = int(round(a / 30.0)) % 12
    return 12 if h == 0 else h


def where(x: float, y: float, cam: placement.Camera | None, *, fovea=None, disc=None,
          laterality: str | None = None) -> Where:
    """What is said about the pixel ``(x, y)`` of a photo. ``cam`` None (no image circle): the clock hour
    round the fovea / disc-less middle is all there is — no distances."""
    out = Where()
    centre, out.about = (fovea, "fovea") if fovea is not None else (None, "image")
    if centre is None and cam is not None and disc is not None:
        centre = placement.expected_fovea(cam, disc, laterality)
        out.about = "expected" if centre is not None else "image"
    if centre is None:
        centre = (cam.cx, cam.cy) if cam is not None else None
    q = cam.direction(x, y) if cam is not None else None
    if cam is not None and q is None:
        out.inside = False
        return out
    if q is not None:
        for name, mark in (("disc", disc), ("fovea", fovea if fovea is not None else
                                            (centre if out.about == "expected" else None))):
            m = cam.direction(*mark) if mark is not None else None
            if m is not None:
                deg = placement.angle_between(q, m)
                setattr(out, f"{name}_deg", deg)
                setattr(out, f"{name}_mm", math.radians(deg) * EYE_RADIUS_MM)
    if centre is not None:
        dx, dy = x - centre[0], y - centre[1]
        central = (out.fovea_deg is not None and out.fovea_deg < CENTRAL_DEG) or math.hypot(dx, dy) < 1e-6
        out.hour = None if central and out.about != "image" else _hour(dx, dy)
        if math.hypot(dx, dy) < 1e-6:
            out.hour = None
    return out


def nearest(pins: list[Pin], x: float, y: float, radius: float) -> int | None:
    """The pin within ``radius`` pixels of ``(x, y)`` (the nearest), or None."""
    best, at = None, radius
    for i, p in enumerate(pins):
        d = math.hypot(p.x - x, p.y - y)
        if d <= at:
            best, at = i, d
    return best
