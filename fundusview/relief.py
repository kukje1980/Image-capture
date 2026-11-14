"""망막 높낮이: the shape of the retinal surface under a fundus photo, for the 3D eye.

A photo shows the retina's colour, not its shape. This gives the shape a viewer expects:

* the vessels stand up from the surface: thin dark lines, found as a black top-hat of the green
  channel (a closing fills them in; what it filled is the vessel);
* the optic disc has its cup, a bowl in its middle, and a slightly raised rim around it;
* the fovea is a pit with a slightly thicker rim around it.

Heights run from -1 (the cup's floor) to about +1, 0 on the sphere; the 3D eye scales them
(``EyeView.relief_amount``) and builds a fine mesh over the photographed field from them
(:func:`sheet_mesh`). The web page (``web3d/app.js``) does the same in the same way.
"""
from __future__ import annotations

import math

import numpy as np

from . import imaging
from . import projection as proj

ANALYSIS_SIDE = 512     # the height map's longer side (pixels), as the disc and fovea are found
VESSEL_H = 0.55         # a vessel's top
CUP_H = -1.0            # the cup's floor
CUP_FRAC = 0.45         # cup radius / disc radius
DISC_R_DEG = 3.8        # disc radius as an angle at the eye's centre (as imaging.detect_disc expects it)
DISC_RIM_H = 0.22       # the neuroretinal rim, raised a little
PIT_H = -0.55           # the foveal pit's floor
PIT_R_DEG = 3.7         # foveal pit radius (≈ 0.75 mm)
PIT_RIM_H = 0.12        # the thicker retina around the pit
SHEET_N = 256           # the relief sheet: vertices across the image circle


def _rank_filter(a: np.ndarray, r: int, fn) -> np.ndarray:
    """A square max (``np.maximum``) or min (``np.minimum``) filter of half-size ``r``, edges repeated."""
    out = a
    for axis in (0, 1):
        pad = [(r, r) if ax == axis else (0, 0) for ax in (0, 1)]
        p = np.pad(out, pad, mode="edge")
        n = out.shape[axis]
        acc = None
        for k in range(2 * r + 1):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(k, k + n)
            v = p[tuple(sl)]
            acc = v.copy() if acc is None else fn(acc, v, out=acc)
        out = acc
    return out


def vessels(rgb: np.ndarray, circle, tmax_deg: float) -> tuple[np.ndarray, float]:
    """Vessel strength 0…1 on the analysis grid (every ``step``-th pixel) and that step."""
    small, step = imaging._downsample(rgb, ANALYSIS_SIDE)
    cx, cy, R = (float(v) / step for v in circle)
    ppd = R / max(tmax_deg, 1.0)                         # pixels per degree, near the centre
    r = int(np.clip(round(ppd * 0.6), 2, 10))            # half the widest vessel (≈ 0.6°) and a bit
    g = small[..., 1].astype(np.float32)
    closed = _rank_filter(_rank_filter(g, r, np.maximum), r, np.minimum)
    th = closed - g
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= (0.97 * R) ** 2
    if inside.sum() < 50:
        return np.zeros_like(g), step
    lo, hi = np.percentile(th[inside], [60.0, 99.5])
    v = np.clip((th - lo) / max(float(hi - lo), 1e-6), 0.0, 1.0)
    return imaging.gaussian_blur(v, max(0.6, r * 0.35)).astype(np.float32), step


def _bowl(x: np.ndarray) -> np.ndarray:
    """1 at the centre, 0 from x = 1 on, smooth (a raised cosine)."""
    return 0.5 * (1.0 + np.cos(np.pi * np.clip(x, 0.0, 1.0)))


def height_map(vessel: np.ndarray, step: float, circle, tmax_deg: float,
               disc=None, fovea=None) -> np.ndarray:
    """Heights (-1…1) on the analysis grid: the vessels, the disc's cup and rim, the foveal pit."""
    h, w = vessel.shape
    cx, cy, R = (float(v) / step for v in circle)
    ppd = R / max(tmax_deg, 1.0)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    H = VESSEL_H * vessel
    if disc is not None:
        rd = DISC_R_DEG * ppd
        dist = np.hypot(xx - disc[0] / step, yy - disc[1] / step)
        H = H + CUP_H * _bowl(dist / (CUP_FRAC * rd)) + DISC_RIM_H * np.exp(-((dist - 0.9 * rd) / (0.28 * rd)) ** 2)
    if fovea is not None:
        rp = PIT_R_DEG * ppd
        dist = np.hypot(xx - fovea[0] / step, yy - fovea[1] / step)
        H = H + PIT_H * _bowl(dist / rp) + PIT_RIM_H * np.exp(-((dist - 1.35 * rp) / (0.45 * rp)) ** 2)
    t = np.clip((np.hypot(xx - cx, yy - cy) / max(R, 1.0) - 0.88) / 0.12, 0.0, 1.0)
    taper = 1.0 - t * t * (3.0 - 2.0 * t)              # flat again at the edge of the image circle
    return np.clip(H * taper, -1.0, 1.0).astype(np.float32)


def encode16(H: np.ndarray) -> np.ndarray:
    """Heights → an RGBA8 image with 16 bits in R (high) and G (low), as the shaders read it."""
    v = np.round((np.clip(H, -1.0, 1.0) * 0.5 + 0.5) * 65535.0).astype(np.uint32)
    out = np.zeros(H.shape + (4,), np.uint8)
    out[..., 0] = v >> 8
    out[..., 1] = v & 255
    out[..., 3] = 255
    return out


def _sample(H: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear heights at grid coordinates (x, y), 0 outside."""
    h, w = H.shape
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    out = np.zeros(x.shape, np.float64)
    for dy, wy in ((0, 1.0 - fy), (1, fy)):
        for dx, wx in ((0, 1.0 - fx), (1, fx)):
            xi, yi = x0 + dx, y0 + dy
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            out += np.where(ok, H[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], 0.0) * wx * wy
    return out


def sheet_mesh(H: np.ndarray, step: float, circle, camera, place: np.ndarray, amount: float, radius: float,
               n: int = SHEET_N):
    """The relief sheet: a fine mesh over the photographed field, raised by the heights.

    ``camera`` is the photo's :class:`placement.Camera` (its field, projection and roll), ``place``
    the 3×3 matrix from the photo's frame to the eye (``Placement.matrix``), ``amount`` the height
    of +1 in model units, ``radius`` the retina's. Returns (positions, normals, triangle indices);
    normals point into the eye, as the inner wall's do.
    """
    cx, cy, R = (float(v) for v in circle)
    s = np.linspace(-1.03, 1.03, n)
    a, b = np.meshgrid(s, s)                            # a: to the photo's right, b: up
    rr = np.hypot(a, b)
    keep = rr <= 1.03
    tmax = camera.tmax
    flat = rr.ravel()
    th = tmax * flat                                    # (beyond the field: on, evenly)
    lut_r = np.linspace(0.0, 1.0, 257)
    lut_t = np.array([proj.theta_of_rho(float(x), tmax, camera.projection, camera.viewpoint, c=camera.radial_c)
                      for x in lut_r])
    inner = flat <= 1.0
    th[inner] = np.interp(flat[inner], lut_r, lut_t)
    phi = np.arctan2(b, a).ravel() - math.radians(camera.roll_deg)
    q = np.stack([np.sin(th) * np.cos(phi), np.sin(th) * np.sin(phi), -np.cos(th)], axis=1)
    d = q @ np.asarray(place, np.float64).T             # the photo's frame → the eye
    px = cx + a.ravel() * R                             # pixels, then the height grid
    py = cy - b.ravel() * R
    hgt = _sample(H, px / step, py / step)
    hgt = np.where(keep.ravel(), hgt, 0.0)
    pos = d * (radius - amount * hgt)[:, None]
    P = pos.reshape(n, n, 3)
    du = np.zeros_like(P)
    dv = np.zeros_like(P)
    du[:, 1:-1] = P[:, 2:] - P[:, :-2]
    du[:, 0], du[:, -1] = P[:, 1] - P[:, 0], P[:, -1] - P[:, -2]
    dv[1:-1] = P[2:] - P[:-2]
    dv[0], dv[-1] = P[1] - P[0], P[-1] - P[-2]
    nrm = np.cross(du, dv).reshape(-1, 3)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    nrm *= np.where(np.sum(nrm * -d, axis=1) < 0.0, -1.0, 1.0)[:, None]     # into the eye
    k = keep
    quad = k[:-1, :-1] & k[1:, :-1] & k[:-1, 1:] & k[1:, 1:]
    i0 = (np.arange(n - 1)[:, None] * n + np.arange(n - 1)[None, :])[quad]
    idx = np.stack([i0, i0 + n, i0 + 1, i0 + 1, i0 + n, i0 + n + 1], axis=1).ravel().astype(np.uint32)
    return pos.astype(np.float32), nrm.astype(np.float32), idx
