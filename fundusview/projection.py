"""Geometry that maps a fundus photograph onto the retina of a model eye.

Model eye: a sphere of radius 1 (≈ 12 mm), centre at the origin, the
posterior pole (fovea) at ``(0, 0, -1)`` and the pupil toward ``+z``.  A
retinal point is described by

* ``theta`` — angle at the **eye centre** between the point and the
  posterior pole (the "internal" or eye-steered angle used by wide-field
  devices, e.g. 200° internal ≈ 100° from the pole), and
* ``phi``   — azimuth around the optical axis (0 = image right, CCW).

A fundus image has its centre on the optical axis; the image radius ``rho``
(0 at the centre, 1 at the edge of the field of view) is a function of
``theta`` given by the projection:

``perspective``  The camera looks through the pupil: a retinal point is
                 seen at external angle ``alpha`` from a viewpoint on the
                 axis at ``z = d`` (≈ the eye's nodal point/pupil), and a
                 rectilinear camera maps it to ``tan(alpha)``. Here
                 ``tan(alpha) = sin(theta) / (cos(theta) + d)``.  With
                 ``d = 0.58`` this reproduces the 200° internal ↔ 135°
                 external convention of ultra-wide-field devices and is the
                 right default for conventional (45–50°) cameras too.
``stereographic`` ``tan(theta/2)`` — the special case ``d = 1``.
``equidistant``  ``theta`` — for images already re-projected so that
                 distance from the centre is proportional to retinal angle.
``orthographic`` ``sin(theta)`` — a parallel view of the eye cup.

Field of view is quoted either *external* (the angle at the pupil, as in
"45° fundus camera" or "135°") or *internal* (eye-centre, as in "200°"); for
the 3D model it is converted to ``theta_max`` = half the internal angle.
"""
from __future__ import annotations

import math

PROJECTIONS = ("perspective", "stereographic", "equidistant", "orthographic")
PROJECTION_LABELS = {
    "perspective": "카메라 원근 (동공 시점)",
    "stereographic": "스테레오그래픽",
    "equidistant": "등거리 (각도 비례)",
    "orthographic": "정사영",
}
PROJECTION_INDEX = {name: i for i, name in enumerate(PROJECTIONS)}

# Viewpoint (pupil / nodal point) on the axis, in eye radii from the centre.
DEFAULT_VIEWPOINT = 0.58


def internal_from_external(fov_external_deg: float, d: float = DEFAULT_VIEWPOINT) -> float:
    """Internal (eye-centre) FOV for a field seen at ``fov_external_deg`` from ``z=d``.

    ``theta = alpha + asin(d * sin(alpha))`` for half-angles (law of sines in
    the triangle centre–viewpoint–retinal point).
    """
    a = math.radians(min(max(fov_external_deg, 0.1), 179.0) / 2.0)
    theta = a + math.asin(max(-1.0, min(1.0, d * math.sin(a))))
    return math.degrees(2.0 * theta)


def external_from_internal(fov_internal_deg: float, d: float = DEFAULT_VIEWPOINT) -> float:
    t = math.radians(fov_internal_deg / 2.0)
    return math.degrees(2.0 * math.atan2(math.sin(t), math.cos(t) + d))


def theta_max(fov_deg: float, fov_type: str = "external", d: float = DEFAULT_VIEWPOINT) -> float:
    """Half internal FOV in radians (angle from the posterior pole to the field edge)."""
    internal = fov_deg if fov_type == "internal" else internal_from_external(fov_deg, d)
    return math.radians(min(max(internal, 1.0), 300.0) / 2.0)


def g(theta: float, projection: str, d: float = DEFAULT_VIEWPOINT) -> float:
    """Un-normalised image radius for retinal angle ``theta`` (radians)."""
    if projection == "stereographic":
        return math.tan(theta / 2.0)
    if projection == "equidistant":
        return theta
    if projection == "orthographic":
        return math.sin(theta)
    denom = math.cos(theta) + d
    return math.inf if denom <= 1e-6 else math.sin(theta) / denom


def rho(theta: float, tmax: float, projection: str, d: float = DEFAULT_VIEWPOINT) -> float:
    """Normalised image radius (1 = field edge) of a retinal point at ``theta``."""
    gm = g(tmax, projection, d)
    return g(theta, projection, d) / gm if gm > 0 else 0.0


def theta_of_rho(r: float, tmax: float, projection: str, d: float = DEFAULT_VIEWPOINT) -> float:
    """Inverse of :func:`rho` (bisection; ``g`` is monotonic on the used range)."""
    lo, hi = 0.0, tmax
    target = r * g(tmax, projection, d)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if g(mid, projection, d) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def sphere_point(theta: float, phi: float) -> tuple[float, float, float]:
    """Unit-sphere point for retinal angle ``theta`` and azimuth ``phi``."""
    s = math.sin(theta)
    return (s * math.cos(phi), s * math.sin(phi), -math.cos(theta))


def image_to_sphere(u: float, v: float, cx: float, cy: float, radius: float, tmax: float,
                    projection: str, d: float = DEFAULT_VIEWPOINT, rotation: float = 0.0):
    """Pixel ``(u, v)`` (v down) -> unit-sphere point, or ``None`` outside the FOV."""
    dx, dy = (u - cx) / radius, (cy - v) / radius
    r = math.hypot(dx, dy)
    if r > 1.0:
        return None
    phi = math.atan2(dy, dx) - rotation
    return sphere_point(theta_of_rho(r, tmax, projection, d), phi)


def sphere_to_image(p, cx: float, cy: float, radius: float, tmax: float,
                    projection: str, d: float = DEFAULT_VIEWPOINT, rotation: float = 0.0):
    """Unit-sphere point -> pixel ``(u, v)`` or ``None`` outside the FOV (mirrors the shader)."""
    x, y, z = p
    theta = math.acos(max(-1.0, min(1.0, -z)))
    if theta > tmax:
        return None
    r = rho(theta, tmax, projection, d)
    phi = math.atan2(y, x) + rotation
    return (cx + r * radius * math.cos(phi), cy - r * radius * math.sin(phi))
