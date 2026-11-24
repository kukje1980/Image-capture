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

The **nerve behind the disc** (시신경 다발) is a picture to explain with, not a finding: strands run over
the retina into the disc, across the rim and out behind as one bundle (:func:`fibre_paths`). Where
the photo shows the stripes of the nerve fibre layer their direction is read off it
(:func:`fibre_field`) and the strands follow it; elsewhere they follow the usual course.
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
MIN_LIGHT_Z = 0.35       # shade: the light is never lower over the photo's plane than this
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


def height_from_photo(crop: np.ndarray, disc_frac: float, n: int = 256, info: dict | None = None) -> np.ndarray:
    """Estimated heights (``n``², -1…1) of a square picture centred on the optic disc, whose
    disc is ``disc_frac`` of the picture's side across. ``info`` (a dict) is told ``"cup"``: whether
    a pale cup was seen (False: the hollow is only a stand-in, nothing to measure).

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
    if info is not None:
        info["cup"] = hi - lo > 6.0
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


CUP_LEVEL = 0.30         # the cup's margin: this part of the way down to its deepest point
MIN_CUP_DEPTH = 0.12     # a hollow shallower than this (of height 1) is no cup to measure


def outline_points(e: dict, k: int = 120) -> np.ndarray:
    """``k`` points round an outline (``glaucoma.outline``: four quarter ellipses), as (k, 2) x, y."""
    o = G.outline(e)
    a = np.linspace(0.0, 2.0 * math.pi, k, endpoint=False)
    c, s = np.cos(a), np.sin(a)                                  # (y down: s > 0 is below the centre)
    x = o["cx"] + np.where(c >= 0, o["right"], o["left"]) * c
    y = o["cy"] + np.where(s >= 0, o["bottom"], o["top"]) * s
    return np.stack([x, y], axis=1)


def cup_from_surface(H: np.ndarray, disc: dict, level: float = CUP_LEVEL) -> tuple[dict, np.ndarray] | None:
    """The cup read off the surface ``H``: the hollow inside the ``disc`` outline (in pixels of ``H``)
    that lies deeper than ``level`` of the way from the retina's level down to the deepest point —
    the one piece of it that holds that point. Returns its outline (``glaucoma.outline``: centre and
    the reach up · right · down · left, so that ``glaucoma.cdr_metrics`` takes it) and its margin as
    (k, 2) points, or None when there is no hollow to speak of.

    An estimate as good as the surface: from one photo that is the pale part of the disc, from a
    stereo pair the part the parallax puts deepest."""
    n = H.shape[0]
    inside = np.zeros((n, n), np.uint8)
    cv2.fillPoly(inside, [np.round(outline_points(disc)).astype(np.int32)], 1)
    if not inside.any():
        return None
    Hs = cv2.GaussianBlur(H, (0, 0), max(1.0, n / 200.0))        # (a vessel across the cup is not its margin)
    deep = np.where(inside > 0, Hs, np.inf)
    iy, ix = np.unravel_index(int(np.argmin(deep)), deep.shape)
    bottom = float(deep[iy, ix])
    if bottom > -MIN_CUP_DEPTH:
        return None
    mask = ((deep <= float(np.clip(level, 0.02, 0.98)) * bottom)).astype(np.uint8)
    _, labels = cv2.connectedComponents(mask, connectivity=4)
    mask = (labels == labels[iy, ix]).astype(np.uint8)
    ys, xs = np.nonzero(mask)
    cx, cy = float(xs.mean()), float(ys.mean())
    cup = {"cx": cx, "cy": cy, "top": cy - ys.min() + 0.5, "bottom": ys.max() - cy + 0.5,
           "left": cx - xs.min() + 0.5, "right": xs.max() - cx + 0.5}
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    edge = max(contours, key=len).reshape(-1, 2).astype(np.float32)
    return cup, edge


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
        if L[2] < MIN_LIGHT_Z:                                   # turned far: the light stays in front of the
            xy = float(np.hypot(L[0], L[1]))                     # sheet (behind it the whole photo went dark)
            L = np.array([L[0] / xy * math.sqrt(1.0 - MIN_LIGHT_Z ** 2), L[1] / xy * math.sqrt(1.0 - MIN_LIGHT_Z ** 2),
                          MIN_LIGHT_Z])
        lit = (-gx * L[0] - gy * L[1] + L[2]) / np.sqrt(gx * gx + gy * gy + 1.0)
        k = np.clip(1.0 + strength * (lit / float(L[2]) - 1.0), 0.35, 1.6)      # (the flat retina: as taken)
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
           background=(0, 0, 0), behind: dict | None = None, sheet_alpha: float = 1.0) -> np.ndarray:
    """The square photo ``tex`` on the surface ``H`` (heights -1…1, ``depth_px`` texture pixels
    for 1, towards the viewer) seen turned by ``yaw`` / ``pitch``, as an ``out_px``² RGB picture.

    Orthographic view of a height field: a point (x, y, h) lands at A·(x, y) + h·d, that is the
    photo's plane moved by ``h`` along one direction e = A⁻¹d, then the affine A. Turned so that
    e runs along the rows, each row is solved on its own: the first point (the highest one) whose
    moved place reaches a pixel is what is seen there.

    ``behind`` (:func:`fibres_behind`) is drawn under the sheet — seen beside it, and through it
    when ``sheet_alpha`` < 1.
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
    out = cv2.remap(src, tx, ty, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                    borderValue=tuple(int(v) for v in background))
    if not behind:
        return out
    back = np.empty_like(out)
    back[:] = tuple(int(v) for v in background)
    _draw_behind(back, behind, R, n, out_px, zoom)
    on = ((seen > -1e5) & (tx > -0.5) & (tx < n - 0.5) & (ty > -0.5) & (ty < n - 0.5))[..., None]    # where the photo is
    a = float(np.clip(sheet_alpha, 0.0, 1.0))
    sheet = out if a >= 1.0 else cv2.addWeighted(out, a, back, 1.0 - a, 0.0)
    return np.where(on, sheet, back)


def anaglyph(tex: np.ndarray, H: np.ndarray, depth_px: float, yaw_deg: float, pitch_deg: float,
             eye_deg: float = 3.0, **kw) -> np.ndarray:
    """The surface for red–cyan glasses: the view of each eye, ``2 · eye_deg`` apart."""
    left = render(tex, H, depth_px, yaw_deg - eye_deg, pitch_deg, **kw)
    right = render(tex, H, depth_px, yaw_deg + eye_deg, pitch_deg, **kw)
    return G.anaglyph(left, right)


# -- the nerve behind the disc (a picture to explain with) ----------------------------------------
FIBRE_MAX = 300          # strands at most
FIBRE_STEP = 0.045       # a step over the retina, of half the picture
FIBRE_STEPS = 44
FIELD_MIN = 0.2          # the photo's stripes: less sure of their direction than this is not read
BUNDLE = 0.56            # the bundle's width against the disc's
STRAND_RGB = (255, 242, 200)
READ_RGB = (95, 240, 192)        # a stretch whose direction was read off the photo
_GOLDEN = 0.6180339887


def _seeds() -> np.ndarray:
    """The strands' fixed traits, (FIBRE_MAX, 6): angle round the disc, the rim it needs, place in
    the bundle, place across the rim, phase, speed. Any first part of them is spread evenly."""
    rng = np.random.default_rng(11)
    i = np.arange(FIBRE_MAX)
    a = ((i * _GOLDEN + rng.random(FIBRE_MAX) * 0.004) % 1.0) * 2.0 * math.pi
    return np.stack([a, rng.random(FIBRE_MAX), 0.25 + 0.75 * np.sqrt(rng.random(FIBRE_MAX)), rng.random(FIBRE_MAX),
                     rng.random(FIBRE_MAX) * 2.0 * math.pi, 0.16 + 0.12 * rng.random(FIBRE_MAX)], axis=1)


SEEDS = _seeds()


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def fibre_field(tex: np.ndarray, disc_frac: float, m: int = 128) -> np.ndarray:
    """The direction of the nerve fibre layer's stripes in a disc-centred photo, as (``m``, ``m``, 2):
    (cos 2θ, sin 2θ) · confidence, θ the direction along the stripes (mod 180°), confidence 0…1.

    Green channel with the vessels taken out, the fine stripes kept, and the direction they agree
    on around each place (a structure tensor). Sure only where stripes are seen: mostly in the
    arching bundles above and below the disc of a sharp photo, hardly anywhere in a wide one."""
    n = tex.shape[0]
    k = max(disc_frac * n / 2.0, 4.0) / 86.0                    # (the sizes below are for a disc 172 px across)
    out = np.zeros((m, m, 2), np.float32)
    fov = (tex.sum(axis=2) > 60).astype(np.uint8)
    e = 2 * max(1, int(round(12 * k))) + 1
    fov = cv2.erode(fov, np.ones((e, e), np.uint8))
    if not fov.any():
        return out
    cl = cv2.createCLAHE(3.0, (8, 8)).apply(np.ascontiguousarray(tex[..., 1]))
    hk = 2 * max(2, int(round(8 * k))) + 1
    hat = cv2.morphologyEx(cl, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (hk, hk)))
    lo, top = np.percentile(hat[fov > 0], (86, 99.5))
    ves = (hat > max(float(lo), 0.25 * float(top))).astype(np.uint8)      # (a vessel is dark, a stripe faint)
    dk = 2 * max(1, int(round(3 * k))) + 1
    ves = cv2.dilate(ves, np.ones((dk, dk), np.uint8))
    flat = cv2.inpaint(cl, ves, max(3.0, 7.0 * k), cv2.INPAINT_TELEA).astype(np.float32)
    bp = cv2.GaussianBlur(flat, (0, 0), 1.5 * k) - cv2.GaussianBlur(flat, (0, 0), 5.0 * k)
    gx = cv2.Sobel(bp, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(bp, cv2.CV_32F, 0, 1, ksize=3)
    wk = 2 * max(2, int(round(6 * k))) + 1                     # (a vessel's shoulder runs along it: not a stripe)
    near = cv2.dilate(ves, np.ones((wk, wk), np.uint8))
    w = ((near == 0) & (fov > 0) & (_radius(n, disc_frac) > 1.2)).astype(np.float32)
    s = 16.0 * k
    ws = cv2.GaussianBlur(w, (0, 0), s)

    def mean(a):
        return cv2.GaussianBlur(a * w, (0, 0), s) / np.maximum(ws, 1e-3)
    jxx, jyy, jxy = mean(gx * gx), mean(gy * gy), mean(gx * gy)
    coh = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy ** 2) / np.maximum(jxx + jyy, 1e-6)
    coh = coh * np.clip((ws - 0.3) * 3.0, 0.0, 1.0)           # (little but vessels around: not to be read)
    a2 = np.arctan2(2.0 * jxy, jxx - jyy) + math.pi           # twice the direction along the stripes
    out[..., 0] = cv2.resize(np.cos(a2) * coh, (m, m), interpolation=cv2.INTER_AREA)
    out[..., 1] = cv2.resize(np.sin(a2) * coh, (m, m), interpolation=cv2.INTER_AREA)
    return out


def _spline(pts: np.ndarray, k: int) -> np.ndarray:
    """``k`` points along the smooth curve through ``pts`` (Catmull–Rom)."""
    p = np.vstack([pts[:1], pts, pts[-1:]])
    u = np.linspace(0.0, len(pts) - 1.0, k)
    i = np.minimum(u.astype(int), len(pts) - 2)
    t = (u - i)[:, None]
    p0, p1, p2, p3 = p[i], p[i + 1], p[i + 2], p[i + 3]
    return 0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * (p1 - p2) + p3 - p0) * t ** 3)


def fibre_paths(disc: dict, cup: dict, H: np.ndarray, depth_px: float, n: int = TEX_PX, count: int = 150,
                temporal: float = math.pi, field: np.ndarray | None = None, mask: np.ndarray | None = None) -> list:
    """The strands of the nerve for a disc and cup outline (texture pixels of an ``n``² picture) on
    the surface ``H``: each ``{"retina": (k, 2) x, y from far out to the rim, "read": (k,) bool —
    direction read off the photo there, "behind": (j, 3) x, y, z from the rim down and out behind
    (z in pixels, towards the viewer), "seed": its row of SEEDS}``.

    A strand leaves the rim at its angle: straight on the nasal side, arching towards ``temporal``
    (the direction of the macula from the disc, radians, y down) elsewhere, and along the stripes
    of ``field`` (:func:`fibre_field`) where they are sure. It is drawn only while the rim that way
    is wide enough — the thinner the rim, the fewer strands. ``mask`` (``n``², bool): where the
    photo is; a strand ends at its edge."""
    half = n / 2.0
    hq = H.shape[0]
    fm = field.shape[0] if field is not None else 0

    def h_at(x, y):
        return float(H[int(np.clip(round(y * (hq - 1) / (n - 1)), 0, hq - 1)),
                       int(np.clip(round(x * (hq - 1) / (n - 1)), 0, hq - 1))])

    def at(e, a):
        c, s = math.cos(a), math.sin(a)
        return e["cx"] + (e["right"] if c >= 0 else e["left"]) * c, e["cy"] + (e["bottom"] if s >= 0 else e["top"]) * s
    rad = (disc["left"] + disc["right"] + disc["top"] + disc["bottom"]) / 4.0
    z_l = -depth_px - 0.09 * half                               # the lamina: under the cup's floor
    length, step = 1.0 * half, FIBRE_STEP * half
    nasal = temporal + math.pi

    def axis(t):
        return (disc["cx"] + 0.34 * half * t * t * math.cos(nasal), disc["cy"] + 0.05 * half * t * t, z_l - length * t)
    out = []
    for seed in SEEDS[:int(np.clip(count, 0, FIBRE_MAX))]:
        a, need, rho, across, phase, _speed = (float(v) for v in seed)
        pd, pc = at(disc, a), at(cup, a)
        rd = math.hypot(pd[0] - disc["cx"], pd[1] - disc["cy"])
        rc = math.hypot(pc[0] - disc["cx"], pc[1] - disc["cy"])
        if max(0.0, 1.0 - rc / max(rd, 1e-6)) < 0.06 + need * 0.5:      # the rim's share of the radius this way
            continue
        mix = 0.3 + 0.5 * across
        sx, sy = pc[0] + (pd[0] - pc[0]) * mix, pc[1] + (pd[1] - pc[1]) * mix
        # over the retina, outwards from the rim
        th, x, y = _wrap(a), sx, sy
        arch = min(1.0, max(0.0, (abs(_wrap(a - nasal)) - 0.7) / 0.5))
        pts, read = [], []
        for i in range(FIBRE_STEPS):
            if not (2 <= x <= n - 3 and 2 <= y <= n - 3) or (mask is not None and not mask[int(y), int(x)]):
                break
            pts.append((x, y))
            th += 1.25 * arch * math.sin(temporal - th) * FIBRE_STEP + 0.012 * math.sin(i * 0.5 + phase)
            hit = False
            if fm:
                fx, fy = field[int(np.clip(round(y * (fm - 1) / (n - 1)), 0, fm - 1)),
                               int(np.clip(round(x * (fm - 1) / (n - 1)), 0, fm - 1))]
                if math.hypot(fx, fy) > FIELD_MIN:
                    d = _wrap(0.5 * math.atan2(fy, fx) - th)
                    if abs(d) > math.pi / 2:                     # (a direction mod 180°: the way the strand runs)
                        d = _wrap(d + math.pi)
                    if abs(d) < 0.9:
                        th += d * 0.6
                        hit = True
            read.append(hit)
            x += math.cos(th) * step
            y += math.sin(th) * step
        # from the rim down to the lamina and out behind
        h0 = h_at(sx, sy) * depth_px
        tx, ty = disc["cx"] + math.cos(a) * rad * BUNDLE * rho, disc["cy"] + math.sin(a) * rad * BUNDLE * rho
        ctl = [(sx, sy, h0), (sx + (tx - sx) * 0.35, sy + (ty - sy) * 0.35, min(h0, 0.0) * 0.5 + z_l * 0.55), (tx, ty, z_l)]
        for t in (0.1, 0.28, 0.5, 0.75, 1.0):
            b = a + 0.22 * math.sin(t * 3.0 + phase)
            r = rad * rho * BUNDLE * (1.0 + 0.3 * min(1.0, t * 5.0))
            ox, oy, oz = axis(t)
            ctl.append((ox + math.cos(b) * r, oy + math.sin(b) * r, oz))
        out.append({"retina": np.float32(pts[::-1]).reshape(-1, 2), "read": np.array(read[::-1], bool),
                    "behind": _spline(np.float64(ctl), 28).astype(np.float32), "seed": seed})
    return out


def read_share(paths: list) -> float:
    """The part of the strands' way over the retina whose direction was read off the photo (0…1)."""
    total = sum(len(p["read"]) for p in paths)
    return sum(int(p["read"].sum()) for p in paths) / total if total else 0.0


def fibres_on_texture(tex: np.ndarray, paths: list) -> np.ndarray:
    """The photo with the strands over the retina drawn on it: faint far out, bright at the disc;
    the stretches read off the photo in their own colour."""
    n = tex.shape[0]
    alpha = np.zeros((n, n), np.uint8)
    col = np.empty((n, n, 3), np.uint8)
    col[:] = STRAND_RGB
    w = max(1, int(round(n / 520)))
    for p in paths:
        pts = p["retina"]
        k = len(pts)
        if k < 2:
            continue
        q = np.round(pts * 8).astype(np.int32)
        for lo, hi, a in ((0, k // 3 + 1, 70), (k // 3, 2 * k // 3 + 1, 130), (2 * k // 3, k, 205)):
            if hi - lo >= 2:
                cv2.polylines(alpha, [q[lo:hi]], False, a, w, cv2.LINE_AA, shift=3)
        run = []
        for i in range(k + 1):                                   # the stretches read off the photo
            if i < k and p["read"][i]:
                run.append(q[i])
                continue
            if len(run) >= 3:
                cv2.polylines(col, [np.int32(run)], False, READ_RGB, w + 2, cv2.LINE_8, shift=3)
                cv2.polylines(alpha, [np.int32(run)], False, 215, w, cv2.LINE_AA, shift=3)
            run = []
    a = (alpha.astype(np.float32) / 255.0)[..., None]
    return (tex.astype(np.float32) * (1.0 - a) + col.astype(np.float32) * a).astype(np.uint8)


def pulses(paths: list, t: float, on_retina: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Where each strand's signal is at time ``t`` (seconds): on its way over the retina, (k, 2)
    x, y, or behind the disc, (j, 3) x, y, z."""
    flat, deep = [], []
    for p in paths:
        head = len(p["retina"]) if on_retina else 0
        total = head + len(p["behind"])
        s = ((t * p["seed"][5] * 0.7 + p["seed"][1]) % 1.0) * (total - 4)
        i = int(s)
        f = s - i
        if i + 1 < head:
            flat.append(p["retina"][i] * (1 - f) + p["retina"][i + 1] * f)
        else:
            j = min(max(i - head, 0), len(p["behind"]) - 2)
            deep.append(p["behind"][j] * (1 - f) + p["behind"][j + 1] * f)
    return np.float32(flat).reshape(-1, 2), np.float32(deep).reshape(-1, 3)


def fibres_behind(paths: list, disc: dict, depth_px: float, n: int = TEX_PX, dots: np.ndarray | None = None) -> dict:
    """What :func:`render` draws under the sheet: the strands from the rim out behind, the ring of
    the lamina they pass, and the signals on them (``dots``, (j, 3))."""
    rad = (disc["left"] + disc["right"] + disc["top"] + disc["bottom"]) / 4.0
    a = np.linspace(0.0, 2.0 * math.pi, 49)
    ring = np.stack([disc["cx"] + np.cos(a) * rad * BUNDLE * 1.1, disc["cy"] + np.sin(a) * rad * BUNDLE * 1.1,
                     np.full(49, -depth_px - 0.09 * n / 2.0)], axis=1).astype(np.float32)
    return {"lines": [p["behind"] for p in paths], "ring": ring,
            "dots": dots if dots is not None else np.zeros((0, 3), np.float32)}


_FADE = np.float32([(255, 242, 196), (241, 223, 174), (185, 154, 106), (58, 44, 32), (0, 0, 0)])   # along a strand


def _draw_behind(img: np.ndarray, behind: dict, R: np.ndarray, n: int, out_px: int, zoom: float) -> None:
    """Draw the nerve into ``img`` as :func:`render` sees it: farther strands first."""
    ct, co, s = (n - 1) / 2.0, (out_px - 1) / 2.0, out_px * zoom / n
    A, d = R[:2, :2], R[:2, 2]

    def screen(p):                                              # (k, 3) → (k, 2) pixels, and how near each is
        xy = (p[:, :2] - ct) @ A.T + p[:, 2:3] * d[None, :]
        return co + s * xy, (p[:, :2] - ct) @ R[2, :2] + p[:, 2] * R[2, 2]
    w = max(1, int(round(out_px / 520)))
    lines = []
    for p in behind.get("lines", ()):
        q, near = screen(p)
        lines.append((float(near.mean()), q))
    ring = behind.get("ring")
    if ring is not None and len(ring):
        cv2.polylines(img, [np.round(screen(ring)[0] * 8).astype(np.int32)], True, (150, 156, 166), w + 1, cv2.LINE_AA, shift=3)
    stops = (0.0, 0.6, 0.86, 0.96, 1.0)
    for _, q in sorted(lines, key=lambda v: v[0]):
        k = len(q)
        qi = np.round(q * 8).astype(np.int32)
        for lo in range(0, k - 1, 4):
            t = (lo + 2) / (k - 1)
            c = [float(np.interp(t, stops, _FADE[:, ch])) for ch in range(3)]
            cv2.polylines(img, [qi[lo:lo + 5]], False, c, w, cv2.LINE_AA, shift=3)
    dots = behind.get("dots")
    if dots is not None and len(dots):
        for x, y in np.round(screen(dots)[0] * 8).astype(np.int32):
            cv2.circle(img, (int(x), int(y)), (w + 1) * 8, (255, 250, 215), -1, cv2.LINE_AA, shift=3)
