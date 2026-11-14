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
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

try:                         # OpenCV (also used by 몽타주): the heavy per-pixel steps in C
    import cv2
except ImportError:          # pragma: no cover - listed in requirements.txt
    cv2 = None

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


def detect_fovea(rgb: np.ndarray, cam, disc, laterality: str | None = None, *,
                 window_deg: float = 7.0, with_side: bool = False):
    """The fovea ``(x, y, confidence)`` or ``None``.

    The macula is a dark, vessel-free patch about 4.5 mm temporal of the disc and a little below
    it. ``cam`` (:class:`placement.Camera`) says where that is in this photo; within
    ``window_deg`` of it the fovea is the centre of the darkest macula-sized patch (the green
    channel against its surroundings — the foveal reflex and thin vessels are blurred away).
    ``None`` without a disc, when the macula is outside the photo, or when nothing dark enough is
    there (then the disc alone places the photo).

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
    small, step = _downsample(rgb, 384)
    h, w = small.shape[:2]
    green = small[..., 1].astype(np.float64) if small.ndim == 3 else small.astype(np.float64)
    yy, xx = np.mgrid[0:h, 0:w]
    dirs, inside = cam.directions((xx + 0.5) * step, (yy + 0.5) * step)
    mask = (inside & (luminance(small.astype(np.float64)) > 8.0)).astype(np.float64)
    best = None
    for side in sides:
        guess = placement.expected_fovea(cam, disc, side)
        if guess is None:
            continue
        q0 = cam.direction(*guess)
        gx, gy = guess[0] / step, guess[1] / step
        q1 = cam.direction(min(guess[0] + step, cam.cx + cam.r), guess[1])
        deg_px = max(placement.angle_between(q0, q1), 1e-3) if q1 is not None else math.degrees(cam.tmax) / (cam.r / step)
        s_small, s_big = 1.5 / deg_px, 6.0 / deg_px
        g = green
        if cv2 is not None:                          # the foveal reflex and other small bright spots: opened away
            k = max(3, int(round(2.0 / deg_px)) | 1)
            g = cv2.morphologyEx(np.ascontiguousarray(green, np.float32), cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))).astype(np.float64)
        cover = np.maximum(_blur(mask, s_big), 1e-6)
        dark = _blur(g * mask, s_big) / cover - _blur(g * mask, s_small) / np.maximum(_blur(mask, s_small), 1e-6)
        valid = (mask > 0) & (cover > 0.85)
        if valid.sum() < 50:
            continue
        dist = np.degrees(np.arccos(np.clip(dirs @ q0, -1.0, 1.0)))
        win = valid & (dist <= window_deg)
        if not win.any():
            continue
        spread = float(dark[valid].std()) + 0.25
        score = np.where(win, dark / spread * (0.55 + 0.45 * np.exp(-(dist / (0.7 * window_deg)) ** 2)), -1e9)
        iy, ix = np.unravel_index(int(np.argmax(score)), score.shape)
        peak = float(dark[iy, ix])
        around = float(_blur(g * mask, s_big)[iy, ix] / cover[iy, ix])
        if peak < max(1.0, 0.012 * around):          # not darker than its surroundings: no macula to see
            continue
        conf = peak / spread
        # the centre of the dark patch, not its single darkest pixel
        near = win & (np.hypot(xx - ix, yy - iy) <= 4.0 / deg_px)
        wgt = np.where(near, np.maximum(dark - 0.5 * peak, 0.0), 0.0)
        if peak > 0 and wgt.sum() > 0:
            fx, fy = float((wgt * xx).sum() / wgt.sum()), float((wgt * yy).sum() / wgt.sum())
        else:
            fx, fy = float(ix), float(iy)
        cand = ((fx + 0.5) * step, (fy + 0.5) * step, conf, side, math.hypot(fx - gx, fy - gy))
        if best is None or cand[2] > best[2]:
            best = cand
    if best is None or best[2] < 1.2:
        return None
    return best[:4] if with_side else best[:3]


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
CHANNEL_LABELS = {"rgb": "컬러", "redfree": "Red-free (녹색)", "red": "적색 채널",
                  "green": "녹색 채널(흑백)", "blue": "청색 채널"}


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
    elif channel == "redfree":  # green channel, shown as green-tinted grey
        g = np.ascontiguousarray(rgb[..., 1])
        if cv2 is not None and g.dtype == np.uint8:
            tint = cv2.LUT(g, (np.arange(256) * 0.85).astype(np.uint8))
            src = cv2.merge([tint, g, tint])
        else:
            tint = (g * 0.85).astype(np.uint8)
            src = np.stack([tint, g, tint], axis=-1)
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
