"""Optic disc pair (디스크 2장): the discs of two photos, cropped and side by side.

Insurance claims (e.g. for glaucoma) ask for optic disc photographs; this
module cuts a square around each photo's disc and puts the two in order —
OD on the left and OS on the right (as the examiner faces the patient), the
older photo first for two of the same eye.

The crop is sized in **disc diameters**, not pixels: the local scale at the
disc comes from the photo's own geometry (circle, field of view, projection —
``projection.py``), so a 45° photo and an ultra-wide-field one give the same
retinal field around the disc.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import measure
from . import projection as proj

DISC_DIAMETER_MM = 1.8       # mean optic disc diameter (adult)
FOVEA_DISC_MM = 4.5          # fovea → disc centre, along the horizontal meridian
PANEL_PX = 1000              # side of one disc panel in the sheet
# crop width in disc diameters (key, label, factor)
FIELDS = (("near", "가깝게", 2.5), ("normal", "보통", 3.5), ("wide", "넓게", 5.0))
FIELD_FACTOR = {k: f for k, _, f in FIELDS}
EYE_LABELS = {"OD": "OD  우안 (R)", "OS": "OS  좌안 (L)"}


@dataclass
class DiscSource:
    """One photo of the pair."""
    image_id: int
    rgb: np.ndarray
    disc: tuple[float, float]          # disc centre (image px)
    geometry: measure.Geometry | None
    eye: str | None = None             # OD / OS / None (unknown)
    when: str = ""                     # "YYYY-MM-DD HH:MM:SS" (sort key, caption)
    caption: str = ""                  # line under the panel (date · device · field)
    found: str = "saved"               # saved (detected at import or picked) / estimated

    @property
    def eye_label(self) -> str:
        return EYE_LABELS.get(self.eye or "", "눈 미상")


def disc_diameter_px(geo: measure.Geometry | None, disc, size: tuple[int, int] | None = None) -> float:
    """Expected optic disc diameter (pixels) at ``disc``.

    The disc subtends ``DISC_DIAMETER_MM / 12 mm`` radians at the eye centre;
    the projection gives the pixels per radian there along the meridian
    (radial) and across it (tangential), whose geometric mean is the local
    scale. Without geometry (or outside the field) 12 % of the image circle
    radius / half the shorter side is used.
    """
    ang = DISC_DIAMETER_MM / measure.EYE_RADIUS_MM
    if geo is not None and geo.r > 0:
        tmax = geo.tmax
        rho_px = math.hypot(disc[0] - geo.cx, disc[1] - geo.cy)
        rho = rho_px / geo.r
        if rho < 1.0:
            kw = dict(d=geo.viewpoint, c=geo.radial_c)
            th = proj.theta_of_rho(rho, tmax, geo.projection, **kw)
            h = min(1e-3, tmax / 4)
            t0, t1 = max(th - h, 0.0), min(th + h, tmax)
            radial = (proj.rho(t1, tmax, geo.projection, **kw)
                      - proj.rho(t0, tmax, geo.projection, **kw)) * geo.r / (t1 - t0)
            tangential = rho_px / math.sin(th) if th > 1e-3 else radial
            if radial > 0 and tangential > 0:
                return ang * math.sqrt(radial * tangential)
    r = geo.r if geo is not None and geo.r > 0 else (min(size) / 2.0 if size else 500.0)
    return 0.12 * r


def expected_disc(geo: measure.Geometry | None, laterality: str | None,
                  size: tuple[int, int]) -> tuple[float, float]:
    """Where the disc of a fovea-centred photo should be (nasal, 4.5 mm from the
    fovea) when it was not found; the image centre if the side is unknown."""
    w, h = size
    if geo is None or not geo.r or laterality not in ("OD", "OS"):
        return (geo.cx, geo.cy) if geo is not None and geo.r else (w / 2.0, h / 2.0)
    th = min(FOVEA_DISC_MM / measure.EYE_RADIUS_MM, geo.tmax * 0.95)
    rho = proj.rho(th, geo.tmax, geo.projection, geo.viewpoint, c=geo.radial_c)
    side = 1.0 if laterality == "OD" else -1.0
    return (geo.cx + side * rho * geo.r, geo.cy)


def crop_box(src: DiscSource, field: str = "normal") -> tuple[int, int, int]:
    """``(x0, y0, side)`` of the square crop around the disc (may leave the photo)."""
    h, w = src.rgb.shape[:2]
    factor = FIELD_FACTOR.get(field, FIELD_FACTOR["normal"])
    side = max(32, int(round(factor * disc_diameter_px(src.geometry, src.disc, (w, h)))))
    side = min(side, 2 * max(w, h))
    x0 = int(round(src.disc[0] - side / 2.0))
    y0 = int(round(src.disc[1] - side / 2.0))
    return x0, y0, side


def panel(src: DiscSource, field: str = "normal", out_px: int = PANEL_PX, adjust=None) -> np.ndarray:
    """``out_px``² RGB crop centred on the disc; outside the photo is black.
    ``adjust`` (rgb -> rgb) applies display adjustments to the crop."""
    x0, y0, side = crop_box(src, field)
    img = Image.fromarray(src.rgb).crop((x0, y0, x0 + side, y0 + side))   # pads with black
    out = np.asarray(img.resize((out_px, out_px), Image.Resampling.LANCZOS))
    return adjust(out) if adjust is not None else out


def to_source_point(src: DiscSource, field: str, u: float, v: float) -> tuple[float, float]:
    """Panel position ``(u, v)`` in 0…1 → photo pixel (to re-centre on a click)."""
    x0, y0, side = crop_box(src, field)
    return (x0 + u * side, y0 + v * side)


def order_pair(a: DiscSource, b: DiscSource) -> tuple[DiscSource, DiscSource]:
    """OD left, OS right; otherwise (same or unknown eye) the older photo first."""
    rank = {"OD": 0, "OS": 1}

    def key(s: DiscSource):
        return (rank.get(s.eye or "", 2), s.when or "", s.image_id)

    return (a, b) if key(a) <= key(b) else (b, a)
