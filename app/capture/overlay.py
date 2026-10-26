"""겹쳐보기(Overlay) — 서로 다른 날 찍은 두 영상을 겹쳐 경과(진행)를 본다.

입력·출력 모두 BGR uint8. 위 영상(top)은 아래 영상(base) 크기에 맞춰 늘리고,
dx/dy(px) 만큼 옮겨 위치를 맞춘 뒤 아래 방식으로 합성한다.
  blend     투명도 alpha(0~1) 로 섞기
  diff      두 영상의 차이 (변한 곳만 밝게)
  checker   바둑판 무늬로 번갈아 보이기 (경계가 이어지는지 확인)
  split     세로 경계선 왼쪽 = 아래 영상, 오른쪽 = 위 영상 (alpha = 경계 위치)
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

MODES = ("blend", "diff", "checker", "split")
MODE_LABELS = {"blend": "겹치기 (투명도)", "diff": "차이 강조", "checker": "바둑판", "split": "좌우 분할"}


def fit_to(top: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """top 을 (w, h) 크기로 맞춤."""
    w, h = size
    if top.shape[1] == w and top.shape[0] == h:
        return top
    if cv2 is not None:
        return cv2.resize(top, (w, h), interpolation=cv2.INTER_LINEAR)
    ys = (np.arange(h) * top.shape[0] / h).astype(int)
    xs = (np.arange(w) * top.shape[1] / w).astype(int)
    return top[ys][:, xs]


def shift(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """dx, dy(px) 만큼 평행 이동. 빈 곳은 검정."""
    if not dx and not dy:
        return img
    h, w = img.shape[:2]
    out = np.zeros_like(img)
    xs, xd = (0, dx) if dx >= 0 else (-dx, 0)
    ys, yd = (0, dy) if dy >= 0 else (-dy, 0)
    cw, ch = w - abs(dx), h - abs(dy)
    if cw > 0 and ch > 0:
        out[yd:yd + ch, xd:xd + cw] = img[ys:ys + ch, xs:xs + cw]
    return out


def compose(base: np.ndarray, top: np.ndarray, mode: str = "blend", alpha: float = 0.5,
            dx: int = 0, dy: int = 0, cell: int = 0) -> np.ndarray:
    if base is None or top is None:
        return base if top is None else top
    h, w = base.shape[:2]
    t = shift(fit_to(top, (w, h)), int(dx), int(dy))
    a = float(min(1.0, max(0.0, alpha)))
    if mode == "diff":
        d = np.abs(base.astype(np.int16) - t.astype(np.int16)).astype(np.float32)
        gain = 255.0 / max(1.0, float(d.max()))          # 작은 차이도 보이도록 늘림
        return np.clip(d * gain, 0, 255).astype(np.uint8)
    if mode == "checker":
        n = int(cell) or max(16, min(w, h) // 8)
        yy, xx = np.mgrid[0:h, 0:w]
        mask = ((yy // n + xx // n) % 2).astype(bool)
        out = base.copy()
        out[mask] = t[mask]
        return out
    if mode == "split":
        x = int(round(w * a))
        out = base.copy()
        out[:, x:] = t[:, x:]
        if 0 < x < w:
            out[:, max(0, x - 1):x + 1] = (255, 255, 255)
        return out
    return np.clip(base.astype(np.float32) * (1 - a) + t.astype(np.float32) * a, 0, 255).astype(np.uint8)
