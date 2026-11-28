"""이 환자의 시야 (설명용): where the places marked on a photo (병변 핀) lie in what the eye sees.

The retina sees the world upside down: a place **above** the fovea looks at what is **below** the point
looked at. Left and right in a fundus photo stay as they are in that eye's field (the disc, on the nasal
side of the photo, is the blind spot on the temporal side of the field — for OD both are on the right).
So a pin at clock hour *h* of the photo lies at the hour mirrored top ↔ bottom in the field, as far out
as its angle from the fovea — taken as a visual angle with the same eye model as the 3D view
(``projection.external_from_internal``).

What is drawn is a soft dim patch at each such place over a street scene, the point looked at in the
middle. It is a picture for explaining where a lesion would be noticed **if** it takes sight there — a
pin says where, not whether or how much — and stands in for no visual field test. The sheet says so.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import projection as proj

SPAN_DEG = 60.0             # the scene's width as a visual angle (the point looked at in its middle)
PATCH_DEG = 6.0             # radius of the patch drawn for a pin (a pin has no size of its own)
MAX_ECC_DEG = 85.0


@dataclass
class Spot:
    x_deg: float            # in the eye's field: right of the point looked at (+)
    y_deg: float            # above it (+)
    label: str = ""

    @property
    def ecc_deg(self) -> float:
        return math.hypot(self.x_deg, self.y_deg)


def visual_angle(centre_deg: float) -> float:
    """The visual angle (from the line of sight) of a retinal place ``centre_deg`` from the fovea as seen
    from the eye's centre."""
    centre_deg = max(0.0, min(float(centre_deg), 179.0))
    return min(MAX_ECC_DEG, proj.external_from_internal(2.0 * centre_deg) / 2.0)


def spot_of(where, label: str = "") -> Spot | None:
    """The place in the field of a pin's ``pins.Where`` — None where it cannot be said (outside the photo,
    or no distance from the fovea known)."""
    if where is None or not where.inside or where.fovea_deg is None:
        return None
    if where.bearing is None:                       # the fovea itself: the point looked at
        return Spot(0.0, 0.0, label)
    ecc = visual_angle(where.fovea_deg)
    a = math.radians(where.bearing)                 # on the photo: clockwise from up
    # photo right stays right; photo up (superior retina) is the lower field
    return Spot(ecc * math.sin(a), -ecc * math.cos(a), label)


def to_pixel(spot: Spot, shape, span_deg: float = SPAN_DEG) -> tuple[float, float]:
    """Where the spot is in a scene of ``shape`` (h, w …) spanning ``span_deg`` across."""
    h, w = shape[:2]
    k = w / span_deg
    return w / 2.0 + spot.x_deg * k, h / 2.0 - spot.y_deg * k


def span_for(spots, shape, least: float = SPAN_DEG, most: float = 170.0) -> float:
    """The scene's width as a visual angle so that every spot (and its patch) is in the picture: ``least``
    for places near the middle, wider for places far out (the scene then stands for more of the field)."""
    h, w = shape[:2]
    need = least
    for s in spots or ():
        need = max(need, 2.0 * (abs(s.x_deg) + PATCH_DEG) * 1.08, 2.0 * (abs(s.y_deg) + PATCH_DEG) * 1.08 * w / h)
    return min(most, need)


def simulate(scene: np.ndarray, spots, *, span_deg: float = SPAN_DEG, patch_deg: float = PATCH_DEG,
             depth: float = 0.86) -> np.ndarray:
    """The scene with a soft dim, greyed patch at each spot (those outside the picture leave it as it
    is). ``depth`` 0 … 1: how dark the middle of a patch gets."""
    h, w = scene.shape[:2]
    out = scene.astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    k = w / span_deg
    keep = np.ones((h, w), np.float32)
    for s in spots or ():
        x, y = to_pixel(s, scene.shape, span_deg)
        r = max(4.0, patch_deg * k)
        d2 = ((xx - x) ** 2 + (yy - y) ** 2) / (r * r)
        keep *= 1.0 - depth * np.exp(-d2 * 1.1)
    grey = out.mean(axis=2, keepdims=True) * 0.35 + 28.0
    out = out * keep[..., None] + grey * (1.0 - keep[..., None]) * 0.55
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
