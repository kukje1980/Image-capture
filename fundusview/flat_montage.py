"""수동 합치기: photos laid flat over each other — as they are — and blended into one picture.

``montage.py`` places photos on the eyeball (exact, but a photo away from the middle is drawn bent on
the map). Here nothing is reprojected: every photo keeps its own shape and is only **moved and
turned** on a plane by the user (``Placement``), like prints on a light table. The plane's unit is
the radius of the image circle of the first photo; a photo with another field of view is drawn
larger or smaller in proportion (``unit_radii``).

``render`` draws the result with the blend of the montage (``montage.two_band``): the broad
brightness as a soft-weighted average that fades towards each photo's edge — no seams, no steps of
brightness — and the fine detail (vessels) from the photo that sees a place most centrally, so a
vessel is not drawn twice where the photos do not fit to the pixel. ``match_gains`` first makes the
overlapping parts equally bright.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import montage as mt

try:
    import cv2
except ImportError:          # pragma: no cover - listed in requirements.txt
    cv2 = None


@dataclass
class Placement:
    """Where a photo lies: the centre of its image circle on the plane (y down, as on the screen) and
    its turn in degrees, counter-clockwise as seen."""
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0

    def copy(self) -> "Placement":
        return Placement(self.x, self.y, self.angle)


def unit_radii(shots: list[mt.Shot]) -> list[float]:
    """The radius of each photo's image circle on the plane: 1 for the first, the others by their
    field of view (photos of one camera: all 1)."""
    if not shots:
        return []
    t0 = max(shots[0].tmax, 1e-6)
    return [float(s.tmax / t0) for s in shots]


def matrix(circle, rho: float, pl: Placement, k: float = 1.0, ox: float = 0.0, oy: float = 0.0) -> np.ndarray:
    """2×3: a pixel of the photo → the picture drawn at ``k`` pixels per plane unit, whose top-left
    corner is (``ox``, ``oy``) on the plane."""
    cx, cy, r = circle
    s = rho / r * k
    c, sn = math.cos(math.radians(pl.angle)), math.sin(math.radians(pl.angle))
    return np.array([[s * c, s * sn, k * (pl.x - ox) - s * (c * cx + sn * cy)],
                     [-s * sn, s * c, k * (pl.y - oy) - s * (-sn * cx + c * cy)]], np.float64)


def to_photo(circle, rho: float, pl: Placement, x: float, y: float) -> tuple[float, float]:
    """A point of the plane → the pixel of the photo there."""
    m = matrix(circle, rho, pl)
    u, v = np.linalg.solve(m[:, :2], np.array([x - m[0, 2], y - m[1, 2]]))
    return float(u), float(v)


def mask(shot: mt.Shot) -> np.ndarray:
    """uint8, 255 where the photo shows the retina: its ``alpha`` inside the image circle."""
    h, w = shot.alpha.shape
    cx, cy, r = shot.circle
    yy, xx = np.ogrid[0:h, 0:w]
    return np.where((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r, shot.alpha, 0).astype(np.uint8)


def hit(shot: mt.Shot, rho: float, pl: Placement, x: float, y: float) -> bool:
    """Does the photo show something at that point of the plane?"""
    u, v = to_photo(shot.circle, rho, pl, x, y)
    cx, cy, r = shot.circle
    h, w = shot.alpha.shape
    return (0 <= u < w and 0 <= v < h and (u - cx) ** 2 + (v - cy) ** 2 <= r * r
            and shot.alpha[int(v), int(u)] >= 64)


def bounds(rhos: list[float], places: list[Placement]) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) on the plane around every photo's image circle."""
    return (min(p.x - r for p, r in zip(places, rhos)), min(p.y - r for p, r in zip(places, rhos)),
            max(p.x + r for p, r in zip(places, rhos)), max(p.y + r for p, r in zip(places, rhos)))


def square_around(rhos, places, base: int = 0) -> tuple[float, float, float, float]:
    """The square around every photo with photo ``base`` in its middle (the map of a saved montage:
    its centre is the centre of that photo)."""
    b = places[base]
    half = max(max(abs(p.x - b.x), abs(p.y - b.y)) + r for p, r in zip(places, rhos))
    return b.x - half, b.y - half, b.x + half, b.y + half


def from_sphere(shots: list[mt.Shot], ref: int = 0) -> list[Placement]:
    """The photos as 자동 합치기 placed them on the eye, flattened: where each centre lies on the map
    around photo ``ref`` and how the photo is turned there (a start for 수동 합치기)."""
    t0 = max(shots[0].tmax, 1e-6)
    inv = shots[ref].R.T
    out = []
    for s in shots:
        cx, cy, r = s.circle
        c, e = (s.dirs(np.array([[cx, cy], [cx + 0.05 * r, cy]])) @ s.R.T) @ inv.T
        x, y = mt.plane_xy(c)
        ex, ey = mt.plane_xy(e)
        out.append(Placement(float(x) / t0, -float(y) / t0,
                             math.degrees(math.atan2(float(ey) - float(y), float(ex) - float(x)))))
    return out


def spread(rhos: list[float], base: int = 0) -> list[Placement]:
    """A start with nothing matched: ``base`` in the middle, the others around it, half over it."""
    out = [Placement() for _ in rhos]
    others = [k for k in range(len(rhos)) if k != base]
    for n, k in enumerate(others):
        a = 2 * math.pi * n / max(1, len(others))
        d = 0.9 * (rhos[base] + rhos[k]) / 2
        out[k] = Placement(d * math.cos(a), d * math.sin(a), 0.0)
    return out


def _sample(shot: mt.Shot, msk: np.ndarray, m: np.ndarray, size: tuple[int, int]):
    """The photo drawn by ``m`` on a picture of ``size`` (w, h): colour (uint8), coverage (0 … 1) and
    the distance from the edge of what it shows (radii, up to ``montage.EDGE_SPAN``)."""
    flags = cv2.INTER_LINEAR
    col = cv2.warpAffine(shot.rgb, m, size, flags=flags, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = cv2.warpAffine(msk, m, size, flags=flags, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    e = cv2.warpAffine(shot.edge_image(), m, size, flags=flags, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return col, a.astype(np.float32) / 255.0, e.astype(np.float32) * (mt.EDGE_SPAN / 255.0)


def _picture(rhos, places, shots, rect, max_side):
    """(x0, y0, pixels per plane unit, width, height) of the picture of ``rect`` (default: every photo),
    as detailed as the sharpest photo, at most ``max_side`` across."""
    x0, y0, x1, y1 = rect if rect is not None else bounds(rhos, places)
    finest = max(s.circle[2] / max(r, 1e-6) for s, r in zip(shots, rhos))
    k = min(finest, max_side / max(x1 - x0, y1 - y0, 1e-6))
    return x0, y0, k, max(1, int(math.ceil((x1 - x0) * k))), max(1, int(math.ceil((y1 - y0) * k)))


def match_gains(shots: list[mt.Shot], rhos: list[float], places: list[Placement], size: int = 256) -> None:
    """Per-photo colour gains that make the overlapping parts equally bright (``shot.gain``)."""
    if len(shots) < 2:
        return
    x0, y0, k, w, h = _picture(rhos, places, shots, None, size)
    samples = []
    for s, r, p in zip(shots, rhos, places):
        col, a, e = _sample(s, mask(s), matrix(s.circle, r, p, k, x0, y0), (w, h))
        samples.append((col.astype(np.float32), a, e))
    mt.gains_from_samples(shots, samples, size)


def render(shots: list[mt.Shot], rhos: list[float], places: list[Placement], *, max_side: int = 4000,
           rect=None, band: int = 384, progress=None):
    """Draw the photos as they lie, blended. Returns (rgb uint8, coverage uint8, (x0, y0, k)) — the
    picture's top-left corner on the plane and its pixels per plane unit. Drawn in bands of rows, so
    a large picture needs little memory; ``progress(f)`` hears the fraction done."""
    x0, y0, k, w, h = _picture(rhos, places, shots, rect, max_side)
    out = np.zeros((h, w, 3), np.uint8)
    cover = np.zeros((h, w), np.uint8)
    sigma = max(2.0, max(w, h) / 220.0)
    margin = int(math.ceil(4 * sigma))
    masks = [mask(s) for s in shots]
    spans = [((p.y - r - y0) * k - 2, (p.y + r - y0) * k + 2) for p, r in zip(places, rhos)]
    xs = (np.arange(w, dtype=np.float32) + 0.5) / k + x0
    starts = list(range(0, h, band))
    for b, r0 in enumerate(starts):
        if progress:
            progress(b / len(starts))
        r1 = min(h, r0 + band)
        a0, a1 = max(0, r0 - margin), min(h, r1 + margin)
        use = [i for i, (lo, hi) in enumerate(spans) if hi >= a0 and lo < a1]
        if not use:
            continue
        ys = (np.arange(a0, a1, dtype=np.float32) + 0.5) / k + y0
        central = [np.clip(1.0 - np.hypot(xs[None, :] - places[i].x, ys[:, None] - places[i].y) / rhos[i],
                           0.0, 1.0).astype(np.float32) for i in use]

        def sample(j):
            i = use[j]
            m = matrix(shots[i].circle, rhos[i], places[i], k, x0, y0 + a0 / k)
            col, a, e = _sample(shots[i], masks[i], m, (w, a1 - a0))
            return col.astype(np.float32) * shots[i].gain.astype(np.float32), a, e

        col, alpha = mt.two_band(central, sample, sigma)
        out[r0:r1] = col[r0 - a0:r1 - a0]
        cover[r0:r1] = alpha[r0 - a0:r1 - a0]
    if progress:
        progress(1.0)
    return out, cover, (x0, y0, k)


def crop(rgb: np.ndarray, cover: np.ndarray, pad: int = 0):
    """The picture cut to what the photos cover. Returns (rgb, cover, (left, top))."""
    ys, xs = np.flatnonzero(cover.any(axis=1)), np.flatnonzero(cover.any(axis=0))
    if not len(ys) or not len(xs):
        return rgb, cover, (0, 0)
    t, b = max(0, ys[0] - pad), min(rgb.shape[0], ys[-1] + 1 + pad)
    le, ri = max(0, xs[0] - pad), min(rgb.shape[1], xs[-1] + 1 + pad)
    return np.ascontiguousarray(rgb[t:b, le:ri]), np.ascontiguousarray(cover[t:b, le:ri]), (int(le), int(t))
