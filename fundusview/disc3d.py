"""유두 3D (3D 입체): the optic disc as a surface that can be turned — ``ui/glaucoma_dialog.py``.

A photo gives the disc's colour, the surface needs its shape. Two ways to a shape:

* one photo (:func:`height_from_photo`) — an **estimate from brightness**: the cup is the pale
  part of the disc, so the paler the deeper; the rim stands a little above the retina and the
  vessels above the surface. A picture of the shape a viewer expects, not a measurement;
* two photos of the same disc from slightly different positions (:func:`height_from_stereo`) —
  the **parallax** between them (``glaucoma.disparity``): what moves more is deeper. Relative
  depth, not a length.

:func:`render` then draws the photo on that surface seen from any direction — an exact view of
the height field (nearer parts hide farther ones), computed without OpenGL.

Heights run from -1 (deepest) to about +1, 0 = the retina around the disc; x right, y down.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import glaucoma as G

TEX_PX = 640             # side of the disc-centred texture (and of the picture drawn from it)
DEPTH_DD = 0.5           # depth of height -1 at 100 %: half a disc diameter (the cup, exaggerated)
RIM_H = 0.16             # the neuroretinal rim / peripapillary retina, raised a little
VESSEL_H = 0.14          # a vessel's top
CUP_GAMMA = 2.2          # one photo: depth against pallor (1 = the whole pale disc is the hollow)
SOLVE_PX = 320           # render: side of the grid the visible surface is solved on
MIN_PARALLAX_PX = 1.0    # stereo: less parallax than this (at the analysis width) is no depth
LIGHT = (-0.45, -0.55, 0.70)     # the light in view space: from the upper left, towards the viewer


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _radius(n: int, disc_frac: float) -> np.ndarray:
    """Distance from the centre of an ``n``² picture in disc radii."""
    c = (n - 1) / 2.0
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    return np.hypot(xx - c, yy - c) / max(disc_frac * n / 2.0, 1.0)


def _edge_taper(n: int) -> np.ndarray:
    """1 inside, 0 at the border of the picture (the sheet lies flat where it ends)."""
    t = np.minimum(np.arange(n), np.arange(n)[::-1]).astype(np.float32) / max(n * 0.06, 1.0)
    w = _smoothstep(t)
    return np.minimum(w[:, None], w[None, :])


def height_from_photo(crop: np.ndarray, disc_frac: float, n: int = 256) -> np.ndarray:
    """Estimated heights (``n``², -1…1) of a square picture centred on the optic disc, whose
    disc is ``disc_frac`` of the picture's side across.

    The cup: brightness of green + blue (vessels closed out, smoothed) between the level of the
    rim and the brightest part of the disc. Around it the rim, and the vessels on top.
    """
    small = cv2.resize(crop, (n, n), interpolation=cv2.INTER_AREA).astype(np.float32)
    rd = max(disc_frac * n / 2.0, 2.0)                         # disc radius (px)
    pale = 0.6 * small[..., 1] + 0.4 * small[..., 2]
    k = 2 * max(1, int(round(rd * 0.16))) + 1                   # wider than a vessel
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, kernel)
    smooth = cv2.GaussianBlur(closed, (0, 0), rd * 0.10)
    r = _radius(n, disc_frac)
    # the disc may sit a little off the picture's centre: measure from the pale patch itself
    w = np.clip(smooth - float(np.median(smooth)), 0.0, None) ** 2 * (r < 1.5)
    if float(w.sum()) > 0.0:
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        mx, my = float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())
        if math.hypot(mx - (n - 1) / 2.0, my - (n - 1) / 2.0) < 1.3 * rd:
            r = np.hypot(xx - mx, yy - my) / rd
    ring = (r > 0.85) & (r < 1.3)
    inside = r < 0.75
    lo = float(np.median(smooth[ring])) if ring.any() else float(smooth.mean())
    hi = float(np.percentile(smooth[inside], 99.0)) if inside.any() else lo
    if hi - lo > 6.0:                                           # a pale cup stands out from the rim
        # the whole disc is paler than the retina, the cup paler still: deep only towards the palest
        # part, so that the rim slopes in and the cup is not the disc cut out
        cup = np.clip((smooth - lo) / (hi - lo), 0.0, 1.0) ** CUP_GAMMA
    else:                                                       # no cup to see: a shallow bowl
        cup = 0.35 * _smoothstep(1.0 - r / 0.45)
    window = 1.0 - _smoothstep((r - 0.9) / 0.25)                # only inside the disc
    bowl = cv2.GaussianBlur(cup * window, (0, 0), rd * 0.09)    # walls that slope, not a cliff
    H = -bowl / max(float(bowl.max()), 0.5) * float((cup * window).max()) + RIM_H * np.exp(-((r - 1.0) / 0.3) ** 2)
    g = small[..., 1]
    vk = 2 * max(1, int(round(rd * 0.09))) + 1
    hat = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (vk, vk)))
    top = float(np.percentile(hat, 99.5))
    if top > 4.0:                                               # (below a third of the darkest: grain, not vessels)
        H = H + VESSEL_H * cv2.GaussianBlur(np.clip((hat / top - 0.33) / 0.67, 0.0, 1.0), (0, 0), 1.2)
    H = cv2.GaussianBlur(H, (0, 0), max(0.8, rd * 0.035))
    return np.clip(H * _edge_taper(n), -1.0, 1.0).astype(np.float32)


def height_from_stereo(a: np.ndarray, b: np.ndarray, disc_frac: float, n: int = 256,
                       flip: bool = False) -> tuple[np.ndarray, dict]:
    """Heights (``n``², -1…1) from the parallax between two registered pictures of one disc, and
    ``{"parallax": px at the analysis width, "flipped", "enough" (parallax to speak of), "reliable"
    (… and the retina around the disc came out flat: the two are a stereo pair)}``.

    Which photo was taken from the left is not known, so the sign is chosen so that the middle
    of the disc is the deep part (``flip`` turns it over). The level and tilt of the retina
    around the disc (a leftover shift between the photos) are taken out.
    """
    disp = -G.disparity(a, b, width=240, max_d=12)             # positive = towards the viewer
    disp = cv2.resize(disp, (n, n), interpolation=cv2.INTER_CUBIC)
    r = _radius(n, disc_frac)
    m = max(4, n // 16)
    core = np.zeros((n, n), bool)
    core[m:n - m, m:n - m] = True
    around = core & (r > 1.25)
    if around.sum() >= 50:                                      # the retina's plane: level and tilt
        yy, xx = np.nonzero(around)
        A = np.stack([xx, yy, np.ones_like(xx)], axis=1).astype(np.float64)
        coef, *_ = np.linalg.lstsq(A, disp[around].astype(np.float64), rcond=None)
        gy, gx = np.mgrid[0:n, 0:n]
        disp = disp - (coef[0] * gx + coef[1] * gy + coef[2]).astype(np.float32)
    else:
        disp = disp - float(np.median(disp[core]))
    middle = core & (r < 0.5)
    flipped = bool(middle.any() and float(disp[middle].mean()) > 0.0)
    if flipped != bool(flip):
        disp = -disp
    parallax = float(np.percentile(np.abs(disp[core]), 99.5))     # (disparity is in pixels of its own 240 grid)
    H = disp / max(float(np.percentile(np.abs(disp[core]), 99.5)), 1e-6)
    H = cv2.GaussianBlur(H, (0, 0), n / 90.0)
    # a stereo pair of a disc: the retina around it is flat, the middle is the hollow. Two photos
    # that are not such a pair (another gaze, another day's framing) give bumps everywhere instead.
    noise = float(disp[around].std()) if around.sum() >= 50 else 0.0
    signal = abs(float(disp[middle].mean())) if middle.any() else 0.0
    enough = parallax >= MIN_PARALLAX_PX
    info = {"parallax": parallax, "flipped": flipped, "enough": enough, "noise": noise, "signal": signal,
            "reliable": enough and noise <= 0.5 * signal}
    return np.clip(H * _edge_taper(n), -1.0, 1.0).astype(np.float32), info


def rotation(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """View rotation: yaw turns about the vertical axis, pitch about the horizontal one."""
    a, b = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(a), 0.0, math.sin(a)], [0.0, 1.0, 0.0], [-math.sin(a), 0.0, math.cos(a)]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(b), -math.sin(b)], [0.0, math.sin(b), math.cos(b)]])
    return rx @ ry


def shade(tex: np.ndarray, H: np.ndarray, depth_px: float, R: np.ndarray, strength: float = 1.0,
          contours: bool = False) -> np.ndarray:
    """The photo lit from the upper left of the view (slopes towards the light are brighter),
    with lines of equal height when ``contours``."""
    n = tex.shape[0]
    Hf = cv2.resize(H, (n, n), interpolation=cv2.INTER_CUBIC) if H.shape[0] != n else H
    out = tex.astype(np.float32)
    if strength > 0.0 and depth_px > 0.0:
        z = Hf * depth_px
        gx = cv2.Sobel(z, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        gy = cv2.Sobel(z, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        L = R.T @ (np.asarray(LIGHT, np.float64) / np.linalg.norm(LIGHT))    # the light in the object's frame
        lit = (-gx * L[0] - gy * L[1] + L[2]) / np.sqrt(gx * gx + gy * gy + 1.0)
        k = np.clip(1.0 + strength * (lit / max(float(L[2]), 0.25) - 1.0), 0.35, 1.6)
        out *= k[..., None]
    if contours:
        lv = Hf * 8.0                                                         # 8 lines from 0 to the deepest
        d = np.abs(lv - np.round(lv))
        grad = np.hypot(cv2.Sobel(lv, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(lv, cv2.CV_32F, 0, 1, ksize=3)) / 8.0
        line = np.clip(1.0 - d / np.maximum(grad * 1.2, 1e-4), 0.0, 1.0) * (np.abs(Hf) > 0.04)
        tint = np.where((Hf < 0)[..., None], np.float32([90, 190, 255]), np.float32([255, 170, 90]))
        out = out * (1.0 - 0.75 * line[..., None]) + tint * (0.75 * line[..., None])
    return np.clip(out, 0, 255).astype(np.uint8)


def render(tex: np.ndarray, H: np.ndarray, depth_px: float, yaw_deg: float = 0.0, pitch_deg: float = 0.0,
           out_px: int | None = None, zoom: float = 0.86, light: float = 1.0, contours: bool = False,
           background=(0, 0, 0)) -> np.ndarray:
    """The square photo ``tex`` on the surface ``H`` (heights -1…1, ``depth_px`` texture pixels
    for 1, towards the viewer) seen turned by ``yaw`` / ``pitch``, as an ``out_px``² RGB picture.

    Orthographic view of a height field: a point (x, y, h) lands at A·(x, y) + h·d, that is the
    photo's plane moved by ``h`` along one direction e = A⁻¹d, then the affine A. Turned so that
    e runs along the rows, each row is solved on its own: the first point (the highest one) whose
    moved place reaches a pixel is what is seen there.
    """
    n = tex.shape[0]
    out_px = out_px or n
    R = rotation(yaw_deg, pitch_deg)
    Hf = cv2.resize(H, (n, n), interpolation=cv2.INTER_CUBIC) if H.shape[0] != n else H
    src = shade(tex, Hf, depth_px, R, light, contours)
    A, d = R[:2, :2], R[:2, 2]
    Ainv = np.linalg.inv(A)
    e = Ainv @ d
    k = float(np.hypot(*e))
    phi = math.atan2(e[1], e[0]) if k > 1e-9 else 0.0
    cs, sn = math.cos(phi), math.sin(phi)
    # the rows are solved on a coarser grid (``q`` of the texture): the surface is smooth
    q = min(1.0, SOLVE_PX / n)
    m = max(8, int(round(n * q)))
    q = m / n
    Hq = cv2.resize(Hf, (m, m), interpolation=cv2.INTER_AREA) if m != n else Hf
    reach = k * depth_px * q                                    # pixels (of that grid) a height of 1 moves
    pad = int(math.ceil(reach)) + 3
    D = int(math.ceil(m * math.sqrt(2.0))) + 2 * pad
    cm, cc = (m - 1) / 2.0, (D - 1) / 2.0
    # the photo's plane → the frame where e is the +x axis (a turn by -phi about the centre)
    M1 = np.float64([[cs, sn, cc - cs * cm - sn * cm], [-sn, cs, cc + sn * cm - cs * cm]])
    Hrot = cv2.warpAffine(Hq, M1, (D, D), flags=cv2.INTER_LINEAR, borderValue=0.0)
    f = np.arange(D, dtype=np.float64)[None, :] + reach * Hrot.astype(np.float64)
    g = np.maximum.accumulate(f, axis=1)
    big = 4.0 * D
    rows = np.arange(D, dtype=np.float64)[:, None] * big
    idx = np.searchsorted((g + rows).ravel(), (np.arange(D, dtype=np.float64)[None, :] + rows).ravel(),
                          side="left").reshape(D, D) - np.arange(D)[:, None] * D
    ok = (idx > 0) & (idx < D)
    i1 = np.clip(idx, 1, D - 1)
    f0 = np.take_along_axis(f, i1 - 1, axis=1)
    f1 = np.take_along_axis(f, i1, axis=1)
    t = (np.arange(D)[None, :] - f0) / np.maximum(f1 - f0, 1e-9)
    sx = np.where(ok, i1 - 1 + np.clip(t, 0.0, 1.0), -1e4).astype(np.float32)
    # output pixel → the photo's plane → that frame → the point seen there → texture
    ct, co = (n - 1) / 2.0, (out_px - 1) / 2.0
    s = out_px * zoom / n
    oy, ox = np.mgrid[0:out_px, 0:out_px].astype(np.float64)
    px, py = (ox - co) / s, (oy - co) / s
    ux = Ainv[0, 0] * px + Ainv[0, 1] * py                      # (texture pixels from the centre)
    uy = Ainv[1, 0] * px + Ainv[1, 1] * py
    rx = (cc + q * (cs * ux + sn * uy)).astype(np.float32)
    ry = cc + q * (-sn * ux + cs * uy)
    ry32 = ry.astype(np.float32)
    seen = cv2.remap(sx, rx, ry32, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=-1e4)
    hit = cv2.remap(ok.astype(np.float32), rx, ry32, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    seen[hit < 0.999] = -1e6                                    # beside the sheet: the background, not a mix
    qx, qy = (seen - cc) / q, (ry - cc) / q
    tx = (ct + cs * qx - sn * qy).astype(np.float32)
    ty = (ct + sn * qx + cs * qy).astype(np.float32)
    return cv2.remap(src, tx, ty, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                     borderValue=tuple(int(v) for v in background))


def anaglyph(tex: np.ndarray, H: np.ndarray, depth_px: float, yaw_deg: float, pitch_deg: float,
             eye_deg: float = 3.0, **kw) -> np.ndarray:
    """The surface for red–cyan glasses: the view of each eye, ``2 · eye_deg`` apart."""
    left = render(tex, H, depth_px, yaw_deg - eye_deg, pitch_deg, **kw)
    right = render(tex, H, depth_px, yaw_deg + eye_deg, pitch_deg, **kw)
    return G.anaglyph(left, right)
