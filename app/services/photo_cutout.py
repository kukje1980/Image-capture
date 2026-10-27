"""제품 사진에서 장비만 떼어내기 (홈 화면 사진용).

- cutout_white_background: 흰 배경 — 가장자리와 이어진 거의 흰 영역 · 장비 사이로 보이는 닫힌 흰 영역을 투명하게,
  경계는 밝기에 따라 부드럽게 비우고 흰 번짐을 빼서 어두운 · 밝은 바탕 어디에 올려도 테두리가 남지 않게 한다.
  아래쪽(바닥)의 옅은 그림자 꼬리도 투명하게 한다.
- cutout_gradient_background: 옅은 그라데이션 배경(스튜디오 사진) — 배경을 2차 곡면으로 추정해 그보다 어두운 곳만 남기고,
  바닥 반사는 주어진 선 아래를 지운다.
- fade_cut_edges: 사진 끝에서 직선으로 잘린 장비는 그쪽이 서서히 사라지게.
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
                            hole_min: int = 400, floor_frac: float = 0.70, protect=None,
                            hole_min_radius: float = 0.0) -> np.ndarray:
    """BGR → BGRA (배경 투명). protect: 바닥 그림자 처리에서 뺄 (x0, x1, y1) 비율 상자 (예: 은색 기둥).
    hole_min_radius: 닫힌 흰 영역은 이만큼 두꺼울 때만 배경으로 (얇은 흰 링 · 테두리는 장비로 남김)."""
    bgr = np.ascontiguousarray(bgr[..., :3])
    h, w = bgr.shape[:2]
    g = bgr.min(axis=2).astype(np.float32)
    spread = bgr.max(axis=2).astype(np.float32) - g
    white = ((g >= thr) & (spread <= 10)).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    thick = cv2.distanceTransform(white, cv2.DIST_L2, 3) if hole_min_radius > 0 else None
    for i in range(1, n):                      # 장비 사이로 보이는 배경 (닫힌 흰 영역)
        if i not in border and stats[i, cv2.CC_STAT_AREA] >= hole_min and np.median(g[lab == i]) >= 252:
            if thick is not None and thick[lab == i].max() < hole_min_radius:
                continue
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


def fade_cut_edges(bgra: np.ndarray, width: int = 80, touch: float = 0.25) -> np.ndarray:
    """장비가 사진 끝에서 직선으로 잘린 쪽(장비 영역의 맨 끝 줄이 거의 다 장비)은 부드럽게 사라지게."""
    a = bgra[..., 3].astype(np.float32) / 255
    ys, xs = np.nonzero(a > 0.5)
    if len(xs) == 0:
        return bgra
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    m = np.ones_like(a)

    def span(v):
        return np.clip(v / width, 0, 1) ** 1.4
    if (a[y0:y1 + 1, x0] > 0.5).mean() > touch:
        m *= span(xx - x0)
    if (a[y0:y1 + 1, x1] > 0.5).mean() > touch:
        m *= span(x1 - xx)
    if (a[y0, x0:x1 + 1] > 0.5).mean() > touch:
        m *= span(yy - y0)
    if (a[y1, x0:x1 + 1] > 0.5).mean() > touch:
        m *= span(y1 - yy)
    out = bgra.copy()
    out[..., 3] = (a * m * 255 + 0.5).astype(np.uint8)
    return out


def cutout_gradient_background(bgr: np.ndarray, diff_thr: float = 14, feather: float = 0.8,
                               floor_pts=None) -> np.ndarray:
    """옅은 그라데이션 배경 → BGRA. floor_pts: [(x, y), ...] 바닥 선 (이 선 아래의 바닥 반사는 지움, 화소 좌표)."""
    bgr = np.ascontiguousarray(bgr[..., :3])
    h, w = bgr.shape[:2]
    f = bgr.astype(np.float32)
    gray = f.mean(axis=2)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cut = np.interp(np.arange(w), *zip(*floor_pts)) if floor_pts else np.full(w, float(h))
    xn, yn = xx / w, yy / h
    A = np.stack([np.ones_like(xn), xn, yn, xn * xn, xn * yn, yn * yn], -1)
    sel = (gray > 236) & (yy < cut[None, :])          # 밝은 화소에 2차 곡면을 맞춰 배경 추정 (채널별)
    bg = np.zeros_like(f)
    for c in range(3):
        coef, *_ = np.linalg.lstsq(A[sel], f[..., c][sel], rcond=None)
        bg[..., c] = A @ coef
    diff = (bg - f).max(axis=2)                       # 배경보다 어두운 정도
    chroma = np.abs(f - bg).max(axis=2)
    obj = ((diff > diff_thr) | (chroma > 28)).astype(np.uint8)
    obj[yy >= cut[None, :]] = 0
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(obj, connectivity=8)
    if n > 1:                                         # 가장 큰 덩어리 + 그 안쪽에 걸친 중간 크기 조각
        big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        bx, by, bw, bh = st[big, :4]
        keep = np.zeros_like(obj)
        for i in range(1, n):
            x, y, ww, hh = st[i, :4]
            inside = x + ww > bx - 6 and x < bx + bw + 6 and y + hh > by - 6 and y < by + bh + 6
            if i == big or (st[i, cv2.CC_STAT_AREA] >= 300 and inside):
                keep[lab == i] = 1
        obj = keep
    inv = (1 - obj).astype(np.uint8)                  # 장비 안의 밝은 반사(작은 구멍) 채우기
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    border = set(np.unique(np.concatenate([lab2[0], lab2[-1], lab2[:, 0], lab2[:, -1]])))
    for i in range(1, n2):
        if i not in border and st2[i, cv2.CC_STAT_AREA] < 3000:
            obj[lab2 == i] = 1
    dist = cv2.distanceTransform(obj, cv2.DIST_L2, 3)
    a = obj.astype(np.float32)
    band = (obj > 0) & (dist <= 2.5)
    soft = np.clip((diff - 4) / (diff_thr + 6), 0, 1)
    a = np.where(band, np.maximum(np.minimum(a, soft), 0.25 * a), a)
    a = cv2.GaussianBlur(a, (0, 0), feather)
    a[obj == 0] = np.minimum(a[obj == 0], 0.3)
    a = np.clip(a, 0, 1)
    af = np.clip(a, 1e-3, 1)[..., None]
    fg = np.clip((f - (1 - af) * bg) / af, 0, 255)  # 배경색 번짐 빼기
    alpha = (a * 255 + 0.5).astype(np.uint8)
    fg[alpha == 0] = 0
    return np.dstack([fg.astype(np.uint8), alpha])
