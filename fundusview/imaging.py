"""Image loading and analysis (numpy + Pillow; pydicom for DICOM pixels).

* :func:`load_rgb`      — any supported file -> ``uint8`` RGB array
* :func:`detect_circle` — the fundus image circle (centre, radius) on its black
  mask, robust to burned-in text/logos outside the circle and to circles
  clipped at the top/bottom of the frame
* :func:`detect_disc`   — brightest-blob estimate of the optic disc
* :func:`fundus_alpha`  — soft-edged mask used as the 3D texture's alpha
* :func:`adjust`        — display adjustments (brightness/contrast/gamma,
  red-free / single channel, invert, auto-stretch) via 256-entry LUTs
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = 400_000_000  # montages are large; files are local and trusted


def load_rgb(path: Path | str) -> np.ndarray:
    path = Path(path)
    from .extract.dicom_meta import is_dicom

    if is_dicom(path):
        return _dicom_rgb(path)
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("I;16", "I;16B", "I;16L", "I"):
            a = np.asarray(img, dtype=np.float64)
            return np.repeat(_to_uint8(a)[..., None], 3, axis=2)
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGB", img.size, (0, 0, 0))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.getchannel("A"))
            return np.asarray(bg)
        return np.asarray(img.convert("RGB"))


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
    thr = max(10.0, 0.08 * float(np.percentile(lum, 99)))
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
    A = np.stack([np.ones_like(ys_a), 2.0 * ys_a], axis=1)
    sol, *_ = np.linalg.lstsq(A, half ** 2 + ys_a ** 2, rcond=None)
    c0, cy = sol
    r2 = c0 + cy ** 2
    r = math.sqrt(r2) if r2 > 0 else float(half.max())
    if not (0.2 * w < r < 1.2 * max(w, h)):
        r, cy = float(half.max()), float(ys_a[np.argmax(half)])
    return ((cx + 0.5) * step, (cy + 0.5) * step, r * step)


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur of a float image (reflect padding)."""
    rad = max(1, int(3 * sigma))
    x = np.arange(-rad, rad + 1, dtype=np.float64)
    k = np.exp(-x * x / (2 * sigma * sigma))
    k /= k.sum()
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
    z-score; detections closer than 8 % of the radius to the centre are
    rejected (a fovea-centred photo never has its disc there).
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
    if conf < 3.0 or d2[iy, ix] < (0.08 * r) ** 2:
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


def fundus_alpha(rgb: np.ndarray, circle: tuple[float, float, float] | None = None) -> np.ndarray:
    """``uint8`` alpha: 255 on illuminated retina, 0 on the black surround."""
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


def thumbnail(rgb: np.ndarray, size: int = 320) -> Image.Image:
    img = Image.fromarray(rgb)
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    return img


# ---------------------------------------------------------------------------
# display adjustments
# ---------------------------------------------------------------------------
CHANNELS = ("rgb", "redfree", "red", "green", "blue")
CHANNEL_LABELS = {"rgb": "컬러", "redfree": "Red-free (녹색)", "red": "적색 채널",
                  "green": "녹색 채널(흑백)", "blue": "청색 채널"}


def _lut(brightness: float, contrast: float, gamma: float, lo: float = 0.0, hi: float = 255.0) -> np.ndarray:
    x = np.arange(256, dtype=np.float64)
    x = (x - lo) / max(hi - lo, 1.0)                    # auto-stretch window
    x = np.clip(x, 0, 1) ** (1.0 / max(gamma, 0.05))
    x = (x - 0.5) * contrast + 0.5 + brightness
    return np.clip(np.rint(x * 255.0), 0, 255).astype(np.uint8)


def adjust(rgb: np.ndarray, *, brightness: float = 0.0, contrast: float = 1.0, gamma: float = 1.0,
           channel: str = "rgb", invert: bool = False, auto: bool = False) -> np.ndarray:
    """``brightness`` −1..1, ``contrast`` 0..3, ``gamma`` 0.2..5."""
    if channel == "rgb":
        src = rgb
    elif channel == "redfree":  # green channel, shown as green-tinted grey
        g = rgb[..., 1]
        tint = (g * 0.85).astype(np.uint8)
        src = np.stack([tint, g, tint], axis=-1)
    else:
        g = rgb[..., {"red": 0, "green": 1, "blue": 2}[channel]]
        src = np.stack([g, g, g], axis=-1)
    identity = brightness == 0 and contrast == 1 and gamma == 1 and not invert and not auto
    if identity:
        return src
    out = np.empty_like(src)
    for c in range(3):
        ch = src[..., c]
        lo, hi = 0.0, 255.0
        if auto:
            sample = ch[::4, ::4]
            sample = sample[sample > 8]
            if sample.size > 100:
                lo, hi = np.percentile(sample, 1.0), np.percentile(sample, 99.5)
        lut = _lut(brightness, contrast, gamma, lo, hi)
        if invert:
            lut = 255 - lut
        out[..., c] = lut[ch]
    return out
