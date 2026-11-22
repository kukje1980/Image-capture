"""질환 설명 그림의 붓: drawn pictures that explain a retinal disease to a patient (diseases.py says what
to draw for each disease and stage; ui/disease_view.py puts them together with the words).

Three kinds of picture, all RGB ``uint8`` and all drawn (no photo of anybody):

* :class:`Fundus` — a schematic fundus photo of a right eye (the disc on the right, the macula left of
  the middle) with lesions painted on: haemorrhages, exudates, cotton-wool spots, drusen, a hole, a
  detachment … Points are in *fundus units*: (0, 0) the middle of the photo, 1 its radius, y down.
  Each lesion can leave a :class:`Mark` (where to put a number and what it is called).
* :class:`Section` — the retina cut through and seen from the side (vitreous, retina, photoreceptors,
  RPE, choroid, sclera), through the fovea or through the optic disc, with what the disease does to the
  layers (fluid under or in the retina, a hole, drusen, a membrane, the cup …).
* :func:`vision` / :func:`amsler` — what the patient sees, as an example: a street scene (the one the
  glaucoma explanation uses) or an Amsler grid, blurred, darkened, bent or cut the way the disease does.
  A lesion at fundus point (u, v) shows in the scene at (u, −v) from the fovea: the field is the
  fundus picture turned upside down.

Everything is drawn twice as large and shrunk at the end (smooth edges), and is the same every time
(fixed random seeds), so a saved picture can be made again.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

SS = 2                                # drawn this many times larger, then shrunk
DISC = (0.44, -0.03)                  # optic disc centre (fundus units)
DISC_R = 0.125                        # its horizontal radius (vertical: × 1.08)
FOVEA = (-0.20, 0.03)

# colours (RGB)
ARTERY = (198, 62, 44)
VEIN = (128, 26, 28)
HEME = (122, 14, 16)
HEME_DARK = (92, 8, 12)
EXUDATE = (252, 226, 120)
CWS = (246, 240, 226)
DRUSEN = (240, 205, 120)
PIGMENT = (34, 20, 14)


@dataclass
class Mark:
    """A numbered note on a picture: ``(x, y)`` in pixels of the finished picture."""
    x: float
    y: float
    label: str


def _catmull(pts, n: int = 10) -> np.ndarray:
    """A smooth curve through the points (Catmull–Rom)."""
    p = np.asarray(pts, np.float64)
    if len(p) < 3:
        return p
    p = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(p[-2])
    return np.asarray(out)


def _noise(shape, cell: int, rng: np.random.Generator) -> np.ndarray:
    """Smooth noise, about −1 … 1, with blobs about ``cell`` pixels across."""
    h, w = shape
    small = rng.normal(0, 1, (h // cell + 3, w // cell + 3)).astype(np.float32)
    big = cv2.resize(small, (w + 3 * cell, h + 3 * cell), interpolation=cv2.INTER_CUBIC)
    return big[cell:cell + h, cell:cell + w] / 1.2


# -----------------------------------------------------------------------------------------------
# the fundus
# -----------------------------------------------------------------------------------------------
# main vessels: name → points (from the disc outwards). The temporal arcades bend round the macula; an
# artery and a vein of each arcade cross once (where a branch vein occlusion starts).
VESSELS = {
    "STV": [(0.43, -0.02), (0.42, -0.08), (0.35, -0.19), (0.21, -0.32), (0.02, -0.41), (-0.20, -0.44),
            (-0.42, -0.40), (-0.62, -0.32), (-0.80, -0.25), (-0.97, -0.20)],
    "STA": [(0.44, -0.03), (0.41, -0.10), (0.30, -0.25), (0.14, -0.36), (-0.06, -0.39), (-0.26, -0.38),
            (-0.46, -0.32), (-0.67, -0.24), (-0.86, -0.18), (-0.98, -0.15)],
    "ITV": [(0.43, -0.01), (0.42, 0.05), (0.35, 0.16), (0.21, 0.30), (0.02, 0.39), (-0.20, 0.43),
            (-0.42, 0.40), (-0.62, 0.33), (-0.80, 0.27), (-0.97, 0.23)],
    "ITA": [(0.44, -0.02), (0.41, 0.06), (0.30, 0.22), (0.14, 0.34), (-0.06, 0.38), (-0.26, 0.38),
            (-0.46, 0.34), (-0.67, 0.27), (-0.86, 0.22), (-0.98, 0.19)],
    "SNV": [(0.45, -0.04), (0.47, -0.14), (0.51, -0.30), (0.56, -0.50), (0.60, -0.70), (0.62, -0.86)],
    "SNA": [(0.46, -0.05), (0.52, -0.15), (0.62, -0.28), (0.72, -0.44), (0.79, -0.60)],
    "INV": [(0.45, -0.01), (0.48, 0.10), (0.53, 0.26), (0.58, 0.46), (0.62, 0.66), (0.63, 0.83)],
    "INA": [(0.46, -0.01), (0.53, 0.10), (0.63, 0.22), (0.73, 0.38), (0.80, 0.55)],
    "NA": [(0.47, -0.03), (0.60, -0.05), (0.76, -0.07), (0.92, -0.09)],
    "NV": [(0.47, -0.02), (0.61, 0.01), (0.77, 0.04), (0.93, 0.06)],
}
ARTERIES = {"STA", "ITA", "SNA", "INA", "NA"}
QUADRANT = {"STV": "ST", "STA": "ST", "ITV": "IT", "ITA": "IT", "SNV": "SN", "SNA": "SN",
            "INV": "IN", "INA": "IN", "NA": "N", "NV": "N"}


@dataclass
class Look:
    """How the healthy parts look (diseases change these before the lesions are painted)."""
    artery_w: float = 1.0          # width of the arteries (× normal)
    vein_w: float = 1.0
    tortuous: float = 0.0          # veins wind (0 … 1)
    tortuous_only: tuple = ()      # … only these vessels ("STV" …), or all veins if empty
    vein_wide_only: tuple = ()     # vein_w only for these vessels (else all veins)
    wiring: float = 0.0            # arteries' light reflex: copper → silver wiring (0 … 1)
    cup: float = 0.32              # cup / disc
    notch: float = 0.0             # the rim thinned below (glaucoma)
    disc_pale: float = 0.0         # pale (atrophic) disc (0 … 1)
    disc_swell: float = 0.0        # swollen disc (0 … 1)
    disc_tilt: float = 0.0         # oval, tilted disc (myopia, 0 … 1)
    tessellate: float = 0.0        # choroidal vessels show through (myopia, 0 … 1)
    pale_bg: float = 0.0           # a paler, thinner fundus (0 … 1)
    fovea_reflex: bool = True
    branches: float = 1.0          # how many small branches (× normal)
    macular_pull: float = 0.0      # small vessels drawn towards a point near the fovea (membrane)
    seed: int = 5
    skip: tuple = ()               # vessels left out


class Fundus:
    """A schematic fundus photo being painted (see the module's note)."""

    def __init__(self, size: int = 640, look: Look | None = None):
        self.size = size
        self.n = n = size * SS
        self.look = look or Look()
        self.R = n * 0.47
        self.c = n / 2.0
        self.rng = np.random.default_rng(self.look.seed)
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        self.U = (xx - self.c) / self.R
        self.V = (yy - self.c) / self.R
        self.marks: list[tuple[float, float, str]] = []
        self.paths: dict[str, np.ndarray] = {}            # main vessels as drawn (fundus units)
        self.img = self._background()
        self._disc()
        before = self.img.copy()
        self._vessels()
        diff = np.abs(self.img - before).sum(axis=2)
        self.vessel_mask = cv2.GaussianBlur(np.clip(diff / 60.0, 0, 1).astype(np.float32), (0, 0), SS * 0.8)
        del before
        self._swelling()

    # -- coordinates ------------------------------------------------------------------------------
    def px(self, u: float, v: float) -> tuple[int, int]:
        return int(round(self.c + u * self.R)), int(round(self.c + v * self.R))

    def r(self, d: float) -> int:
        return max(1, int(round(d * self.R)))

    def mark(self, u: float, v: float, label: str) -> None:
        self.marks.append((u, v, label))

    def dist(self, p) -> np.ndarray:
        return np.hypot(self.U - p[0], self.V - p[1])

    def angle_from(self, p) -> np.ndarray:
        """Degrees about point ``p``: 0 = right (nasal), 90 = up (superior), 180 = left (temporal)."""
        return np.degrees(np.arctan2(-(self.V - p[1]), self.U - p[0])) % 360

    # -- painting ---------------------------------------------------------------------------------
    def mask(self) -> np.ndarray:
        return np.zeros((self.n, self.n), np.float32)

    def paint(self, m: np.ndarray, color, alpha: float = 1.0, blur: float = 0.0, under_vessels: bool = False) -> None:
        """Lay ``color`` where the mask ``m`` (0 … 1) is, feathered by ``blur`` (fundus units);
        ``under_vessels``: the vessels stay in front (a change of the retina behind them)."""
        if blur > 0:
            s = blur * self.R
            m = cv2.GaussianBlur(m, (0, 0), s)
        if under_vessels:
            m = m * (1 - 0.85 * self.vessel_mask)
        a = np.clip(m * alpha, 0, 1)[..., None]
        self.img = self.img * (1 - a) + np.float32(color) * a

    def tone(self, m: np.ndarray, gain: float, blur: float = 0.0) -> None:
        """Darken (gain < 1) or brighten where ``m`` is."""
        if blur > 0:
            m = cv2.GaussianBlur(m, (0, 0), blur * self.R)
        self.img = self.img * (1 + (gain - 1) * np.clip(m, 0, 1)[..., None])

    def ellipse(self, m: np.ndarray, u: float, v: float, a: float, b: float | None = None,
                angle: float = 0.0, value: float = 1.0) -> None:
        b = a if b is None else b
        cv2.ellipse(m, self.px(u, v), (self.r(a), self.r(b)), -angle, 0, 360, value, -1, cv2.LINE_AA)

    def polyline(self, m: np.ndarray, pts, width: float, value: float = 1.0) -> None:
        q = np.int32([self.px(u, v) for u, v in pts])
        cv2.polylines(m, [q], False, value, max(1, self.r(width)), cv2.LINE_AA)

    # -- the healthy fundus --------------------------------------------------------------------------
    def _background(self) -> np.ndarray:
        lk, n = self.look, self.n
        rr = np.hypot(self.U, self.V)
        base = np.float32([206, 92, 48]) * (1 - lk.pale_bg) + np.float32([214, 128, 84]) * lk.pale_bg
        edge = np.float32([112, 38, 24])
        t = np.clip(rr ** 1.8, 0, 1)[..., None]
        img = base * (1 - t) + edge * t
        img = img * (1 + 0.05 * _noise((n, n), int(self.R * 0.25), self.rng)[..., None]
                     + 0.025 * _noise((n, n), max(2, int(self.R * 0.02)), self.rng)[..., None])
        if lk.tessellate > 0:                 # choroidal vessels: broad orange bands, dark brown between them
            rad = self.dist(FOVEA)
            f = (np.sin(7 * _noise((n, n), int(self.R * 0.30), self.rng) + 2.5 * _noise((n, n), int(self.R * 0.10), self.rng))
                 + 0.45 * _noise((n, n), int(self.R * 0.05), self.rng))
            gaps = np.clip((np.abs(f) - 0.55) / 0.35, 0, 1)          # 1 between the vessels
            fade = (np.clip(0.4 + 0.9 * rad, 0, 1) * lk.tessellate)[..., None]
            dark = gaps[..., None] * fade
            img = img * (1 - 0.34 * dark) + np.float32([96, 44, 26]) * 0.34 * dark
            img = img + ((1 - gaps)[..., None] * fade) * np.float32([16, 10, 2])
        mac = np.exp(-(self.dist(FOVEA) / 0.17) ** 2)[..., None]
        img = img * (1 - 0.30 * mac) + np.float32([60, 22, 10]) * 0.12 * mac
        return img.astype(np.float32)

    def _wind(self, pts: np.ndarray, amp: float, seed: int) -> np.ndarray:
        if amp <= 0 or len(pts) < 3:
            return pts
        d = np.diff(pts, axis=0)
        seg = np.hypot(d[:, 0], d[:, 1])
        s = np.concatenate([[0], np.cumsum(seg)])
        tang = np.vstack([d, d[-1:]]) / np.maximum(np.concatenate([seg, seg[-1:]]), 1e-6)[:, None]
        normal = np.stack([-tang[:, 1], tang[:, 0]], 1)
        ph = seed * 1.7
        wob = amp * (np.sin(s / 0.045 + ph) + 0.5 * np.sin(s / 0.021 + 2 * ph)) * np.clip(s / 0.12, 0, 1)
        return pts + normal * wob[:, None]

    def _stroke(self, pts: np.ndarray, w0: float, w1: float, color, reflex: float = 0.0) -> None:
        """A vessel tapering from ``w0`` to ``w1`` (fundus units), painted straight onto the picture."""
        q = np.array([[self.c + u * self.R, self.c + v * self.R] for u, v in pts], np.float64)
        img = self.img
        k = len(q)
        for i in range(k - 1):
            t = i / max(1, k - 2)
            w = (w0 + (w1 - w0) * t) * self.R
            a, b = tuple(np.int32(np.round(q[i]))), tuple(np.int32(np.round(q[i + 1])))
            cv2.line(img, a, b, color, max(1, int(round(w))), cv2.LINE_AA)
        if reflex > 0:                        # the light reflex along an artery
            col = tuple(float(c) for c in np.float32(color) * (1 - reflex) + np.float32([250, 214, 170]) * reflex)
            for i in range(k - 1):
                t = i / max(1, k - 2)
                w = (w0 + (w1 - w0) * t) * self.R * (0.22 + 0.25 * self.look.wiring)
                a, b = tuple(np.int32(np.round(q[i]))), tuple(np.int32(np.round(q[i + 1])))
                cv2.line(img, a, b, col, max(1, int(round(w))), cv2.LINE_AA)

    def _vessels(self) -> None:
        lk, rng = self.look, self.rng
        jobs = []
        for k, (name, pts) in enumerate(VESSELS.items()):
            if name in lk.skip:
                continue
            artery = name in ARTERIES
            path = _catmull(pts, 12)
            tort = lk.tortuous if (not artery and (not lk.tortuous_only or name in lk.tortuous_only)) else 0.0
            path = self._wind(path, 0.018 * tort, k + 1)
            self.paths[name] = path
            wide = lk.vein_w if (not artery and (not lk.vein_wide_only or name in lk.vein_wide_only)) else 1.0
            main = name[0] in "SI" and name[1] == "T"
            w0 = (0.020 if artery else 0.026) * (lk.artery_w if artery else wide) * (1.0 if main else 0.8)
            w1 = w0 * 0.45
            jobs.append((artery, path, w0, w1, True))
            # branches: off the main vessel, away from the fovea, now and then a smaller one off them
            s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(path, axis=0).T))])
            nxt = 0.10 + rng.uniform(0, 0.06)
            for i in range(1, len(path) - 1):
                if s[i] < nxt:
                    continue
                nxt = s[i] + rng.uniform(0.09, 0.17) / max(0.3, lk.branches)
                if rng.random() > 0.8 * min(1.0, lk.branches):
                    continue
                self._branch(path[i], path[i + 1] - path[i - 1], w0 * (1 - s[i] / max(s[-1], 1e-6) * 0.55) * 0.62,
                             artery, jobs, depth=0, tort=tort)
        # small vessels towards the macula (they stop short of the fovea)
        for base, sign in (("STA", -1), ("ITA", 1), ("STV", -1), ("ITV", 1)):
            if base not in self.paths:
                continue
            path = self.paths[base]
            for f in ((0.40, 0.60) if base in ARTERIES else (0.50,)):
                i = int(f * (len(path) - 1))
                p = path[i]
                q = np.array(FOVEA) + (p - np.array(FOVEA)) * rng.uniform(0.36, 0.48)
                q = q + lk.macular_pull * (np.array(FOVEA) + np.array([0.05, 0.02]) - q) * 0.6
                q = q + np.array([rng.uniform(-0.05, 0.05), 0])
                mid = (p + q) / 2 + np.array([rng.uniform(-0.05, 0.05), sign * rng.uniform(0.0, 0.03)])
                pts = _catmull([p, mid, q], 10)
                pts = self._wind(pts, 0.010 * lk.macular_pull, i)
                jobs.append((base in ARTERIES, pts, 0.0065 * (lk.artery_w if base in ARTERIES else lk.vein_w),
                             0.0035, False))
        # veins first, arteries over them (they cross over the veins in most places)
        for artery, pts, w0, w1, main in sorted(jobs, key=lambda j: j[0]):
            col = ARTERY if artery else VEIN
            if artery and lk.wiring > 0:
                col = tuple(float(c) for c in np.float32(ARTERY) * (1 - 0.35 * lk.wiring) + np.float32([226, 150, 100]) * 0.35 * lk.wiring)
            if artery:
                reflex = (0.22 if main else 0.0) + 0.6 * lk.wiring
            else:
                reflex = 0.10 if main else 0.0
            self._stroke(pts, w0, w1, col, reflex=reflex)

    def _branch(self, p, tangent, w, artery, jobs, depth, tort):
        rng = self.rng
        t = tangent / max(1e-9, np.hypot(*tangent))
        side = rng.choice([-1, 1])
        a = math.atan2(t[1], t[0]) + side * rng.uniform(0.45, 1.0)
        pts = [np.array(p, np.float64)]
        x = pts[0].copy()
        length = rng.uniform(0.16, 0.34) * (0.6 if depth else 1.0)
        steps = int(length / 0.03)
        for _ in range(steps):
            a += rng.normal(0, 0.18)
            nxt = x + 0.03 * np.array([math.cos(a), math.sin(a)])
            if np.hypot(*(nxt - np.array(FOVEA))) < 0.15:      # round the fovea
                a += 0.5 * side
                nxt = x + 0.03 * np.array([math.cos(a), math.sin(a)])
            x = nxt
            pts.append(x.copy())
            if np.hypot(*x) > 1.05:
                break
        if len(pts) < 3:
            return
        path = self._wind(_catmull(pts, 6), 0.010 * tort, int(rng.integers(1, 99)))
        jobs.append((artery, path, max(0.004, w), max(0.003, w * 0.5), False))
        if depth == 0 and len(pts) > 4 and rng.random() < 0.6:
            k = int(rng.integers(2, len(pts) - 1))
            self._branch(pts[k], pts[k] - pts[k - 1], w * 0.6, artery, jobs, 1, tort)

    def _disc(self) -> None:
        lk = self.look
        du, dv = DISC
        rx = DISC_R * (1 - 0.18 * lk.disc_tilt) * (1 + 0.22 * lk.disc_swell)
        ry = DISC_R * 1.08 * (1 + 0.08 * lk.disc_tilt) * (1 + 0.22 * lk.disc_swell)
        self.disc_rx, self.disc_ry = rx, ry
        d = np.hypot((self.U - du) / rx, (self.V - dv) / ry)
        self._disc_d = d
        # a darker ring round the disc, the rim, the cup (the vessels go on over it, from the cup)
        ring = np.clip(1.3 - d, 0, 1) * (d > 0.95)
        self.tone(ring.astype(np.float32), 0.86, blur=0.01)
        rim_col = np.float32([236, 148, 100]) * (1 - lk.disc_pale) + np.float32([244, 222, 196]) * lk.disc_pale
        if lk.disc_swell > 0:
            rim_col = rim_col * (1 - 0.5 * lk.disc_swell) + np.float32([232, 112, 86]) * 0.5 * lk.disc_swell
        edge = 0.02 + 0.10 * lk.disc_swell                    # a swollen disc has no sharp edge
        disc = np.clip((1 - d) / (edge / DISC_R) + 0.5, 0, 1).astype(np.float32)
        self.paint(disc, rim_col, 0.95 - 0.2 * lk.disc_swell)
        if lk.cup > 0 and lk.disc_swell < 0.5:
            cr = lk.cup * (1 - 0.6 * lk.disc_swell)
            cu = du - rx * 0.10 * (1 - lk.cup)
            dc = np.hypot((self.U - cu) / (rx * cr * 0.94),
                          (self.V - dv - ry * 0.10 * lk.notch * cr) / (ry * cr * (1 + 0.14 * lk.notch)))
            cup = np.clip((1 - dc) / 0.14 + 0.5, 0, 1).astype(np.float32)
            self.paint(cup, (252, 232, 200), 0.95)

    def _swelling(self) -> None:
        """A swollen disc hides the vessels as they cross its edge (drawn over them)."""
        lk = self.look
        if lk.disc_swell <= 0:
            return
        d = self._disc_d
        striae = 0.5 + 0.5 * np.sin(np.radians(self.angle_from(DISC)) * 34)
        halo = np.exp(-((d - 1.0) / (0.16 * lk.disc_swell + 0.04)) ** 2) * (0.5 + 0.4 * striae)
        self.paint(halo.astype(np.float32), (224, 132, 100), 0.75 * lk.disc_swell, blur=0.004)
        core = np.clip(1 - d, 0, 1) ** 0.6
        self.paint(core.astype(np.float32), (240, 156, 112), 0.35 * lk.disc_swell, blur=0.01)

    # -- finishing ----------------------------------------------------------------------------------
    def finish(self) -> np.ndarray:
        lk = self.look
        img = self.img
        if lk.fovea_reflex:
            m = np.exp(-(self.dist(FOVEA) / 0.012) ** 2)[..., None]
            img = img * (1 - 0.6 * m) + np.float32([255, 238, 200]) * 0.6 * m
        img = cv2.GaussianBlur(img, (0, 0), 0.6 * SS)
        rr = np.hypot(self.U, self.V)
        inside = np.clip((1.0 - rr) * self.R / (1.2 * SS), 0, 1)[..., None]
        self._full = np.clip(img * inside, 0, 255).astype(np.uint8)
        small = cv2.resize(self._full, (self.size, self.size), interpolation=cv2.INTER_AREA)
        return small

    def crop(self, u: float, v: float, half: float, out: int = 240) -> tuple[np.ndarray, tuple]:
        """A close-up of the finished picture round (u, v) (``half``: half its side, fundus units), drawn from
        the larger picture; and where it is in the finished picture (x, y, w, h pixels)."""
        x0, y0 = self.px(u - half, v - half)
        x1, y1 = self.px(u + half, v + half)
        part = self._full[max(0, y0):y1, max(0, x0):x1]
        return (cv2.resize(part, (out, out), interpolation=cv2.INTER_AREA),
                (x0 / SS, y0 / SS, (x1 - x0) / SS, (y1 - y0) / SS))

    def finished_marks(self) -> list[Mark]:
        out = []
        for u, v, label in self.marks:
            x, y = self.px(u, v)
            out.append(Mark(x / SS, y / SS, label))
        return out

    # -- lesions ------------------------------------------------------------------------------------
    def spots(self, points, size, color, alpha=1.0, blur=0.0, aspect=1.0, along_disc=False, jitter=0.3) -> None:
        """Round (or, ``along_disc``, flame-shaped: stretched along the nerve fibres) spots."""
        m = self.mask()
        rng = self.rng
        for u, v in points:
            s = size * rng.uniform(1 - jitter, 1 + jitter)
            ang = 0.0
            if along_disc:
                ang = math.degrees(math.atan2(-(v - DISC[1]), u - DISC[0]))
            self.ellipse(m, u, v, s * aspect, s, ang)
            if along_disc:                        # a feathered end
                d = np.array([math.cos(math.radians(ang)), -math.sin(math.radians(ang))]) * s * aspect * 0.9
                self.ellipse(m, u + d[0], v + d[1], s * aspect * 0.5, s * 0.6, ang, 0.7)
        self.paint(m, color, alpha, blur)

    def scatter(self, n, center, radius, *, avoid=None, avoid_r=0.0, inner=0.0, sector=None, about=None) -> list:
        """``n`` points in a disc (or ring ``inner`` … ``radius``) round ``center``, maybe only in the
        ``sector`` (from°, to°) as seen from ``about`` (default: the centre), not within ``avoid_r`` of ``avoid``."""
        rng = self.rng
        out, tries = [], 0
        about = center if about is None else about
        while len(out) < n and tries < n * 200:
            tries += 1
            a = rng.uniform(0, 2 * math.pi)
            r = math.sqrt(rng.uniform((inner / radius) ** 2 if radius else 0, 1)) * radius
            u, v = center[0] + r * math.cos(a), center[1] + r * math.sin(a)
            if math.hypot(u, v) > 0.95:
                continue
            if avoid is not None and math.hypot(u - avoid[0], v - avoid[1]) < avoid_r:
                continue
            if math.hypot(u - DISC[0], v - DISC[1]) < DISC_R * 1.2:
                continue
            if sector is not None:
                ang = math.degrees(math.atan2(-(v - about[1]), u - about[0])) % 360
                lo, hi = sector
                if not (lo <= ang <= hi if lo <= hi else (ang >= lo or ang <= hi)):
                    continue
            out.append((u, v))
        return out

    def near_vessels(self, n, names, spread=0.03, lo=0.15, hi=0.9) -> list:
        """``n`` points beside the named main vessels (between ``lo`` and ``hi`` of their length)."""
        rng = self.rng
        out = []
        paths = [self.paths[k] for k in names if k in self.paths]
        if not paths:
            return out
        for _ in range(n):
            p = paths[int(rng.integers(len(paths)))]
            i = int(rng.uniform(lo, hi) * (len(p) - 1))
            u, v = p[i] + rng.normal(0, spread, 2)
            if math.hypot(u, v) < 0.95:
                out.append((float(u), float(v)))
        return out

    def flames(self, points, size=0.03, alpha=0.95) -> None:
        self.spots(points, size * 0.42, HEME, alpha, blur=0.006, aspect=2.4, along_disc=True)

    def blots(self, points, size=0.018, alpha=0.95) -> None:
        self.spots(points, size, HEME, alpha, blur=0.004, jitter=0.45)

    def microaneurysms(self, points) -> None:
        self.spots(points, 0.0065, (150, 18, 18), 1.0, blur=0.0015, jitter=0.2)

    def exudates(self, points, size=0.008) -> None:
        self.spots(points, size, EXUDATE, 0.95, blur=0.0025, jitter=0.5)

    def cotton_wool(self, points, size=0.035) -> None:
        m = self.mask()
        rng = self.rng
        for u, v in points:
            for _ in range(3):
                self.ellipse(m, u + rng.normal(0, size * 0.3), v + rng.normal(0, size * 0.3),
                             size * rng.uniform(0.45, 0.8), size * rng.uniform(0.3, 0.55), rng.uniform(0, 180))
        self.paint(m, CWS, 0.85, blur=0.010)

    def ring_points(self, center, radius, n, width=0.02) -> list:
        rng = self.rng
        out = []
        for k in range(n):
            a = 2 * math.pi * k / n + rng.normal(0, 0.08)
            r = radius + rng.normal(0, width)
            out.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
        return out

    def star(self, center, radius=0.13, n=80) -> None:
        """Exudates in a star round the fovea (lines radiating out)."""
        rng = self.rng
        pts = []
        for k in range(n):
            a = rng.choice(np.linspace(0, 2 * math.pi, 14, endpoint=False)) + rng.normal(0, 0.05)
            r = rng.uniform(0.03, radius)
            pts.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
        self.exudates(pts, 0.006)

    def drusen(self, points, size=0.016) -> None:
        self.spots(points, size, DRUSEN, 0.75, blur=0.006, jitter=0.5)

    def pigment_spicules(self, points, size=0.03) -> None:
        """Bone-spicule pigment: little dark stars."""
        m = self.mask()
        rng = self.rng
        for u, v in points:
            arms = int(rng.integers(3, 6))
            for _ in range(arms):
                a = rng.uniform(0, 2 * math.pi)
                l = size * rng.uniform(0.5, 1.0)
                mid = (u + math.cos(a) * l * 0.5 + rng.normal(0, l * 0.12), v + math.sin(a) * l * 0.5 + rng.normal(0, l * 0.12))
                end = (u + math.cos(a) * l, v + math.sin(a) * l)
                self.polyline(m, [(u, v), mid, end], 0.0028)
            self.ellipse(m, u, v, size * 0.16)
        self.paint(m, PIGMENT, 0.92, blur=0.0015)

    def region(self, m: np.ndarray, color, alpha, blur=0.01) -> None:
        self.paint(m.astype(np.float32), color, alpha, blur)

    def nv_tuft(self, center, radius=0.05, color=(214, 52, 52), n=16) -> None:
        """New vessels: fine, looping, tangled."""
        m = self.mask()
        rng = self.rng
        for _ in range(n):
            a = rng.uniform(0, 2 * math.pi)
            pts = [center]
            x = np.array(center, np.float64)
            for _ in range(int(rng.integers(5, 9))):
                a += rng.normal(0, 0.7)
                x = x + radius * 0.22 * np.array([math.cos(a), math.sin(a)])
                if np.hypot(*(x - np.array(center))) > radius:
                    a += math.pi * 0.8
                pts.append(tuple(x))
            self.polyline(m, _catmull(pts, 5), 0.0032)
        self.paint(m, color, 0.95, blur=0.0012)

    def nick(self, at, along, size=0.03) -> None:
        """Arteriovenous nicking: the vein seems cut on both sides of the artery that crosses it."""
        m = self.mask()
        t = np.asarray(along, np.float64)
        t /= max(1e-9, np.hypot(*t))
        for s in (-1, 1):
            u, v = at[0] + s * t[0] * size * 0.75, at[1] + s * t[1] * size * 0.75
            self.ellipse(m, u, v, size * 0.45, size * 0.22, math.degrees(math.atan2(-t[1], t[0])))
        self.paint(m, self.background_near(at), 0.9, blur=0.004)

    def background_near(self, p, r=0.06) -> tuple:
        """The fundus colour about ``p`` without the vessels (a median of the neighbourhood)."""
        x, y = self.px(*p)
        k = self.r(r)
        patch = self.img[max(0, y - k):y + k, max(0, x - k):x + k].reshape(-1, 3)
        lum = patch.mean(1)
        keep = patch[lum >= np.percentile(lum, 55)]
        return tuple(float(c) for c in np.median(keep if len(keep) else patch, 0))

    def crossing(self, artery: str, vein: str) -> tuple[tuple[float, float], np.ndarray] | None:
        """Where an artery crosses a vein (and the vein's direction there)."""
        a, b = self.paths.get(artery), self.paths.get(vein)
        if a is None or b is None:
            return None
        for i in range(len(b) - 1):
            p, r = b[i], b[i + 1] - b[i]
            for j in range(len(a) - 1):
                q, s = a[j], a[j + 1] - a[j]
                den = r[0] * s[1] - r[1] * s[0]
                if abs(den) < 1e-12:
                    continue
                t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
                w = ((q[0] - p[0]) * r[1] - (q[1] - p[1]) * r[0]) / den
                if 0 <= t <= 1 and 0 <= w <= 1 and np.hypot(*(p - np.array(DISC))) > DISC_R * 1.5:
                    return (float(p[0] + t * r[0]), float(p[1] + t * r[1])), r
        return None

    def vessel_point(self, name: str, frac: float) -> tuple[float, float]:
        p = self.paths[name]
        i = int(np.clip(frac, 0, 1) * (len(p) - 1))
        return float(p[i][0]), float(p[i][1])


# -----------------------------------------------------------------------------------------------
# the cross-section
# -----------------------------------------------------------------------------------------------
LAYER_COLORS = {
    "vitreous": (34, 40, 54),
    "nfl": (240, 196, 182),
    "inner": (226, 168, 160),
    "outer": (206, 136, 132),
    "pr": (186, 112, 104),
    "rpe": (92, 42, 26),
    "choroid": (170, 46, 40),
    "sclera": (236, 228, 214),
    "nerve": (236, 214, 190),
}
LAYER_NAMES = (("vitreous", "유리체"), ("inner", "망막"), ("pr", "시세포"), ("rpe", "망막색소상피"),
               ("choroid", "맥락막"), ("sclera", "공막"))


@dataclass
class Section:
    """The retina cut through and seen from the side (see the module's note). Thicknesses are fractions
    of the picture's height, per column; a disease changes them (and adds ``extras``) before ``draw``."""
    width: int = 640
    height: int = 250
    through: str = "fovea"                # or "disc"
    seed: int = 3
    marks: list = field(default_factory=list)

    def __post_init__(self):
        w = self.width * SS
        self.W, self.H = w, self.height * SS
        self.x = np.linspace(0, 1, w, dtype=np.float32)
        x = self.x
        self.rpe_top = np.full(w, 0.66, np.float32)       # top of the RPE
        self.rpe_t = np.full(w, 0.022, np.float32)
        self.pr_t = np.full(w, 0.075, np.float32)
        self.outer_t = 0.085 + 0.035 * np.exp(-((x - 0.5) / 0.05) ** 2)
        pit = np.exp(-((x - 0.5) / 0.065) ** 2)
        shoulder = np.exp(-((np.abs(x - 0.5) - 0.12) / 0.05) ** 2)
        self.inner_t = (0.15 * (1 - 0.96 * pit) + 0.03 * shoulder).astype(np.float32)
        self.nfl_t = (0.028 + 0.04 * np.clip((x - 0.5) / 0.5, 0, 1)).astype(np.float32)   # thicker towards the disc
        self.nfl_t *= (1 - 0.95 * pit)
        self.choroid_t = np.full(w, 0.17, np.float32)
        self.sub_rpe = np.zeros(w, np.float32)            # drusen / PED: lifts the RPE
        self.sub_rpe_color = (238, 204, 120)
        self.sub_ret = np.zeros(w, np.float32)            # fluid (or blood) under the retina
        self.sub_ret_color = (72, 92, 124)
        self.hole = np.zeros(w, bool)                     # no retina here
        self.pr_loss = np.zeros(w, np.float32)            # photoreceptors (and RPE) gone (0 … 1)
        self.rpe_loss = np.zeros(w, np.float32)
        self.bow = np.zeros(w, np.float32)                # the whole wall pushed back (staphyloma)
        self.cysts: list = []                             # (x, y-in-retina 0..1, rx, ry) fluid spaces
        self.extras: list = []                            # callables(img, sec) drawn last
        self.disc_cup = 0.3
        self.disc_swell = 0.0
        self.nfl_scale = 1.0
        if self.through == "disc":
            self._disc_shape()

    def _disc_shape(self) -> None:
        x = self.x
        self.canal = 0.11
        off = np.abs(x - 0.5)
        self.inner_t = np.full(self.W, 0.10, np.float32)
        self.outer_t = np.full(self.W, 0.08, np.float32)
        self.nfl_t = (0.03 + 0.13 * np.exp(-((off - self.canal) / 0.09) ** 2)).astype(np.float32)

    def mark(self, x: float, y: float, label: str) -> None:
        """A note at (x, y) — fractions of the picture."""
        self.marks.append((x, y, label))

    def draw(self) -> np.ndarray:
        W, H = self.W, self.H
        rng = np.random.default_rng(self.seed)
        bow = self.bow
        rpe_top = self.rpe_top + bow - self.sub_rpe
        rpe_bot = self.rpe_top + bow + self.rpe_t
        bruch = self.rpe_top + bow + self.rpe_t
        pr_bot = rpe_top - self.sub_ret
        pr_t = self.pr_t * (1 - self.pr_loss)
        pr_top = pr_bot - pr_t
        outer_top = pr_top - self.outer_t * (1 - 0.6 * self.pr_loss)
        nfl_t = self.nfl_t * self.nfl_scale
        inner_top = outer_top - self.inner_t
        surface = inner_top - nfl_t
        ch_bot = bruch + self.choroid_t
        self.y_surface = surface
        yy = (np.arange(H, dtype=np.float32) / H)[:, None]
        img = np.zeros((H, W, 3), np.float32)
        img[:] = LAYER_COLORS["vitreous"]
        # a faint vitreous texture
        img += (8 * _noise((H, W), 40, rng))[..., None]

        def fill(top, bot, color, where=None):
            m = (yy >= top[None, :]) & (yy < bot[None, :])
            if where is not None:
                m &= where[None, :]
            img[m] = color
            return m

        retina = ~self.hole
        fill(bruch, ch_bot, LAYER_COLORS["choroid"])
        fill(ch_bot, np.full(W, 2.0, np.float32), LAYER_COLORS["sclera"])
        # choroidal vessels (round, dark) and the scleral texture
        for _ in range(int(W / SS / 9)):
            cx = rng.uniform(0, W)
            i = int(np.clip(cx, 0, W - 1))
            cy = (bruch[i] + self.choroid_t[i] * rng.uniform(0.35, 0.8)) * H
            r = self.choroid_t[i] * H * rng.uniform(0.12, 0.3)
            cv2.ellipse(img, (int(cx), int(cy)), (int(r * 1.3), int(r)), 0, 0, 360, (122, 24, 26), -1, cv2.LINE_AA)
        fill(rpe_top, rpe_bot, LAYER_COLORS["rpe"], self.rpe_loss < 0.5)
        fill(rpe_top - 0.004, rpe_bot, (204, 118, 96), self.rpe_loss >= 0.5)      # bare: the choroid shows
        if self.sub_rpe.max() > 0:
            fill(rpe_top + self.rpe_t, bruch, self.sub_rpe_color, self.sub_rpe > 0.002)
            fill(rpe_top, rpe_top + self.rpe_t, LAYER_COLORS["rpe"], (self.sub_rpe > 0.002) & (self.rpe_loss < 0.5))
        if self.sub_ret.max() > 0:
            fill(pr_bot, rpe_top, self.sub_ret_color, (self.sub_ret > 0.002) & retina)
        fill(pr_top, pr_bot, LAYER_COLORS["pr"], retina & (pr_t > 0.004))
        fill(outer_top, pr_top, LAYER_COLORS["outer"], retina)
        fill(inner_top, outer_top, LAYER_COLORS["inner"], retina)
        fill(surface, inner_top, LAYER_COLORS["nfl"], retina)
        # photoreceptors: fine vertical lines
        prm = (yy >= pr_top[None, :]) & (yy < pr_bot[None, :]) & retina[None, :]
        stripes = ((np.arange(W) // SS) % 4 == 0)[None, :]
        img[prm & stripes] *= 0.82
        # nuclear layers: speckle
        speck = (_noise((H, W), 3, rng) > 0.9)
        img[((yy >= outer_top[None, :]) & (yy < pr_top[None, :]) & retina[None, :]) & speck] *= 0.85
        if self.through == "disc":
            self._draw_disc(img, yy, surface, rpe_bot, ch_bot)
        for cx, cy, rx, ry in self.cysts:               # fluid spaces inside the retina
            i = int(np.clip(cx, 0, 1) * (W - 1))
            top, bot = surface[i], outer_top[i] + self.outer_t[i] * 0.6
            y = (top + (bot - top) * cy) * H
            cv2.ellipse(img, (int(cx * W), int(y)), (int(rx * W), int(ry * H)), 0, 0, 360, (96, 120, 150), -1, cv2.LINE_AA)
        self.levels = dict(surface=surface, inner_top=inner_top, outer_top=outer_top, pr_top=pr_top, pr_bot=pr_bot,
                           rpe_top=rpe_top, bruch=bruch, choroid_bottom=ch_bot)
        for fn in self.extras:
            fn(img, self)
        img = cv2.GaussianBlur(img, (0, 0), 0.6 * SS)
        out = cv2.resize(np.clip(img, 0, 255).astype(np.uint8), (self.width, self.height), interpolation=cv2.INTER_AREA)
        return out

    def _draw_disc(self, img, yy, surface, rpe_bot, ch_bot) -> None:
        """The optic nerve head: the nerve fibres of the retina bend down into the canal and go on as
        the nerve; the cup is the dip in the middle (deeper and wider as fibres are lost); a swollen
        head bulges up above the retina."""
        W, H = self.W, self.H
        x = self.x
        off = np.abs(x - 0.5)
        cw = self.canal
        inside = off < cw
        i_edge = int(np.argmin(np.abs(off - cw)))
        edge = float(surface[i_edge])
        cupw = cw * (0.25 + 0.75 * self.disc_cup)
        depth = 0.03 + 0.34 * self.disc_cup ** 1.5
        cup = depth * np.clip(1 - (off / cupw) ** 2, 0, 1) ** 0.8
        top = np.where(inside, edge + cup, surface)
        sw = self.disc_swell
        if sw > 0:                                   # the head bulges up and spreads over the retina beside it
            bump = 0.13 * sw * np.clip(1 - (off / (cw * 2.4)) ** 2, 0, 1) ** 0.7
            top = np.minimum(top, np.where(inside, edge - bump + cup * (1 - sw), surface - bump * 0.75))
            over = (yy >= top[None, :]) & (yy < surface[None, :]) & (~inside)[None, :]
            img[over] = (240, 182, 166)
        # the nerve: fibre colour at the top fading to the nerve's below
        t = np.clip((yy - top[None, :]) / 0.35, 0, 1)
        col = np.float32(LAYER_COLORS["nfl"])[None, None, :] * (1 - t[..., None]) + np.float32(LAYER_COLORS["nerve"]) * t[..., None]
        nerve = (yy >= top[None, :]) & inside[None, :]
        img[nerve] = col[nerve]
        # nerve fibres: from the retina, round the edge of the canal and down the nerve
        n_fib = max(2, int(round(9 * self.nfl_scale)))
        for side in (-1, 1):
            for k in range(n_fib):
                f = (k + 0.5) / n_fib
                x0 = 0.5 + side * (cw + 0.10 + 0.30 * f)
                i0 = int(np.clip(x0, 0, 1) * (W - 1))
                y0 = surface[i0] + (self.nfl_t[i0] * self.nfl_scale) * (0.3 + 0.5 * f)
                xe = 0.5 + side * cw * (0.15 + 0.8 * f)
                ie = int(np.clip(xe, 0, 1) * (W - 1))
                ye = top[ie] + 0.06 + 0.10 * f
                pts = _catmull([(x0, y0), (0.5 + side * (cw + 0.03 * f), (y0 + ye) / 2 - 0.02), (xe, ye), (xe * 0.9 + 0.05, 1.02)], 14)
                q = np.int32([(px * W, py * H) for px, py in pts])
                cv2.polylines(img, [q], False, (214, 168, 150), max(1, SS), cv2.LINE_AA)
        mid = int(0.5 * (W - 1))
        lam = (rpe_bot[mid] + ch_bot[mid]) / 2 * H
        x0, x1 = int((0.5 - cw) * W), int((0.5 + cw) * W)
        for d in range(4):                           # the lamina cribrosa
            y = int(lam + d * 5 * SS)
            for xs in range(x0, x1, 8 * SS):
                cv2.line(img, (xs, y), (xs + 5 * SS, y), (176, 160, 150), max(1, SS), cv2.LINE_AA)
        for dx, colv in ((-0.012, ARTERY), (0.012, VEIN)):   # the central artery and vein
            xi = int((0.5 + dx) * W)
            y0 = int((top[xi] + 0.015) * H)
            cv2.line(img, (xi, y0), (xi, H), colv, int(4 * SS), cv2.LINE_AA)
        self.y_surface = top


# -----------------------------------------------------------------------------------------------
# what the patient sees
# -----------------------------------------------------------------------------------------------
@dataclass
class Sight:
    """How a disease changes what one sees (all 0 = normal). Places are in the patient's view: x right,
    y down, 1 = half the picture's width, (0, 0) where the eye looks."""
    blur: float = 0.0                  # all over (pixels at 600 wide)
    center_blur: float = 0.0           # more blur in the middle
    center_dark: float = 0.0           # a dark patch in the middle (0 … 1)
    center_r: float = 0.12
    center_tint: tuple = (20, 20, 22)  # its colour (dark; greyish-brown for fluid)
    center_off: tuple = (0.0, 0.0)
    warp: float = 0.0                  # wavy lines in the middle (metamorphopsia)
    warp_r: float = 0.30
    pinch: float = 0.0                 # lines drawn in to the middle (macular hole) …
    shrink: float = 0.0                # … or things look smaller (micropsia)
    spots: int = 0                     # floaters / blots
    spot_size: float = 0.05
    spot_color: tuple = (30, 18, 16)
    haze: float = 0.0                  # red-brown haze (vitreous blood)
    sector: tuple | None = None        # (from°, to°, strength, inner radius): a dark wedge (0° right, 90° up)
    curtain: tuple | None = None       # (direction°, reach 0 … 2, strength): a shadow from that side
    tunnel: float = 0.0                # field left (radius; 0 = no narrowing)
    ring: tuple | None = None          # (radius, width, strength): a ring of loss
    blind_spot: float = 0.0            # an enlarged blind spot (radius), to the right (temporal, right eye)
    dim: float = 0.0                   # darker overall
    desat: float = 0.0                 # less colour
    flashes: int = 0                   # flashes of light at the edge
    all_dark: float = 0.0              # nearly nothing (0 … 1)
    keep_center: float = 0.0          # … except a little in the middle (radius)


def _apply_sight(img: np.ndarray, s: Sight, scale: float = 1.0) -> np.ndarray:
    """``scale``: how much larger the middle of the view is drawn (an Amsler grid shows the middle 20°)."""
    h, w = img.shape[:2]
    out = img.astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    X, Y = (xx - w / 2) / (w / 2), (yy - h / 2) / (w / 2)
    if s.warp or s.pinch or s.shrink:
        rr = np.hypot(X - s.center_off[0] * scale, Y - s.center_off[1] * scale)
        env = np.exp(-(rr / (s.warp_r * scale)) ** 2)
        dx = s.warp * scale * 0.06 * np.sin(Y / (0.09 * scale) + 1.3) * env + s.warp * scale * 0.03 * np.sin(X / (0.07 * scale)) * env
        dy = s.warp * scale * 0.06 * np.sin(X / (0.11 * scale) + 0.4) * env
        k = (s.pinch * 0.55 * np.exp(-(rr / (0.10 * scale)) ** 2) - s.shrink * 0.35 * env)
        dx = dx + X * k
        dy = dy + Y * k
        mapx = (xx + dx * w / 2).astype(np.float32)
        mapy = (yy + dy * w / 2).astype(np.float32)
        out = cv2.remap(out, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if s.blur:
        out = cv2.GaussianBlur(out, (0, 0), s.blur * w / 600)
    if s.center_blur:
        rr = np.hypot(X - s.center_off[0] * scale, Y - s.center_off[1] * scale)
        env = np.exp(-(rr / (s.center_r * 2.2 * scale)) ** 2)[..., None]
        out = out * (1 - env) + cv2.GaussianBlur(out, (0, 0), s.center_blur * w / 600) * env
    if s.haze:
        blur = cv2.GaussianBlur(out, (0, 0), 4 * w / 600)
        out = out * (1 - s.haze) + (blur * 0.55 + np.float32([90, 30, 22]) * 0.45) * s.haze
    if s.desat:
        g = out.mean(axis=2, keepdims=True)
        out = out * (1 - s.desat) + g * s.desat
    if s.dim:
        out = out * (1 - s.dim)
    keep = np.ones((h, w), np.float32)
    dark = np.float32([16, 16, 18])
    if s.center_dark:
        rr = np.hypot(X - s.center_off[0] * scale, Y - s.center_off[1] * scale) / (s.center_r * scale)
        wob = 1 + 0.12 * np.sin(np.arctan2(Y, X) * 3 + 0.7)
        m = np.clip(1.25 - rr * wob, 0, 1) ** 0.8 * s.center_dark
        out = out * (1 - m[..., None]) + np.float32(s.center_tint) * m[..., None]
    if s.sector is not None:
        lo, hi, st, inner = s.sector
        ang = np.degrees(np.arctan2(-Y, X)) % 360
        inside = (ang >= lo) & (ang <= hi) if lo <= hi else (ang >= lo) | (ang <= hi)
        soft = cv2.GaussianBlur(inside.astype(np.float32), (0, 0), 0.04 * w)
        rr = np.hypot(X, Y)
        soft *= np.clip((rr - inner * scale) / (0.08 * scale), 0, 1)
        keep = np.minimum(keep, 1 - st * soft)
    if s.curtain is not None:
        direction, reach, st = s.curtain
        a = math.radians(direction)
        cx, cy = 2.0 * math.cos(a), -2.0 * math.sin(a)              # far out on that side
        d = np.hypot(X - cx, Y - cy) * (1 + 0.03 * np.sin(np.arctan2(Y - cy, X - cx) * 7))
        m = np.clip(((1.0 + reach) - d) / 0.22 + 0.5, 0, 1)
        keep = np.minimum(keep, 1 - st * np.clip(m, 0, 1))
    if s.tunnel:
        rr = np.hypot(X, Y * 1.1)
        keep = np.minimum(keep, np.clip((s.tunnel - rr) / 0.14 + 0.5, 0, 1))
    if s.ring is not None:
        r0, wid, st = s.ring
        rr = np.hypot(X, Y * 1.1)
        keep = np.minimum(keep, 1 - st * np.exp(-((rr - r0) / wid) ** 2))
    if s.blind_spot:
        rr = np.hypot(X - 0.36 * scale, Y - 0.03 * scale)
        keep = np.minimum(keep, np.clip((rr - s.blind_spot * scale) / (0.07 * scale) + 0.5, 0, 1) * 0.45 + 0.55)
    if s.all_dark:
        rr = np.hypot(X, Y)
        m = s.all_dark * (1 - np.exp(-(rr / max(1e-3, s.keep_center * scale)) ** 2) if s.keep_center else np.ones_like(rr))
        keep = np.minimum(keep, 1 - m)
    if (keep < 1).any():
        k = keep[..., None]
        out = out * k + dark * (1 - k)
    rng = np.random.default_rng(11)
    if s.spots:
        for _ in range(s.spots):
            cx, cy = rng.uniform(0.1, 0.9) * w, rng.uniform(0.1, 0.9) * h
            r = s.spot_size * w * rng.uniform(0.4, 1.2)
            m = np.zeros((h, w), np.float32)
            pts = [(cx, cy)]
            for _ in range(int(rng.integers(2, 6))):                     # a floater: a string of blobs
                cx += rng.normal(0, r * 0.9)
                cy += rng.normal(0, r * 0.9)
                pts.append((cx, cy))
            for (px, py) in pts:
                cv2.circle(m, (int(px), int(py)), int(max(1, r * rng.uniform(0.3, 0.7))), 1.0, -1, cv2.LINE_AA)
            m = cv2.GaussianBlur(m, (0, 0), r * 0.35) * 0.75
            out = out * (1 - m[..., None]) + np.float32(s.spot_color) * m[..., None]
    if s.flashes:
        for _ in range(s.flashes):
            a = rng.uniform(math.radians(150), math.radians(250))
            cx, cy = w / 2 + math.cos(a) * w * 0.42, h / 2 - math.sin(a) * w * 0.28
            m = np.zeros((h, w), np.float32)
            p = (cx, cy)
            for _ in range(5):
                q = (p[0] + rng.normal(0, w * 0.025), p[1] + rng.normal(0, w * 0.025))
                cv2.line(m, (int(p[0]), int(p[1])), (int(q[0]), int(q[1])), 1.0, max(1, w // 200), cv2.LINE_AA)
                p = q
            m = cv2.GaussianBlur(m, (0, 0), w / 400) * 1.0
            glow = cv2.GaussianBlur(m, (0, 0), w / 90) * 1.5
            k = np.clip(m + glow, 0, 1)[..., None]
            out = out * (1 - k) + np.float32([255, 252, 230]) * k
    return np.clip(out, 0, 255).astype(np.uint8)


def vision(scene: np.ndarray, s: Sight) -> np.ndarray:
    """``scene`` as the patient would see it (an example)."""
    return _apply_sight(scene, s)


def amsler_grid(size: int = 300) -> np.ndarray:
    """An Amsler grid: black lines on white, a dot in the middle (20 × 20 squares)."""
    img = np.full((size, size, 3), 250, np.uint8)
    n = 20
    for k in range(n + 1):
        p = int(round(k * (size - 1) / n))
        cv2.line(img, (p, 0), (p, size - 1), (30, 30, 30), 1, cv2.LINE_AA)
        cv2.line(img, (0, p), (size - 1, p), (30, 30, 30), 1, cv2.LINE_AA)
    cv2.circle(img, (size // 2, size // 2), max(2, size // 70), (20, 20, 20), -1, cv2.LINE_AA)
    return img


def amsler(s: Sight, size: int = 300) -> np.ndarray:
    """The Amsler grid as the patient would see it: the middle of the view, about 3.3 × larger."""
    big = 3.3
    t = Sight(**{k: getattr(s, k) for k in s.__dataclass_fields__})
    # what the grid does not show: far edges of the field, floaters, flashes
    t.tunnel, t.ring, t.curtain, t.sector, t.flashes, t.spots, t.blind_spot = 0.0, None, None, None, 0, 0, 0.0
    t.haze = s.haze * 0.6
    t.blur = s.blur * 0.6
    t.center_tint = tuple(min(255, c + 24) for c in s.center_tint) if s.center_tint != (20, 20, 22) else (60, 60, 64)
    return _apply_sight(amsler_grid(size), t, scale=big)
