"""Image loading and analysis (numpy + Pillow; pydicom for DICOM pixels).

* :func:`load_rgb`      — any supported file -> ``uint8`` RGB array
* :func:`detect_circle` — the fundus image circle (centre, radius) on its black
  mask, robust to burned-in text/logos outside the circle and to circles
  clipped at the top/bottom of the frame
* :func:`detect_disc`   — brightest-blob estimate of the optic disc
* :func:`detect_fovea`  — the dark macula where the disc says it should be
* :func:`fundus_alpha`  — soft-edged mask used as the 3D texture's alpha
* :func:`adjust`        — display adjustments (brightness/contrast/gamma,
  red-free / single channel, invert, auto-stretch) via 256-entry LUTs
"""
from __future__ import annotations

import math
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

try:                         # OpenCV (also used by 몽타주): the heavy per-pixel steps in C
    import cv2
except ImportError:          # pragma: no cover - listed in requirements.txt
    cv2 = None

Image.MAX_IMAGE_PIXELS = 400_000_000  # montages are large; files are local and trusted


def _check_size(img: Image.Image) -> None:
    """Past the limit Pillow itself only warns, up to twice as many pixels: a 1 MB PNG of
    21000 × 20000 was decoded into gigabytes of memory. The limit is the limit (the importer's
    describe_error tells the user of it)."""
    if img.width * img.height > Image.MAX_IMAGE_PIXELS:
        raise Image.DecompressionBombError(
            f"Image size ({img.width * img.height} pixels) exceeds limit of {Image.MAX_IMAGE_PIXELS} pixels")


_EXIF_ORIENTATION = 0x0112


def _upright(img: Image.Image) -> Image.Image:
    """``img`` turned as its EXIF orientation says. Most photos say nothing: they are returned
    as they are (``ImageOps.exif_transpose`` copies every pixel even then — 0.1 s of a
    24-megapixel frame)."""
    try:
        turned = img.getexif().get(_EXIF_ORIENTATION, 1) not in (1, None)
    except Exception:
        turned = False
    return ImageOps.exif_transpose(img) if turned else img


def load_rgb(path: Path | str) -> np.ndarray:
    path = Path(path)
    from .extract.dicom_meta import is_dicom

    if is_dicom(path):
        return _dicom_rgb(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)   # (checked below, as an error)
        img = Image.open(path)
    with img:
        _check_size(img)
        img = _upright(img)
        if img.mode in ("I;16", "I;16B", "I;16L", "I"):
            a = np.asarray(img, dtype=np.float64)
            return np.repeat(_to_uint8(a)[..., None], 3, axis=2)
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGB", img.size, (0, 0, 0))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.getchannel("A"))
            return np.asarray(bg)
        return np.asarray(img if img.mode == "RGB" else img.convert("RGB"))


def load_for_import(path: Path | str, min_side: int = 1024) -> tuple[np.ndarray, int, int]:
    """``(rgb, width, height)`` for analysing a photo that is being imported: ``width`` ×
    ``height`` is the photo's full size, ``rgb`` may be smaller.

    The import looks at the photo at about 500 px (image circle, disc, fovea) and writes a
    320 px thumbnail, so a large JPEG is decoded straight at 1/2, 1/4 or 1/8 of its size (never
    below ``min_side``) — a 24-megapixel frame in 0.03 s instead of 0.25 s. Anything else is
    read in full (:func:`load_rgb`)."""
    path = Path(path)
    try:
        with Image.open(path) as img:
            if img.format == "JPEG" and img.mode in ("RGB", "L", "YCbCr") and max(img.size) >= 2 * min_side:
                full = img.size
                swapped = img.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8)
                img.draft("RGB", (min_side, min_side))
                img = _upright(img)
                a = np.asarray(img if img.mode == "RGB" else img.convert("RGB"))
                w, h = full[::-1] if swapped else full
                return a, w, h
    except Exception:
        pass                                                  # not a plain image: the full reader knows more
    a = load_rgb(path)
    return a, a.shape[1], a.shape[0]


def load_reduced(path: Path | str, max_side: int) -> np.ndarray:
    """The photo no larger than about ``max_side`` (many small views at once). A JPEG is decoded
    straight at 1/2, 1/4 or 1/8 of its size — a 24-megapixel frame in a few ms instead of 0.3 s."""
    path = Path(path)
    try:
        with Image.open(path) as img:
            if img.format == "JPEG" and img.mode in ("RGB", "L", "YCbCr"):
                img.draft("RGB", (max_side, max_side))       # never below the asked size
                img = _upright(img).convert("RGB")
                img.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
                return np.asarray(img)
    except Exception:
        pass                                                  # not a plain image: the full reader knows more
    return downscale(load_rgb(path), max_side)


def _to_uint8(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.float64)
    lo, hi = np.percentile(a, 0.5), np.percentile(a, 99.8)
    if hi <= lo:
        lo, hi = float(a.min()), float(a.max()) or 1.0
    return np.clip((a - lo) * (255.0 / max(hi - lo, 1e-9)), 0, 255).astype(np.uint8)


def _dicom_rgb(path: Path) -> np.ndarray:
    import pydicom

    ds = pydicom.dcmread(str(path), force=True)
    arr = ds.pixel_array
    spp = int(ds.get("SamplesPerPixel", 1))
    frames = int(ds.get("NumberOfFrames", 1) or 1)
    if frames > 1:
        arr = arr[0]
    pi = str(ds.get("PhotometricInterpretation", "")).upper()
    if pi == "PALETTE COLOR":
        from pydicom.pixels import apply_color_lut
        arr = apply_color_lut(arr, ds)
        spp = 3
    if spp == 1:
        g = arr if arr.dtype == np.uint8 and int(ds.get("BitsStored", 8)) <= 8 else _to_uint8(arr)
        if pi == "MONOCHROME1":
            g = 255 - g
        return np.repeat(g[..., None], 3, axis=2)
    # pydicom >= 3 returns YBR_FULL / YBR_FULL_422 already converted to RGB.
    if arr.dtype != np.uint8:
        arr = _to_uint8(arr)
    return np.ascontiguousarray(arr[..., :3])


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _downsample(rgb: np.ndarray, max_side: int = 512) -> tuple[np.ndarray, float]:
    h, w = rgb.shape[:2]
    step = max(1, int(math.ceil(max(h, w) / max_side)))
    return rgb[::step, ::step], float(step)


def detect_circle(rgb: np.ndarray) -> tuple[float, float, float]:
    """Centre and radius (pixels) of the illuminated fundus circle.

    Each row's *longest* run of non-black pixels is the circle chord (text and
    logos give short runs). Fitting ``w² + y² = (r² - cy²) + 2·cy·y`` to the
    half-chords by least squares gives ``cy`` and ``r`` even when the circle
    is clipped by the frame. Falls back to the inscribed circle of the frame.
    """
    small, step = _downsample(rgb)
    h, w = small.shape[:2]
    lum = luminance(small.astype(np.float32))
    top = float(np.percentile(lum, 99))
    thr = max(10.0, 0.08 * top) if top >= 60.0 else max(3.0, 0.15 * top)    # (a dark photo: by its own brightness)
    mask = lum > thr
    ys, x0s, x1s = [], [], []
    for y in range(h):
        row = mask[y]
        if row.sum() < 0.15 * w:
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        k = int(np.argmax(ends - starts))
        if ends[k] - starts[k] >= 0.15 * w:
            ys.append(y)
            x0s.append(starts[k])
            x1s.append(ends[k] - 1)
    fallback = (rgb.shape[1] / 2.0, rgb.shape[0] / 2.0, min(rgb.shape[:2]) / 2.0)
    if len(ys) < 8:
        return fallback
    ys_a = np.asarray(ys, float)
    x0, x1 = np.asarray(x0s, float), np.asarray(x1s, float)
    half = (x1 - x0 + 1) / 2.0
    cx = float(np.median((x0 + x1) / 2.0))
    # Reject rows whose chord is not centred (text touching the circle edge).
    ok = np.abs((x0 + x1) / 2.0 - cx) < 0.05 * w
    if ok.sum() >= 8:
        ys_a, half = ys_a[ok], half[ok]
    # A lid's shadow, lashes or a dark corner cut chords short (never long): the rows whose chord falls
    # short of the fitted circle are left out and the circle fitted again
    for _ in range(4):
        A = np.stack([np.ones_like(ys_a), 2.0 * ys_a], axis=1)
        sol, *_ = np.linalg.lstsq(A, half ** 2 + ys_a ** 2, rcond=None)
        c0, cy = sol
        r2 = c0 + cy ** 2
        r = math.sqrt(r2) if r2 > 0 else float(half.max())
        model = np.sqrt(np.maximum(r * r - (ys_a - cy) ** 2, 0.0))
        keep = half >= model - max(1.5, 0.02 * r)
        if keep.all() or keep.sum() < max(8, 0.4 * len(ys_a)):
            break
        ys_a, half = ys_a[keep], half[keep]
    if not (0.2 * w < r < 1.2 * max(w, h)):
        r, cy = float(half.max()), float(ys_a[np.argmax(half)])
    return ((cx + 0.5) * step, (cy + 0.5) * step, r * step)


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur of a float image (reflect padding)."""
    rad = max(1, int(3 * sigma))
    x = np.arange(-rad, rad + 1, dtype=np.float64)
    k = np.exp(-x * x / (2 * sigma * sigma))
    k /= k.sum()
    if cv2 is not None and rad < min(a.shape[:2]):   # the same kernel and border, in C (20× faster)
        return cv2.sepFilter2D(np.ascontiguousarray(a, np.float64), cv2.CV_64F, k, k,
                               borderType=cv2.BORDER_REFLECT_101)
    p = np.pad(a.astype(np.float64), rad, mode="reflect")
    t = np.apply_along_axis(np.convolve, 1, p, k, mode="valid")
    return np.apply_along_axis(np.convolve, 0, t, k, mode="valid")


def detect_disc(rgb: np.ndarray, circle: tuple[float, float, float], *, disc_frac: float = 0.11,
                search: float = 0.7) -> tuple[float, float, float] | None:
    """Optic disc estimate ``(x, y, confidence)`` or ``None``.

    The disc is where vessels converge on a bright cup: the strongest local
    contrast (standard deviation over a disc-sized window) inside ``search``
    × radius. ``disc_frac`` is the expected disc radius as a fraction of the
    image-circle radius (≈ 3.8° / half internal FOV). Confidence is the peak's
    z-score. A detection closer than 8 % of the radius to the centre is kept
    only when the place is bright as well (a disc-centred photo); the centre
    of a fovea-centred photo — the dark macula with its reflex — is not a disc.
    """
    small, step = _downsample(rgb, 384)
    cx, cy, r = (v / step for v in circle)
    lum = luminance(small.astype(np.float32))
    dr = max(1.5, r * disc_frac)
    mean = gaussian_blur(lum, dr)
    sd = np.sqrt(np.maximum(gaussian_blur(lum * lum, dr) - mean * mean, 0))
    h, w = lum.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    inside = d2 <= (search * r) ** 2
    if inside.sum() < 50:
        return None
    vals = sd[inside]
    z = (sd - np.median(vals)) / (vals.std() + 1e-6)
    z[~inside] = -1e9
    iy, ix = np.unravel_index(np.argmax(z), z.shape)
    conf = float(z[iy, ix])
    if conf < 3.0:
        return None
    if d2[iy, ix] < (0.08 * r) ** 2:
        means = mean[inside]
        if (mean[iy, ix] - np.median(means)) / (means.std() + 1e-6) < 1.0:
            return None
    return ((ix + 0.5) * step, (iy + 0.5) * step, conf)


def laterality_from_disc(disc, circle: tuple[float, float, float]) -> str | None:
    """OD shows its disc right of centre, OS left (examiner's view)."""
    if disc is None or (len(disc) > 2 and disc[2] < 4.0):
        return None
    dx = (disc[0] - circle[0]) / max(circle[2], 1.0)
    if abs(dx) < 0.1:
        return None
    return "OD" if dx > 0 else "OS"


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    if cv2 is not None:
        return cv2.GaussianBlur(np.ascontiguousarray(a, np.float32), (0, 0), max(0.3, sigma)).astype(np.float64)
    return gaussian_blur(a, max(0.3, sigma))


LANDMARKS_VERSION = 4       # how the disc and the macula are found (photos found an older way: again)
# 3 (0.13.15): the edge of a glare band along the rim (the lid's reflex) is not taken for the disc
# 4 (0.13.15): several cues on the photo with its illumination evened out (see _Field); measured on
#              516 photos marked by experts (IDRiD, docs/landmarks.md)
OPEN_MAX = 0.25             # a disc candidate brighter beyond than this share of its surroundings: an edge
FOVEA_MIN = 0.0             # the macula: at least this much darker than the field's spread (else: not found)


def _robust_z(a: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """``a`` in units of the field's own spread (median and MAD over ``valid``: a glare band or a
    plaque of exudates does not set the scale, as it did with the standard deviation)."""
    v = a[valid]
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826 + 1e-6
    return (a - med) / mad


class _Field:
    """A photo reduced (384 px), lightly smoothed against sensor noise, with what the finders of the
    disc and the macula share: the lit field, and brightness against the retina around each place.

    A poorly taken photo is dark on one side, flared on the other, hazy, or cut by the lid: what is
    looked for is therefore never a brightness as it is, but against the retina's own brightness
    around the place (``lum / background`` — background: the photo blurred over four disc radii, with
    bright things capped so that the disc or a plaque does not lift its own background)."""

    def __init__(self, rgb: np.ndarray, circle: tuple[float, float, float]):
        self.small, self.step = _downsample(rgb, 384)
        small = self.small.astype(np.float32)
        if small.ndim == 2:
            small = np.repeat(small[..., None], 3, axis=2)
        small = _blur32(small, 0.8)
        self.h, self.w = small.shape[:2]
        self.cx, self.cy, self.r = (v / self.step for v in circle)
        self.yy, self.xx = np.mgrid[0:self.h, 0:self.w]
        self.d2 = (self.xx - self.cx) ** 2 + (self.yy - self.cy) ** 2
        self.lum = 0.299 * small[..., 0] + 0.587 * small[..., 1] + 0.114 * small[..., 2]
        self.green = np.ascontiguousarray(small[..., 1])
        inside = self.d2 <= (0.97 * self.r) ** 2
        # (a dark photo: lit by its own brightness, not by a fixed level)
        floor = max(2.0, 0.06 * float(np.percentile(self.lum[inside], 99))) if inside.any() else 8.0
        self.lit = inside & (self.lum > floor)
        self.field = self.lit.astype(np.float32)
        self._even: dict = {}
        self.away = None                       # glare and shadow (clean()): not retina

    def clean(self, dr: float) -> np.ndarray:
        """Glare and shadow are taken out of the field (once): a bright area far larger than a disc (a
        flare), or larger than a few discs and reaching in from the rim (the lid's reflex) — and the
        lid's shadow and lashes, far darker than the retina around. Left in, a band of glare lifts the
        "retina's brightness" of everything near it (a disc beside it then looks dull), and lashes
        count as thick vessels. Returns what was taken out."""
        if self.away is not None:
            return self.away
        E = self.even("lum", dr, 80.0)[0]
        # (… or than the field as a whole: a shadow so wide that it is itself "the retina around")
        away = ((E < 0.45) | (self.lum < 0.3 * float(np.median(self.lum[self.lit])))) & self.lit
        if cv2 is not None:
            if away.any():
                away = cv2.dilate(away.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            rim = self.d2 >= (0.88 * self.r) ** 2
            glare = np.zeros((self.h, self.w), bool)
            # (clearly brighter than the retina around — or burnt out, where a band of glare is so large
            # that it is itself "the retina around": a few discs' worth at the rim, or far more anywhere)
            burnt = (self.lum >= 215.0) & (self.lum >= 1.6 * float(np.median(self.lum[self.lit])))
            for bright in ((E > 1.45) & self.lit, burnt & self.lit):
                n, lab, stats, _ = cv2.connectedComponentsWithStats(bright.astype(np.uint8), connectivity=8)
                for k in range(1, n):
                    area = stats[k, cv2.CC_STAT_AREA] / (math.pi * dr * dr)
                    if area > 20.0 or (area > 6.0 and (rim & (lab == k)).any()):
                        glare |= lab == k
            if glare.any():
                kk = max(3, int(dr) | 1)
                away |= cv2.dilate(glare.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk))) > 0
        self.away = away & self.lit
        if self.away.any() and (self.lit & ~self.away).sum() >= 50:
            self.lit = self.lit & ~self.away
            self.field = self.lit.astype(np.float32)
            self._even.clear()                 # (against the retina without them)
        return self.away

    def even(self, channel: str, dr: float, cap: float) -> np.ndarray:
        """``channel`` ("lum" / "green") against the retina around: 1 = as bright as the retina there."""
        key = (channel, round(dr * 2) / 2, cap)
        if key not in self._even:
            a = self.lum if channel == "lum" else self.green
            if self.lit.sum() > 50:
                # (a band of glare over a fifth of the field and more: the retina is what the middle
                # of the field's brightness is, not its upper end)
                top = min(float(np.percentile(a[self.lit], cap)), 1.5 * float(np.median(a[self.lit])))
            else:
                top = 255.0
            cover = np.maximum(_blur32(self.field, 4 * dr), 1e-3)
            back = np.maximum(_blur32(np.minimum(a, top) * self.field, 4 * dr) / cover, 0.5)
            self._even[key] = (a / back, np.minimum(a, top) / back, cover)
        return self._even[key]


def _blur32(a: np.ndarray, sigma: float) -> np.ndarray:
    if cv2 is not None:
        a = np.ascontiguousarray(a, np.float32)
        k = int(sigma // 4)
        if k >= 2 and min(a.shape[:2]) >= 8 * k:     # a wide blur: on the picture reduced (as smooth, 10× faster)
            h, w = a.shape[:2]
            small = cv2.resize(a, (max(1, w // k), max(1, h // k)), interpolation=cv2.INTER_AREA)
            small = cv2.GaussianBlur(small, (0, 0), sigma / k)
            return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        return cv2.GaussianBlur(a, (0, 0), max(0.5, sigma))
    if a.ndim == 3:
        return np.stack([gaussian_blur(a[..., k], max(0.5, sigma)) for k in range(a.shape[2])], axis=2).astype(np.float32)
    return gaussian_blur(a, max(0.5, sigma)).astype(np.float32)


def _morph(a: np.ndarray, k: int, close: bool) -> np.ndarray:
    if cv2 is not None:
        return cv2.morphologyEx(np.ascontiguousarray(a, np.float32), cv2.MORPH_CLOSE if close else cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    from .relief import _rank_filter
    first, second = (np.maximum, np.minimum) if close else (np.minimum, np.maximum)
    return _rank_filter(_rank_filter(a, k // 2, first), k // 2, second).astype(np.float32)


def _vessels(f: _Field, dr: float) -> np.ndarray:
    """Vessel strength: the dark lines a closing fills on the evened green — capped (a lash or the lid's
    shadow is far darker than any vessel), nothing outside the field (glare and shadow: clean())."""
    G = f.even("green", dr, 80.0)[0]
    k = max(3, int(round(dr * 0.45)) | 1)                     # ≈ the widest vessel at the disc
    return np.clip(_morph(G, k, True) - G, 0.0, 0.3) * f.field


def detect_fovea(rgb: np.ndarray, cam, disc, laterality: str | None = None, *,
                 window_deg: float = 7.0, with_side: bool = False, _field: _Field | None = None):
    """The fovea ``(x, y, confidence)`` or ``None``.

    The macula is a dark, vessel-free patch about 4.5 mm (2.65 ± 0.3 disc diameters) temporal of the
    disc and a little below it (7.8° ± 3.6° below the horizontal through the disc — Jonas 2015).
    ``cam`` (:class:`placement.Camera`) says where that is in this photo; around it the fovea is where
    three things add up: darker than its surroundings (on the green evened for the photo's uneven
    light, the foveal reflex and small bright spots opened away), free of vessels, and near the
    expected place — the last one keeps a haemorrhage or a shadow elsewhere from being taken, and
    carries a macula that is hardly darker than the retina. ``None`` without a disc, when the macula
    is outside the photo, or when the place is not darker than the field varies anyway
    (``FOVEA_MIN`` — then the disc alone places the photo). ``window_deg`` is kept for callers of
    older versions (the window is two disc diameters).

    An eye not known (``laterality`` None) is looked at on both sides of the disc, the side the
    disc's place suggests first; the macula found tells the eye (``with_side``: the result is
    ``(x, y, confidence, "OD" | "OS")``).
    """
    from . import placement

    if disc is None or cam is None or not cam.r:
        return None
    if laterality in ("OD", "OS"):
        sides = [laterality]
    else:                                            # an unknown eye: both sides, the likelier first
        sides = ["OS", "OD"] if placement.side_of(disc, cam, None) == "OS" else ["OD", "OS"]
    f = _field or _Field(rgb, (cam.cx, cam.cy, cam.r))
    if f.lit.sum() < 50:
        return None
    f.clean(max(1.5, f.r * min(0.25, 3.8 / max(math.degrees(cam.tmax), 5.0))))
    step, xx, yy = f.step, f.xx, f.yy
    best = None
    for n, side in enumerate(sides):
        guess = placement.expected_fovea(cam, disc, side)
        if guess is None:
            continue
        gx, gy = guess[0] / step, guess[1] / step
        dr = math.hypot(disc[0] - guess[0], disc[1] - guess[1]) / step / 5.3     # a disc radius, here
        if dr < 0.8:
            continue
        if math.hypot(gx - f.cx, gy - f.cy) > f.r - 1.5 * dr:    # the macula cut by the edge: the disc alone places the photo
            continue
        key = ("fovea", round(dr * 2) / 2)
        if key not in f._even:                       # (the same for every candidate of about this scale)
            d_ = key[1]
            _, G, _ = f.even("green", d_, 85.0)
            k = max(3, int(round(d_ * 0.45)) | 1)
            opened = _morph(G, k, False)
            s1, s2 = 0.5 * d_, 2.2 * d_
            c1, c2 = np.maximum(_blur32(f.field, s1), 1e-3), np.maximum(_blur32(f.field, s2), 1e-3)
            dark = _blur32(opened * f.field, s2) / c2 - _blur32(opened * f.field, s1) / c1
            th = np.clip(_morph(G, k, True) - G, 0.0, 0.3) * f.field
            ves = _blur32(th, 1.2 * d_) / np.maximum(_blur32(f.field, 1.2 * d_), 1e-3)
            valid = f.lit & (c2 > 0.8)
            if valid.sum() < 50:
                f._even[key] = None
            else:
                f._even[key] = (dark, valid, np.clip(_robust_z(dark, valid), -3.0, 8.0),
                                np.clip(_robust_z(ves, valid), -2.0, 6.0))
        if f._even[key] is None:
            continue
        dark, valid, zd, zv = f._even[key]
        # the expected place is surer across the line from the disc than along it: how far the macula
        # lies from the disc goes with the photo's scale (a field of view set a quarter off moves it a
        # disc diameter and more), which side of that line it lies on does not
        ux, uy = gx - disc[0] / step, gy - disc[1] / step
        un = math.hypot(ux, uy) or 1.0
        along = ((xx - gx) * ux + (yy - gy) * uy) / un / dr
        across = ((xx - gx) * -uy + (yy - gy) * ux) / un / dr
        win = valid & (np.abs(along) <= 4.2) & (np.abs(across) <= 3.2)
        if win.sum() < 20:
            continue
        score = np.where(win, zd - zv + 5.4 * np.exp(-0.5 * ((along / 3.0) ** 2 + (across / 1.6) ** 2)), -1e9)
        iy, ix = np.unravel_index(int(np.argmax(score)), score.shape)
        conf = float(zd[iy, ix])
        if conf < FOVEA_MIN or dark[iy, ix] <= 0.004:          # not darker than its surroundings: no macula to see
            continue
        # the centre of the dark patch, not its single darkest pixel
        near = win & (np.hypot(xx - ix, yy - iy) <= 1.2 * dr)
        wgt = np.where(near, np.maximum(score - (score[iy, ix] - 1.5), 0.0), 0.0)
        if wgt.sum() > 0:
            fx, fy = float((wgt * xx).sum() / wgt.sum()), float((wgt * yy).sum() / wgt.sum())
        else:
            fx, fy = float(ix), float(iy)
        # (which side: the darker, vessel-free place — the side the disc's place suggests a little ahead)
        rank = float(zd[iy, ix] - zv[iy, ix]) + (0.75 if n == 0 else 0.0)
        cand = ((fx + 0.5) * step, (fy + 0.5) * step, conf, side, rank)
        if best is None or cand[4] > best[4]:
            best = cand
    if best is None:
        return None
    return best[:4] if with_side else best[:3]


def disc_candidates(rgb: np.ndarray, circle: tuple[float, float, float], *, disc_frac: float = 0.11,
                    search: float = 0.7, reach: float = 0.9, count: int = 6,
                    _field: _Field | None = None) -> list[tuple[float, ...]]:
    """Places that could be the optic disc, the likeliest first: ``(x, y, score, brightness, vessels,
    open)``.

    The strongest local contrast alone (:func:`detect_disc`, Sinthanayothin 1999) lies on the disc's
    *rim*, a radius or two beside its centre, and is taken in by exudates, scars and glare. Here three
    cues add up, each in units of the field's own spread, on the photo with its illumination evened
    out (:class:`_Field`):

    * ``brightness`` — a bright *blob the size of a disc* (difference of Gaussians): its peak is the
      disc's centre, and a plaque larger or smaller than a disc answers less;
    * ``vessels`` — thick vessels running mostly up and down through the place (the vessels of the
      retina leave the disc upward and downward — Hoover & Goldbaum 2003, Mahfouz & Fahmy 2010):
      what a bright lesion or a reflex does not have;
    * the local contrast, with a small weight.

    Not candidates: a bright area far larger than a disc (a flare), or larger than a few discs and
    reaching in from the rim (the lid's reflex) — and the lid's shadow and lashes, far darker than
    retina. ``open`` is the share of the surroundings (two rings, 3 and 5 disc radii out, inside the
    field) brighter than the place itself — a disc has darker retina all round (about 0), the edge of
    a band has not. ``search`` is kept for callers of older versions; the peaks are taken out to
    ``reach`` × radius, each at least three disc radii from the others."""
    f = _field or _Field(rgb, circle)
    r, cx, cy, xx, yy = f.r, f.cx, f.cy, f.xx, f.yy
    dr = max(1.5, r * disc_frac)
    if f.lit.sum() < 50:
        return []
    f.clean(dr)
    E, _, cover = f.even("lum", dr, 80.0)
    valid = f.lit & (cover > 0.5)
    ok = valid & (f.d2 <= (reach * r) ** 2)
    if ok.sum() < 50:
        return []
    Em = np.minimum(E, 2.5) * f.field
    blob = (_blur32(Em, 0.7 * dr) / np.maximum(_blur32(f.field, 0.7 * dr), 1e-3)
            - _blur32(Em, 2.5 * dr) / np.maximum(_blur32(f.field, 2.5 * dr), 1e-3))
    th = _vessels(f, dr)
    if cv2 is not None:
        vx = np.abs(cv2.Sobel(th, cv2.CV_32F, 1, 0, ksize=3))      # vessels running up and down: change along x
        vy = np.abs(cv2.Sobel(th, cv2.CV_32F, 0, 1, ksize=3))
        kw, kh = max(3, int(2 * dr) | 1), max(3, int(6 * dr) | 1)
        vert = cv2.blur(vx - 0.5 * vy, (kw, kh)) / np.maximum(cv2.blur(f.field, (kw, kh)), 0.3)
    else:
        vert = _blur32(th, 2 * dr)
    mean = _blur32(f.lum, dr)
    sd = np.sqrt(np.maximum(_blur32(f.lum * f.lum, dr) - mean * mean, 0)) / np.maximum(mean / np.maximum(E, 1e-3), 0.5)
    zb, zv = np.clip(_robust_z(blob, ok), -3, 12), np.clip(_robust_z(vert, ok), -3, 8)
    score = np.where(ok, zb + 0.8 * zv + 0.3 * np.clip(_robust_z(sd, ok), -3, 8), -1e9)
    level = _blur32(Em, dr)
    out = []
    for _ in range(count):
        iy, ix = np.unravel_index(int(np.argmax(score)), score.shape)
        if score[iy, ix] < 2.0:                 # (nothing there stands out of the field)
            break
        best = float(score[iy, ix])
        score[(xx - ix) ** 2 + (yy - iy) ** 2 <= (3.0 * dr) ** 2] = -1e9
        # the place: towards the centre of the bright blob (the vessels pull the sum's peak along their run)
        near = ok & ((xx - ix) ** 2 + (yy - iy) ** 2 <= (1.3 * dr) ** 2)
        if near.any():
            by, bx = np.unravel_index(int(np.argmax(np.where(near, zb, -1e9))), zb.shape)
            if zb[by, bx] >= 1.5:
                wgt = np.where(near & ((xx - bx) ** 2 + (yy - by) ** 2 <= dr * dr), np.maximum(zb - 0.5 * zb[by, bx], 0.0), 0.0)
                if wgt.sum() > 0:
                    fx, fy = float((wgt * xx).sum() / wgt.sum()), float((wgt * yy).sum() / wgt.sum())
                    # (… and half of a disc seen large is dimmed by its own vessels: between the two there;
                    # a disc a few pixels across — ultra-wide-field — is one bright spot: the blob's centre)
                    t = float(np.clip((dr - 10.0) / 6.0, 0.0, 1.0)) * 0.5
                    fx, fy = fx + t * (ix - fx), fy + t * (iy - fy)
                    ix_, iy_ = int(round(fx)), int(round(fy))
                    if any(math.hypot(c[0] / f.step - fx, c[1] / f.step - fy) < 2.0 * dr for c in out):
                        continue                # (the blob of a candidate already taken)
                    out.append(((fx + 0.5) * f.step, (fy + 0.5) * f.step, best, float(zb[iy_, ix_]),
                                float(zv[iy_, ix_]), _open_share(level, ix_, iy_, dr, cx, cy, r)))
                    continue
        out.append(((ix + 0.5) * f.step, (iy + 0.5) * f.step, best, float(zb[iy, ix]),
                    float(zv[iy, ix]), _open_share(level, ix, iy, dr, cx, cy, r)))
    return out


def _open_share(mean: np.ndarray, ix: int, iy: int, dr: float, cx: float, cy: float, r: float) -> float:
    """The share of the places 3 and 5 disc radii around ``(ix, iy)``, inside the field, that are at
    least as bright as it (``mean``: the picture blurred over a disc radius)."""
    h, w = mean.shape
    here = mean[iy, ix]
    hits = seen = 0
    for k in (3.0, 5.0):
        for a in np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False):
            x, y = ix + k * dr * math.cos(a), iy + k * dr * math.sin(a)
            if not (0 <= x < w and 0 <= y < h) or (x - cx) ** 2 + (y - cy) ** 2 > (0.97 * r) ** 2:
                continue                       # (outside the field: black — says nothing either way)
            seen += 1
            hits += mean[int(y), int(x)] >= here
    return hits / seen if seen else 0.0


def detect_landmarks(rgb: np.ndarray, cam, laterality: str | None = None, *, search: float = 0.7):
    """The optic disc and the fovea together: ``(disc, fovea)`` — ``(x, y, confidence)`` or ``None``
    each, the fovea with the eye its side tells as a fourth value (as :func:`detect_fovea` with
    ``with_side``).

    Every place that looks like a disc is a candidate (:func:`disc_candidates`: a bright blob of a
    disc's size with vessels running through it), and the one is taken that looks most like a disc
    *and* has a macula where a disc's macula lies (:func:`detect_fovea`). Beyond ``search`` × radius a
    candidate must earn it (the rim of the field has reflexes, lashes and the lid).

    Measured on 516 photos marked by experts (IDRiD) and on their poorly taken versions (blurred,
    dark, flared, hazy, uneven, noisy, with lashes): docs/landmarks.md.
    """
    if cam is None or not cam.r:
        return None, None
    circle = (cam.cx, cam.cy, cam.r)
    tmax = math.degrees(cam.tmax)
    field = _Field(rgb, circle)
    best = None
    for x, y, conf, *_ in disc_candidates(rgb, circle, disc_frac=min(0.25, 3.8 / max(tmax, 5.0)),
                                          search=search, count=4, _field=field):
        fovea = detect_fovea(rgb, cam, (x, y), laterality, with_side=True, _field=field)
        score = conf + (0.6 * min(fovea[2], 6.0) if fovea else 0.0)
        if math.hypot(x - cam.cx, y - cam.cy) > search * cam.r:
            score -= 2.5
        if best is None or score > best[0]:
            best = (score, (x, y, conf), fovea)
    return (None, None) if best is None else (best[1], best[2])


def fundus_alpha(rgb: np.ndarray, circle: tuple[float, float, float] | None = None) -> np.ndarray:
    """``uint8`` alpha: 255 on illuminated retina, 0 on the black surround."""
    if cv2 is not None and rgb.dtype == np.uint8 and rgb.ndim == 3:
        return _fundus_alpha_cv(rgb, circle)       # 24-megapixel photo: 0.1 s instead of 1.5 s
    lum = luminance(rgb.astype(np.float32))
    thr = max(8.0, 0.05 * float(np.percentile(lum, 99)))
    mask = (lum > thr).astype(np.uint8) * 255
    if circle is not None:
        h, w = mask.shape
        cx, cy, r = circle
        yy, xx = np.ogrid[0:h, 0:w]
        mask[(xx - cx) ** 2 + (yy - cy) ** 2 > (r * 1.01) ** 2] = 0
    img = Image.fromarray(mask).filter(ImageFilter.MinFilter(3))
    img = img.filter(ImageFilter.GaussianBlur(max(1.0, min(mask.shape) / 600)))
    return np.asarray(img)


def _fundus_alpha_cv(rgb: np.ndarray, circle) -> np.ndarray:
    """``fundus_alpha`` with OpenCV: the same steps on bytes instead of floats."""
    lum = cv2.cvtColor(np.ascontiguousarray(rgb[..., :3]), cv2.COLOR_RGB2GRAY)
    cdf = np.cumsum(cv2.calcHist([lum], [0], None, [256], [0, 256]).ravel())
    p99 = int(np.searchsorted(cdf, 0.99 * cdf[-1]))
    thr = max(8.0, 0.05 * p99)
    _, mask = cv2.threshold(lum, int(math.floor(thr)), 255, cv2.THRESH_BINARY)   # lum > thr
    if circle is not None:
        cx, cy, r = circle
        disc = np.zeros_like(mask)
        cv2.circle(disc, (int(round(cx)), int(round(cy))), int(r * 1.01), 255, -1)
        mask = cv2.bitwise_and(mask, disc)
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8))
    sigma = max(1.0, min(mask.shape) / 600)
    k = int(sigma // 2)                               # a wide soft edge: blurred on a smaller copy
    if k < 2:
        return cv2.GaussianBlur(mask, (0, 0), sigma)
    h, w = mask.shape
    small = cv2.resize(mask, (max(1, w // k), max(1, h // k)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigma / k)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def thumbnail(rgb: np.ndarray, size: int = 320) -> Image.Image:
    img = Image.fromarray(rgb)
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    return img


# ---------------------------------------------------------------------------
# display adjustments
# ---------------------------------------------------------------------------
CHANNELS = ("rgb", "redfree", "red", "green", "blue")
CHANNEL_LABELS = {"rgb": "컬러", "redfree": "Red-free (RNFL 강화 0.9)", "red": "적색 채널",
                  "green": "녹색 채널(흑백)", "blue": "청색 채널"}
RNFL_K = 0.9            # Red-free: the strength of 녹내장 분석 → 광각 분석's RNFL 대비 강화


def rnfl_green(rgb: np.ndarray, k: float = RNFL_K) -> np.ndarray:
    """The green channel with its local contrast raised, which brings out the nerve fibre layer — grey;
    outside the image circle the photo as it is. The same picture as 녹내장 분석 → 광각 분석 with 레드프리
    and RNFL 대비 강화 ``k`` (``glaucoma.enhance_wide``) — the Red-free button's picture at 0.9."""
    h, w = rgb.shape[:2]
    g = rgb[..., 1].astype(np.float32)
    if cv2 is not None:
        small = cv2.resize(np.ascontiguousarray(rgb[..., 1]), (max(1, w // 16), max(1, h // 16)),
                           interpolation=cv2.INTER_AREA)
        blur = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    else:
        img = Image.fromarray(np.ascontiguousarray(rgb[..., 1]))
        blur = np.asarray(img.resize((max(1, w // 16), max(1, h // 16)), Image.Resampling.BOX)
                          .resize((w, h), Image.Resampling.BICUBIC)).astype(np.float32)
    lit = rgb.astype(np.int32).sum(axis=2) > 24              # outside the image circle stays as it is
    mean = float(g[lit].mean()) if lit.any() else 80.0
    v = np.clip(105 + (g - mean) * 1.9 + k * 2.2 * (g - blur), 0, 255).astype(np.uint8)
    out = np.repeat(v[..., None], 3, axis=2)
    out[~lit] = rgb[~lit]
    return out


def _lut(brightness: float, contrast: float, gamma: float, lo: float = 0.0, hi: float = 255.0) -> np.ndarray:
    x = np.arange(256, dtype=np.float64)
    x = (x - lo) / max(hi - lo, 1.0)                    # auto-stretch window
    x = np.clip(x, 0, 1) ** (1.0 / max(gamma, 0.05))
    x = (x - 0.5) * contrast + 0.5 + brightness
    return np.clip(np.rint(x * 255.0), 0, 255).astype(np.uint8)


def adjust(rgb: np.ndarray, *, brightness: float = 0.0, contrast: float = 1.0, gamma: float = 1.0,
           channel: str = "rgb", invert: bool = False, auto: bool = False,
           levels: tuple[int, int] = (0, 255)) -> np.ndarray:
    """``brightness`` −1..1, ``contrast`` 0..3, ``gamma`` 0.2..5, ``levels`` =
    black / white input points (histogram dialog)."""
    if channel == "rgb":
        src = rgb
    elif channel == "redfree":  # Red-free: green + RNFL 강화 0.9 (the picture of 광각 분석)
        src = rnfl_green(rgb)
    else:
        g = np.ascontiguousarray(rgb[..., {"red": 0, "green": 1, "blue": 2}[channel]])
        src = cv2.merge([g, g, g]) if cv2 is not None and g.dtype == np.uint8 else np.stack([g, g, g], axis=-1)
    identity = brightness == 0 and contrast == 1 and gamma == 1 and not invert and not auto \
        and tuple(levels) == (0, 255)
    if identity:
        return src
    lo, hi = float(levels[0]), float(levels[1])
    if auto:
        # One window for all channels (from luminance inside the fundus): a
        # per-channel stretch would shift the retina's colour.
        sample = luminance(src[::4, ::4].astype(np.float32))
        sample = sample[sample > 8]
        if sample.size > 100:
            lo, hi = float(np.percentile(sample, 1.0)), float(np.percentile(sample, 99.5))
    lut = _lut(brightness, contrast, gamma, lo, hi)
    if invert:
        lut = 255 - lut
    if cv2 is not None and src.dtype == np.uint8:      # table look-up in C: ~8× faster on a large photo
        return cv2.LUT(np.ascontiguousarray(src), lut)
    return lut[src]


# ---------------------------------------------------------------------------
# processing operations (VK-2 "Image Processing" toolbar) — applied on a copy,
# the stored photograph is never modified
# ---------------------------------------------------------------------------
OPS = ("sharpen_light", "sharpen", "sharpen_strong", "enhance", "equalize", "denoise", "denoise_avg")
OP_LABELS = {
    "sharpen_light": "선명하게(약)", "sharpen": "선명하게", "sharpen_strong": "선명하게(강)",
    "enhance": "향상(국소 대비)", "equalize": "히스토그램 평활화", "denoise": "노이즈 감소(중간값)",
    "denoise_avg": "노이즈 감소(평균)",
}


def _fundus_mask(rgb: np.ndarray) -> np.ndarray:
    return luminance(rgb.astype(np.float32)) > 10


def apply_op(rgb: np.ndarray, op: str) -> np.ndarray:
    img = Image.fromarray(rgb)
    side = max(rgb.shape[:2])
    if op.startswith("sharpen"):
        pct = {"sharpen_light": 60, "sharpen": 120, "sharpen_strong": 220}[op]
        rad = max(1.0, side / 1400)
        return np.asarray(img.filter(ImageFilter.UnsharpMask(radius=rad, percent=pct, threshold=2)))
    if op == "enhance":
        # Local contrast: a wide unsharp mask (≈ CLAHE look) followed by a stretch
        # inside the fundus, so faint vessels and lesions stand out.
        rad = max(4.0, side / 60)
        out = np.asarray(img.filter(ImageFilter.UnsharpMask(radius=rad, percent=90, threshold=0)))
        return adjust(out, auto=True)
    if op == "equalize":
        mask = Image.fromarray((_fundus_mask(rgb) * 255).astype(np.uint8))
        return np.asarray(ImageOps.equalize(img, mask=mask))
    if op == "denoise":
        return np.asarray(img.filter(ImageFilter.MedianFilter(3 if side < 3000 else 5)))
    if op == "denoise_avg":
        return np.asarray(img.filter(ImageFilter.BoxBlur(1 if side < 3000 else 2)))
    raise ValueError(op)


def apply_ops(rgb: np.ndarray, ops) -> np.ndarray:
    for op in ops:
        rgb = apply_op(rgb, op)
    return rgb


def histogram(rgb: np.ndarray) -> np.ndarray:
    """``(3, 256)`` per-channel counts inside the fundus (black surround excluded)."""
    sample = rgb[::2, ::2].reshape(-1, 3)
    sample = sample[luminance(sample.astype(np.float32)) > 10]
    return np.stack([np.bincount(sample[:, c], minlength=256)[:256] for c in range(3)])


def shrink(a: np.ndarray, factor: float, like: np.ndarray | None = None) -> np.ndarray:
    """``a`` (uint8, grey or RGB) reduced by ``factor`` < 1 with area averaging — or to the size of ``like``."""
    h, w = a.shape[:2]
    if like is not None:
        size = (like.shape[1], like.shape[0])
    else:
        size = (max(1, round(w * factor)), max(1, round(h * factor)))
    if cv2 is not None:
        return cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    return np.asarray(Image.fromarray(a).resize(size, Image.Resampling.BOX))


def downscale(rgb: np.ndarray, max_side: int) -> np.ndarray:
    h, w = rgb.shape[:2]
    if max(h, w) <= max_side:
        return rgb
    img = Image.fromarray(rgb)
    img.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return np.asarray(img)
