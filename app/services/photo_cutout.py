"""흰 배경 제품 사진에서 장비만 떼어내기 (홈 화면 사진용).

배경(가장자리와 이어진 거의 흰 영역 · 장비 사이로 보이는 닫힌 흰 영역)을 투명하게 하고,
경계는 밝기에 따라 부드럽게 비우며 흰 번짐을 빼서 어두운 · 밝은 바탕 어디에 올려도 테두리가 남지 않게 한다.
아래쪽(바닥)의 옅은 그림자 꼬리도 투명하게 한다.
"""
from __future__ import annotations

import cv2
import numpy as np


def is_white_background(bgr: np.ndarray, level: int = 232) -> bool:
    """가장자리가 모두 거의 흰색이면 True (제품 사진)."""
    if bgr is None or bgr.ndim != 3 or min(bgr.shape[:2]) < 8:
        return False
    h, w = bgr.shape[:2]
    edge = np.concatenate([bgr[1, :, :3], bgr[h - 2, :, :3], bgr[:, 1, :3], bgr[:, w - 2, :3]])
    return int(edge.min()) >= level


def cutout_white_background(bgr: np.ndarray, thr: int = 246, band_px: float = 3.0, soft_lo: int = 212,
                            hole_min: int = 400, floor_frac: float = 0.70, protect=None) -> np.ndarray:
    """BGR → BGRA (배경 투명). protect: 바닥 그림자 처리에서 뺄 (x0, x1, y1) 비율 상자 (예: 은색 기둥)."""
    bgr = np.ascontiguousarray(bgr[..., :3])
    h, w = bgr.shape[:2]
    g = bgr.min(axis=2).astype(np.float32)
    spread = bgr.max(axis=2).astype(np.float32) - g
    white = ((g >= thr) & (spread <= 10)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    for i in range(1, n):                      # 장비 사이로 보이는 배경 (닫힌 흰 영역)
        if i not in border and stats[i, cv2.CC_STAT_AREA] >= hole_min and np.median(g[lab == i]) >= 252:
            bg |= lab == i
    fgm = (~bg).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(fgm, connectivity=8)
    for i in range(1, n2):                     # 케이블 옆 흰 점 같은 작은 조각
        if st2[i, cv2.CC_STAT_AREA] < 40:
            fgm[lab2 == i] = 0
    dist = cv2.distanceTransform(fgm, cv2.DIST_L2, 3)
    a = fgm.astype(np.float32)
    neutral = spread <= 16
    band = (fgm > 0) & (dist <= band_px)
    a = np.where(band & neutral, np.minimum(a, np.clip((thr + 4 - g) / (thr + 4 - soft_lo), 0, 1)), a)
    floor = np.zeros((h, w), bool)
    floor[int(h * floor_frac):] = True
    tail = floor & (fgm > 0) & (dist <= 14) & neutral & (g >= 226)
    a = np.where(tail, np.minimum(a, np.clip((thr + 4 - g) / 60, 0, 1)), a)
    keep = np.zeros((h, w), bool)
    if protect:
        x0, x1, y1 = protect
        keep[: int(h * y1), int(w * x0): int(w * x1) + 1] = True
    rim = floor & ~keep & (fgm > 0) & (dist <= 10) & neutral & (g >= 180)
    a = np.where(rim, np.minimum(a, np.clip((thr + 4 - g) / 90, 0, 1)), a)
    a = cv2.GaussianBlur(a, (0, 0), 0.6)
    a[fgm == 0] = np.minimum(a[fgm == 0], 0.35)
    a = np.clip(a, 0, 1)
    af = np.clip(a, 1e-3, 1)[..., None]       # 흰 번짐 빼기: C = a·F + (1 − a)·255
    fg = np.clip((bgr.astype(np.float32) - (1 - af) * 255) / af, 0, 255)
    alpha = (a * 255 + 0.5).astype(np.uint8)
    fg[alpha == 0] = 0                         # 완전히 투명한 곳은 검정 (PNG 가 작아짐)
    return np.dstack([fg.astype(np.uint8), alpha])


def trim_transparent(bgra: np.ndarray, pad: int = 6) -> np.ndarray:
    """투명한 가장자리를 잘라 장비만 꼭 맞게 (여백 pad px)."""
    ys, xs = np.nonzero(bgra[..., 3] > 8)
    if len(xs) == 0:
        return bgra
    h, w = bgra.shape[:2]
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
    return np.ascontiguousarray(bgra[y0:y1, x0:x1])
