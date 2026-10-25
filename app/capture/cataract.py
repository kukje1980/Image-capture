"""수정체 혼탁 지수 (백내장 측정 보조) — 고전 영상처리, 등급 판정 없음.

핵 혼탁 (슬릿 광학 단면 사진)
  맑은 수정체는 슬릿 단면이 어둡고 얇게, 탁한 수정체는 밝고 두껍게 보인다 → 밝기 문제.
  1. 세로 슬릿광의 밝은 띠를 열(column) 프로파일에서 찾는다: 가장 좁은 띠 = 각막 단면, 가장 넓은 띠 = 수정체 단면
  2. 수정체 띠 평균 밝기 ÷ 각막 띠 평균 밝기 (각막을 기준자로 — 조명 밝기가 달라도 비율은 비슷)
  3. 비율 → 0~100 '핵 혼탁 지수'. 포화 화소(각막 정반사 등)는 계산에서 뺀다.
피질·후낭하 혼탁 (역조명 사진)
  동공(붉은 반사) 안에서 주변보다 어두운 얼룩의 면적 % → 0~100 '피질 혼탁 지수'. 동공 가장자리 띠는 제외.
  동공 직경(px / 보정 시 mm)도 함께 돌려준다 (산동이 안 된 눈은 피질이 안 보여 과소평가).

지수는 촬영 조건(슬릿 폭·각도·배율·노출)이 같을 때만 비교 의미가 있고, LOCS 등급이 아니다.
아래 상수는 합성 영상으로 잡은 초기값이며 실제 슬릿램프 사진 30장 정도로 조정해야 한다.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

# ---- 조정 상수 (실사진으로 검증 필요) ----
RATIO_CLEAR = 0.12       # 수정체/각막 밝기 비 — 이 이하를 지수 0 으로
RATIO_DENSE = 0.95       # 이 이상을 지수 100 으로
SAT_LEVEL = 250          # 포화 화소 (정반사) 제외 기준
DARK_FRAC = 0.72         # 역조명: 주변 밝기의 72% 미만이면 혼탁 얼룩
PUPIL_EDGE_SKIP = 0.08   # 역조명: 동공 반경의 8% 가장자리 띠 제외


def _gray(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _index(ratio: float) -> float:
    return float(np.clip((ratio - RATIO_CLEAR) / (RATIO_DENSE - RATIO_CLEAR), 0, 1) * 100)


def _bands(profile: np.ndarray, min_width: int = 2) -> list[tuple[int, int, float]]:
    """열 프로파일에서 밝은 띠 [(x0, x1, 최고값)] — 배경(중앙값) 위로 충분히 솟은 연속 구간."""
    base = float(np.percentile(profile, 10))              # 배경 (띠 바깥 어두운 열)
    spread = float(np.percentile(profile, 90) - base)     # p90 = 넓은 수정체 띠 수준 (각막 띠는 더 좁아 영향 적음)
    if spread < 8:
        return []
    thr = base + max(8.0, 0.25 * spread)
    on = profile > thr
    bands, start = [], None
    for x, v in enumerate(on):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if x - start >= min_width:
                bands.append((start, x, float(profile[start:x].max())))
            start = None
    if start is not None and len(on) - start >= min_width:
        bands.append((start, len(on), float(profile[start:].max())))
    return bands


def nuclear_opacity(frame: np.ndarray, roi: tuple | None = None) -> dict:
    """슬릿 단면 사진의 핵 혼탁 지수.

    roi = (x1, y1, x2, y2) 측정 영역 (없으면 전체). 반환:
      index 0~100, ratio(수정체/각막 밝기), lens_mean, cornea_mean, lens_band, cornea_band (x0, x1, 원본 좌표),
      has_cornea (각막 기준 띠를 찾았는지 — 없으면 수정체 띠 밝기만으로 계산한 참고값), mask(수정체 띠 표시용)
    """
    g = _gray(frame)
    H, W = g.shape[:2]
    x1, y1, x2, y2 = (0, 0, W, H) if roi is None else (
        max(0, int(min(roi[0], roi[2]))), max(0, int(min(roi[1], roi[3]))),
        min(W, int(max(roi[0], roi[2]))), min(H, int(max(roi[1], roi[3]))))
    sub = g[y1:y2, x1:x2].astype(np.float32)
    valid = sub < SAT_LEVEL
    sub_v = np.where(valid, sub, np.nan)
    with np.errstate(all="ignore"):
        prof = np.nanmean(sub_v, axis=0)
    prof = np.nan_to_num(prof, nan=0.0)
    k = max(3, (x2 - x1) // 100 | 1)
    prof_s = cv2.GaussianBlur(prof.reshape(1, -1), (k, 1), 0).ravel()
    bands = _bands(prof_s)
    out = {"index": 0.0, "ratio": 0.0, "lens_mean": 0.0, "cornea_mean": 0.0, "lens_band": None,
           "cornea_band": None, "has_cornea": False, "mask": np.zeros((H, W), bool)}
    if not bands:
        return out
    bands.sort(key=lambda b: b[1] - b[0])
    lens = bands[-1]
    cornea = None
    if len(bands) >= 2:
        # 가장 좁으면서 수정체 띠보다 좁고 밝은 띠 = 각막 단면
        cands = [b for b in bands[:-1] if (b[1] - b[0]) < 0.6 * (lens[1] - lens[0])]
        if cands:
            cornea = max(cands, key=lambda b: b[2])

    base = float(np.percentile(prof_s, 10))

    def band_mean(b):
        # 띠 가장자리(경계 열)가 들어가고 빠지는 데 흔들리지 않게, 최고값의 절반 이상인 '심' 열만 평균
        core = np.flatnonzero(prof_s[b[0]:b[1]] >= base + 0.5 * (b[2] - base)) + b[0]
        if core.size == 0:
            core = np.arange(b[0], b[1])
        seg = sub[:, core]
        v = valid[:, core]
        return float(seg[v].mean()) if v.any() else 0.0

    lens_mean = band_mean(lens)
    out.update(lens_mean=lens_mean, lens_band=(x1 + lens[0], x1 + lens[1]))
    if cornea is not None:
        cornea_mean = band_mean(cornea)
        if cornea_mean > 1:
            ratio = lens_mean / cornea_mean
            out.update(ratio=ratio, cornea_mean=cornea_mean, has_cornea=True,
                       cornea_band=(x1 + cornea[0], x1 + cornea[1]), index=_index(ratio))
    if not out["has_cornea"]:
        out["ratio"] = lens_mean / 255.0                    # 참고값: 절대 밝기 기준
        out["index"] = _index(out["ratio"])
    m = np.zeros((H, W), bool)
    m[y1:y2, x1 + lens[0]:x1 + lens[1]] = valid[:, lens[0]:lens[1]] & (sub[:, lens[0]:lens[1]] > prof_s.min() + 10)
    out["mask"] = m
    return out


def cortical_opacity(frame: np.ndarray, pupil: tuple, px_per_mm: float = 0.0) -> dict:
    """역조명 사진의 피질·후낭하 혼탁 지수. pupil = 동공 타원 (x1, y1, x2, y2).

    반환: index 0~100 (= 어두운 얼룩 면적 %), area_pct, pupil_diameter_px, pupil_diameter_mm, small_pupil, mask
    """
    g = _gray(frame)
    H, W = g.shape[:2]
    x1, y1, x2, y2 = pupil
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    ax, ay = abs(x2 - x1) / 2, abs(y2 - y1) / 2
    m = np.zeros((H, W), np.uint8)
    skip = 1.0 - PUPIL_EDGE_SKIP
    cv2.ellipse(m, (int(round(cx)), int(round(cy))), (max(1, int(ax * skip)), max(1, int(ay * skip))),
                0, 0, 360, 1, -1)
    inside = m > 0
    out = {"index": 0.0, "area_pct": 0.0, "pupil_diameter_px": float(2 * max(ax, ay)),
           "pupil_diameter_mm": (2 * max(ax, ay) / px_per_mm) if px_per_mm > 0 else None,
           "small_pupil": False, "mask": np.zeros((H, W), bool)}
    if out["pupil_diameter_mm"] is not None:
        out["small_pupil"] = out["pupil_diameter_mm"] < 5.0
    if not inside.any():
        return out
    # 동공 영역을 ≤ 400px 로 축소해 계산 (큰 얼룩보다 넓은 창의 중앙값 → 4K 에서도 빠르게)
    bx0, by0 = max(0, int(cx - ax)), max(0, int(cy - ay))
    bx1, by1 = min(W, int(cx + ax) + 1), min(H, int(cy + ay) + 1)
    crop, ins = g[by0:by1, bx0:bx1], inside[by0:by1, bx0:bx1]
    s = min(1.0, 400.0 / max(1, max(crop.shape)))
    if s < 1.0:
        size = (max(1, int(crop.shape[1] * s)), max(1, int(crop.shape[0] * s)))
        crop = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
        ins = cv2.resize(ins.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    gf = crop.astype(np.float32)
    k = min(255, max(9, int(max(ax, ay) * s * 0.9))) | 1
    local = cv2.medianBlur(crop, k).astype(np.float32)                  # 국소 배경 (붉은 반사의 밝기 기울기)
    ref = float(np.percentile(gf[ins], 70)) if ins.any() else 0.0        # 동공 전체 기준 밝기
    bg = np.maximum(local, 0.85 * ref)
    dark = ins & (gf < DARK_FRAC * bg) & (bg > 25) & (gf < SAT_LEVEL)
    dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    pct = 100.0 * float(dark.sum()) / float(max(1, ins.sum()))
    full = np.zeros((H, W), bool)
    if s < 1.0:
        dark = cv2.resize(dark.astype(np.uint8), (bx1 - bx0, by1 - by0), interpolation=cv2.INTER_NEAREST) > 0
    full[by0:by1, bx0:bx1] = dark & inside[by0:by1, bx0:bx1]
    out.update(index=float(min(100.0, pct)), area_pct=pct, mask=full)
    return out
