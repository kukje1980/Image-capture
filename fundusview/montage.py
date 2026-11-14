"""몽타주: several photos of one eye placed on the eyeball and blended into one picture.

Every photo keeps its own camera geometry — field of view, projection and image
circle, the same model the 3D view and the measurements use (``projection.py``) —
and gets a **rotation** ``R``: a pixel maps to a direction ``d`` in the photo's own
frame (its centre on the optical axis, ``d = (0, 0, -1)``) and to ``R @ d`` on the
eye. Placing photos is therefore a rotation on the sphere, exact also for
ultra-wide-field shots where a flat 2D montage would bend.

* 자동 (``auto_align``): SIFT points on the vessel-enhanced green channel, matched
  between every pair of photos; the rotation between two photos comes from the
  matched directions (RANSAC + Kabsch) and, optionally, a correction of the field
  of view. The best-connected tree from the reference photo places the others,
  then every photo is refined against all its placed neighbours.
* 기준점 (``align_points``): the user clicks the same spot (a vessel crossing)
  on two photos; two or more pairs give the rotation directly.
* 수동: the editor rotates a photo so the point under the mouse follows it
  (``rotation_between``), or turns it about its own centre (``roll_about``).

``render`` draws the result as an azimuthal-equidistant map around the posterior
pole of the reference photo — distance from the centre is proportional to the
angle on the retina, so the 3D view shows it with the ``equidistant``
projection and the field of view ``2 · angle`` without further calibration.
Brightness is matched between the photos (gains from their overlaps) and the
photos are blended in two bands: the broad brightness with soft weights that
fade towards each photo's edge (no seams), the fine detail from the photo that
sees that place best (no doubled vessels).
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np

from . import projection as proj

try:                         # OpenCV: features, fast resampling, blurs
    import cv2
except ImportError:          # pragma: no cover - listed in requirements.txt
    cv2 = None

MIN_INLIERS = 12             # matched points that must agree before two photos are linked
WORK_SIDE = 1600             # photos are aligned and drawn from copies at most this size
EDGE_SPAN = 0.25             # distances from the edge of a photo are kept up to this (× circle radius)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def _unit(v):
    v = np.asarray(v, np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n > 0, n, 1.0)


def kabsch(src: np.ndarray, dst: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """Rotation ``R`` (3×3, det +1) that best maps unit vectors ``src`` onto ``dst`` (``R @ s ≈ d``)."""
    src, dst = np.asarray(src, np.float64), np.asarray(dst, np.float64)
    w = np.ones(len(src)) if weights is None else np.asarray(weights, np.float64)
    h = (src * w[:, None]).T @ dst
    u, _, vt = np.linalg.svd(h)
    s = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(vt.T @ u.T)) or 1.0)])
    return vt.T @ s @ u.T


def rotation_between(a, b) -> np.ndarray:
    """Smallest rotation turning direction ``a`` into direction ``b``."""
    a, b = _unit(a), _unit(b)
    v = np.cross(a, b)
    s, c = float(np.linalg.norm(v)), float(a @ b)
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        p = np.cross(a, [1.0, 0.0, 0.0] if abs(a[0]) < 0.9 else [0.0, 1.0, 0.0])
        return axis_angle(p, math.pi)
    return axis_angle(v / s, math.atan2(s, c))


def axis_angle(axis, angle: float) -> np.ndarray:
    k = _unit(axis)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(angle) * kx + (1 - math.cos(angle)) * (kx @ kx)


def angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Angles (degrees) between rows of unit vectors ``a`` and ``b``."""
    return np.degrees(np.arccos(np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)))


def _g(theta, projection: str, d: float, tmax: float, c: float):
    """Vectorised ``projection.g`` for the radius on the photo (``radial``: already normalised)."""
    t = np.asarray(theta, np.float64)
    if projection == "stereographic":
        return np.tan(t / 2.0)
    if projection == "equidistant":
        return t
    if projection == "orthographic":
        return np.sin(np.minimum(t, math.pi / 2))
    if projection == "radial":
        s = t / tmax
        if c <= 1e-9:
            return s
        p, q = (1.0 - c) / c, -s / c
        disc = np.sqrt((q / 2.0) ** 2 + (p / 3.0) ** 3)
        return np.cbrt(-q / 2.0 + disc) + np.cbrt(-q / 2.0 - disc)
    den = np.cos(t) + d
    return np.where(den > 1e-6, np.sin(t) / np.maximum(den, 1e-6), np.inf)


def _theta(gval, projection: str, d: float, tmax: float, c: float):
    """Inverse of ``_g``."""
    g = np.asarray(gval, np.float64)
    if projection == "stereographic":
        return 2.0 * np.arctan(g)
    if projection == "equidistant":
        return g
    if projection == "orthographic":
        return np.arcsin(np.clip(g, -1.0, 1.0))
    if projection == "radial":
        return tmax * ((1.0 - c) * g + c * g ** 3)
    a = np.arctan(g)                     # tan(alpha) = sin(t) / (cos(t) + d)  →  t = a + asin(d sin a)
    return a + np.arcsin(np.clip(d * np.sin(a), -1.0, 1.0))


@dataclass
class Shot:
    """One photo of the montage, on a working copy (``scale`` = original pixels per working pixel)."""
    rgb: np.ndarray
    alpha: np.ndarray                     # uint8: 255 on the illuminated retina
    circle: tuple[float, float, float]    # image circle on the working copy (cx, cy, r)
    fov_deg: float
    fov_type: str = "internal"
    projection: str = "equidistant"
    viewpoint: float = proj.DEFAULT_VIEWPOINT
    radial_c: float = proj.DEFAULT_RADIAL_C
    image_id: int | None = None
    label: str = ""
    scale: float = 1.0
    R: np.ndarray = field(default_factory=lambda: np.eye(3))
    gain: np.ndarray = field(default_factory=lambda: np.ones(3))
    fov_scale: float = 1.0                # correction found by 자동 (1 = as given)
    cut: np.ndarray | None = field(default=None, repr=False, compare=False)   # uint8, 255 = glare / flare left out
    _edge: np.ndarray | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_photo(cls, rgb: np.ndarray, alpha: np.ndarray | None, circle, *, max_side: int = WORK_SIDE,
                   **geometry) -> "Shot":
        h, w = rgb.shape[:2]
        k = min(1.0, max_side / max(h, w))
        if alpha is None:
            alpha = np.full((h, w), 255, np.uint8)
        if k < 1.0:
            size = (max(1, round(w * k)), max(1, round(h * k)))
            rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
            alpha = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)
        cx, cy, r = circle
        return cls(np.ascontiguousarray(rgb), np.ascontiguousarray(alpha), (cx * k, cy * k, r * k),
                   scale=1.0 / k, **geometry)

    # -- geometry ------------------------------------------------------------
    @property
    def tmax(self) -> float:
        """Half internal field of view (radians), with the correction of 자동."""
        return proj.theta_max(self.fov_deg, self.fov_type, self.viewpoint) * self.fov_scale

    def _gmax(self) -> float:
        return float(_g(self.tmax, self.projection, self.viewpoint, self.tmax, self.radial_c))

    def dirs(self, uv: np.ndarray) -> np.ndarray:
        """Pixels (N×2, working copy) → unit directions in the photo's own frame."""
        uv = np.asarray(uv, np.float64).reshape(-1, 2)
        cx, cy, r = self.circle
        dx, dy = (uv[:, 0] - cx) / r, (cy - uv[:, 1]) / r
        rho = np.hypot(dx, dy)
        th = _theta(rho * self._gmax(), self.projection, self.viewpoint, self.tmax, self.radial_c)
        ph = np.arctan2(dy, dx)
        s = np.sin(th)
        return np.stack([s * np.cos(ph), s * np.sin(ph), -np.cos(th)], axis=1)

    def pixels(self, d: np.ndarray):
        """Unit directions in the photo's frame → pixel coordinates (u, v) and the ``rho`` (0 … 1 at the edge)."""
        d = np.asarray(d, np.float64)
        th = np.arctan2(np.hypot(d[..., 0], d[..., 1]), -d[..., 2])
        ph = np.arctan2(d[..., 1], d[..., 0])
        gm = self._gmax()
        rho = _g(np.minimum(th, math.pi - 1e-6), self.projection, self.viewpoint, self.tmax, self.radial_c) / gm
        rho = np.where(th <= self.tmax + 1e-9, rho, np.inf)
        cx, cy, r = self.circle
        rr = np.where(np.isfinite(rho), rho, 0.0) * r        # outside the field: (cx, cy), rho = inf
        return cx + rr * np.cos(ph), cy - rr * np.sin(ph), rho

    def edge_image(self) -> np.ndarray:
        """Distance of every pixel from the edge of what the photo shows — the image circle, a frame
        that crops it (4:3 cameras), masked text or eyelashes — as uint8 (255 = ``EDGE_SPAN`` radii)."""
        if self._edge is None:
            h, w = self.alpha.shape
            cx, cy, r = self.circle
            yy, xx = np.ogrid[0:h, 0:w]
            m = ((self.alpha > 128) & ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r)).astype(np.uint8)
            m = cv2.copyMakeBorder(m, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)   # the frame is an edge too
            d = cv2.distanceTransform(m, cv2.DIST_L2, 5)[1:-1, 1:-1]
            self._edge = np.clip(d * (255.0 / (EDGE_SPAN * r)), 0, 255).astype(np.uint8)
        return self._edge

    def outline(self, n: int = 180) -> np.ndarray:
        """The edge of what the photo shows on the eye: its image circle, cut by the frame."""
        cx, cy, r = self.circle
        h, w = self.alpha.shape
        a = np.linspace(0.0, 2 * math.pi, n)
        c, s_ = np.cos(a), -np.sin(a)                   # image y runs down
        with np.errstate(divide="ignore", invalid="ignore"):
            tx = np.where(c > 1e-9, (w - 0.5 - cx) / c, np.where(c < -1e-9, (-0.5 - cx) / c, np.inf))
            ty = np.where(s_ > 1e-9, (h - 0.5 - cy) / s_, np.where(s_ < -1e-9, (-0.5 - cy) / s_, np.inf))
        t = np.minimum(np.minimum(tx, ty), r * 0.999)
        uv = np.stack([cx + t * c, cy + t * s_], axis=1)
        return self.dirs(uv) @ self.R.T

    def centre(self) -> np.ndarray:
        """Where the centre of the photo lies on the eye."""
        return self.R @ np.array([0.0, 0.0, -1.0])

    def edge_world(self, n: int = 180) -> np.ndarray:
        """The edge of the photographed field on the eye (for drawing outlines)."""
        a = np.linspace(0.0, 2 * math.pi, n)
        t = self.tmax
        d = np.stack([np.sin(t) * np.cos(a), np.sin(t) * np.sin(a), np.full_like(a, -math.cos(t))], axis=1)
        return d @ self.R.T

    def to_json(self) -> dict:
        return {"image_id": self.image_id, "R": [float(x) for x in self.R.reshape(-1)],
                "fov_deg": self.fov_deg, "fov_type": self.fov_type, "projection": self.projection,
                "fov_scale": self.fov_scale, "gain": [float(x) for x in self.gain],
                "radial_c": float(self.radial_c)}

    def apply_json(self, d: dict) -> None:
        for k in ("fov_deg", "fov_type", "projection"):
            if d.get(k):
                setattr(self, k, float(d[k]) if k == "fov_deg" else str(d[k]))
        if d.get("R") and len(d["R"]) == 9:
            self.R = np.asarray(d["R"], np.float64).reshape(3, 3)
        self.fov_scale = float(d.get("fov_scale", 1.0) or 1.0)
        if d.get("radial_c") is not None:
            self.radial_c = float(d["radial_c"])
        if d.get("gain") and len(d["gain"]) == 3:
            self.gain = np.asarray(d["gain"], np.float64)


def roll_about(shot: Shot, degrees: float) -> None:
    """Turn a photo about its own centre, counter-clockwise on the map (and on the photo)."""
    shot.R = axis_angle(shot.centre(), -math.radians(degrees)) @ shot.R


def plane_dirs(x, y) -> np.ndarray:
    """The map plane (azimuthal equidistant around the pole ``(0, 0, -1)``, radians, y up) → directions."""
    x, y = np.asarray(x, np.float64), np.asarray(y, np.float64)
    th = np.hypot(x, y)
    ph = np.arctan2(y, x)
    s = np.sin(th)
    return np.stack([s * np.cos(ph), s * np.sin(ph), -np.cos(th)], axis=-1)


def plane_xy(d) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of ``plane_dirs``."""
    d = np.asarray(d, np.float64)
    th = np.arctan2(np.hypot(d[..., 0], d[..., 1]), -d[..., 2])
    ph = np.arctan2(d[..., 1], d[..., 0])
    return th * np.cos(ph), th * np.sin(ph)


def move_on_plane(shot: Shot, dx: float, dy: float) -> None:
    """Slide a photo towards (dx, dy) on the map, by ``hypot(dx, dy)`` radians on the eye (이동 keys)."""
    step = math.hypot(dx, dy)
    if step <= 0.0:
        return
    c = shot.centre()
    x, y = plane_xy(c)
    eps = 1e-5
    ahead = plane_dirs(float(x) + dx / step * eps, float(y) + dy / step * eps)
    axis = np.cross(c, ahead - c)
    if np.linalg.norm(axis) < 1e-15:
        return
    shot.R = axis_angle(axis, step) @ shot.R


def recentre(shots: list[Shot], k: int) -> None:
    """Make photo ``k`` the centre of the montage (the posterior pole of the map and of the 3D eye)."""
    inv = shots[k].R.T.copy()
    for s in shots:
        s.R = inv @ s.R


def most_central(shots: list[Shot], among=None) -> int:
    """The photo nearest the middle of the others (a good centre for the montage)."""
    idx = list(range(len(shots)) if among is None else among)
    if not idx:
        return 0
    mean = _unit(np.sum([shots[k].centre() for k in idx], axis=0))
    return max(idx, key=lambda k: float(shots[k].centre() @ mean))


def spread(shots: list[Shot], ref: int = 0) -> None:
    """Starting layout before anything is matched: ``ref`` in the middle, the others around it, overlapping
    a little, so each can be seen and dragged."""
    others = [k for k in range(len(shots)) if k != ref]
    shots[ref].R = np.eye(3)
    for n, k in enumerate(others):
        a = 2 * math.pi * n / max(1, len(others)) + math.pi / 2
        t = shots[ref].tmax + 0.6 * shots[k].tmax
        shots[k].R = rotation_between([0.0, 0.0, -1.0], plane_dirs(t * math.cos(a), t * math.sin(a)))


def shot_at(shots: list[Shot], d, prefer: int | None = None) -> int | None:
    """The photo that shows direction ``d`` (``prefer`` if it does, else the one seeing it most centrally)."""
    best, best_rho = None, math.inf
    for k, s in enumerate(shots):
        u, v, rho = s.pixels(np.asarray(d, np.float64) @ s.R)
        rho = float(rho)
        if not math.isfinite(rho) or rho > 1.0:
            continue
        x, y = int(u), int(v)
        if not (0 <= x < s.alpha.shape[1] and 0 <= y < s.alpha.shape[0]) or s.alpha[y, x] < 64:
            continue
        if k == prefer:
            return k
        if rho < best_rho:
            best, best_rho = k, rho
    return best


# ---------------------------------------------------------------------------
# alignment
# ---------------------------------------------------------------------------
@dataclass
class Features:
    dirs: np.ndarray        # N×3 unit directions in the photo's frame
    desc: np.ndarray        # N×128 SIFT descriptors
    uv: np.ndarray          # N×2 pixels (working copy)


def _vessel_image(shot: Shot) -> np.ndarray:
    g = shot.rgb[..., 1]
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(np.ascontiguousarray(g))


def _coarse_vessels(shot: Shot, scale: float) -> np.ndarray:
    """The vessels alone at a reduced size: smoothed against noise, the uneven light taken out, dark
    lines turned into bright ones. Blurred, noisy or pale photos still give points here."""
    g = cv2.GaussianBlur(np.ascontiguousarray(shot.rgb[..., 1]), (0, 0), 1.0 / scale)
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    g = cv2.medianBlur(g, 5)
    k = max(9, int(round(min(g.shape) * 0.035)) | 1)
    v = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    v = cv2.GaussianBlur(v, (0, 0), 1.2)
    hi = float(np.percentile(v, 99.7)) or 1.0
    return np.clip(v.astype(np.float32) * (255.0 / hi), 0, 255).astype(np.uint8)


COARSE = 0.5        # size of the second, coarser look at the vessels


def features(shot: Shot, n: int = 3000) -> Features:
    """SIFT points away from the edge of the field: on the vessel-enhanced green channel, and a
    second set on the vessels alone at half size (what is left when a photo is blurred or noisy)."""
    img = _vessel_image(shot)
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy, r = shot.circle
    inner = ((xx - cx) ** 2 + (yy - cy) ** 2 <= (0.96 * r) ** 2) & (shot.alpha > 128)
    mask = cv2.erode(inner.astype(np.uint8) * 255, np.ones((9, 9), np.uint8))
    uvs, descs = [], []
    kps, desc = cv2.SIFT_create(nfeatures=n, contrastThreshold=0.015).detectAndCompute(img, mask)
    if desc is not None and kps:
        uvs.append(np.array([k.pt for k in kps], np.float64))
        descs.append(desc)
    coarse = _coarse_vessels(shot, COARSE)
    cmask = cv2.resize(mask, (coarse.shape[1], coarse.shape[0]), interpolation=cv2.INTER_NEAREST)
    cmask = cv2.erode(cmask, np.ones((7, 7), np.uint8))
    kps, desc = cv2.SIFT_create(nfeatures=n // 2, contrastThreshold=0.02).detectAndCompute(coarse, cmask)
    if desc is not None and kps:
        uvs.append(np.array([k.pt for k in kps], np.float64) / COARSE)
        descs.append(desc)
    if not uvs:
        return Features(np.zeros((0, 3)), np.zeros((0, 128), np.float32), np.zeros((0, 2)))
    uv = np.concatenate(uvs)
    return Features(shot.dirs(uv), np.concatenate(descs), uv)


def match(fa: Features, fb: Features, ratio: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """Indices of mutual best matches passing Lowe's ratio test."""
    if len(fa.desc) < 2 or len(fb.desc) < 2:
        return np.zeros(0, int), np.zeros(0, int)
    bf = cv2.BFMatcher(cv2.NORM_L2)
    ab = bf.knnMatch(fa.desc, fb.desc, k=2)
    ba = {m.queryIdx: m.trainIdx for m in bf.match(fb.desc, fa.desc)}
    ia, ib = [], []
    for pair in ab:
        if len(pair) < 2:
            continue
        m, n2 = pair
        if m.distance < ratio * n2.distance and ba.get(m.trainIdx) == m.queryIdx:
            ia.append(m.queryIdx)
            ib.append(m.trainIdx)
    return np.asarray(ia, int), np.asarray(ib, int)


def ransac_rotation(src: np.ndarray, dst: np.ndarray, thresh_deg: float = 1.0, iters: int = 1500,
                    seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Rotation mapping ``src`` onto ``dst`` despite wrong matches; returns (R, inlier mask)."""
    n = len(src)
    if n < 3:
        return np.eye(3), np.zeros(n, bool)
    rng = np.random.default_rng(seed)
    best = np.zeros(n, bool)
    for _ in range(iters):
        i, j = rng.choice(n, 2, replace=False)
        if abs(float(src[i] @ src[j])) > 0.99995:          # too close to define a rotation
            continue
        r = kabsch(src[[i, j]], dst[[i, j]])
        inl = angle_deg(src @ r.T, dst) < thresh_deg
        if inl.sum() > best.sum():
            best = inl
            if best.sum() > 0.8 * n:
                break
    if best.sum() < 3:
        return np.eye(3), best
    r = kabsch(src[best], dst[best])
    for _ in range(2):                                    # settle on the consensus
        inl = angle_deg(src @ r.T, dst) < thresh_deg
        if inl.sum() < 3:
            break
        r = kabsch(src[inl], dst[inl])
        best = inl
    return r, best


@dataclass
class PairResult:
    i: int
    j: int
    R_ji: np.ndarray        # maps photo j's frame onto photo i's frame
    idx_i: np.ndarray       # inlier feature indices
    idx_j: np.ndarray

    @property
    def n(self) -> int:
        return len(self.idx_i)


@dataclass
class AlignReport:
    placed: list[int]
    unplaced: list[int]
    residual_deg: float     # median angle between matched points after alignment
    links: int              # photo pairs that were matched
    lens: str = ""          # the lens model found from the photos themselves, if it replaced the given one
    masked: int = 0         # photos with glare or a flare spot left out of the blend

    def text(self) -> str:
        n = len(self.placed) + len(self.unplaced)
        msg = f"{len(self.placed)}/{n}장 맞춤"
        if self.placed and self.links:
            msg += f" · 맞춘 점의 오차 {self.residual_deg:.2f}°"
        if self.lens:
            msg += f" · {self.lens}"
        if self.masked:
            msg += f" · 반사·플레어 가림 {self.masked}장"
        if self.unplaced:
            msg += f" · 겹치는 곳을 찾지 못한 사진 {len(self.unplaced)}장은 손으로 옮기거나 기준점으로 맞추세요"
        return msg


def _pair(shots, feats, i, j, refine_fov: bool) -> PairResult | None:
    # the usual strict matching first; poor photos get a second, looser try whose wrong matches the
    # rotation consensus has to throw out — so it asks for more agreeing points
    for ratio, need in ((0.8, MIN_INLIERS), (0.92, 2 * MIN_INLIERS)):
        ia, ib = match(feats[i], feats[j], ratio)
        if len(ia) < need:
            continue
        r, inl = ransac_rotation(feats[j].dirs[ib], feats[i].dirs[ia], iters=1500 if ratio == 0.8 else 4000)
        if inl.sum() >= need:
            return PairResult(i, j, r, ia[inl], ib[inl])
    return None


def _refine_fov(shot: Shot, own_uv: np.ndarray, targets: np.ndarray) -> None:
    """Correct the photo's field of view (±15 %) so its matched points land best on ``targets``."""
    def cost(k):                                          # trimmed mean: smooth in k, deaf to stray points
        shot.fov_scale = k
        d = shot.dirs(own_uv)
        r = kabsch(d, targets)
        e = np.sort(angle_deg(d @ r.T, targets))
        return float(e[: max(3, int(len(e) * 0.8))].mean()), r

    base, _ = cost(1.0)
    ks = np.linspace(0.85, 1.15, 13)
    costs = [cost(k)[0] for k in ks]
    k0 = float(ks[int(np.argmin(costs))])
    for step in (0.0125, 0.004):                         # refine around the best
        trial = [k0 - step, k0, k0 + step]
        k0 = min(trial, key=lambda k: cost(k)[0])
    best, r = cost(k0)
    if best < 0.8 * base:
        shot.fov_scale, shot.R = k0, r
    else:
        shot.fov_scale = 1.0
        shot.R = kabsch(shot.dirs(own_uv), targets)


# -- the lens, from the photos themselves ---------------------------------------------------------
WIDE = ("radial", "equidistant")      # wide-field lenses: angle ≈ a curve of the image radius
CAL_FOVS = (0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15)     # × the field of view as given
CAL_CS = (-0.15, 0.0, 0.15, 0.2545, 0.4)
CAL_GAIN = 1.3                        # that many times more agreeing points before the given lens is dropped


def _frames(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Orthonormal frames (H×3×3, rows = axes) spanned by pairs of unit vectors."""
    e1 = u
    e3 = np.cross(u, v)
    e3 /= np.maximum(np.linalg.norm(e3, axis=1, keepdims=True), 1e-12)
    e2 = np.cross(e3, e1)
    return np.stack([e1, e2, e3], axis=1)


def quick_rotation(src: np.ndarray, dst: np.ndarray, thresh_deg: float, tries: int = 200,
                   seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """``ransac_rotation`` for many candidates at once: every try is the rotation that carries two
    matched points onto their partners, all tries are scored together, and the best is settled on
    its agreeing points. Used where the same matches are fitted again and again (the lens search)."""
    n = len(src)
    if n < 3:
        return np.eye(3), np.zeros(n, bool)
    rng = np.random.default_rng(seed)
    i, j = rng.integers(0, n, tries), rng.integers(0, n, tries)
    ok = (i != j) & (np.abs(np.einsum("ij,ij->i", src[i], src[j])) < 0.99995)
    i, j = i[ok], j[ok]
    if len(i) == 0:
        return np.eye(3), np.zeros(n, bool)
    fa, fb = _frames(src[i], src[j]), _frames(dst[i], dst[j])
    rot = np.einsum("hki,hkj->hij", fb, fa)                  # R = Fbᵀ·Fa: src frame → dst frame
    moved = np.einsum("hij,nj->hni", rot, src)               # H × N × 3
    cos = np.clip(np.einsum("hni,ni->hn", moved, dst), -1.0, 1.0)
    inl = cos > math.cos(math.radians(thresh_deg))
    best = inl[int(np.argmax(inl.sum(axis=1)))]
    if best.sum() < 3:
        return np.eye(3), best
    r = kabsch(src[best], dst[best])
    for _ in range(2):
        again = angle_deg(src @ r.T, dst) < thresh_deg
        if again.sum() < 3:
            break
        r, best = kabsch(src[again], dst[again]), again
    return r, best


def _agree(shots, feats, matches, thresh_share: float = 0.003) -> tuple[int, float]:
    """Matched points that agree on one rotation per photo pair, and their median error (°). The
    tolerance is a share of the field, so a smaller field of view gets no advantage."""
    total, res = 0, []
    for (i, j), (ia, ib) in matches.items():
        if len(ia) < 6:
            continue
        a, b = shots[i].dirs(feats[i].uv[ia]), shots[j].dirs(feats[j].uv[ib])
        thr = thresh_share * math.degrees(shots[i].tmax)
        r, inl = quick_rotation(b, a, thr, tries=200)
        total += int(inl.sum())
        if inl.sum() >= 3:
            res.append(angle_deg(b[inl] @ r.T, a[inl]))
    return total, (float(np.median(np.concatenate(res))) if res else 0.0)


def calibrate_lens(shots: list[Shot], feats, matches) -> str:
    """Wide-field photos of one camera: try other fields of view and lens curves (``radial``) on the
    matched vessels of the series and keep the one on which clearly more of them agree. The
    camera's own numbers are a guess until it is calibrated; the overlap of a series measures them.
    Returns a note for the report, "" when the given lens stays."""
    first = shots[0]
    same = all((s.projection, s.fov_type, round(s.fov_deg, 3), round(s.radial_c, 4)) ==
               (first.projection, first.fov_type, round(first.fov_deg, 3), round(first.radial_c, 4)) for s in shots)
    if not same or first.projection not in WIDE or sum(len(m[0]) for m in matches.values()) < 40:
        return ""
    given = (first.projection, first.fov_deg, first.radial_c)

    def use(fov: float, c: float) -> None:
        for s in shots:
            s.projection, s.fov_deg, s.radial_c, s.fov_scale = "radial", fov, c, 1.0

    base, _ = _agree(shots, feats, matches)
    best = (base, given[1], given[2] if given[0] == "radial" else 0.0)
    for k in CAL_FOVS:
        for c in CAL_CS:
            use(given[1] * k, c)
            n, _ = _agree(shots, feats, matches)
            if n > best[0]:
                best = (n, given[1] * k, c)
    # a closer look around the best
    n0, f0, c0 = best
    for df in (-0.08, -0.04, 0.04, 0.08):
        for dc in (-0.07, 0.0, 0.07):
            use(f0 * (1 + df), c0 + dc)
            n, _ = _agree(shots, feats, matches)
            if n > best[0]:
                best = (n, f0 * (1 + df), c0 + dc)
    if best[0] < CAL_GAIN * max(base, 1) or best[0] < 30:
        for s in shots:
            s.projection, s.fov_deg, s.radial_c, s.fov_scale = given[0], given[1], given[2], 1.0
        return ""
    best = (best[0], round(best[1], 1), round(best[2], 3))
    use(best[1], best[2])
    return f"렌즈 보정 {given[1]:.0f}° → {best[1]:.0f}° (일치점 {base} → {best[0]})"


# -- what is not retina: eyelid glare, flare spots ------------------------------------------------
MASK_SIDE = 480      # glare and flare are large and soft: they are looked for on a small copy


def _small(shot: Shot) -> Shot:
    h, w = shot.alpha.shape
    k = min(1.0, MASK_SIDE / max(h, w))
    if k >= 1.0:
        return shot
    size = (max(1, round(w * k)), max(1, round(h * k)))
    cx, cy, r = shot.circle
    return dataclasses.replace(shot, rgb=cv2.resize(shot.rgb, size, interpolation=cv2.INTER_AREA),
                               alpha=cv2.resize(shot.alpha, size, interpolation=cv2.INTER_AREA),
                               circle=(cx * k, cy * k, r * k), cut=None)


def _full_mask(mask: np.ndarray, shot: Shot) -> np.ndarray:
    h, w = shot.alpha.shape
    if mask.shape == (h, w):
        return mask
    return (cv2.resize(mask * 255, (w, h), interpolation=cv2.INTER_LINEAR) > 127).astype(np.uint8)


def _bright_blobs(shot: Shot) -> np.ndarray:
    """Soft bright spots that stand out from their surroundings (flare, reflections)."""
    g = cv2.GaussianBlur(shot.rgb[..., 1], (0, 0), 2.0 * shot.circle[2] / 760.0).astype(np.float32)
    cx, cy, r = shot.circle
    # the surroundings of a pixel = the lit field around it (the black outside does not count), and
    # the rim of the field is left alone: it is bright against the outside in every photo
    lit = (shot.alpha > 128).astype(np.float32)
    back = cv2.GaussianBlur(g * lit, (0, 0), 0.12 * r) / np.maximum(cv2.GaussianBlur(lit, (0, 0), 0.12 * r), 1e-3)
    k = max(3, int(0.08 * r) | 1)
    inner = cv2.erode((lit > 0).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    yy, xx = np.ogrid[0:g.shape[0], 0:g.shape[1]]
    inner[(xx - cx) ** 2 + (yy - cy) ** 2 > (0.9 * r) ** 2] = 0
    return (((g - back) > 22.0) & (inner > 0)).astype(np.uint8)


def _glare(shot: Shot) -> np.ndarray:
    """Washed-out light at the edge of the field (eyelid, lashes): bright, wide and reaching the rim."""
    cx, cy, r = shot.circle
    sig = max(0.6, 3.0 * r / 760.0)
    v = cv2.GaussianBlur(shot.rgb.max(axis=2), (0, 0), sig)
    g = cv2.GaussianBlur(shot.rgb[..., 1], (0, 0), sig)
    bright = ((v > 200) & (g > 120) & (shot.alpha > 128)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
    yy, xx = np.ogrid[0:bright.shape[0], 0:bright.shape[1]]
    rim = ((xx - cx) ** 2 + (yy - cy) ** 2) > (0.9 * r) ** 2
    out = np.zeros_like(bright)
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < 0.02 * math.pi * r * r:
            continue                                   # the optic disc is small, even at the edge of a photo
        m = lab == k
        if (m & rim).any():
            out[m] = 1
    if out.any():
        grow = max(3, int(0.1 * r) | 1)
        out = cv2.dilate(out, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow)))
    return out


def mask_artifacts(shots: list[Shot], placed: list[int]) -> int:
    """Leave out of the blend what the camera added: eyelid glare, and bright spots that sit at the
    same place of the picture in photos taken at different gazes (a flare of the lens — the retina
    would have moved). Changes ``alpha`` of the working copies; returns how many photos were cut."""
    small = {k: _small(shots[k]) for k in placed}
    blobs = {k: _bright_blobs(small[k]) for k in placed}
    cut = 0
    for k in placed:
        s = shots[k]
        bad = _glare(small[k])
        r = small[k].circle[2]
        still = np.zeros_like(bad)
        votes = 0
        for j in placed:
            if j == k or blobs[j].shape != blobs[k].shape:
                continue
            moved = float(angle_deg(s.centre()[None], shots[j].centre()[None])[0])
            if moved < 4.0:                             # the same gaze: the retina is at the same place too
                continue
            votes += 1
            still = still + (blobs[k] & cv2.dilate(blobs[j], np.ones((3, 3), np.uint8)))
        if votes:
            flare = (still >= max(1, math.ceil(0.5 * votes))).astype(np.uint8)
            if flare.any():
                grow = int(0.05 * r) | 1
                bad = bad | cv2.dilate(flare, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow)))
        if bad.any():
            bad = _full_mask(bad, s)
            r = s.circle[2]
            a = s.alpha.copy()
            a[bad > 0] = 0
            s.alpha = cv2.GaussianBlur(a, (0, 0), max(1.0, 0.004 * r))
            s.cut = np.maximum(s.cut, bad * 255) if s.cut is not None else (bad * 255).astype(np.uint8)
            s._edge = None
            cut += 1
    return cut


def auto_align(shots: list[Shot], ref: int = 0, *, refine_fov: bool = True, progress=None,
               calibrate: bool = True, mask: bool = True) -> AlignReport:
    """Place every photo relative to ``shots[ref]`` (whose rotation is kept) from matched vessels."""
    n = len(shots)
    say = progress or (lambda *_: None)
    feats = []
    for k, s in enumerate(shots):
        say(f"혈관 특징점 찾는 중 ({k + 1}/{n})")
        feats.append(features(s))
    lens = ""
    if calibrate and n >= 2:
        say("렌즈 보정 확인 중")
        loose = {(i, j): match(feats[i], feats[j], 0.85) for i in range(n) for j in range(i + 1, n)}
        lens = calibrate_lens(shots, feats, loose)
        if lens:
            for k, s in enumerate(shots):
                feats[k].dirs = s.dirs(feats[k].uv)
    pairs: dict[tuple[int, int], PairResult] = {}
    for i in range(n):
        for j in range(i + 1, n):
            say(f"겹치는 곳 맞추는 중 ({i + 1}↔{j + 1})")
            pr = _pair(shots, feats, i, j, refine_fov)
            if pr is not None:
                pairs[(i, j)] = pr

    # maximum spanning tree from the reference (most shared points first)
    placed, order = {ref}, []
    while True:
        best = None
        for (i, j), pr in pairs.items():
            if (i in placed) != (j in placed) and (best is None or pr.n > best.n):
                best = pr
        if best is None:
            break
        new = best.j if best.i in placed else best.i
        order.append((best, new))
        placed.add(new)
    for pr, new in order:
        if new == pr.j:                                     # j's frame → i's frame → eye
            shots[new].R = shots[pr.i].R @ pr.R_ji
        else:
            shots[new].R = shots[pr.j].R @ pr.R_ji.T

    # refine each photo against all its placed neighbours (and its field of view)
    def world_targets(k):
        own, tgt = [], []
        for (i, j), pr in pairs.items():
            # the neighbour's directions from its current field of view (자동 may have corrected it)
            if k == i and j in placed:
                own.append(feats[i].uv[pr.idx_i])
                tgt.append(shots[j].dirs(feats[j].uv[pr.idx_j]) @ shots[j].R.T)
            elif k == j and i in placed:
                own.append(feats[j].uv[pr.idx_j])
                tgt.append(shots[i].dirs(feats[i].uv[pr.idx_i]) @ shots[i].R.T)
        if not own:
            return None, None
        return np.concatenate(own), np.concatenate(tgt)

    sweeps = 5
    for sweep in range(sweeps):
        say(f"전체 맞추는 중 ({sweep + 1}/{sweeps})")
        for k in placed:
            if k == ref:
                continue
            uv, tgt = world_targets(k)
            if uv is None or len(uv) < MIN_INLIERS:
                continue
            if refine_fov and sweep < 2 and len(uv) >= 30:
                _refine_fov(shots[k], uv, tgt)
            else:
                shots[k].R = kabsch(shots[k].dirs(uv), tgt)

    res = []
    for (i, j), pr in pairs.items():
        if i in placed and j in placed:
            a = shots[i].dirs(feats[i].uv[pr.idx_i]) @ shots[i].R.T
            b = shots[j].dirs(feats[j].uv[pr.idx_j]) @ shots[j].R.T
            res.append(angle_deg(a, b))
    resid = float(np.median(np.concatenate(res))) if res else 0.0
    masked = 0
    if mask and len(placed) >= 2:
        say("반사 · 플레어 가리는 중")
        masked = mask_artifacts(shots, sorted(placed))
    return AlignReport(sorted(placed), sorted(set(range(n)) - placed), resid,
                       sum(1 for (i, j) in pairs if i in placed and j in placed), lens, masked)


def align_points(moving: Shot, moving_uv, anchor: Shot, anchor_uv) -> float:
    """기준점: rotate ``moving`` so its clicked points meet the same points of ``anchor``.
    Two or more pairs (working-copy pixels). Returns the remaining error (degrees, the largest pair)."""
    mu, au = np.asarray(moving_uv, np.float64), np.asarray(anchor_uv, np.float64)
    if len(mu) < 2 or len(mu) != len(au):
        raise ValueError("두 사진에서 같은 곳을 두 군데 이상 찍어 주세요")
    target = anchor.dirs(au) @ anchor.R.T
    src = moving.dirs(mu)
    if len(mu) >= 4:                                      # enough points: the field of view may be corrected too
        _refine_fov(moving, mu, target)
    else:
        moving.R = kabsch(src, target)
    return float(angle_deg(moving.dirs(mu) @ moving.R.T, target).max())


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------
@dataclass
class MapGeometry:
    """Azimuthal-equidistant map of the eye around the posterior pole: pixel ↔ direction."""
    size: int
    angle: float            # radians from the centre to the edge of the map

    @property
    def radius(self) -> float:
        return self.size / 2.0

    @property
    def rad_per_px(self) -> float:
        return self.angle / self.radius

    def dirs(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        k = self.rad_per_px
        return plane_dirs((np.asarray(x) - self.radius) * k, (self.radius - np.asarray(y)) * k)

    def xy(self, d: np.ndarray):
        x, y = plane_xy(d)
        k = self.rad_per_px
        return self.radius + x / k, self.radius - y / k

    def circle(self) -> tuple[float, float, float]:
        return (self.radius, self.radius, self.radius)


def coverage_angle(shots: list[Shot]) -> float:
    """Radians from the posterior pole to the farthest photographed point (a little margin)."""
    far = 0.0
    for s in shots:
        c = s.centre()
        far = max(far, math.acos(max(-1.0, min(1.0, -c[2]))) + s.tmax)
    return min(math.radians(170.0), far * 1.02)


def map_for(shots: list[Shot], max_size: int = 4000, min_size: int = 400) -> MapGeometry:
    """A map just large enough to keep the sharpest photo's detail (at most ``max_size``)."""
    ang = coverage_angle(shots)
    finest = min(_deg_per_px(s) for s in shots)
    size = int(round(2 * math.degrees(ang) / max(finest, 1e-6)))
    return MapGeometry(max(min_size, min(max_size, size)), ang)


def _deg_per_px(s: Shot) -> float:
    cx, cy, _ = s.circle
    a, b = s.dirs(np.array([[cx, cy], [cx + 2.0, cy]]))
    return float(angle_deg(a[None], b[None])[0]) / 2.0


def _band_dirs(geom: MapGeometry, rows: slice) -> np.ndarray:
    n = geom.size
    ys = np.arange(n)[rows].astype(np.float64) + 0.5
    xx, yy = np.meshgrid(np.arange(n, dtype=np.float64) + 0.5, ys)
    return geom.dirs(xx, yy)


def _sample_dirs(shot: Shot, dirs: np.ndarray):
    """The photo seen in the directions ``dirs`` (…×3, on the eye): colour (uint8), coverage (0 … 1)
    and the distance from the edge of what it shows (radii, up to ``EDGE_SPAN``)."""
    u, v, rho = shot.pixels(dirs @ shot.R)                # eye → photo frame (R orthonormal)
    inside = np.isfinite(rho)
    mx = np.where(inside, u, -10).astype(np.float32)
    my = np.where(inside, v, -10).astype(np.float32)
    col = cv2.remap(shot.rgb, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = cv2.remap(shot.alpha, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = a.astype(np.float32) / 255.0 * inside
    e = cv2.remap(shot.edge_image(), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    edge = e.astype(np.float32) * (EDGE_SPAN / 255.0) * inside
    return col, a, edge


def _sample(shot: Shot, geom: MapGeometry, rows: slice | None = None):
    """The photo drawn on (a band of) the map: colour (float32), coverage and edge distance."""
    col, a, edge = _sample_dirs(shot, _band_dirs(geom, rows if rows is not None else slice(None)))
    return col.astype(np.float32), a, edge


def _rows_of(shot: Shot, geom: MapGeometry) -> tuple[float, float]:
    """The rows of the map the photo reaches (its outline bounds it: the map is continuous up to 170°)."""
    _, y = geom.xy(shot.outline(120))
    return float(np.min(y)) - 2.0, float(np.max(y)) + 2.0


def match_gains(shots: list[Shot], size: int = 256, strength: float = 0.05) -> None:
    """Per-photo colour gains that make overlapping parts equally bright (least squares, kept near 1)."""
    n = len(shots)
    if n < 2:
        return
    geom = MapGeometry(size, coverage_angle(shots))
    samples = [_sample(s, geom) for s in shots]
    ok = [(a > 0.9) & (e > 0.08) for _, a, e in samples]
    for ch in range(3):
        rows, rhs = [], []
        for i in range(n):
            for j in range(i + 1, n):
                both = ok[i] & ok[j]
                if both.sum() < 50:
                    continue
                mi, mj = float(samples[i][0][..., ch][both].mean()), float(samples[j][0][..., ch][both].mean())
                if mi < 2 or mj < 2:
                    continue
                wt = math.sqrt(both.sum())
                row = np.zeros(n)
                row[i], row[j] = mi * wt / 255, -mj * wt / 255
                rows.append(row)
                rhs.append(0.0)
        for i in range(n):                                # keep the gains near 1 (no drift to black)
            row = np.zeros(n)
            row[i] = strength * size
            rows.append(row)
            rhs.append(strength * size)
        g = np.linalg.lstsq(np.asarray(rows), np.asarray(rhs), rcond=None)[0]
        for i in range(n):
            shots[i].gain[ch] = float(np.clip(g[i], 0.5, 2.0))


def render(shots: list[Shot], geom: MapGeometry | None = None, *, smooth: bool = True,
           highlight: int | None = None, opacity: float = 0.5, band: int = 384, progress=None):
    """Draw the montage. Returns (rgb uint8, alpha uint8, geometry).

    ``smooth``: the finished montage (two-band blend of the gain-matched photos). Otherwise the
    photos laid over each other evenly, ``highlight`` on top at ``opacity``. Drawn in bands of rows
    (each with only the photos that reach it) so a large map needs little memory; ``progress(f)``
    hears the fraction done."""
    geom = geom or map_for(shots)
    n = geom.size
    out = np.zeros((n, n, 3), np.uint8)
    cover = np.zeros((n, n), np.uint8)
    sigma = max(2.0, n / 220.0)                           # the broad brightness band (smooth blend)
    margin = int(math.ceil(4 * sigma)) if smooth else 0
    spans = [_rows_of(s, geom) for s in shots]
    starts = list(range(0, n, band))
    for b, y0 in enumerate(starts):
        if progress:
            progress(b / len(starts))
        y1 = min(n, y0 + band)
        a0, a1 = max(0, y0 - margin), min(n, y1 + margin)
        use = [k for k, (lo, hi) in enumerate(spans) if hi >= a0 and lo < a1]
        if not use:
            continue
        dirs = _band_dirs(geom, slice(a0, a1))
        if smooth:
            col, alpha = _smooth_band([shots[k] for k in use], dirs, sigma)
        else:
            hl = use.index(highlight) if highlight in use else None
            col, alpha = _blend_overlay([shots[k] for k in use], dirs, hl, opacity)
        out[y0:y1] = col[y0 - a0:y1 - a0]
        cover[y0:y1] = alpha[y0 - a0:y1 - a0]
    if progress:
        progress(1.0)
    return out, cover, geom


def _weights(alpha, edge, feather: float = 0.22):
    """Blend weight: full inside, fading to 0 over the outer ``feather`` of each photo's field."""
    t = np.clip(edge / feather, 0.0, 1.0)
    return alpha * (t * t * (3 - 2 * t)) + 1e-6 * alpha


def _blend_overlay(shots, dirs, highlight, opacity):
    acc = wsum = top = None
    for k, s in enumerate(shots):
        col, a, _ = _sample_dirs(s, dirs)
        col = col.astype(np.float32) * s.gain.astype(np.float32)
        if acc is None:
            acc = np.zeros_like(col)
            wsum = np.zeros(a.shape, np.float32)
        if k == highlight:
            top = (col, a)
            continue
        acc += col * a[..., None]
        wsum += a
    return _over(acc / np.maximum(wsum, 1e-6)[..., None], np.minimum(wsum, 1.0), top, opacity)


def _over(base, cover, top, opacity):
    """``top`` = (colour, coverage) laid over ``base`` at ``opacity`` (alone where nothing is below)."""
    if top is not None:
        col, a = top
        o = (opacity * a)[..., None]
        base = np.where(cover[..., None] > 0, base * (1 - o) + col * o, col)
        cover = np.maximum(cover, a)
    return np.clip(base * (cover[..., None] > 0), 0, 255).astype(np.uint8), (cover * 255).astype(np.uint8)


def _smooth_band(shots, dirs, sigma):
    """Two-band blend: the broad brightness as a soft-weighted average (no seams), the fine detail
    (vessels) mostly from the photo that sees each place best, so slightly misaligned photos do
    not double the vessels; in overlaps the detail eases from one photo to the next."""
    low_acc = w_acc = det_acc = dw_acc = cover = None
    for s in shots:
        col, a, e = _sample_dirs(s, dirs)
        col = col.astype(np.float32) * s.gain.astype(np.float32)
        w = _weights(a, e)
        num = cv2.GaussianBlur(col * a[..., None], (0, 0), sigma)
        den = cv2.GaussianBlur(a, (0, 0), sigma)
        low = num / np.maximum(den, 1e-4)[..., None]
        high = (col - low) * (a[..., None] > 0.5)
        wd = w ** 8                                       # near winner-take-all, but continuous
        if low_acc is None:
            low_acc, det_acc = np.zeros_like(col), np.zeros_like(col)
            w_acc, dw_acc, cover = (np.zeros(a.shape, np.float32) for _ in range(3))
        low_acc += low * w[..., None]
        w_acc += w
        det_acc += high * wd[..., None]
        dw_acc += wd
        cover = np.maximum(cover, a)
    out = low_acc / np.maximum(w_acc, 1e-9)[..., None] + det_acc / np.maximum(dw_acc, 1e-12)[..., None]
    out = np.clip(out, 0, 255) * (cover[..., None] > 0.02)
    return out.astype(np.uint8), (cover * 255).astype(np.uint8)


class Overlay:
    """The editing view (반투명 겹치기) for one window of the map plane, kept between frames: while one
    photo is dragged only that photo is drawn again. The selected photo lies on top at ``opacity``;
    ``tint`` shows it green over the others in magenta, so matching vessels turn grey."""

    def __init__(self):
        self._view = None
        self._dirs = None
        self._layers: dict[int, tuple] = {}
        self._base = None

    @property
    def shape(self) -> tuple[int, int]:
        return self._dirs.shape[:2] if self._dirs is not None else (0, 0)

    def set_view(self, x0: float, y0: float, rad_per_px: float, w: int, h: int) -> None:
        """The window: its top-left corner on the map plane (radians, y up) and the size of its pixels."""
        key = (x0, y0, rad_per_px, int(w), int(h))
        if key == self._view:
            return
        self._view = key
        xs = x0 + (np.arange(int(w)) + 0.5) * rad_per_px
        ys = y0 - (np.arange(int(h)) + 0.5) * rad_per_px
        self._dirs = plane_dirs(*np.meshgrid(xs, ys))
        self._layers.clear()
        self._base = None

    @staticmethod
    def _key(s: Shot):
        return (s.R.tobytes(), s.fov_scale, s.fov_deg, s.fov_type, s.projection, s.viewpoint, s.radial_c,
                s.gain.tobytes(), s.circle, id(s.rgb), id(s.alpha))

    def _layer(self, s: Shot):
        key = self._key(s)
        hit = self._layers.get(id(s))
        if hit is None or hit[0] != key:
            col, a, _ = _sample_dirs(s, self._dirs)
            hit = (key, col.astype(np.float32) * s.gain.astype(np.float32), a)
            self._layers[id(s)] = hit
        return hit[1], hit[2]

    def compose(self, shots: list[Shot], highlight: int | None = None, opacity: float = 0.5,
                tint: bool = False, hidden=()) -> np.ndarray:
        others = [s for k, s in enumerate(shots) if k != highlight and k not in hidden]
        bkey = tuple((id(s), self._key(s)) for s in others)
        if self._base is None or self._base[0] != bkey:
            h, w = self.shape
            acc, wsum = np.zeros((h, w, 3), np.float32), np.zeros((h, w), np.float32)
            for s in others:
                col, a = self._layer(s)
                acc += col * a[..., None]
                wsum += a
            self._base = (bkey, acc / np.maximum(wsum, 1e-6)[..., None], np.minimum(wsum, 1.0))
        _, base, cover = self._base
        top = None
        if highlight is not None and highlight not in hidden and 0 <= highlight < len(shots):
            top = self._layer(shots[highlight])
        if not tint:
            return _over(base, cover, top, opacity)[0]
        out = np.zeros(base.shape, np.float32)

        def grey(col, a):                                  # the green channel shows the vessels best
            g = col[..., 1]
            m = float(g[a > 0.5].mean()) if (a > 0.5).any() else 1.0
            return np.clip(g * (120.0 / max(m, 1.0)), 0, 255) * (a > 0)

        lo = grey(base, cover)
        out[..., 0] = lo
        out[..., 2] = lo
        if top is not None:
            out[..., 1] = grey(*top)
        return out.astype(np.uint8)


def disc_on_map(shot: Shot, disc_px, geom: MapGeometry) -> tuple[float, float]:
    """Where the photo's optic disc (original pixels) lies on the map."""
    uv = np.array([[disc_px[0] / shot.scale, disc_px[1] / shot.scale]])
    x, y = geom.xy(shot.dirs(uv) @ shot.R.T)
    return float(x[0]), float(y[0])


def definition(shots: list[Shot], ref: int) -> dict:
    """What a saved montage needs to be edited again (stored with it in the patient record)."""
    return {"version": 1, "ref": ref, "shots": [s.to_json() for s in shots]}


def full_alpha(shot: Shot, alpha: np.ndarray) -> np.ndarray:
    """``alpha`` of the original photo with what 자동 left out of the working copy (``shot.cut``)."""
    if shot.cut is None:
        return alpha
    h, w = alpha.shape[:2]
    cut = cv2.resize(shot.cut, (w, h), interpolation=cv2.INTER_LINEAR)
    out = alpha.copy()
    out[cut > 127] = 0
    return cv2.GaussianBlur(out, (0, 0), max(1.0, 0.004 * shot.circle[2] * shot.scale))
