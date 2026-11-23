"""유두 3D (3D 입체): the optic disc as a surface that can be turned — ``ui/glaucoma_dialog.py``.

A photo gives the disc's colour, the surface needs its shape. Two ways to a shape:

* one photo (:func:`height_from_photo`) — an **estimate from brightness**: the cup is the pale
  part of the disc, so the paler the deeper; the rim stands a little above the retina and the
  vessels a little above the surface. A picture of the shape a viewer expects, not a measurement;
* two photos of the same disc from slightly different positions (:func:`height_from_stereo`) —
  the **parallax** between them (``glaucoma.disparity``): what moves more is deeper. Relative
  depth, not a length.

:func:`render` then draws the photo on that surface seen from any direction — an exact view of
the height field (nearer parts hide farther ones), computed without OpenGL. It is the photo that is
seen: its own colours and its own light (:func:`shade` adds only what turning it changes), at the
depth a real cup has — the front view is the photo as it was taken.

Heights run from -1 (deepest) to about +1, 0 = the retina around the disc; x right, y down.
"""
from __future__ import annotations

import hashlib
import math

import cv2
import numpy as np

from . import glaucoma as G

TEX_PX = 640             # side of the disc-centred texture (and of the picture drawn from it)
DEPTH_DD = 0.4           # depth of height -1 at 100 %: 0.4 disc diameters — about a deep cup's (0.7 mm)
RIM_H = 0.16             # the neuroretinal rim / peripapillary retina, raised a little
VESSEL_H = 0.07          # a vessel's top: about half its width above the surface it lies on
CUP_GAMMA = 2.2          # one photo: depth against pallor (1 = the whole pale disc is the hollow)
SOLVE_PX = 320           # render: side of the grid the visible surface is solved on
MIN_PARALLAX_PX = 1.0    # stereo: less parallax than this (at the analysis width) is no depth
SHADE = 0.8              # shade: how much a slope's turn to or from the viewer lightens / darkens it
SHADE_RANGE = (0.75, 1.14)       # … and never more than this (the photo keeps its own colours)
MIN_VIEW_Z = 0.5         # shade: the viewer is never lower over the photo's plane than this
VIEW_DIST = 3.0          # the 3D tab's camera: this many sides of the picture away (a slight perspective)


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


def _pallor(crop: np.ndarray, disc_frac: float, n: int) -> dict:
    """What a one-photo shape stands on: the picture at ``n``², the disc radius ``rd`` (px), the
    distance from the disc's centre in disc radii ``r`` and that centre ``(x, y)`` (px) — the
    middle of the pale patch, when the disc sits a little off the picture's centre — and the
    pallor ``cup`` (0…1, the palest part 1), or a shallow stand-in when ``seen`` is False.

    The cup: brightness of green + blue (vessels closed out, smoothed) between the level of the
    rim and the brightest part of the disc.
    """
    small = cv2.resize(crop, (n, n), interpolation=cv2.INTER_AREA).astype(np.float32)
    rd = max(disc_frac * n / 2.0, 2.0)                         # disc radius (px)
    pale = 0.6 * small[..., 1] + 0.4 * small[..., 2]
    k = 2 * max(1, int(round(rd * 0.16))) + 1                   # wider than a vessel
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, kernel)
    smooth = cv2.GaussianBlur(closed, (0, 0), rd * 0.10)
    r = _radius(n, disc_frac)
    centre = ((n - 1) / 2.0, (n - 1) / 2.0)
    # the disc may sit a little off the picture's centre: measure from the pale patch itself
    w = np.clip(smooth - float(np.median(smooth)), 0.0, None) ** 2 * (r < 1.5)
    if float(w.sum()) > 0.0:
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        mx, my = float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())
        if math.hypot(mx - (n - 1) / 2.0, my - (n - 1) / 2.0) < 1.3 * rd:
            r = np.hypot(xx - mx, yy - my) / rd
            centre = (mx, my)
    ring = (r > 0.85) & (r < 1.3)
    inside = r < 0.75
    lo = float(np.median(smooth[ring])) if ring.any() else float(smooth.mean())
    hi = float(np.percentile(smooth[inside], 99.0)) if inside.any() else lo
    seen = hi - lo > 6.0
    if seen:                                                    # a pale cup stands out from the rim
        # the whole disc is paler than the retina, the cup paler still: deep only towards the palest
        # part, so that the rim slopes in and the cup is not the disc cut out
        cup = np.clip((smooth - lo) / (hi - lo), 0.0, 1.0) ** CUP_GAMMA
    else:                                                       # no cup to see: a shallow bowl
        cup = 0.35 * _smoothstep(1.0 - r / 0.45)
    return {"small": small, "rd": rd, "r": r, "centre": centre, "cup": cup, "seen": seen, "n": n}


def _pallor_depth(p: dict) -> np.ndarray:
    """The pallor as a hollow (0…1 down, 1 at the deepest where a cup was seen): only inside the
    disc, with walls that slope rather than a cliff."""
    cup, r, rd = p["cup"], p["r"], p["rd"]
    window = 1.0 - _smoothstep((r - 0.9) / 0.25)                # only inside the disc
    bowl = cv2.GaussianBlur(cup * window, (0, 0), rd * 0.09)    # walls that slope, not a cliff
    return bowl / max(float(bowl.max()), 0.5) * float((cup * window).max())


def _finish(H: np.ndarray, p: dict) -> np.ndarray:
    """The vessels on top of the surface ``H``, smoothed, flat at the picture's border."""
    n, rd = p["n"], p["rd"]
    g = p["small"][..., 1]
    vk = 2 * max(1, int(round(rd * 0.09))) + 1
    hat = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (vk, vk)))
    top = float(np.percentile(hat, 99.5))
    if top > 4.0:                                               # (below a sixth of the darkest: grain, not vessels)
        # as high all along a vessel, whatever its darkness from place to place: a rounded ridge, not beads
        H = H + VESSEL_H * cv2.GaussianBlur(_smoothstep((hat / top - 0.15) / 0.30), (0, 0), 1.4)
    H = cv2.GaussianBlur(H, (0, 0), max(0.8, rd * 0.035))
    return np.clip(H * _edge_taper(n), -1.0, 1.0).astype(np.float32)


def height_from_photo(crop: np.ndarray, disc_frac: float, n: int = 256, info: dict | None = None) -> np.ndarray:
    """Estimated heights (``n``², -1…1) of a square picture centred on the optic disc, whose
    disc is ``disc_frac`` of the picture's side across — from its brightness (밝기): the paler,
    the deeper. ``info`` (a dict) is told ``"cup"``: whether a pale cup was seen (False: the
    hollow is only a stand-in, nothing to measure).

    The cup: the pallor (``_pallor``). Around it the rim, and the vessels on top.
    """
    p = _pallor(crop, disc_frac, n)
    if info is not None:
        info["cup"] = p["seen"]
    H = -_pallor_depth(p) + RIM_H * np.exp(-((p["r"] - 1.0) / 0.3) ** 2)
    return _finish(H, p)


# -- one photo: the cup's margin where the vessels bend (혈관 꺾임) ---------------------------------
# A vessel on the disc lies on the tissue. Where the rim falls away into the cup it goes down the
# wall too, and seen from the front that stretch is foreshortened: the vessel seems to turn (or
# to step aside, "bayoneting") at the cup's margin. Those turns mark the margin whatever the colour
# — in glaucoma the hollow is often wider than the pale part. They say where the wall is, not how
# deep the floor lies.
METHODS = ("pallor", "vessels", "hybrid")    # one photo: 밝기 · 혈관 꺾임 · 하이브리드
BEND_DISC_PX = 170       # the disc's diameter (px) the vessels are traced at
BEND_TURN = 30.0         # a vessel turning more than this (degrees) over a short stretch is a bend
BEND_R = (0.25, 0.92)    # bends counted between these radii (disc radii): not the trunk, not the arcades
BEND_MIN_WEIGHT = 1.2    # fewer bends than this (weighted): no margin from the vessels
WALL = 0.20              # the cup's wall: this wide (disc radii), centred on the margin
FLOOR = 0.60             # the hollow at its margin's foot (of the deepest), the rest by the floor's shape


def _odd(x: float) -> int:
    return 2 * max(1, int(round(x / 2.0))) + 1


# the eight neighbours P2…P9 (N, NE, E, SE, S, SW, W, NW) of a pixel as the bits of one number
_NEIGHBOURS = np.float32([[128, 1, 2], [64, 0, 4], [32, 16, 8]])
_BITS = (np.arange(256)[:, None] >> np.arange(8)) & 1             # P2 … P9 of each number
_CROSSINGS = ((_BITS == 0) & (np.roll(_BITS, -1, axis=1) == 1)).sum(1)   # 0 → 1 going round


def _neighbour_code(img: np.ndarray) -> np.ndarray:
    return cv2.filter2D(img.astype(np.float32), -1, _NEIGHBOURS, borderType=cv2.BORDER_CONSTANT).astype(np.int32)


def _thin(mask: np.ndarray) -> np.ndarray:
    """Zhang–Suen thinning of a boolean mask: lines one pixel wide along its middle."""
    b = _BITS.sum(1)
    p2, p4, p6, p8 = _BITS[:, 0], _BITS[:, 2], _BITS[:, 4], _BITS[:, 6]
    base = (b >= 2) & (b <= 6) & (_CROSSINGS == 1)
    lut = (base & (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0),
           base & (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0))
    img = mask.astype(np.uint8)
    while True:
        changed = False
        for step in lut:
            gone = (img > 0) & step[_neighbour_code(img)]
            if gone.any():
                img[gone] = 0
                changed = True
        if not changed:
            return img > 0


_STEPS4 = ((0, 1), (1, 0), (0, -1), (-1, 0))
_STEPS8 = _STEPS4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _trace(ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """The pixels of one thin line in order along it (as (k, 2) x, y), from one end."""
    left = set(zip(ys.tolist(), xs.tolist()))
    def neighbours(p):
        return [(p[0] + dy, p[1] + dx) for dy, dx in _STEPS8 if (p[0] + dy, p[1] + dx) in left]
    start = next((p for p in left if len(neighbours(p)) == 1), next(iter(left)))
    path = [start]
    left.discard(start)
    while True:
        y, x = path[-1]
        nxt = next(((y + dy, x + dx) for dy, dx in _STEPS4 if (y + dy, x + dx) in left), None)
        if nxt is None:                                         # (a straight neighbour first: no corner skipped)
            nxt = next(((y + dy, x + dx) for dy, dx in _STEPS8 if (y + dy, x + dx) in left), None)
        if nxt is None:
            return np.float32([(x, y) for y, x in path])
        path.append(nxt)
        left.discard(nxt)


_BENDS_SEEN: dict = {}    # the last few ``find_bends`` (혈관 꺾임 and 하이브리드 ask for the same photo's)


def find_bends(crop: np.ndarray, disc_frac: float, centre: tuple[float, float] | None = None) -> dict:
    """``_find_bends``, remembered for the last few pictures."""
    key = (hashlib.blake2b(np.ascontiguousarray(crop).tobytes(), digest_size=16).digest(), crop.shape,
           round(float(disc_frac), 6), None if centre is None else (round(centre[0], 4), round(centre[1], 4)))
    if key not in _BENDS_SEEN:
        if len(_BENDS_SEEN) >= 8:
            _BENDS_SEEN.pop(next(iter(_BENDS_SEEN)))
        _BENDS_SEEN[key] = _find_bends(crop, disc_frac, centre)
    return _BENDS_SEEN[key]


def _find_bends(crop: np.ndarray, disc_frac: float, centre: tuple[float, float] | None = None) -> dict:
    """Where the vessels on the disc bend, in a square picture centred on the disc (``disc_frac``
    of its side across; the disc's ``centre`` as fractions of the side, the middle if None).

    Returns ``{"xy": (k, 2) as fractions of the side, "r": disc radii from the centre, "theta":
    radians (x right, y down), "turn": degrees, "weight", "vessels": how many vessels bend}``.
    One vessel can bend twice (down the wall, then onto the floor): its outermost bend — the top
    of the wall, the cup's margin — counts in full, the others a little.
    """
    m = int(np.clip(round(BEND_DISC_PX / max(disc_frac, 1e-3)), 128, 768))       # (a small disc: traced larger)
    img = cv2.resize(crop, (m, m), interpolation=cv2.INTER_AREA if m <= crop.shape[0] else cv2.INTER_CUBIC)
    rd = disc_frac * m / 2.0
    cx, cy = ((m - 1) / 2.0, (m - 1) / 2.0) if centre is None else (centre[0] * m, centre[1] * m)
    yy, xx = np.mgrid[0:m, 0:m].astype(np.float32)
    r = np.hypot(xx - cx, yy - cy) / max(rd, 1.0)
    k = _odd(0.26 * rd)                                         # wider than the widest vessel on the disc
    ball = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    def darker(ch: int) -> np.ndarray:
        """How much darker than around it (on the pale disc or not), in one colour."""
        g = img[..., ch].astype(np.float32)
        g = cv2.morphologyEx(g, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        g = cv2.GaussianBlur(g, (0, 0), 0.8)                    # (the light reflex along an artery, the grain)
        shut = cv2.morphologyEx(g, cv2.MORPH_CLOSE, ball)
        return (shut - g) / np.maximum(shut, 20.0)

    hat, red = darker(1), darker(0)
    # a vessel is dark in green but red in red; pigment (round the disc, in the rim) is dark in both
    roi = (r < 1.35) & (img.max(axis=2) > 20) & ~((red > 0.08) & (red > 0.5 * hat))
    empty = {"xy": np.zeros((0, 2), np.float32), "r": np.zeros(0), "theta": np.zeros(0), "turn": np.zeros(0),
             "weight": np.zeros(0), "vessels": 0}
    if roi.sum() < 50:
        return empty
    vals = hat[roi]
    level = max(0.05, float(np.percentile(vals, 82)), 0.22 * float(np.percentile(vals, 99.5)))
    # a faint stretch counts where it carries on from a clear one (a thin vessel on the pale cup)
    vessel = ((hat > 0.6 * level) & roi).astype(np.uint8)
    vessel = cv2.morphologyEx(vessel, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(vessel, connectivity=8)
    clear = np.zeros(count, bool)
    clear[np.unique(labels[(hat > level) & (vessel > 0)])] = True
    drop = (stats[:, cv2.CC_STAT_AREA] < max(12, 0.5 * rd)) | ~clear
    drop[0] = True
    vessel[drop[labels]] = 0
    if not vessel.any():
        return empty
    width = cv2.distanceTransform(vessel, cv2.DIST_L2, 3)       # half the vessel's width, inside it
    skel = _thin(vessel > 0)
    junction = skel & (_CROSSINGS[_neighbour_code(skel)] >= 3)  # three ways out: a branch or a crossing
    # a line bends where it meets another, whatever the depth: no bend counts near a branch
    off_junction = cv2.distanceTransform((~junction).astype(np.uint8), cv2.DIST_L2, 3)
    junction = cv2.dilate(junction.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    lines = (skel & ~junction).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    step = max(4, int(round(0.12 * rd)))                        # the stretch a turn is measured over
    order = np.argsort(labels.ravel(), kind="stable")
    starts = np.searchsorted(labels.ravel()[order], np.arange(count + 1))
    typical = float(np.median(width[skel])) if skel.any() else 1.0
    out = []
    vessels = 0
    shortest = max(2 * step + 3, int(round(0.45 * rd)))         # (a fleck of pigment, a stub: not a vessel)
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] < shortest:
            continue
        idx = order[starts[i]:starts[i + 1]]
        path = _trace(idx // m, idx % m)
        if len(path) < shortest or float(hat[idx // m, idx % m].mean()) < level:
            continue                                            # (a faint wandering line: grain, not a vessel)
        pad = np.pad(path, ((3, 3), (0, 0)), mode="edge")
        kern = np.exp(-0.5 * (np.arange(-3, 4) / 1.3) ** 2)
        kern /= kern.sum()
        sm = np.stack([np.convolve(pad[:, j], kern, mode="valid") for j in (0, 1)], axis=1)
        v1 = sm[step:-step] - sm[:-2 * step]
        v2 = sm[2 * step:] - sm[step:-step]
        l1, l2 = np.hypot(*v1.T), np.hypot(*v2.T)
        cosang = (v1 * v2).sum(1) / np.maximum(l1 * l2, 1e-6)
        turn = np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0)))
        turn[(l1 < 0.6 * step) | (l2 < 0.6 * step)] = 0.0
        found = []
        for j in range(len(turn)):
            lo, hi = max(0, j - step // 2), min(len(turn), j + step // 2 + 1)
            if turn[j] >= BEND_TURN and turn[j] == turn[lo:hi].max():
                x, y = sm[j + step]
                rr = math.hypot(x - cx, y - cy) / max(rd, 1.0)
                py, px = int(round(min(max(y, 0), m - 1))), int(round(min(max(x, 0), m - 1)))
                if BEND_R[0] <= rr <= BEND_R[1] and off_junction[py, px] >= 1.5 * step:
                    wv = float(width[py, px])
                    w = min(1.5, 0.3 + (turn[j] - BEND_TURN) / 30.0) * float(np.clip(math.sqrt(max(wv, 0.5) / max(typical, 0.5)), 0.5, 1.4))
                    found.append((x, y, rr, math.atan2(y - cy, x - cx), float(turn[j]), w))
        if found:
            vessels += 1
            outer = max(range(len(found)), key=lambda q: found[q][2])
            for q, f in enumerate(found):
                out.append((*f[:5], f[5] if q == outer else 0.35 * f[5]))
    if not out:
        return empty
    a = np.float64(out)
    return {"xy": (a[:, :2] / m).astype(np.float32), "r": a[:, 2], "theta": a[:, 3], "turn": a[:, 4],
            "weight": a[:, 5], "vessels": vessels}


def margin_from_bends(bends: dict, k: int = 360) -> tuple[np.ndarray, np.ndarray] | None:
    """The cup's margin through the bends: its radius (disc radii) at ``k`` angles round the disc
    (from +x towards +y), a smooth closed curve (a Fourier series to the second order, nearer a
    circle where the bends are few), and how well the bends back it there (0…1). None: too few
    bends to speak of. A bend far off the curve the others agree on is let go."""
    th, rr, w0 = bends["theta"], bends["r"], bends["weight"]
    if float(w0.sum()) < BEND_MIN_WEIGHT or bends["vessels"] < 2:
        return None
    def design(t):
        return np.stack([np.ones_like(t), np.cos(t), np.sin(t), np.cos(2 * t), np.sin(2 * t)], axis=1)
    A = design(th)
    ridge = np.diag([1e-6, 0.8, 0.8, 1.6, 1.6])                  # (few bends: nearer a circle)
    w = w0.copy()
    for _ in range(5):
        coef = np.linalg.solve(A.T @ (A * w[:, None]) + ridge, A.T @ (w * rr))
        res = rr - A @ coef
        s = max(0.06, 1.4826 * float(np.median(np.abs(res))))
        u = res / (3.5 * s)
        w = w0 * np.where(np.abs(u) < 1.0, (1.0 - u * u) ** 2, 0.0)
        if float(w.sum()) < 0.5 * BEND_MIN_WEIGHT:
            return None
    grid = np.linspace(0.0, 2.0 * math.pi, k, endpoint=False)
    radius = np.clip(design(grid) @ coef, 0.15, 0.97)
    gap = np.angle(np.exp(1j * (grid[:, None] - th[None, :])))  # (angle from each bend, -π…π)
    support = 1.0 - np.exp(-(w[None, :] * np.exp(-(gap / 0.45) ** 2)).sum(1) / 0.8)
    return radius.astype(np.float32), support.astype(np.float32)


def _polar(p: dict) -> np.ndarray:
    n = p["n"]
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    return np.arctan2(yy - p["centre"][1], xx - p["centre"][0])


def _around(values: np.ndarray, angle: np.ndarray) -> np.ndarray:
    """``values`` at ``len(values)`` angles round the disc, read at each pixel's ``angle``."""
    k = len(values)
    pos = (angle % (2.0 * math.pi)) / (2.0 * math.pi) * k
    i0 = np.floor(pos).astype(np.int32) % k
    t = pos - np.floor(pos)
    return (values[i0] * (1.0 - t) + values[(i0 + 1) % k] * t).astype(np.float32)


def _walled(p: dict, radius: np.ndarray, floor: np.ndarray) -> np.ndarray:
    """A hollow (0…1 down) whose wall is centred on the margin ``radius`` (at angles round the
    disc): ``FLOOR`` at the foot of the wall, the rest by ``floor`` (0…1) — so the margin lies
    at about ``CUP_LEVEL`` of the depth, where ``cup_from_surface`` reads it."""
    r = p["r"]
    edge = _around(radius, _polar(p))
    inside = _smoothstep((WALL / 2.0 - (r - edge)) / WALL)
    D = inside * (FLOOR + (1.0 - FLOOR) * np.clip(floor, 0.0, 1.0))
    return D / max(float(D.max()), 1e-6)


def height_from_vessels(crop: np.ndarray, disc_frac: float, n: int = 256, info: dict | None = None) -> np.ndarray:
    """Heights (``n``², -1…1) with the cup's margin where the vessels bend (혈관 꺾임) — the colour
    is not used. The floor is a plain bowl: the bends say where the wall is, not how deep.
    ``info`` is told ``"cup"`` (False: too few bends, the hollow is a stand-in), ``"bends"``
    (``find_bends``) and ``"support"`` (how much of the margin the bends back, 0…1)."""
    p = _pallor(crop, disc_frac, n)
    bends = find_bends(crop, disc_frac, (p["centre"][0] / n, p["centre"][1] / n))
    margin = margin_from_bends(bends)
    if margin is None:
        D = 0.35 * _smoothstep(1.0 - p["r"] / 0.45)
    else:
        edge = _around(margin[0], _polar(p))
        D = _walled(p, margin[0], 1.0 - (p["r"] / np.maximum(edge, 0.05)) ** 2)
    if info is not None:
        info.update(cup=margin is not None, bends=bends,
                    support=float(margin[1].mean()) if margin is not None else 0.0)
    inside = 1.0 - _smoothstep((p["r"] - 0.9) / 0.25) if margin is None else 1.0
    H = -D * inside + RIM_H * np.exp(-((p["r"] - 1.0) / 0.3) ** 2) * (1.0 - np.clip(D / FLOOR, 0.0, 1.0))
    return _finish(H, p)


def height_hybrid(crop: np.ndarray, disc_frac: float, n: int = 256, info: dict | None = None) -> np.ndarray:
    """Heights (``n``², -1…1) from both (하이브리드): where vessels bend, the cup's margin is there
    and its floor is shaped by the pallor (the paler, the deeper); round the rest of the disc, where
    no vessel says, the pallor alone (as ``height_from_photo``). No bends at all: the same as the
    brightness. ``info``: ``"cup"``, ``"bends"``, ``"support"`` as ``height_from_vessels``."""
    p = _pallor(crop, disc_frac, n)
    bends = find_bends(crop, disc_frac, (p["centre"][0] / n, p["centre"][1] / n))
    margin = margin_from_bends(bends)
    pale = _pallor_depth(p)
    if margin is None:
        D = pale
    else:
        radius, support = margin
        edge = _around(radius, _polar(p))
        hollow = 1.0 - (p["r"] / np.maximum(edge, 0.05)) ** 2
        if p["seen"]:
            within = _smoothstep((WALL / 2.0 - (p["r"] - edge)) / WALL) > 0.5
            top = float(pale[within].max()) if within.any() else 0.0
            floor = 0.5 * hollow + 0.5 * pale / top if top > 0.05 else hollow
            vessel_cup = _walled(p, radius, floor)
            c = _around(support, _polar(p))
            D = c * vessel_cup + (1.0 - c) * pale
        else:                                                   # no pallor to fall back on: the vessels'
            D = _walled(p, radius, hollow)
    if info is not None:
        info.update(cup=p["seen"] or margin is not None, bends=bends,
                    support=float(margin[1].mean()) if margin is not None else 0.0)
    H = -D + RIM_H * np.exp(-((p["r"] - 1.0) / 0.3) ** 2) * (1.0 - np.clip(D / FLOOR, 0.0, 1.0))
    if margin is None:                                          # (the same surface as the brightness)
        H = -D + RIM_H * np.exp(-((p["r"] - 1.0) / 0.3) ** 2)
    return _finish(H, p)


def height_one_photo(crop: np.ndarray, disc_frac: float, method: str = "pallor", n: int = 256,
                     info: dict | None = None) -> np.ndarray:
    """One photo's surface by ``method`` (``METHODS``): 밝기 · 혈관 꺾임 · 하이브리드."""
    if method == "vessels":
        return height_from_vessels(crop, disc_frac, n, info)
    if method == "hybrid":
        return height_hybrid(crop, disc_frac, n, info)
    return height_from_photo(crop, disc_frac, n, info)


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



STEREO_METHODS = ("parallax", "parallax_vessels")    # two photos: 시차 · 시차 + 혈관 꺾임


def merge_bends(*found: dict) -> dict:
    """The bends of several photos of one disc (registered onto each other) as one ``find_bends``:
    each photo's bends weigh ``1/len(found)`` — a bend both photos show counts in full, one only
    one of them shows by half — and ``vessels`` is the most any one photo has."""
    k = max(1, len(found))
    keep = [b for b in found if len(b["r"])]
    if not keep:
        return found[0] if found else _find_bends(np.zeros((8, 8, 3), np.uint8), 0.3)
    out = {key: np.concatenate([b[key] for b in keep]) for key in ("xy", "r", "theta", "turn", "weight")}
    out["weight"] = out["weight"] / k
    out["vessels"] = max(b["vessels"] for b in found)
    return out


def height_stereo_vessels(a: np.ndarray, b: np.ndarray, disc_frac: float, n: int = 256,
                          flip: bool = False) -> tuple[np.ndarray, dict]:
    """Two photos (시차 + 혈관 꺾임): the depth from their parallax (``height_from_stereo``), the cup's
    margin where the vessels bend (``find_bends`` in both photos, ``merge_bends``). Where vessels
    bend, the hollow's wall stands there and its floor follows the parallax; round the rest of the
    disc, and wherever the surface rises, the parallax alone. No bends, or no hollow in the parallax
    inside their margin (a raised disc, or 깊이 뒤집기): the parallax surface itself.
    Returns ``(heights, info)``: ``height_from_stereo``'s info with ``"bends"``, ``"support"`` and
    ``"no_hollow"`` (bends found, but the parallax shows nothing deep where they put the cup)."""
    H, info = height_from_stereo(a, b, disc_frac, n, flip)
    bends = merge_bends(find_bends(a, disc_frac), find_bends(b, disc_frac))
    margin = margin_from_bends(bends)
    info = {**info, "bends": bends, "support": float(margin[1].mean()) if margin is not None else 0.0,
            "no_hollow": False}
    if margin is None:
        return H, info
    radius, support = margin
    frame = {"n": n, "r": _radius(n, disc_frac), "centre": ((n - 1) / 2.0, (n - 1) / 2.0)}
    angle = _polar(frame)
    edge = _around(radius, angle)
    deep = np.clip(-H, 0.0, None)                               # the parallax's hollow (0…1 down)
    within = _smoothstep((WALL / 2.0 - (frame["r"] - edge)) / WALL) > 0.5
    top = float(deep[within].max()) if within.any() else 0.0
    if top < 0.2:                                               # the bends place the wall of a hollow the
        return H, {**info, "support": 0.0, "no_hollow": True}   # parallax shows — here it shows none
    hollow = 1.0 - (frame["r"] / np.maximum(edge, 0.05)) ** 2
    floor = 0.5 * hollow + 0.5 * deep / top
    walled = _walled(frame, radius, floor)
    c = _around(support, angle)
    # where the bends say: the parallax's hollow swapped for the walled one (what rises stays)
    out = H + c * (deep - walled)
    return np.clip(out * _edge_taper(n), -1.0, 1.0).astype(np.float32), info

CUP_LEVEL = 0.30         # the cup's margin: this part of the way down to its deepest point
MIN_CUP_DEPTH = 0.12     # a hollow shallower than this (of height 1) is no cup to measure


def outline_points(e: dict, k: int = 120) -> np.ndarray:
    """``k`` points round an outline (``glaucoma.curve``), as (k, 2) x, y — an ellipse or four quarter
    ellipses at even angles from +x towards +y, any other outline evenly along its length."""
    if "pts" not in e and "poly" not in e:
        return G._on_reach(e, np.linspace(0.0, 2.0 * math.pi, k, endpoint=False))
    p = G.curve(e)
    seg = np.hypot(*(np.roll(p, -1, axis=0) - p).T)
    at = np.concatenate([[0.0], np.cumsum(seg)])
    want = np.linspace(0.0, at[-1], k, endpoint=False)
    closed = np.vstack([p, p[:1]])
    return np.stack([np.interp(want, at, closed[:, 0]), np.interp(want, at, closed[:, 1])], axis=1)


CONTOUR_UP = 2           # lines of equal depth are traced on a grid this much finer than the surface


def _depths(H: np.ndarray, disc: dict) -> tuple[np.ndarray, tuple[int, int], float] | None:
    """The surface inside the ``disc`` outline (pixels of ``H``) on the finer grid (outside: +inf), its
    deepest point there and that depth — or None when no hollow there is deep enough to be a cup."""
    n = H.shape[0]
    m = n * CONTOUR_UP
    inside = np.zeros((m, m), np.uint8)
    pts = (G.curve(disc) + 0.5) * CONTOUR_UP - 0.5
    cv2.fillPoly(inside, [np.round(pts * 4).astype(np.int32)], 1, shift=2)
    if not inside.any():
        return None
    Hs = cv2.GaussianBlur(H, (0, 0), max(1.0, n / 200.0))        # (a vessel across the cup is not its margin)
    Hs = cv2.resize(Hs, (m, m), interpolation=cv2.INTER_CUBIC)
    deep = np.where(inside > 0, Hs, np.inf).astype(np.float32)
    iy, ix = np.unravel_index(int(np.argmin(deep)), deep.shape)
    bottom = float(deep[iy, ix])
    if bottom > -MIN_CUP_DEPTH:
        return None
    return deep, (int(iy), int(ix)), bottom


def _contour_at(deep: np.ndarray, at: tuple[int, int], bottom: float, level: float) -> np.ndarray | None:
    """The line where the hollow holding ``at`` is ``level`` of the way down to ``bottom``: (k, 2) points
    in pixels of the surface — traced half a grid step out (on the line, not just inside it), then evened
    out to a smooth closed line (``glaucoma.evened``)."""
    mask = (deep <= float(np.clip(level, 0.02, 0.98)) * bottom).astype(np.uint8)
    _, labels = cv2.connectedComponents(mask, connectivity=4)
    mask = (labels == labels[at]).astype(np.uint8)
    # a cup is a round hollow: a thin tongue running out of it (along a vessel, towards one bend) is not
    k = 2 * int(round(0.09 * math.sqrt(float(mask.sum())))) + 1
    if k >= 3:
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        if opened[at]:
            _, labels = cv2.connectedComponents(opened, connectivity=4)
            mask = (labels == labels[at]).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    p = max(contours, key=len).reshape(-1, 2).astype(np.float64)
    if len(p) >= 7:                                              # (the grid's stairs evened out)
        p = sum(np.roll(p, s, axis=0) for s in range(-2, 3)) / 5.0
    c = p.mean(axis=0)
    d = np.maximum(np.hypot(*(p - c).T), 1e-6)[:, None]
    p = p + (p - c) / d * 0.5                                    # (the pixels' edge, not their centres)
    p = (p + 0.5) / CONTOUR_UP - 0.5
    return G.evened(p).astype(np.float32)                         # (a smooth closed line: a cup's margin)


def cup_from_surface(H: np.ndarray, disc: dict, level: float = CUP_LEVEL) -> tuple[dict, np.ndarray] | None:
    """The cup read off the surface ``H`` along a line of equal depth (등고선): the hollow inside the
    ``disc`` outline (in pixels of ``H``) that lies deeper than ``level`` of the way from the retina's
    level down to the deepest point — the one piece of it that holds that point. Returns its outline
    (``{"poly": …}``, so that ``glaucoma.cdr_metrics`` takes it) and its margin as (k, 2) points, or None
    when there is no hollow to speak of.

    An estimate as good as the surface: from one photo that is the pale part of the disc, from a
    stereo pair the part the parallax puts deepest."""
    found = _depths(H, disc)
    if found is None:
        return None
    edge = _contour_at(*found, level)
    if edge is None or len(edge) < 3:
        return None
    return {"poly": edge.astype(np.float64)}, edge


CONTOUR_LEVELS = tuple(round(0.1 * i, 1) for i in range(1, 10))   # 등고선: every tenth of the way down


def depth_contours(H: np.ndarray, disc: dict, levels=CONTOUR_LEVELS) -> list:
    """The lines of equal depth of the hollow inside the ``disc`` outline (pixels of ``H``): ``[(level,
    (k, 2) points), …]`` for each ``level`` of the way down to the deepest point (the cup at ``level``
    is what ``cup_from_surface`` reads) — none when there is no hollow."""
    found = _depths(H, disc)
    if found is None:
        return []
    out = []
    for lv in levels:
        edge = _contour_at(*found, lv)
        if edge is not None and len(edge) >= 3:
            out.append((float(lv), edge))
    return out


def rotation(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """View rotation: yaw turns about the vertical axis, pitch about the horizontal one."""
    a, b = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = np.array([[math.cos(a), 0.0, math.sin(a)], [0.0, 1.0, 0.0], [-math.sin(a), 0.0, math.cos(a)]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(b), -math.sin(b)], [0.0, math.sin(b), math.cos(b)]])
    return rx @ ry


def shade(tex: np.ndarray, H: np.ndarray, depth_px: float, R: np.ndarray, strength: float = 1.0,
          contours: bool = False) -> np.ndarray:
    """The photo as it was taken, with the little the view adds: a slope turned towards the viewer is
    a touch lighter, one turned away a touch darker (and lines of equal height when ``contours``).

    The photo was lit along the camera's axis, and that light is in it already — a pale cup is pale,
    not a dark pit. So nothing is shaded from the front (the front view is the photo itself), and
    turned, only what the turn changes: as if the examiner's light went round with them. Kept within
    ``SHADE_RANGE``: the photo keeps its own colours.
    """
    n = tex.shape[0]
    Hf = cv2.resize(H, (n, n), interpolation=cv2.INTER_CUBIC) if H.shape[0] != n else H
    out = tex.astype(np.float32)
    if strength > 0.0 and depth_px > 0.0:
        z = cv2.GaussianBlur(Hf * depth_px, (0, 0), max(0.8, n / 256.0))
        gx = cv2.Sobel(z, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        gy = cv2.Sobel(z, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        v = R.T @ np.array([0.0, 0.0, 1.0])                      # towards the viewer, in the photo's frame
        if v[2] < MIN_VIEW_Z:                                    # turned far: as from MIN_VIEW_Z over the sheet
            xy = float(np.hypot(v[0], v[1]))
            v = np.array([v[0] / xy * math.sqrt(1.0 - MIN_VIEW_Z ** 2), v[1] / xy * math.sqrt(1.0 - MIN_VIEW_Z ** 2),
                          MIN_VIEW_Z])
        # how much more (or less) the surface faces the viewer than it faced the camera
        turn = -(gx * v[0] + gy * v[1]) / (float(v[2]) * np.sqrt(gx * gx + gy * gy + 1.0))
        out *= np.clip(1.0 + strength * SHADE * turn, *SHADE_RANGE)[..., None]
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
           background=(0, 0, 0), perspective: float = 0.0) -> np.ndarray:
    """The square photo ``tex`` on the surface ``H`` (heights -1…1, ``depth_px`` texture pixels
    for 1, towards the viewer) seen turned by ``yaw`` / ``pitch``, as an ``out_px``² RGB picture.

    Orthographic view of a height field: a point (x, y, h) lands at A·(x, y) + h·d, that is the
    photo's plane moved by ``h`` along one direction e = A⁻¹d, then the affine A. Turned so that
    e runs along the rows, each row is solved on its own: the first point (the highest one) whose
    moved place reaches a pixel is what is seen there.

    ``perspective``: the camera this many sides of the picture away (0: none, parallel rays) — the
    near side of the turned sheet is then larger than the far one, as a thing in front of the eye is.
    The sheet's own depth sets the size (the relief's height on it is small against the distance).
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
    if perspective > 0.0:                                       # a pixel of the camera's picture → where its
        zc = R[2, :2] @ Ainv                                    # ray meets the sheet, as the parallel view has it
        near = (perspective * n) / np.maximum(perspective * n + zc[0] * px + zc[1] * py, 1e-6)
        px, py = px * near, py * near
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
