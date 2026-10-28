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
