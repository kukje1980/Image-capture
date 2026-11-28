"""변화 지도: an earlier photo of the same eye laid on today's, and what is different marked in colour.

시간별 비교 (timeline.py) follows the optic disc; this is for the rest of the fundus — a haemorrhage
that was not there, an exudate gone, atrophy grown.

* ``register`` — the earlier photo is moved onto today's by its vessels: features of the vessel pattern
  matched and a similarity (shift · turn · size) fitted to them, refined where it holds. Where the vessels
  cannot be matched the disc and the fovea found in both photos do it; where there is neither, the photos
  are only brought to one size (and the window says so).
* ``difference`` — both photos are flattened (the slow change of brightness across a photo and between two
  sittings is taken out), then compared: **darker today** (blood, pigment) and **brighter today**
  (exudate, atrophy, a scar) are kept apart. Thin lines (a vessel a pixel off) and specks are dropped.
* ``swipe`` — the earlier photo left of a line, today's right of it.

A help for looking, not a finding: glare, focus, a lash and the pupil's size change a photo too. No Qt in
here (``ui/patient_views.py`` is the window).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

WORK = 900                  # the photos are compared at this size (longer side)
MIN_INLIERS = 12            # fewer vessel matches than this: not trusted
SENSITIVITY = (1, 10, 5)    # least, most, at first (10 marks the faintest change)
DARKER = (255, 60, 170)     # darker today: magenta
BRIGHTER = (60, 220, 255)   # brighter today: cyan
NOTE = ("참고용입니다 — 빛 반사 · 초점 · 속눈썹 · 동공 크기 때문에 달라 보이는 곳도 표시될 수 있습니다. "
        "표시된 곳을 두 사진에서 직접 확인하세요.")


@dataclass
class Fit:
    """The earlier photo onto today's: a 2 × 3 matrix in today's pixels, and how it was found."""
    matrix: np.ndarray
    how: str = "none"               # "vessels" · "landmarks" · "none"
    inliers: int = 0

    @property
    def text(self) -> str:
        return {"vessels": f"혈관 모양으로 맞춤 (일치점 {self.inliers}개)",
                "landmarks": "유두 · 황반 위치로 맞춤 — 혈관으로는 맞추지 못했습니다",
                "none": "자동으로 맞추지 못했습니다 — 크기만 맞춰 겹쳤습니다"}[self.how]


def _mask(rgb: np.ndarray, circle=None) -> np.ndarray:
    """The part of a photo that is fundus (uint8 0 / 255)."""
    m = (rgb.max(axis=2) > 18).astype(np.uint8) * 255
    if circle is not None and circle[2]:
        c = np.zeros_like(m)
        cv2.circle(c, (int(circle[0]), int(circle[1])), int(circle[2] * 0.97), 255, -1)
        m = cv2.bitwise_and(m, c)
    return cv2.erode(m, np.ones((5, 5), np.uint8))


def _vessels(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The vessel pattern, for matching: green channel, local contrast evened out."""
    g = rgb[..., 1]
    g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(g)
    back = cv2.GaussianBlur(g, (0, 0), max(4.0, max(g.shape) / 40.0))
    out = cv2.addWeighted(g, 1.0, back, -1.0, 128)
    out[mask == 0] = 128
    return out


def _reduced(rgb: np.ndarray, side: int = WORK) -> tuple[np.ndarray, float]:
    k = side / float(max(rgb.shape[:2]))
    if k >= 1.0:
        return rgb, 1.0
    return cv2.resize(rgb, (max(1, round(rgb.shape[1] * k)), max(1, round(rgb.shape[0] * k))),
                      interpolation=cv2.INTER_AREA), k


def _scaled(m: np.ndarray, k_from: float, k_to: float) -> np.ndarray:
    """A matrix found between reduced pictures (earlier × ``k_from`` → today × ``k_to``), in full pixels."""
    a = np.vstack([m, [0, 0, 1]]).astype(np.float64)
    s_from = np.diag([k_from, k_from, 1.0])
    s_to = np.diag([1.0 / k_to, 1.0 / k_to, 1.0])
    return (s_to @ a @ s_from)[:2]


def _plain(old_shape, new_shape) -> np.ndarray:
    """No fit: the earlier photo brought to today's size, centre on centre."""
    k = min(new_shape[1] / old_shape[1], new_shape[0] / old_shape[0])
    return np.float64([[k, 0, (new_shape[1] - old_shape[1] * k) / 2], [0, k, (new_shape[0] - old_shape[0] * k) / 2]])


def _from_landmarks(old_marks, new_marks) -> np.ndarray | None:
    """The similarity that takes the earlier photo's disc and fovea onto today's."""
    (d0, f0), (d1, f1) = old_marks, new_marks
    if None in (d0, f0, d1, f1):
        return None
    a, b = complex(*d0), complex(*f0)
    c, d = complex(*d1), complex(*f1)
    if abs(b - a) < 1e-6:
        return None
    z = (d - c) / (b - a)
    if not 0.4 < abs(z) < 2.5:
        return None
    t = c - z * a
    return np.float64([[z.real, -z.imag, t.real], [z.imag, z.real, t.imag]])


def register(old: np.ndarray, new: np.ndarray, *, old_circle=None, new_circle=None, old_marks=(None, None),
             new_marks=(None, None)) -> Fit:
    """The earlier photo ``old`` onto today's ``new`` (RGB). ``*_marks``: ``(disc, fovea)`` in pixels."""
    so, ko = _reduced(old)
    sn, kn = _reduced(new)
    mo = _mask(so, None if old_circle is None else tuple(v * ko for v in old_circle))
    mn = _mask(sn, None if new_circle is None else tuple(v * kn for v in new_circle))
    vo, vn = _vessels(so, mo), _vessels(sn, mn)
    orb = cv2.ORB_create(nfeatures=4000, scaleFactor=1.2, nlevels=8, fastThreshold=7)
    ka, da = orb.detectAndCompute(vo, mo)
    kb, db = orb.detectAndCompute(vn, mn)
    if da is not None and db is not None and len(ka) >= MIN_INLIERS and len(kb) >= MIN_INLIERS:
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.8 * p[1].distance]
        if len(good) >= MIN_INLIERS:
            src = np.float32([ka[g.queryIdx].pt for g in good])
            dst = np.float32([kb[g.trainIdx].pt for g in good])
            m, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                                 maxIters=4000, confidence=0.995)
            n = int(inl.sum()) if inl is not None else 0
            scale = math.hypot(m[0, 0], m[1, 0]) if m is not None else 0.0
            if m is not None and n >= MIN_INLIERS and 0.4 < scale < 2.5:
                try:                                        # the last pixel: brightness correlation
                    warped = cv2.warpAffine(vo, m, (vn.shape[1], vn.shape[0]), borderValue=128)
                    both = cv2.bitwise_and(mn, cv2.warpAffine(mo, m, (mn.shape[1], mn.shape[0])))
                    _cc, fine = cv2.findTransformECC(vn, warped, np.eye(2, 3, dtype=np.float32), cv2.MOTION_EUCLIDEAN,
                                                     (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 1e-5),
                                                     both, 5)
                    step = np.vstack([cv2.invertAffineTransform(fine), [0, 0, 1]]) @ np.vstack([m, [0, 0, 1]])
                    if abs(step[0, 2] - m[0, 2]) < 6 and abs(step[1, 2] - m[1, 2]) < 6:
                        m = step[:2]
                except cv2.error:
                    pass
                return Fit(_scaled(m, ko, kn), "vessels", n)
    m = _from_landmarks(old_marks, new_marks)
    if m is not None:
        return Fit(m, "landmarks")
    return Fit(_plain(old.shape, new.shape), "none")


def applied(old: np.ndarray, fit: Fit, shape) -> tuple[np.ndarray, np.ndarray]:
    """The earlier photo in today's frame, and where it has a picture (uint8 0 / 255)."""
    size = (shape[1], shape[0])
    warped = cv2.warpAffine(old, fit.matrix, size, flags=cv2.INTER_LINEAR)
    there = cv2.warpAffine(_mask(old), fit.matrix, size, flags=cv2.INTER_NEAREST)
    return warped, there


def _flat(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Brightness with the slow change across the photo taken out, in units of its own spread."""
    g = (rgb[..., 1].astype(np.float32) * 0.7 + rgb[..., 0].astype(np.float32) * 0.3)
    w = (mask > 0).astype(np.float32)
    sigma = max(8.0, max(g.shape) / 18.0)
    mean = cv2.GaussianBlur(g * w, (0, 0), sigma) / np.maximum(cv2.GaussianBlur(w, (0, 0), sigma), 1e-3)
    d = (g - mean) * w
    spread = float(np.sqrt((d[mask > 0] ** 2).mean())) if (mask > 0).any() else 1.0
    return cv2.GaussianBlur(d / max(spread, 1e-3), (0, 0), 1.2)


def difference(new: np.ndarray, old_warped: np.ndarray, both: np.ndarray, sensitivity: int = SENSITIVITY[2]):
    """``(darker, brighter)``: two float maps 0 … 1 of today's photo at the working size's own pixels —
    where it is darker / brighter than the earlier one. ``both``: where both photos have fundus."""
    sn, k = _reduced(new)
    size = (sn.shape[1], sn.shape[0])
    so = cv2.resize(old_warped, size, interpolation=cv2.INTER_AREA) if k < 1.0 else old_warped
    m = cv2.resize(both, size, interpolation=cv2.INTER_NEAREST) if k < 1.0 else both
    m = cv2.bitwise_and(m, cv2.bitwise_and(_mask(sn), _mask(so)))
    m = cv2.erode(m, np.ones((9, 9), np.uint8))
    d = (_flat(sn, m) - _flat(so, m)) * (m > 0)
    s = int(min(SENSITIVITY[1], max(SENSITIVITY[0], sensitivity)))
    lo = 2.4 - 0.2 * s                                      # 2.2 (least) … 0.4 (most) spreads
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    out = []
    for sign in (-1.0, 1.0):
        v = np.clip((d * sign - lo) / 0.9, 0.0, 1.0)
        solid = cv2.morphologyEx((v > 0.15).astype(np.uint8), cv2.MORPH_OPEN, kernel)     # not a thin line
        out.append(cv2.GaussianBlur(v * solid, (0, 0), 1.5))
    return out[0], out[1]


def changed_share(darker: np.ndarray, brighter: np.ndarray, both: np.ndarray) -> tuple[float, float]:
    """The share of the compared fundus marked darker / brighter (0 … 1)."""
    m = cv2.resize(both, (darker.shape[1], darker.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    n = max(1, int(m.sum()))
    return float((darker[m] > 0.3).sum()) / n, float((brighter[m] > 0.3).sum()) / n


def marked(rgb: np.ndarray, darker: np.ndarray, brighter: np.ndarray, strength: float = 0.75) -> np.ndarray:
    """``rgb`` with the two maps laid on in their colours."""
    size = (rgb.shape[1], rgb.shape[0])
    out = rgb.astype(np.float32)
    for m, color in ((darker, DARKER), (brighter, BRIGHTER)):
        k = cv2.resize(m, size, interpolation=cv2.INTER_LINEAR)[..., None] * float(strength)
        out = out * (1.0 - k) + np.float32(color) * k
    return np.clip(out, 0, 255).astype(np.uint8)


def swipe(old_warped: np.ndarray, new: np.ndarray, at: float) -> np.ndarray:
    """The earlier photo left of the line at ``at`` (0 … 1 of the width), today's right of it."""
    x = int(round(min(1.0, max(0.0, at)) * new.shape[1]))
    out = new.copy()
    out[:, :x] = old_warped[:, :x]
    return out
