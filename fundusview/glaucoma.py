"""Glaucoma analysis (녹내장 분석): the image work behind ``ui/glaucoma_dialog.py``.

* stereo (스테레오): register two photos of one disc (a shift), show them side by side, as a
  red–cyan anaglyph, or as a disparity (relative depth) map;
* disc (디스크 C/D): the disc's margin found in the photo, and from the two outlines (the disc's, the
  cup's — smooth lines through a few points) the cup-to-disc ratios, the rim all round (ISNT, the
  narrowest: DDLS) and what a disc of that size has (``docs/cd_ratio.md``: the method and its sources);
* wide field (광각): red-free with local contrast for the nerve fibre layer, the Garway-Heath
  sectors around the disc and the 24-2 visual field points laid on the fundus;
* progression (경과): blend and change map of two registered photos.

Images are RGB ``uint8``; points are image pixels (x right, y down). Every number is an
estimate for reference — depth is relative, not a length.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

MAX_SIDE = 900

# (name, from°, to°, matching visual field, RGB) — angles turn from temporal (0°) through superior
SECTORS = [
    ("이측", 311, 400, "중심부 (유두황반다발)", (232, 197, 71)),
    ("상이측", 41, 80, "하측 궁상 영역 · 비측 계단", (224, 86, 79)),
    ("상비측", 81, 120, "하측 주변부", (182, 120, 214)),
    ("비측", 121, 230, "이측 시야", (92, 180, 110)),
    ("하비측", 231, 270, "상측 주변부", (74, 163, 223)),
    ("하이측", 271, 310, "상측 궁상 영역 · 비측 계단", (240, 138, 60)),
]


def fit(img: np.ndarray, max_side: int = MAX_SIDE) -> np.ndarray:
    """A copy no longer than ``max_side`` on its long side (the analysis works on this)."""
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s >= 1.0:
        return img.copy()
    return cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


def fit_scale(shape, max_side: int = MAX_SIDE) -> float:
    """The factor ``fit`` shrinks an image of ``shape`` by."""
    return min(1.0, max_side / max(shape[0], shape[1]))


def crop_square(img: np.ndarray, cx: float, cy: float, side: float) -> tuple[np.ndarray, int, int]:
    """The square of ``side`` pixels centred on ``(cx, cy)`` (black outside the photo) and its
    top-left corner in the photo."""
    side = max(8, int(round(side)))
    x0, y0 = int(round(cx - side / 2.0)), int(round(cy - side / 2.0))
    out = np.asarray(Image.fromarray(img).crop((x0, y0, x0 + side, y0 + side)))
    return out, x0, y0


def match_size(img: np.ndarray, ref: np.ndarray) -> np.ndarray:
    h, w = ref.shape[:2]
    if img.shape[:2] == (h, w):
        return img
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img


# -- registration ------------------------------------------------------------------------------
def find_shift(a: np.ndarray, b: np.ndarray, max_frac: float = 0.12) -> tuple[float, float]:
    """``(dx, dy)`` that moves ``b`` onto ``a`` (a shift only — no rotation or scale)."""
    w = 360
    s = w / a.shape[1]
    h = max(8, round(a.shape[0] * s))
    ga = cv2.resize(_gray(a), (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    gb = cv2.resize(_gray(match_size(b, a)), (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    m = max(2, min(int(min(w, h) * max_frac), (min(w, h) - 16) // 2))
    res = cv2.matchTemplate(ga, gb[m:h - m, m:w - m], cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(res)
    return round((loc[0] - m) / s * 2) / 2, round((loc[1] - m) / s * 2) / 2


def shifted(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h))


def find_turn(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float, float] | None:
    """``(angle°, scale, dx, dy)`` that lays ``b`` onto ``a`` — a turn and a size about the centre of the
    frame, then a shift — from vessel points matched between the two (SIFT, RANSAC). Two photos of one
    eye taken from slightly different places differ by more than a shift; what this leaves moving is
    mostly depth (the cup against the rim). None when too few points agree, or the answer is not a
    small turn (then ``find_shift``)."""
    if cv2 is None or not hasattr(cv2, "SIFT_create"):
        return None
    b = match_size(b, a)
    h, w = a.shape[:2]
    k = min(1.0, 900 / max(h, w))

    def prep(img):
        g = img[..., 1] if img.ndim == 3 else img
        g = cv2.resize(g, (max(8, round(w * k)), max(8, round(h * k))), interpolation=cv2.INTER_AREA)
        return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(g), (g > 12).astype(np.uint8)

    (ga, ma), (gb, mb) = prep(a), prep(b)
    sift = cv2.SIFT_create(2500)
    ka, da = sift.detectAndCompute(ga, ma)
    kb, db = sift.detectAndCompute(gb, mb)
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return None
    pairs = cv2.BFMatcher().knnMatch(db, da, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.8 * n.distance]
    if len(good) < 10:
        return None
    pb = np.float32([kb[m.queryIdx].pt for m in good]) / k
    pa = np.float32([ka[m.trainIdx].pt for m in good]) / k
    M, inl = cv2.estimateAffinePartial2D(pb, pa, method=cv2.RANSAC, ransacReprojThreshold=3.0 / k)
    if M is None or inl is None or int(inl.sum()) < 10:
        return None
    alpha, beta = float(M[0, 0]), float(M[0, 1])
    angle, scale = math.degrees(math.atan2(beta, alpha)), math.hypot(alpha, beta)
    if not (0.85 < scale < 1.18 and abs(angle) < 15.0):
        return None
    R = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale)
    return angle, scale, float(M[0, 2] - R[0, 2]), float(M[1, 2] - R[1, 2])


def turned(img: np.ndarray, angle: float, scale: float, dx: float, dy: float) -> np.ndarray:
    """``img`` turned by ``angle``° and sized by ``scale`` about its centre, then shifted (``find_turn``)."""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale)
    M[:, 2] += (dx, dy)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR)


def match_point(a: np.ndarray, b: np.ndarray, x: float, y: float, patch: int = 36,
                search: int = 40) -> tuple[float, float] | None:
    """The shift that lays ``b``'s picture at (``x``, ``y``) exactly onto ``a``'s — the patch of ``a`` round
    the point looked for in ``b`` nearby (to a tenth of a pixel). None where there is nothing to go by
    (an even patch, outside the photo) or no clear match."""
    ga = (a[..., 1] if a.ndim == 3 else a).astype(np.float32)
    gb = (b[..., 1] if b.ndim == 3 else b).astype(np.float32)
    h, w = ga.shape
    x0, y0 = int(round(x)), int(round(y))
    if not (patch <= x0 < w - patch and patch <= y0 < h - patch):
        return None
    tpl = ga[y0 - patch:y0 + patch + 1, x0 - patch:x0 + patch + 1]
    if float(tpl.std()) < 2.0:
        return None
    s = min(search, x0 - patch, y0 - patch, w - patch - 1 - x0, h - patch - 1 - y0)
    if s < 3:
        return None
    win = gb[y0 - patch - s:y0 + patch + s + 1, x0 - patch - s:x0 + patch + s + 1]
    res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
    _, best, _, (lx, ly) = cv2.minMaxLoc(res)
    if best < 0.4:
        return None

    def peak(c, i, n):                                   # (a parabola through the peak and its neighbours)
        if 0 < i < n - 1:
            l, m, r = float(c[i - 1]), float(c[i]), float(c[i + 1])
            d = l - 2 * m + r
            return i + (0.5 * (l - r) / d if abs(d) > 1e-9 else 0.0)
        return float(i)

    fx, fy = peak(res[ly, :], lx, res.shape[1]), peak(res[:, lx], ly, res.shape[0])
    return round(s - fx, 2), round(s - fy, 2)


# -- stereo --------------------------------------------------------------------------------------
def side_by_side(left: np.ndarray, right: np.ndarray, gap: int = 10) -> np.ndarray:
    h, w = left.shape[:2]
    out = np.zeros((h, 2 * w + gap, 3), np.uint8)
    out[:, :w] = left
    out[:, w + gap:] = match_size(right, left)
    return out


def anaglyph(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """For red–cyan glasses: the left eye's photo in red, the right eye's in cyan."""
    gl, gr = _gray(left), _gray(match_size(right, left))
    return cv2.merge([gl, gr, gr])


def disparity(left: np.ndarray, right: np.ndarray, width: int = 200, max_d: int = 10) -> np.ndarray:
    """Disparity map at ``width`` pixels across. Positive = deep (the cup), negative = raised."""
    s = width / left.shape[1]
    h = max(8, round(left.shape[0] * s))
    a = cv2.resize(_gray(left), (width, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(_gray(match_size(right, left)), (width, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    best = np.full((h, width), np.inf, np.float32)
    disp = np.zeros((h, width), np.float32)
    for d in range(-max_d, max_d + 1):
        diff = np.full((h, width), 40.0, np.float32)
        if d >= 0:
            diff[:, :width - d] = np.abs(a[:, :width - d] - b[:, d:])
        else:
            diff[:, -d:] = np.abs(a[:, -d:] - b[:, :width + d])
        cost = cv2.blur(diff, (9, 9)) + abs(d) * 0.15
        better = cost < best
        best[better] = cost[better]
        disp[better] = d
    for _ in range(3):
        disp = cv2.blur(disp, (7, 7))
    return disp


def disparity_range(disp: np.ndarray, image_width: int) -> tuple[float, float]:
    """``(deepest, most raised)`` disparity away from the edges, in pixels of the photo."""
    m = min(14, disp.shape[0] // 4, disp.shape[1] // 4)
    core = disp[m:disp.shape[0] - m, m:disp.shape[1] - m]
    k = image_width / disp.shape[1]
    return float(core.max()) * k, float(core.min()) * k


def depth_overlay(left: np.ndarray, disp: np.ndarray) -> np.ndarray:
    """The photo tinted blue where it is deep and red where it is raised."""
    h, w = left.shape[:2]
    scale = max(2.0, float(np.abs(disp).max()))
    v = cv2.resize(disp / scale, (w, h), interpolation=cv2.INTER_LINEAR)
    alpha = (np.clip(np.abs(v), 0, 1) * (200 / 255))[..., None]
    color = np.where(v[..., None] > 0, np.float32([30, 120, 255]), np.float32([255, 70, 40]))
    return (left.astype(np.float32) * (1 - alpha) + color * alpha).astype(np.uint8)


def depth_profile(disp: np.ndarray, y: float, image_h: int, width: int, height: int = 120) -> np.ndarray:
    """The depth along the row at ``y`` as a graph (deeper is lower)."""
    out = np.full((height, width, 3), (15, 18, 21), np.uint8)
    row = int(np.clip(round(y * disp.shape[0] / image_h), 0, disp.shape[0] - 1))
    scale = max(2.0, float(np.abs(disp).max()))
    zero = 34
    cv2.line(out, (0, zero), (width, zero), (58, 67, 75), 1)
    xs = (np.arange(disp.shape[1]) + 0.5) * width / disp.shape[1]
    ys = zero + disp[row] * (70 / scale)
    pts = np.stack([xs, ys], 1).round().astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(out, [pts], False, (108, 192, 255), 2, cv2.LINE_AA)
    return out


# -- disc: cup-to-disc ratio -----------------------------------------------------------------------
# An outline (the disc's margin, the cup's) is one of
#   {"pts": [[x, y], …]}   points in order round it — the outline is the smooth closed curve through
#                          them (the C/D tab: ``RING`` points, each moved on its own);
#   {"poly": [[x, y], …]}  a traced outline, taken as it is (a line of equal depth: ``disc3d``);
#   {"cx", "cy", "rx", "ry"} an ellipse, or {"cx", "cy", "top", "right", "bottom", "left"} four
#                          quarter ellipses (its reach up · right · down · left from the centre).
# Image pixels, x right, y down. The photo is upright: the right eye's nasal side is on the right.
RING = 8                                         # points round an outline in the C/D tab
RING_DEG = tuple(-90.0 + 45.0 * i for i in range(RING))   # their directions: up first, then clockwise
CURVE_PER = 24                                   # points of the drawn curve between two of them
RIM_NAMES = {"S": "상측", "I": "하측", "N": "비측", "T": "이측",
             "SN": "상비측", "ST": "상이측", "IN": "하비측", "IT": "하이측"}


def ring_names(eye: str | None = "OD") -> tuple:
    """The anatomical name of each of the ``RING`` directions (up, up-right, right, …): the right eye's
    nasal side is on the right of the photo, the left eye's on the left."""
    r, l = ("T", "N") if eye == "OS" else ("N", "T")
    return ("S", "S" + r, r, "I" + r, "I", "I" + l, l, "S" + l)


def _closed_spline(p: np.ndarray, per: int = CURVE_PER) -> np.ndarray:
    """The smooth closed curve through the points ``p`` (k, 2) in order: a periodic cubic spline over
    the chord lengths (no loops where two points lie close), ``per`` points from each to the next."""
    k = len(p)
    if k < 3:
        return p.copy()
    nxt = np.roll(p, -1, axis=0)
    h = np.maximum(np.hypot(*(nxt - p).T), 1e-3)                # chord i → i+1
    hp = np.roll(h, 1)                                          # chord i-1 → i
    a = np.zeros((k, k))
    i = np.arange(k)
    np.add.at(a, (i, (i - 1) % k), hp)
    np.add.at(a, (i, i), 2.0 * (hp + h))
    np.add.at(a, (i, (i + 1) % k), h)
    rhs = 6.0 * ((nxt - p) / h[:, None] - (p - np.roll(p, 1, axis=0)) / hp[:, None])
    m = np.linalg.solve(a, rhs)                                 # the second derivatives at the points
    b = (np.arange(per) / per)[None, :, None]                   # (k, per, 1): the way from i to i+1
    aa = 1.0 - b
    hh = h[:, None, None]
    out = (aa * p[:, None] + b * nxt[:, None]
           + ((aa ** 3 - aa) * m[:, None] + (b ** 3 - b) * np.roll(m, -1, axis=0)[:, None]) * hh * hh / 6.0)
    return out.reshape(-1, 2)


def _reach_dict(e: dict) -> tuple[float, ...]:
    if "top" in e:
        return tuple(float(e[k]) for k in ("cx", "cy", "top", "right", "bottom", "left"))
    return float(e["cx"]), float(e["cy"]), float(e["ry"]), float(e["rx"]), float(e["ry"]), float(e["rx"])


def _on_reach(e: dict, ang: np.ndarray) -> np.ndarray:
    """Points of an ellipse / four quarter ellipses at the parametric angles ``ang`` (from +x towards +y)."""
    cx, cy, t, r, b, l = _reach_dict(e)
    c, s = np.cos(ang), np.sin(ang)
    return np.stack([cx + np.where(c >= 0, r, l) * c, cy + np.where(s >= 0, b, t) * s], axis=1)


def curve(e: dict, per: int = CURVE_PER) -> np.ndarray:
    """An outline as a closed polygon (k, 2) — dense enough to draw and to measure."""
    if "poly" in e:
        return np.asarray(e["poly"], np.float64).reshape(-1, 2)
    if "pts" in e:
        return _closed_spline(np.asarray(e["pts"], np.float64).reshape(-1, 2), per)
    return _on_reach(e, np.linspace(0.0, 2.0 * math.pi, 192, endpoint=False))


def area(e: dict) -> float:
    """The area an outline encloses (px²)."""
    p = curve(e)
    x, y = p[:, 0], p[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))) / 2.0


def centre(e: dict) -> tuple[float, float]:
    """The middle of an outline: the centre of the area it encloses."""
    p = curve(e)
    x, y = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    a = float(cross.sum()) / 2.0
    if abs(a) < 1e-9:
        return float(x.mean()), float(y.mean())
    return float(((x + x1) * cross).sum() / (6.0 * a)), float(((y + y1) * cross).sum() / (6.0 * a))


def reaches(poly: np.ndarray, origin, angles) -> np.ndarray:
    """How far the rays from ``origin`` at ``angles`` (radians, x right, y down) run to the outermost
    place each crosses the closed polygon — 0 where one does not cross it."""
    p = np.asarray(poly, np.float64)
    q = np.roll(p, -1, axis=0) - p                              # (E, 2) edges
    a = np.atleast_1d(np.asarray(angles, np.float64))
    dx, dy = np.cos(a)[:, None], np.sin(a)[:, None]             # (A, 1)
    w = p - np.asarray(origin, np.float64)
    den = dx * q[None, :, 1] - dy * q[None, :, 0]               # (A, E)
    ok = np.abs(den) > 1e-12
    den = np.where(ok, den, 1.0)
    t = (w[:, 0] * q[:, 1] - w[:, 1] * q[:, 0])[None, :] / den  # along the ray
    s = (w[None, :, 0] * dy - w[None, :, 1] * dx) / den         # along the edge
    hit = ok & (t >= 0) & (s >= -1e-9) & (s <= 1 + 1e-9)
    return np.where(hit, t, 0.0).max(axis=1)


def reach(poly: np.ndarray, origin, angle: float) -> float:
    """``reaches`` for one ray."""
    return float(reaches(poly, origin, [angle])[0])


def _harmonics(t: np.ndarray, order: int) -> np.ndarray:
    cols = [np.ones_like(t)]
    for h in range(1, order + 1):
        cols += [np.cos(h * t), np.sin(h * t)]
    return np.stack(cols, axis=1)


def evened(poly: np.ndarray) -> np.ndarray:
    """A traced outline evened out to a smooth closed line (192 points) round its middle: an oval — an
    ellipse comes back as it is, whichever way it is turned — that may lean to one side (by half). A
    cup's margin is a smooth line: a narrow tongue of the traced one (along a vessel, towards one bend)
    or a corner does not stand as drawn (the cup is drawn as a smooth line through its marks: Joshi et
    al., IEEE TMI 2011).

    Fitted to 1 / reach² over the angle — an ellipse's is exactly its second harmonic — each angle
    weighed so that what is made small is the miss in the reach itself."""
    p = np.asarray(poly, np.float64).reshape(-1, 2)
    c = centre({"poly": p})
    ang = np.linspace(0.0, 2.0 * math.pi, 180, endpoint=False)
    r = reaches(p, c, ang)
    ok = r > 0
    if int(ok.sum()) < 16:
        return p
    scale = float(r[ok].mean())
    rho = r[ok] / scale
    lo, hi = 1.0 / (1.5 * float(rho.max())) ** 2, 1.0 / (0.5 * float(rho.min())) ** 2
    a = _harmonics(ang[ok], 3)
    w2 = np.ones_like(rho)
    for _ in range(4):                                          # (d(1/ρ²) = −2 dρ / ρ³, ρ the line's own reach)
        lean = [0.0] * 5 + [0.5 * float(w2.sum())] * 2          # the third harmonic: by half (no corners)
        coef = np.linalg.solve(a.T @ (a * w2[:, None]) + np.diag(lean), a.T @ (w2 / rho ** 2))
        w2 = np.clip(a @ coef, lo, hi) ** -3.0
    fine = np.linspace(0.0, 2.0 * math.pi, 192, endpoint=False)
    rf = scale / np.sqrt(np.clip(_harmonics(fine, 3) @ coef, lo, hi))
    return np.stack([c[0] + rf * np.cos(fine), c[1] + rf * np.sin(fine)], axis=1)


def _ring_of_poly(poly: np.ndarray, k: int = RING) -> np.ndarray:
    """``k`` points on a traced outline, in the ``RING`` directions from its middle — the up, down, left
    and right ones (k = 8) at its top, bottom and sides where those lie near their direction, so that
    the curve through the points is as tall and as wide as the outline."""
    c = centre({"poly": poly})
    degs = RING_DEG if k == RING else tuple(-90.0 + 360.0 * i / k for i in range(k))
    out = np.array([[c[0] + reach(poly, c, math.radians(a)) * math.cos(math.radians(a)),
                     c[1] + reach(poly, c, math.radians(a)) * math.sin(math.radians(a))] for a in degs])
    if k == RING:
        for i, axis, pick in ((0, 1, np.argmin), (4, 1, np.argmax), (2, 0, np.argmax), (6, 0, np.argmin)):
            q = poly[int(pick(poly[:, axis]))]
            off = math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])) - RING_DEG[i]
            if abs((off + 180.0) % 360.0 - 180.0) < 35.0:
                out[i] = q
    return out


def ring(e: dict, k: int = RING) -> np.ndarray:
    """The ``k`` points (k, 2) of an outline as the C/D tab moves them: up first, then clockwise."""
    if "pts" in e and len(e["pts"]) == k:
        return np.asarray(e["pts"], np.float64).reshape(-1, 2).copy()
    if "pts" in e or "poly" in e:
        return _ring_of_poly(curve(e), k)
    return _on_reach(e, np.radians(np.asarray(RING_DEG if k == RING else
                                               [-90.0 + 360.0 * i / k for i in range(k)])))


def moved(e: dict, scale: float, dx: float = 0.0, dy: float = 0.0) -> dict:
    """The outline with every point p taken to ``p · scale + (dx, dy)`` (another picture's pixels)."""
    for key in ("pts", "poly"):
        if key in e:
            return {key: np.asarray(e[key], np.float64).reshape(-1, 2) * scale + (dx, dy)}
    cx, cy, t, r, b, l = _reach_dict(e)
    return {"cx": cx * scale + dx, "cy": cy * scale + dy, "top": t * scale, "right": r * scale,
            "bottom": b * scale, "left": l * scale}


RIM_STEP_DEG = 1             # the rim is measured round the whole disc every so many degrees
RIM_ABSENT = 0.005           # a rim narrower than this (of the disc's diameter there) is no rim
DISC_SMALL_MM, DISC_LARGE_MM = 1.5, 2.0      # DDLS: a small disc is below, a large one above


def expected_cdr(disc_mm: float) -> float:
    """The mean vertical C/D of normal eyes with a disc ``disc_mm`` tall: a large disc has a large
    cup. Garway-Heath et al., Br J Ophthalmol 1998;82:1118 — vertical cup diameter regressed on
    vertical disc diameter in 88 normal eyes (stereo planimetry): CDR = (−1.31 + 1.194 · DD) / DD,
    R² = 0.42 (the scatter round it is wide: a guide, not a limit)."""
    return float(np.clip((-1.31 + 1.194 * disc_mm) / max(disc_mm, 1e-6), 0.0, 1.0))


def ddls_stage(rim_disc: float, absent_deg: float, disc_mm: float | None = None) -> int:
    """Disc Damage Likelihood Scale (Spaeth et al. 2002), 1…10, from the narrowest rim: its width as a
    part of the disc's diameter along the same meridian (``rim_disc``), or — where there is no rim —
    how much of the disc's circumference is without one (``absent_deg``). The nomogram for a disc of
    average size (1.5–2.0 mm); a small disc (< 1.5 mm) is one stage up, a large one (> 2.0 mm) one
    stage down. ``disc_mm`` None: taken as average."""
    if absent_deg > 0:
        stage = 6 if absent_deg < 45 else 7 if absent_deg <= 90 else 8 if absent_deg <= 180 \
            else 9 if absent_deg <= 270 else 10
    else:
        stage = 1 if rim_disc >= 0.4 else 2 if rim_disc >= 0.3 else 3 if rim_disc >= 0.2 \
            else 4 if rim_disc >= 0.1 else 5
    if disc_mm is not None:
        stage += 1 if disc_mm < DISC_SMALL_MM else -1 if disc_mm > DISC_LARGE_MM else 0
    return int(min(10, max(1, stage)))


def cdr_metrics(disc: dict, cup: dict, eye: str = "OD", disc_mm: float | None = None) -> dict:
    """C/D of two outlines, as planimetry measures it: ``vertical`` and ``horizontal`` — the cup's
    height · width over the disc's — and ``area``; ``rim``: the rim width in each of the ``RING``
    directions from the disc's middle (the disc margin less the cup's, as a fraction of the vertical
    disc diameter DD; negative: the cup reaches past the margin); ``isnt``: where the I ≥ S ≥ N ≥ T
    order is broken; ``thinnest``: the narrowest of those eight.

    ``narrow``: the narrowest rim round the whole disc — ``ratio`` (its width over the disc's diameter
    along the same meridian: DDLS's rim/disc ratio), ``name`` (the nearest of the eight directions),
    ``hour`` (clock hour as the photo is seen: 12 up, 3 right) and ``absent`` (degrees of the
    circumference with no rim) — and ``ddls``, its stage (``ddls_stage``; ``disc_mm``: the vertical
    disc diameter in mm where the photo's scale is known). ``dd``: the vertical disc diameter (px)."""
    d, c = curve(disc), curve(cup)
    dd = max(float(np.ptp(d[:, 1])), 1e-6)
    o = centre({"poly": d})
    names = ring_names(eye)
    ang = np.radians(np.arange(0.0, 360.0, RIM_STEP_DEG))       # (x right, y down: 0 = right, 90 = down)
    rd, rc = reaches(d, o, ang), reaches(c, o, ang)
    eight = np.round((np.asarray(RING_DEG) % 360.0) / RIM_STEP_DEG).astype(int) % len(ang)
    rim = {name: float(rd[i] - rc[i]) / dd for name, i in zip(names, eight)}
    bad = []
    if rim["I"] < rim["S"]:
        bad.append("하측 림이 상측보다 얇음")
    if rim["S"] < rim["N"]:
        bad.append("상측 림이 비측보다 얇음")
    if rim["N"] < rim["T"]:
        bad.append("비측 림이 이측보다 얇음")
    across = np.maximum(rd + np.roll(rd, len(ang) // 2), 1e-6)  # the disc's diameter along each meridian
    part = (rd - rc) / across
    i = int(np.argmin(part))
    deg = float(np.degrees(ang[i]))
    absent = float((part <= RIM_ABSENT).sum() * RIM_STEP_DEG)
    narrow = {"ratio": max(0.0, float(part[i])), "deg": deg, "name": names[int(round((deg + 90.0) / 45.0)) % RING],
              "hour": int(round((deg + 90.0) / 30.0)) % 12 or 12, "absent": absent}
    return {"vertical": float(np.ptp(c[:, 1])) / dd,
            "horizontal": float(np.ptp(c[:, 0])) / max(float(np.ptp(d[:, 0])), 1e-6),
            "area": area({"poly": c}) / max(area({"poly": d}), 1e-6), "rim": rim, "isnt": bad,
            "thinnest": min(rim, key=rim.get), "narrow": narrow,
            "ddls": ddls_stage(narrow["ratio"], absent, disc_mm), "dd": dd}


# -- disc: its margin found in the photo ---------------------------------------------------------------
DISC_SEARCH = (0.45, 1.75)   # the margin is looked for between these radii (of the disc expected)
DISC_MIN_EDGE = 0.22         # less than this (of the clearest edge) along the margin: not found


def _odd(x: float) -> int:
    return 2 * max(1, int(round(x / 2.0))) + 1


def find_disc_margin(img: np.ndarray, disc_frac: float, k: int = RING) -> dict | None:
    """The optic disc's margin in a square picture cut round the disc (expected ``disc_frac`` of the
    picture's side across, from the camera — a real disc is often larger or smaller): ``{"pts": (k, 2)
    picture pixels, "centre", "confidence": 0…1}``, or None where no margin stands out.

    The margin is where the brightness falls from the pale rim to the darker retina: the vessels closed
    out, the picture unrolled round the bright patch's middle, and one closed line through the falls
    that turns smoothly (a path found round all the angles at once), then evened out (a few harmonics).
    An estimate — a pale ring of atrophy round the disc can be taken for it."""
    n = 256
    side = float(img.shape[0])
    sm = cv2.resize(img, (n, n), interpolation=cv2.INTER_AREA).astype(np.float32)
    rd = max(disc_frac * n / 2.0, 4.0)
    lum = 0.7 * sm[..., 0] + 0.3 * sm[..., 1]                   # mostly red: the disc against the retina (in
    #                                                             green the cup stands out more than the disc)
    lum = cv2.morphologyEx(lum, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(0.3 * rd),) * 2))
    lum = cv2.GaussianBlur(lum, (0, 0), max(1.0, 0.05 * rd))
    lit = cv2.erode((sm.max(axis=2) > 18).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    cx = cy = (n - 1) / 2.0
    around = lit & (np.hypot(xx - cx, yy - cy) < 2.5 * rd)
    if around.sum() < 20:
        return None
    base = float(np.median(lum[around]))
    for _ in range(8):                                          # the middle of the bright patch near here
        near = lit & (np.hypot(xx - cx, yy - cy) < 1.3 * rd)
        w = np.clip(lum - base, 0.0, None) ** 2 * near
        if near.sum() < 20 or float(w.sum()) <= 0.0:
            return None
        nx, ny = float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())
        if math.hypot(nx - (n - 1) / 2.0, ny - (n - 1) / 2.0) > 1.5 * rd:
            break
        done = math.hypot(nx - cx, ny - cy) < 0.5
        cx, cy = nx, ny
        if done:
            break
    found = None
    for _ in range(2):                                          # (again from the middle of what was found)
        got = _margin_round(lum, lit, cx, cy, rd)
        if got is None:
            break
        found = got
        mx, my = centre({"poly": got[0]})
        if math.hypot(mx - cx, my - cy) < 0.08 * rd:
            break
        cx, cy = mx, my
    if found is None:
        return None
    poly, confidence = found
    k_px = side / n
    poly = (poly + 0.5) * k_px - 0.5
    return {"pts": _ring_of_poly(poly, k), "centre": ((cx + 0.5) * k_px - 0.5, (cy + 0.5) * k_px - 0.5),
            "confidence": confidence}


def _margin_round(lum: np.ndarray, lit: np.ndarray, cx: float, cy: float, rd: float):
    """``find_disc_margin`` from the middle (``cx``, ``cy``): ``(closed polygon, confidence)`` or None."""
    na, nr = 96, 72
    ang = np.linspace(0.0, 2.0 * math.pi, na, endpoint=False)
    rad = np.linspace(DISC_SEARCH[0] * rd, DISC_SEARCH[1] * rd, nr)
    mx = (cx + rad[None, :] * np.cos(ang)[:, None]).astype(np.float32)
    my = (cy + rad[None, :] * np.sin(ang)[:, None]).astype(np.float32)
    prof = cv2.remap(lum, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    seen = cv2.remap(lit.astype(np.float32), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT) > 0.5
    # the fall from the pale disc to the retina: a sharp step, and the disc paler than what lies past it
    # (the step from the cup to the rim is sharp too, but the rim past it is still pale)
    dr = rad[1] - rad[0]
    wide = max(3, int(round(0.3 * rd / dr)))
    cs = np.concatenate([np.zeros((na, 1), np.float32), np.cumsum(prof, axis=1)], axis=1)
    j = np.arange(nr)
    lo, hi = np.clip(j - wide, 0, nr), np.clip(j + wide, 0, nr)
    inner = (cs[:, j] - cs[:, lo]) / np.maximum(j - lo, 1)
    outer = (cs[:, hi] - cs[:, j]) / np.maximum(hi - j, 1)
    level = np.maximum(prof, 25.0)                              # (relative: any exposure)
    sharp = np.zeros_like(prof)
    sharp[:, 2:-2] = (prof[:, :-4] - prof[:, 4:]) / level[:, 2:-2]
    broad = (inner - outer) / level
    tops = []
    for f in (sharp, broad):
        f = np.clip(f, 0.0, None) * seen
        f = (np.roll(f, 1, axis=0) + 2.0 * f + np.roll(f, -1, axis=0)) / 4.0       # (along the angle)
        top = float(np.percentile(f, 99.5))
        if top <= 1e-4:
            return None
        tops.append(np.clip(f / top, 0.0, 1.0))
    score = np.sqrt(tops[0] * tops[1])
    rr = rad / rd                                               # a mild pull towards the size expected
    score = score * (0.65 + 0.35 * np.exp(-((rr - 1.0) / 0.45) ** 2))[None, :]
    # one line round all the angles: three turns, the middle one kept (so that it closes)
    jump, pen = 2, 0.06
    s3 = np.tile(score, (3, 1))
    cost = np.empty_like(s3)
    back = np.zeros(s3.shape, np.int32)
    cost[0] = -s3[0]
    for i in range(1, len(s3)):
        best = np.full(nr, np.inf, np.float32)
        arg = np.zeros(nr, np.int32)
        for dj in range(-jump, jump + 1):
            src = np.clip(j - dj, 0, nr - 1)
            c = cost[i - 1][src] + pen * abs(dj)
            better = c < best
            best[better], arg[better] = c[better], src[better]
        cost[i], back[i] = best - s3[i], arg
    path = np.zeros(len(s3), np.int32)
    path[-1] = int(np.argmin(cost[-1]))
    for i in range(len(s3) - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    jj = path[na:2 * na]
    r_found = rad[jj]
    strength = score[np.arange(na), jj]
    confidence = float(np.median(strength))
    if confidence < DISC_MIN_EDGE:
        return None
    # even it out: a few harmonics, the angles whose fall is weak or far off the rest let go
    a = _harmonics(ang, 3)
    w0 = np.maximum(strength, 0.02)
    w = w0.copy()
    ridge = np.diag([1e-6, 0.5, 0.5, 1.0, 1.0, 3.0, 3.0])
    coef = np.zeros(7)
    for _ in range(5):
        coef = np.linalg.solve(a.T @ (a * w[:, None]) + ridge, a.T @ (w * r_found))
        res = r_found - a @ coef
        s = max(0.04 * rd, 1.4826 * float(np.median(np.abs(res))))
        u = res / (3.0 * s)
        w = w0 * np.where(np.abs(u) < 1.0, (1.0 - u * u) ** 2, 0.0)
    fine = np.linspace(0.0, 2.0 * math.pi, 192, endpoint=False)
    rf = np.clip(_harmonics(fine, 3) @ coef, DISC_SEARCH[0] * rd, DISC_SEARCH[1] * rd)
    return np.stack([cx + rf * np.cos(fine), cy + rf * np.sin(fine)], axis=1), confidence


# -- wide field ------------------------------------------------------------------------------------
def enhance_wide(img: np.ndarray, red_free: bool = True, k: float = 1.5) -> np.ndarray:
    """Red-free (the green channel) with local contrast, which brings out the nerve fibre layer."""
    if not red_free and k <= 0:
        return img.copy()
    if red_free:                                                 # (the main window's G 필터 ▾ RNFL 강화 too)
        from .imaging import rnfl_green
        return rnfl_green(img, k)
    h, w = img.shape[:2]
    f = img.astype(np.float32)
    small = cv2.resize(img, (max(1, w // 16), max(1, h // 16)), interpolation=cv2.INTER_AREA)
    blur = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    lit = img.sum(axis=2) > 24                                   # outside the image circle stays as it is
    if red_free:
        g = f[..., 1]
        mean = float(g[lit].mean()) if lit.any() else 80.0
        v = np.clip(105 + (g - mean) * 1.9 + k * 2.2 * (g - blur[..., 1]), 0, 255)
        out = np.repeat(v[..., None], 3, axis=2)
    else:
        out = np.clip(f + k * 1.4 * (f - blur), 0, 255)
    out[~lit] = f[~lit]
    return out.astype(np.uint8)


def axes(disc: tuple, fovea: tuple) -> dict:
    """Unit vectors from the disc towards the fovea (``t``, temporal) and upwards (``u``), their
    distance, the disc radius it implies, and whether this is a right eye."""
    dx, dy = fovea[0] - disc[0], fovea[1] - disc[1]
    dist = math.hypot(dx, dy) or 1.0
    t = (dx / dist, dy / dist)
    u = (t[1], -t[0])
    if u[1] > 0:
        u = (-u[0], -u[1])
    return {"t": t, "u": u, "dist": dist, "rd": dist / 5.2, "od": disc[0] > fovea[0]}


def _direction(ax: dict, theta_deg: float) -> tuple[float, float]:
    r = math.radians(theta_deg)
    return (ax["t"][0] * math.cos(r) + ax["u"][0] * math.sin(r),
            ax["t"][1] * math.cos(r) + ax["u"][1] * math.sin(r))


def sector_info(disc: tuple, fovea: tuple, pt: tuple) -> dict:
    """A point's clock hour, Garway-Heath sector, matching visual field and distance from the
    disc (in disc diameters)."""
    ax = axes(disc, fovea)
    vx, vy = pt[0] - disc[0], pt[1] - disc[1]
    theta = math.degrees(math.atan2(vx * ax["u"][0] + vy * ax["u"][1],
                                    vx * ax["t"][0] + vy * ax["t"][1])) % 360
    t2 = theta + 360 if theta < 40.5 else theta
    sect = next((s for s in SECTORS if s[1] - 0.5 <= t2 < s[2] + 0.5), SECTORS[0])
    hour = round(9 + theta / 30 if ax["od"] else 3 - theta / 30) % 12 or 12
    return {"hour": hour, "sector": sect[0], "field": sect[3], "theta": theta,
            "dd": math.hypot(vx, vy) / (2 * ax["rd"])}


def sector_polygons(disc: tuple, fovea: tuple) -> list:
    """``[(name, RGB, [(x, y), ...]), ...]`` — the ring of sectors around the disc."""
    ax = axes(disc, fovea)
    r1, r2 = ax["rd"] * 1.25, ax["rd"] * 2.0
    out = []
    for name, a0, a1, _field, rgb in SECTORS:
        angs = list(range(a0, a1 + 1, 3))
        if angs[-1] != a1:
            angs.append(a1)
        outer = [(disc[0] + d[0] * r2, disc[1] + d[1] * r2) for d in (_direction(ax, a) for a in angs)]
        inner = [(disc[0] + d[0] * r1, disc[1] + d[1] * r1) for d in (_direction(ax, a) for a in reversed(angs))]
        out.append((name, rgb, outer + inner))
    return out


def vf_points(disc: tuple, fovea: tuple) -> list:
    """The 24-2 visual field points on the fundus: ``[(x, y, upper field?), ...]`` (the upper
    field is seen by the lower retina)."""
    ax = axes(disc, fovea)
    sc = ax["dist"] / 15.5
    n = (-ax["t"][0], -ax["t"][1])                               # nasal retina = temporal field
    down = (-ax["u"][0], -ax["u"][1])
    pts = []
    for sign in (1, -1):
        for y, x0, x1 in ((21, -9, 9), (15, -15, 15), (9, -21, 21), (3, -27, 21)):
            for x in range(x0, x1 + 1, 6):
                pts.append((fovea[0] + n[0] * x * sc + down[0] * y * sign * sc,
                            fovea[1] + n[1] * x * sc + down[1] * y * sign * sc, sign > 0))
    return pts


def disc_fovea_angle(disc: tuple, fovea: tuple) -> float:
    """Positive when the fovea lies below the disc (degrees)."""
    return math.degrees(math.atan2(fovea[1] - disc[1], abs(fovea[0] - disc[0])))


# -- progression -------------------------------------------------------------------------------------
def blend(a: np.ndarray, b: np.ndarray, mix: float) -> np.ndarray:
    return cv2.addWeighted(a, 1 - mix, match_size(b, a), mix, 0)


def diff_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Grey photo with pink where the brightness differs (an overall difference is taken out)."""
    b = match_size(b, a)
    la = a.astype(np.float32).mean(axis=2)
    lb = b.astype(np.float32).mean(axis=2)
    valid = b.sum(axis=2) > 0                                    # not the empty border the shift leaves
    gain = la[valid].mean() / max(1e-6, lb[valid].mean()) if valid.any() else 1.0
    k = np.clip((np.abs(la - lb * gain) - 14) / 30, 0, 1) * valid
    out = la[..., None] * (1 - k[..., None]) + np.float32([255, 40, 150]) * k[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------
# 환자 설명: what glaucoma does, stage by stage — a model for talking with the patient, not a
# measurement of this patient (the window says so next to it)
# ---------------------------------------------------------------------------------------------
STAGES = ("정상", "초기", "중기", "말기")
STAGE_CUP = (0.3, 0.5, 0.7, 0.9)            # cup / disc of the schematic disc
STAGE_FIELD = (1.0, 0.8, 0.5, 0.22)         # radius of the field that is left (1 = all of it)
STAGE_TEXT = (
    "정상: 시신경유두의 함몰이 작고, 시야 전체가 고르게 보입니다.",
    "초기: 함몰이 조금 커지고 신경섬유층이 얇아지기 시작합니다. 시야 한쪽에 활 모양의 흐린 부분이 생기지만 "
    "본인은 거의 느끼지 못합니다.",
    "중기: 함몰이 더 커지고 신경섬유층 결손이 넓어집니다. 주변 시야가 뚜렷하게 좁아집니다.",
    "말기: 함몰이 유두 대부분을 차지합니다. 가운데만 남아 터널 속에서 보는 것처럼 보입니다. "
    "손상된 시신경은 되돌릴 수 없어 조기 발견과 꾸준한 치료가 중요합니다.",
)
NOTE_MODEL = "설명용 모형입니다. 이 환자의 실제 진행 단계를 뜻하지 않습니다."


def _stage(stage: int) -> int:
    return int(np.clip(stage, 0, len(STAGES) - 1))


def sample_scene(size: int = 600) -> np.ndarray:
    """The picture the visual field is shown on (RGB): a plain street — road, buildings, people."""
    w, h = size, int(size * 0.66)
    img = np.zeros((h, w, 3), np.uint8)
    hz = int(h * 0.55)
    for yy in range(h):                                           # sky down to the horizon
        t = min(yy / (h * 0.55), 1.0)
        img[yy] = (150 + 40 * t, 200 - 20 * t, 235 - 60 * t)
    img[hz:] = (105, 110, 95)                                     # ground
    rng = np.random.default_rng(7)
    k = size / 300.0
    x = 0
    while x < w:                                                  # buildings with windows
        bw = int(rng.integers(int(w * 0.07), int(w * 0.14)))
        bh = int(rng.integers(int(h * 0.15), int(h * 0.42)))
        c = int(rng.integers(90, 170))
        cv2.rectangle(img, (x, hz - bh), (x + bw - int(3 * k), hz), (c - 20, c - 10, c), -1)
        for wy in range(hz - bh + int(6 * k), hz - int(6 * k), int(12 * k)):
            for wx in range(x + int(5 * k), x + bw - int(8 * k), int(10 * k)):
                cv2.rectangle(img, (wx, wy), (wx + int(4 * k), wy + int(6 * k)), (240, 225, 190), -1)
        x += bw
    road = np.array([[w * 0.42, hz], [w * 0.58, hz], [w * 0.95, h], [w * 0.05, h]], np.int32)
    cv2.fillPoly(img, [road], (72, 70, 70))
    for i in range(5):                                            # centre line
        t0, t1 = i / 5, i / 5 + 0.1
        y0, y1 = int(hz + (h - hz) * t0), int(hz + (h - hz) * t1)
        cv2.line(img, (w // 2, y0), (w // 2, y1), (240, 230, 210), max(1, int((1 + 3 * t0) * k)))
    for px, sc in ((0.2, 1.0), (0.8, 0.8), (0.66, 0.5)):          # people
        fx, fy, fh = int(w * px), int(hz + (h - hz) * (0.35 + 0.5 * sc)), int(h * 0.2 * sc)
        cv2.line(img, (fx, fy), (fx, fy - fh), (160, 40, 40), max(2, int(5 * sc * k)))
        cv2.circle(img, (fx, fy - fh - int(4 * sc * k)), max(2, int(5 * sc * k)), (220, 180, 150), -1)
    cv2.circle(img, (int(w * 0.85), int(h * 0.14)), int(h * 0.06), (255, 240, 190), -1)   # sun
    return img


def field_simulation(stage: int, size: int = 600, scene: np.ndarray | None = None) -> np.ndarray:
    """What a patient at ``stage`` (0 정상 … 3 말기) sees, as an example: the field fades from
    the edge inwards — an arc-shaped dim patch first, only the centre at the end."""
    stage = _stage(stage)
    sc = sample_scene(size) if scene is None else scene
    h, w = sc.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = (xs - w / 2) / (w / 2), (ys - h / 2) / (h / 2)
    rad = np.sqrt(nx * nx + ny * ny) / math.sqrt(2)
    keep = np.ones((h, w), np.float32)
    if stage > 0:
        keep = np.clip((STAGE_FIELD[stage] - rad) / 0.16 + 0.5, 0, 1)
        if stage == 1:                                            # early: an arcuate scotoma above fixation
            arc = np.exp(-(((np.sqrt(nx * nx + (ny + 0.05) ** 2) - 0.45) / 0.09) ** 2)) * (ny < 0.0) * (nx > -0.75)
            keep = np.minimum(keep, 1 - 0.85 * arc)
    blur = cv2.GaussianBlur(sc, (0, 0), 6 * w / 300.0)
    dark = blur.astype(np.float32) * 0.12 + 14
    out = sc.astype(np.float32) * keep[..., None] + dark * (1 - keep[..., None])
    return np.clip(out, 0, 255).astype(np.uint8)


def disc_schematic(stage: int, size: int = 396) -> np.ndarray:
    """A drawn optic disc (RGB, square): the rim and the cup, which grows with the stage."""
    stage = _stage(stage)
    img = np.full((size, size, 3), (58, 22, 14), np.uint8)
    c, r = (size // 2, size // 2), int(size * 0.36)
    cv2.circle(img, c, int(r * 1.12), (150, 70, 40), -1, cv2.LINE_AA)             # peripapillary ring
    cv2.circle(img, c, r, (238, 150, 96), -1, cv2.LINE_AA)                        # neuroretinal rim
    cr = STAGE_CUP[stage]
    cv2.ellipse(img, c, (int(r * cr * 0.92), int(r * cr)), 0, 0, 360, (255, 238, 205), -1, cv2.LINE_AA)   # cup
    for ang in (-62, -118, 62, 118):                                              # vessels leave over the rim
        a = math.radians(ang)
        p0 = (int(c[0] - r * cr * 0.55), c[1])
        p1 = (int(c[0] + math.cos(a) * size * 0.56), int(c[1] + math.sin(a) * size * 0.56))
        cv2.line(img, p0, p1, (132, 26, 22), max(2, size // 130), cv2.LINE_AA)
    return cv2.GaussianBlur(img, (0, 0), size / 260.0)


def explain_picture(stage: int, size: int = 600, scene: np.ndarray | None = None) -> np.ndarray:
    """The 환자 설명 picture: the schematic disc beside what the patient sees at that stage."""
    field = field_simulation(stage, size, scene)
    disc = disc_schematic(stage, field.shape[0])
    gap = max(6, size // 50)
    out = np.zeros((field.shape[0], disc.shape[1] + gap + field.shape[1], 3), np.uint8)
    out[:, :disc.shape[1]] = disc
    out[:, disc.shape[1] + gap:] = field
    return out
