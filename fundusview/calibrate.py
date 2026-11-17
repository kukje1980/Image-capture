"""카메라 각도 보정: the lens curve of a wide-field camera from the photos already taken.

A single photo has one thing of known size in it: the optic disc and the fovea lie about 4.5 mm
(``placement.DISC_FOVEA_DEG`` at the eye centre) apart. One eye may differ by several per cent, so
one photo is a poor ruler — but the camera is the same for all of them, and over many patients the
differences cancel: the median is the camera's own.

The edge of the photo stays where the maker puts it (176° for the RetiCam): nothing in a single
photo measures it. What the photos decide is the lens curve ``c`` of the ``radial`` projection
(``projection.py``: ``theta = theta_max · ((1 - c)·rho + c·rho³)``) — how much the centre is
magnified, that is, how many degrees a pixel near the centre is.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import placement
from . import projection as proj

C_GRID = np.linspace(0.0, 0.85, 171)      # the curves tried (0 = equidistant)
MIN_PHOTOS = 5                            # fewer: no answer
GOOD_PHOTOS = 20                          # fewer: an answer with a warning


@dataclass(frozen=True)
class Sample:
    """One photo: its image circle, optic disc and fovea (pixels)."""
    circle: tuple[float, float, float]
    disc: tuple[float, float]
    fovea: tuple[float, float]
    image_id: int | None = None
    by_hand: bool = False                 # the fovea was marked by the user


@dataclass
class Result:
    c: float                # the lens curve found
    old_c: float
    total: int              # photos with a disc and a fovea
    used: int               # … that agree with the others
    by_hand: int            # … of those, with a fovea marked by hand
    before_deg: float       # median disc–fovea angle with the old curve
    after_deg: float        # … with the new one (the target, when all is well)
    spread_deg: float       # how much the photos differ from each other (robust SD, new curve)
    error_deg: float        # what that leaves of doubt in the median (spread / √used)

    @property
    def few(self) -> bool:
        return self.used < GOOD_PHOTOS

    @property
    def changed(self) -> bool:
        return abs(self.c - self.old_c) >= 0.005


def _rho_phi(s: Sample) -> tuple[np.ndarray, np.ndarray]:
    cx, cy, r = s.circle
    pts = np.array([s.disc, s.fovea], np.float64)
    dx, dy = (pts[:, 0] - cx) / r, (cy - pts[:, 1]) / r
    return np.hypot(dx, dy), np.arctan2(dy, dx)


def distance_deg(s: Sample, tmax: float, c) -> np.ndarray:
    """Angle (degrees, at the eye centre) between the disc and the fovea of a photo with the lens
    curve(s) ``c`` and the half field of view ``tmax`` (radians)."""
    rho, phi = _rho_phi(s)
    c = np.atleast_1d(np.asarray(c, np.float64))[:, None]
    theta = tmax * ((1.0 - c) * rho[None, :] + c * rho[None, :] ** 3)
    st = np.sin(theta)
    d = np.stack([st * np.cos(phi), st * np.sin(phi), -np.cos(theta)], axis=-1)      # K × 2 × 3
    return np.degrees(np.arccos(np.clip(np.sum(d[:, 0] * d[:, 1], axis=-1), -1.0, 1.0)))


def curve_of(s: Sample, tmax: float, target_deg: float = placement.DISC_FOVEA_DEG) -> float | None:
    """The lens curve with which this photo's disc and fovea lie ``target_deg`` apart (None: none does,
    or a mark lies outside the image circle)."""
    if s.circle[2] <= 0 or float(_rho_phi(s)[0].max()) > 1.0:
        return None
    d = distance_deg(s, tmax, C_GRID) - target_deg
    k = np.flatnonzero(np.sign(d[:-1]) * np.sign(d[1:]) <= 0)
    if len(k) == 0:
        return None
    i = int(k[0])
    span = d[i] - d[i + 1]
    t = 0.0 if abs(span) < 1e-12 else float(d[i] / span)
    return float(C_GRID[i] + t * (C_GRID[i + 1] - C_GRID[i]))


def _robust_sd(x: np.ndarray) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else 0.0


def fit_curve(samples: list[Sample], fov_deg: float, old_c: float = proj.DEFAULT_RADIAL_C, *,
              fov_type: str = "internal", viewpoint: float = proj.DEFAULT_VIEWPOINT,
              target_deg: float = placement.DISC_FOVEA_DEG) -> Result | None:
    """The lens curve on which the photos' disc–fovea distance is ``target_deg`` in the median.
    Photos far from the others (a wrong disc or fovea, an unusual eye) are left out. ``None``:
    fewer than ``MIN_PHOTOS`` usable photos."""
    tmax = proj.theta_max(fov_deg, fov_type, viewpoint)
    ok = [(s, c) for s in samples for c in (curve_of(s, tmax, target_deg),) if c is not None]
    if len(ok) < MIN_PHOTOS:
        return None
    total = len(samples)                                   # (a photo no curve fits is left out too)
    for _ in range(3):                                     # drop the photos that disagree, look again
        c = float(np.median([ci for _, ci in ok]))
        dist = np.array([float(distance_deg(s, tmax, c)[0]) for s, _ in ok])
        tol = max(2.0, 3.0 * _robust_sd(dist))
        keep = [sc for sc, d in zip(ok, dist) if abs(d - target_deg) <= tol]
        if len(keep) == len(ok) or len(keep) < MIN_PHOTOS:
            break
        ok = keep
    c = round(float(np.median([ci for _, ci in ok])), 4)
    after = np.array([float(distance_deg(s, tmax, c)[0]) for s, _ in ok])
    before = np.array([float(distance_deg(s, tmax, old_c)[0]) for s, _ in ok])
    spread = _robust_sd(after)
    return Result(c=c, old_c=old_c, total=total, used=len(ok), by_hand=sum(1 for s, _ in ok if s.by_hand),
                  before_deg=float(np.median(before)), after_deg=float(np.median(after)), spread_deg=spread,
                  error_deg=spread / math.sqrt(len(ok)))


def centre_scale(fov_deg: float, c: float, fov_type: str = "internal",
                 viewpoint: float = proj.DEFAULT_VIEWPOINT) -> float:
    """Degrees (eye centre) from the middle of the photo to a tenth of its radius — what the curve
    means in plain numbers."""
    tmax = math.degrees(proj.theta_max(fov_deg, fov_type, viewpoint))
    return tmax * ((1.0 - c) * 0.1 + c * 0.001)


SKIPPED_KINDS = ("montage", "disc", "glaucoma", "anterior")


def samples_from_rows(rows, profile) -> list[Sample]:
    """The photos of ``profile``'s camera that can measure its lens: taken with its own field of
    view and projection, with the image circle, the disc and the fovea known."""
    import json

    out = []
    for r in rows:
        if r["profile"] != profile.key or (r["modality"] or "") in SKIPPED_KINDS or not r["circle_r"]:
            continue
        if r["disc_x"] is None or r["fovea_x"] is None:
            continue
        if (r["projection"] or profile.projection) != profile.projection \
                or (r["fov_type"] or profile.fov_type) != profile.fov_type \
                or abs((r["fov_deg"] or profile.fov_deg) - profile.fov_deg) > 0.5:
            continue
        try:
            hand = json.loads(r["meta_json"] or "{}").get("sources", {}).get("fovea") == "manual"
        except (ValueError, TypeError):
            hand = False
        out.append(Sample((r["circle_cx"], r["circle_cy"], r["circle_r"]), (r["disc_x"], r["disc_y"]),
                          (r["fovea_x"], r["fovea_y"]), r["id"], hand))
    return out


def all_rows(db) -> list:
    """Every photo of the library (the patients' and the unassigned ones)."""
    rows = list(db.images_for_patient(None))
    for p in db.list_patients():
        rows.extend(db.images_for_patient(p["id"]))
    return rows
