"""학습한 컵 경계: where the cup's margin lies round the disc, learned from photos whose disc and cup
experts outlined.

Where the vessels bend is the sign of the cup's margin an examiner goes by — but on one flat photo few
bends can be picked out by a rule (about one a photo, and not reliably on the margin: docs/cup_bends.md).
What can be read all round the disc is the **pattern**: how the brightness falls from the pale floor to
the rim, and where the vessels run and crowd (they climb the wall on the nasal side and spread over the
rim). This module reads that pattern on a ring of profiles round the disc and says, for each direction,
how far out the cup reaches as a part of the disc's radius there — by a linear model (ridge regression)
fitted to 870 photos with expert outlines (REFUGE, Drishti-GS, ORIGA, as cut in Chen et al. 2023,
CC BY 4.0, https://zenodo.org/records/8009107). ``tools/train_cup.py`` fits it, ``tools/eval_cup.py``
measures it; the weights are in ``cup_weights.py``.

Two models: ``"vessels"`` goes by the vessel pattern alone (no colour), ``"both"`` by the vessels and
the brightness. An estimate from one photo, as before — a starting line to be put right by hand.
"""
from __future__ import annotations

import base64
import io
import math
from functools import lru_cache

import cv2
import numpy as np

from . import glaucoma as G

A, R, RMAX = 72, 32, 1.28          # directions, steps along each, out to this many disc radii
WORK_PX = 320                      # the picture is read at this size
SPANS = (2, 5, 9)                  # the neighbouring directions looked at with each (± this many)
CHANNELS = {"both": (0, 1, 2), "vessels": (2,)}
RATIO = (0.12, 0.97)               # the cup's reach as a part of the disc's radius: never outside this
HARMONICS = 5                      # the margin round the disc is this smooth


def _odd(x: float) -> int:
    return max(3, int(round(x)) | 1)


def disc_polar(curve: np.ndarray) -> tuple[tuple[float, float], np.ndarray]:
    """A closed outline as its middle and its radius at ``A`` directions (from +x towards +y)."""
    cx, cy = G.centre({"poly": curve})
    ang = np.arctan2(curve[:, 1] - cy, curve[:, 0] - cx)
    rad = np.hypot(curve[:, 0] - cx, curve[:, 1] - cy)
    order = np.argsort(ang)
    ang, rad = ang[order], rad[order]
    want = np.arange(A) * 2.0 * math.pi / A
    want = np.where(want > math.pi, want - 2.0 * math.pi, want)
    out = np.interp(want, np.concatenate([ang - 2 * math.pi, ang, ang + 2 * math.pi]), np.tile(rad, 3))
    return (float(cx), float(cy)), out.astype(np.float32)


def profiles(crop: np.ndarray, curve: np.ndarray) -> np.ndarray:
    """The ring of profiles (``A`` × ``R`` × 3) round the disc outlined by ``curve`` (pixels of the square
    picture ``crop``): green and red with the vessels closed out, each against the photo's own range, and
    how much of a vessel there is — every profile running from the disc's middle out to ``RMAX`` times
    the disc's radius in its direction (so a large and a small disc read alike)."""
    side = float(crop.shape[0])
    s = WORK_PX / side
    small = cv2.resize(crop, (WORK_PX, WORK_PX), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    small = small.astype(np.float32)
    (cx, cy), rad = disc_polar(np.asarray(curve, np.float64) * s)
    rd = float(rad.mean())
    ball = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(0.26 * rd),) * 2)

    def shut(ch: int) -> tuple[np.ndarray, np.ndarray]:
        g = cv2.GaussianBlur(small[..., ch], (0, 0), 0.8)
        return cv2.morphologyEx(g, cv2.MORPH_CLOSE, ball), g
    gs, g = shut(1)
    rs, _ = shut(0)
    hat = (gs - g) / np.maximum(gs, 20.0)
    th = np.arange(A) * 2.0 * math.pi / A
    step = (np.arange(R) + 0.5) / R * RMAX
    reach = rad[:, None] * step[None, :]
    mx = (cx + reach * np.cos(th)[:, None]).astype(np.float32)
    my = (cy + reach * np.sin(th)[:, None]).astype(np.float32)
    P = np.stack([cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) for im in (gs, rs, hat)],
                 axis=-1)
    on_disc = int(R * 0.9 / RMAX)
    for ch in (0, 1):
        v = P[..., ch]
        lo, hi = float(np.percentile(v[:, on_disc:], 30)), float(np.percentile(v[:, :on_disc], 98))
        P[..., ch] = (v - lo) / max(hi - lo, 1.0)
    P[..., 2] = np.clip(P[..., 2] * 6.0, 0.0, 1.5)
    return P.astype(np.float32)


def design(P: np.ndarray, which: str = "both") -> np.ndarray:
    """What the model sees for each direction (``A`` rows): its own profile, the mean of the profiles a
    few directions to either side, the photo's mean profile, and which direction it is."""
    X = P[..., list(CHANNELS[which])]
    parts = [X.reshape(A, -1)]
    for k in SPANS:
        parts.append(((np.roll(X, k, 0) + np.roll(X, -k, 0)) / 2.0).reshape(A, -1))
    parts.append(np.repeat(X.mean(0, keepdims=True), A, 0).reshape(A, -1))
    ang = np.arange(A) * 2.0 * math.pi / A
    parts.append(np.stack([np.cos(ang), np.sin(ang), np.cos(2 * ang), np.sin(2 * ang)], 1))
    return np.concatenate(parts, -1).astype(np.float32)


def smooth(ratio: np.ndarray) -> np.ndarray:
    """Round the disc, only the first few harmonics (a cup's margin does not zigzag)."""
    f = np.fft.rfft(ratio)
    f[HARMONICS:] = 0
    return np.fft.irfft(f, len(ratio))


@lru_cache(maxsize=1)
def weights() -> dict:
    from .cup_weights import DATA
    z = np.load(io.BytesIO(base64.b64decode(DATA)))
    return {k: z[k] for k in z.files}


def ratio(P: np.ndarray, which: str = "both", model: dict | None = None) -> np.ndarray:
    """The cup's reach at each of the ``A`` directions as a part of the disc's radius there."""
    m = weights() if model is None else model
    F = (design(P, which) - m[f"{which}_mu"]) / m[f"{which}_sd"]
    out = F @ m[f"{which}_w"] + float(m[f"{which}_b"])
    return np.clip(smooth(np.clip(out, *RATIO)), *RATIO).astype(np.float32)


def cup_curve(crop: np.ndarray, curve: np.ndarray, which: str = "both") -> np.ndarray:
    """The cup's margin (``A`` × 2, pixels of ``crop``) inside the disc outlined by ``curve``."""
    (cx, cy), rad = disc_polar(np.asarray(curve, np.float64))
    k = ratio(profiles(crop, curve), which)
    th = np.arange(A) * 2.0 * math.pi / A
    return np.stack([cx + k * rad * np.cos(th), cy + k * rad * np.sin(th)], axis=1)
