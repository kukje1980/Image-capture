"""Glaucoma analysis (녹내장 분석): the image work behind ``ui/glaucoma_dialog.py``.

* stereo (스테레오): register two photos of one disc (a shift), show them side by side, as a
  red–cyan anaglyph, or as a disparity (relative depth) map;
* disc (디스크 C/D): cup-to-disc ratios, rim widths and the ISNT order from two ellipses;
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
def cdr_metrics(disc: dict, cup: dict, eye: str = "OD") -> dict:
    """``disc`` / ``cup`` = ``{cx, cy, rx, ry}``. Rim widths are fractions of the vertical disc
    diameter (DD). The photo is upright: the right eye's nasal side is on the right."""
    dd = 2 * disc["ry"]
    s = ((cup["cy"] - cup["ry"]) - (disc["cy"] - disc["ry"])) / dd
    i = ((disc["cy"] + disc["ry"]) - (cup["cy"] + cup["ry"])) / dd
    right = ((disc["cx"] + disc["rx"]) - (cup["cx"] + cup["rx"])) / dd
    left = ((cup["cx"] - cup["rx"]) - (disc["cx"] - disc["rx"])) / dd
    n, t = (left, right) if eye == "OS" else (right, left)
    bad = []
    if i < s:
        bad.append("하측 림이 상측보다 얇음")
    if s < n:
        bad.append("상측 림이 비측보다 얇음")
    if n < t:
        bad.append("비측 림이 이측보다 얇음")
    area = (cup["rx"] * cup["ry"]) / (disc["rx"] * disc["ry"])
    return {"vertical": cup["ry"] / disc["ry"], "horizontal": cup["rx"] / disc["rx"], "area": area,
            "rim": {"I": i, "S": s, "N": n, "T": t}, "isnt": bad}


# -- wide field ------------------------------------------------------------------------------------
def enhance_wide(img: np.ndarray, red_free: bool = True, k: float = 1.5) -> np.ndarray:
    """Red-free (the green channel) with local contrast, which brings out the nerve fibre layer."""
    if not red_free and k <= 0:
        return img.copy()
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
