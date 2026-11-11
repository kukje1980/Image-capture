"""Where a fundus photo lies on the model eye.

The eye is the reference, not the photo. In the model (``projection.py``) the fovea is at the
posterior pole ``(0, 0, -1)`` and the optic disc ``DISC_FOVEA_DEG`` nasal of it, a little
superior (the fovea lies below the level of the disc centre). A photo is not always centred on
the fovea — disc-centred shots, wide-field devices that centre between disc and macula, the
peripheral fields of a series — so its field centre is put where its landmarks say:

* the fovea found in the photo (or marked by hand) goes to the posterior pole;
* without a fovea, the disc goes to its anatomical place;
* without either, the photo is centred on the pole (a fovea-centred shot is assumed).

How large the photo is on the retina is given by its field of view alone; the distance between
its fovea and its disc, measured through that field of view, shows whether the size is real
(≈ 4.5 mm, :data:`DISC_FOVEA_DEG` at the eye centre) and can be used to set it (:func:`fit_fov`).

The camera looks through the pupil while the eye turns to the fixation light — a turn without
torsion (Listing's law). So the photo's frame differs from the eye's by a rotation about an
axis in the equatorial (xy) plane: :func:`tilt`, the shortest turn that takes the pole to the
field centre ``c``. Image up stays superior (plus the roll set by the user).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import projection as proj

POLE = np.array([0.0, 0.0, -1.0])
DISC_FOVEA_DEG = 21.5        # disc centre ↔ fovea at the eye centre: ≈ 4.5 mm on a 12 mm radius
DISC_TILT_DEG = 6.0          # the line fovea → disc rises by this much toward the nose
EYE_RADIUS_MM = 12.0


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _axis_angle(axis, angle: float) -> np.ndarray:
    k = _unit(axis)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * kx + (1 - math.cos(angle)) * (kx @ kx)


def angle_between(a, b) -> float:
    """Angle (degrees) between two directions."""
    a, b = _unit(a), _unit(b)
    return math.degrees(math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b)))


def tilt(c) -> np.ndarray:
    """Photo frame → eye frame for a field centred on ``c``: the shortest turn taking the pole to
    ``c`` (its axis lies in the xy-plane: no torsion)."""
    c = _unit(c)
    axis = np.cross(POLE, c)
    s = float(np.linalg.norm(axis))
    if s < 1e-12:
        return np.eye(3) if c[2] < 0 else _axis_angle([0.0, 1.0, 0.0], math.pi)
    return _axis_angle(axis / s, math.atan2(s, float(POLE @ c)))


def centre_for(q, target=POLE) -> np.ndarray:
    """The field centre ``c`` for which ``tilt(c) @ q == target``: where the photo must be centred
    so that the point it shows in direction ``q`` (photo frame) lies at ``target`` on the eye."""
    q, t = _unit(q), _unit(target)
    dx, dy = float(t[0] - q[0]), float(t[1] - q[1])
    n2 = math.hypot(dx, dy)
    if n2 < 1e-12:                                   # the same point (or its mirror in z: not a photo)
        return POLE.copy()
    n = np.array([-dy / n2, dx / n2, 0.0])           # an axis in the xy-plane, equally far from both
    qp, tp = q - float(n @ q) * n, t - float(n @ t) * n
    ang = math.atan2(float(n @ np.cross(qp, tp)), float(qp @ tp))
    return _axis_angle(n, ang) @ POLE


def anatomical_disc(laterality: str | None) -> np.ndarray:
    """Centre of the optic disc on the eye: nasal of the fovea (OD: +x, the photo's right) and a
    little superior."""
    phi = math.radians(DISC_TILT_DEG)
    if laterality == "OS":
        phi = math.pi - phi
    return np.array(proj.sphere_point(math.radians(DISC_FOVEA_DEG), phi))


@dataclass
class Camera:
    """How a photo maps to directions: its image circle, field of view and projection."""
    cx: float
    cy: float
    r: float
    fov_deg: float
    fov_type: str = "internal"
    projection: str = "equidistant"
    viewpoint: float = proj.DEFAULT_VIEWPOINT
    radial_c: float = proj.DEFAULT_RADIAL_C
    roll_deg: float = 0.0

    @property
    def tmax(self) -> float:
        return proj.theta_max(self.fov_deg, self.fov_type, self.viewpoint)

    def direction(self, x: float, y: float) -> np.ndarray | None:
        """Pixel → unit direction in the photo's frame (None outside the field)."""
        p = proj.image_to_sphere(x, y, self.cx, self.cy, self.r, self.tmax, self.projection, self.viewpoint,
                                 math.radians(self.roll_deg), c=self.radial_c)
        return None if p is None else np.array(p)

    def pixel(self, q) -> tuple[float, float] | None:
        """Direction in the photo's frame → pixel (None outside the field)."""
        return proj.sphere_to_image(tuple(float(v) for v in q), self.cx, self.cy, self.r, self.tmax,
                                    self.projection, self.viewpoint, math.radians(self.roll_deg), c=self.radial_c)

    def directions(self, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        """Many pixels at once: directions (…×3) and whether each lies inside the field."""
        xs, ys = np.asarray(xs, np.float64), np.asarray(ys, np.float64)
        dx, dy = (xs - self.cx) / self.r, (self.cy - ys) / self.r
        rho = np.hypot(dx, dy)
        tmax = self.tmax
        lut = np.array([proj.theta_of_rho(k / 256.0, tmax, self.projection, self.viewpoint, c=self.radial_c)
                        for k in range(257)])
        theta = np.interp(np.clip(rho, 0.0, 1.0), np.linspace(0.0, 1.0, 257), lut)
        phi = np.arctan2(dy, dx) - math.radians(self.roll_deg)
        st = np.sin(theta)
        return np.stack([st * np.cos(phi), st * np.sin(phi), -np.cos(theta)], axis=-1), rho <= 1.0

    def with_fov(self, fov_deg: float) -> "Camera":
        return Camera(self.cx, self.cy, self.r, fov_deg, self.fov_type, self.projection, self.viewpoint,
                      self.radial_c, self.roll_deg)


@dataclass
class Placement:
    """A photo on the eye. ``matrix`` turns directions of the photo's frame into the eye's."""
    by: str = "centre"                 # "fovea" · "disc" · "centre" (nothing to go by) · "off" (not asked)
    centre: np.ndarray = field(default_factory=lambda: POLE.copy())
    matrix: np.ndarray = field(default_factory=lambda: np.eye(3))
    fovea: np.ndarray | None = None    # the photo's fovea on the eye (None: not in the photo)
    disc: np.ndarray | None = None     # the photo's disc on the eye
    distance_deg: float | None = None  # fovea ↔ disc, as the photo's field of view gives it

    @property
    def distance_mm(self) -> float | None:
        return None if self.distance_deg is None else math.radians(self.distance_deg) * EYE_RADIUS_MM

    @property
    def offset_deg(self) -> float:
        """How far the field centre lies from the posterior pole."""
        return angle_between(self.centre, POLE)


def side_of(disc, cam: Camera, laterality: str | None) -> str | None:
    """Which eye: as stated, else from the side of the photo the disc is on (OD: right)."""
    if laterality in ("OD", "OS"):
        return laterality
    if disc is None:
        return None
    dx = (disc[0] - cam.cx) / max(cam.r, 1.0)
    return None if abs(dx) < 0.1 else ("OD" if dx > 0 else "OS")


def place(cam: Camera, *, fovea=None, disc=None, laterality: str | None = None, align: bool = True) -> Placement:
    """Put a photo on the eye by its landmarks (pixels; either may be missing)."""
    qf = cam.direction(*fovea) if fovea is not None else None
    qd = cam.direction(*disc) if disc is not None else None
    out = Placement(by="centre" if align else "off")
    if qf is not None and qd is not None:
        out.distance_deg = angle_between(qf, qd)
    if align:
        if qf is not None:
            out.by, out.centre = "fovea", centre_for(qf, POLE)
        elif qd is not None and side_of(disc, cam, laterality) is not None:
            out.by, out.centre = "disc", centre_for(qd, anatomical_disc(side_of(disc, cam, laterality)))
    out.matrix = tilt(out.centre)
    out.fovea = None if qf is None else out.matrix @ qf
    out.disc = None if qd is None else out.matrix @ qd
    return out


def expected_fovea(cam: Camera, disc, laterality: str | None) -> tuple[float, float] | None:
    """Where the fovea should be in a photo, going by its disc alone (None: outside the field, or
    the eye unknown)."""
    side = side_of(disc, cam, laterality)
    qd = cam.direction(*disc) if disc is not None else None
    if side is None or qd is None:
        return None
    m = tilt(centre_for(qd, anatomical_disc(side)))
    return cam.pixel(m.T @ POLE)


def fit_fov(cam: Camera, fovea, disc, target_deg: float = DISC_FOVEA_DEG) -> float | None:
    """The field of view (in the camera's own convention) with which the photo's fovea and disc
    lie ``target_deg`` apart — the size of the photo taken from the eye's own scale."""
    def dist(fov: float) -> float | None:
        c = cam.with_fov(fov)
        a, b = c.direction(*fovea), c.direction(*disc)
        return None if a is None or b is None else angle_between(a, b)

    lo, hi = 5.0, 300.0 if cam.fov_type == "internal" else 170.0
    dlo, dhi = dist(lo), dist(hi)
    if dlo is None or dhi is None or not (dlo <= target_deg <= dhi):
        return None
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if dist(mid) < target_deg:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
