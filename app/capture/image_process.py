"""이미지 보정·편집 엔진 (Pro 모드 Image Process).

원본은 건드리지 않고 표시/저장용 보정본을 만든다. 입력·출력 모두 BGR uint8.
처리 순서(웹 pro.js 와 동일):
  1 노이즈 제거   denoise   none | median(3×3) | average(3×3)
  2 채널          channel   rgb | green(Red-free) | red | blue | gray
  3 색균형·채도   r/g/b_gain 0.5~1.5, saturation 0~2  (컬러 채널일 때)
  4 레벨          black/white 입력 흑·백점 (히스토그램 / 자동 대비)
  5 대비·밝기     contrast 0.2~3.0 (중간값 기준), brightness -100~+100
  6 감마          gamma 0.2~3.0 (>1 밝게)
  7 국소 대비 향상 enhance 0~3 (CLAHE, 휘도 기반)
  8 샤프닝        sharpen 0~3 (언샤프 마스크: 약/중/강)
  9 네거티브      negative
기하 편집(회전·반전·자르기)은 별도 함수로, 편집 이력(실행 취소)과 함께 캔버스가 관리한다.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

CHANNELS = ("rgb", "green", "red", "blue", "gray")
_CH_INDEX = {"blue": 0, "green": 1, "red": 2}          # BGR
_SHARP_AMOUNT = {1: 0.6, 2: 1.2, 3: 2.0}
_CLAHE_CLIP = {1: 1.6, 2: 2.6, 3: 4.0}


@dataclass
class Adjust:
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    negative: bool = False
    channel: str = "rgb"
    saturation: float = 1.0
    r_gain: float = 1.0
    g_gain: float = 1.0
    b_gain: float = 1.0
    black: int = 0
    white: int = 255
    sharpen: int = 0
    denoise: str = "none"
    enhance: int = 0

    def is_identity(self) -> bool:
        return self == Adjust()

    def copy(self) -> "Adjust":
        return Adjust(**{f.name: getattr(self, f.name) for f in fields(self)})


def _luma(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.114 + img[..., 1] * 0.587 + img[..., 2] * 0.299


def apply_adjust(frame: np.ndarray, adj: Adjust) -> np.ndarray:
    if frame is None:
        return frame
    if adj.is_identity():
        return frame.copy()
    src = frame
    if adj.denoise == "median" and cv2 is not None:
        src = cv2.medianBlur(src, 3)
    elif adj.denoise == "average" and cv2 is not None:
        src = cv2.blur(src, (3, 3))
    img = src.astype(np.float32)

    # 채널
    if adj.channel in _CH_INDEX:
        c = img[..., _CH_INDEX[adj.channel]]
        img = np.stack([c, c, c], axis=-1)
    elif adj.channel == "gray":
        y = _luma(img)
        img = np.stack([y, y, y], axis=-1)
    else:
        # 색균형(RGB 게인) · 채도
        if (adj.r_gain, adj.g_gain, adj.b_gain) != (1.0, 1.0, 1.0):
            img = img * np.array([adj.b_gain, adj.g_gain, adj.r_gain], dtype=np.float32)
        if adj.saturation != 1.0:
            y = _luma(img)[..., None]
            img = y + (img - y) * float(adj.saturation)

    # 레벨
    if adj.black != 0 or adj.white != 255:
        lo, hi = float(adj.black), float(max(adj.white, adj.black + 1))
        img = (img - lo) * (255.0 / (hi - lo))
    # 대비·밝기·감마
    img = (img - 127.5) * float(adj.contrast) + 127.5 + float(adj.brightness)
    np.clip(img, 0, 255, out=img)
    if adj.gamma != 1.0:
        img = 255.0 * np.power(img / 255.0, 1.0 / float(adj.gamma))
    out = np.clip(img, 0, 255).astype(np.uint8)

    # 국소 대비 향상 (CLAHE, 휘도 비율로 색 보존)
    if adj.enhance and cv2 is not None:
        y = np.clip(_luma(out.astype(np.float32)), 0, 255).astype(np.uint8)
        clahe = cv2.createCLAHE(clipLimit=_CLAHE_CLIP.get(int(adj.enhance), 2.6), tileGridSize=(8, 8))
        y2 = clahe.apply(y)
        ratio = (y2.astype(np.float32) + 1.0) / (y.astype(np.float32) + 1.0)
        out = np.clip(out.astype(np.float32) * ratio[..., None], 0, 255).astype(np.uint8)
    # 샤프닝 (언샤프 마스크)
    if adj.sharpen and cv2 is not None:
        a = _SHARP_AMOUNT.get(int(adj.sharpen), 1.2)
        blur = cv2.GaussianBlur(out, (0, 0), 1.2)
        out = cv2.addWeighted(out, 1.0 + a, blur, -a, 0)
    if adj.negative:
        out = 255 - out
    return out


# ---------------- 분석 ----------------
def auto_levels(frame: np.ndarray, clip: float = 0.005) -> tuple[int, int]:
    """자동 대비: 휘도 하위/상위 clip 비율을 흑·백점으로."""
    y = _luma(frame.astype(np.float32))
    lo, hi = np.percentile(y, [clip * 100, 100 - clip * 100])
    lo, hi = int(max(0, np.floor(lo))), int(min(255, np.ceil(hi)))
    if hi - lo < 10:
        return 0, 255
    return lo, hi


def histogram(frame: np.ndarray) -> dict:
    """휘도·R·G·B 히스토그램 (각 256 bin)."""
    y = np.clip(_luma(frame.astype(np.float32)), 0, 255).astype(np.uint8)
    return {
        "lum": np.bincount(y.ravel(), minlength=256),
        "r": np.bincount(frame[..., 2].ravel(), minlength=256),
        "g": np.bincount(frame[..., 1].ravel(), minlength=256),
        "b": np.bincount(frame[..., 0].ravel(), minlength=256),
    }


# ---------------- 기하 편집 ----------------
def rotate90(frame: np.ndarray, k: int) -> np.ndarray:
    """k=1: 시계 방향 90°, k=-1: 반시계 90°."""
    return np.ascontiguousarray(np.rot90(frame, -k))


def flip(frame: np.ndarray, horizontal: bool) -> np.ndarray:
    return np.ascontiguousarray(frame[:, ::-1] if horizontal else frame[::-1])


def crop(frame: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    h, w = frame.shape[:2]
    xa, xb = sorted((int(round(x0)), int(round(x1))))
    ya, yb = sorted((int(round(y0)), int(round(y1))))
    xa, xb = max(0, xa), min(w, xb)
    ya, yb = max(0, ya), min(h, yb)
    return np.ascontiguousarray(frame[ya:yb, xa:xb])
