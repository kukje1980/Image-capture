"""Measurements on a fundus photo (VK-2 style length / angle / cup-disc tools).

Pixel lengths are converted to retinal units with the image's own geometry
(circle, field of view, projection — ``projection.py``): both end points are
mapped onto the model eye and the great-circle angle between them gives
degrees (at the eye centre) and millimetres (× eye radius, 12 mm for a
24 mm eye). This stays correct across wide-field images, where a pixel at
the periphery spans a different retinal distance than one at the centre.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import projection as proj

EYE_RADIUS_MM = 12.0


@dataclass
class Geometry:
    cx: float
    cy: float
    r: float
    fov_deg: float
    fov_type: str
    projection: str
    viewpoint: float = proj.DEFAULT_VIEWPOINT
    radial_c: float = proj.DEFAULT_RADIAL_C

    @property
    def tmax(self) -> float:
        return proj.theta_max(self.fov_deg, self.fov_type, self.viewpoint)

    def to_sphere(self, x: float, y: float):
        return proj.image_to_sphere(x, y, self.cx, self.cy, self.r, self.tmax, self.projection,
                                    self.viewpoint, c=self.radial_c)


def length_px(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def retinal_distance(a, b, geo: Geometry | None, eye_radius_mm: float = EYE_RADIUS_MM):
    """``(degrees, mm)`` between two image points, or ``None`` outside the field."""
    if geo is None or not geo.r:
        return None
    pa, pb = geo.to_sphere(*a), geo.to_sphere(*b)
    if pa is None or pb is None:
        return None
    dot = max(-1.0, min(1.0, sum(u * v for u, v in zip(pa, pb))))
    ang = math.acos(dot)
    return math.degrees(ang), ang * eye_radius_mm


def angle_deg(a, vertex, c) -> float:
    """Angle a–vertex–c in the image plane (0…180°)."""
    v1 = (a[0] - vertex[0], a[1] - vertex[1])
    v2 = (c[0] - vertex[0], c[1] - vertex[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    if n == 0:
        return 0.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / n))
    return math.degrees(math.acos(cos))


def polygon_area(points) -> float:
    """Shoelace area (px²)."""
    if len(points) < 3:
        return 0.0
    s = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def describe_length(a, b, geo: Geometry | None) -> str:
    txt = f"{length_px(a, b):.0f} px"
    rd = retinal_distance(a, b, geo)
    if rd is not None:
        txt += f" · {rd[0]:.1f}° · {rd[1]:.2f} mm"
    return txt


REGIONS = ("posterior", "superior", "inferior", "nasal", "temporal")


def fundus_region(name: str, circle, disc=None, laterality: str | None = None,
                  size: tuple[int, int] | None = None) -> tuple[float, float, float, float] | None:
    """Rectangle ``(x, y, w, h)`` in image pixels to zoom onto a part of the fundus.

    * ``posterior`` — the fovea (centre of a fovea-centred photo) and the disc
    * ``superior`` / ``inferior`` / ``nasal`` / ``temporal`` — the mid-to-far
      periphery (0.35–0.9 of the image-circle radius) on that side; nasal is
      the disc side (OD right, OS left), from the disc when it was found.

    ``circle`` = (cx, cy, r). Wide-field image circles are often cut by the
    frame, so with ``size`` = (width, height) the rectangle stays on the photo.
    None when the side cannot be told (nasal/temporal without disc or eye).
    """
    cx, cy, r = circle
    side = None
    if disc is not None and abs(disc[0] - cx) > 0.05 * r:
        side = 1.0 if disc[0] > cx else -1.0
    elif laterality in ("OD", "OS"):
        side = 1.0 if laterality == "OD" else -1.0
    if name == "posterior":
        if disc is not None:
            mx, my = (cx + disc[0]) / 2, (cy + disc[1]) / 2
            half = max(0.62 * math.hypot(disc[0] - cx, disc[1] - cy), 0.12 * r)
            x, y, w, h = mx - 1.35 * half, my - half, 2.7 * half, 2 * half
        else:
            x, y, w, h = cx - 0.27 * r, cy - 0.2 * r, 0.54 * r, 0.4 * r
    elif name in ("superior", "inferior"):
        yc = cy - 0.62 * r if name == "superior" else cy + 0.62 * r
        x, y, w, h = cx - 0.4 * r, yc - 0.25 * r, 0.8 * r, 0.5 * r
    elif name in ("nasal", "temporal") and side is not None:
        xc = cx + (side if name == "nasal" else -side) * 0.62 * r
        x, y, w, h = xc - 0.28 * r, cy - 0.28 * r, 0.56 * r, 0.56 * r
    else:
        return None
    if size is not None:
        x0, y0 = max(x, 0.0), max(y, 0.0)
        x1, y1 = min(x + w, float(size[0])), min(y + h, float(size[1]))
        x, y, w, h = x0, y0, x1 - x0, y1 - y0
    return (x, y, w, h) if w > 8 and h > 8 else None
