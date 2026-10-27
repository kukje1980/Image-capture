"""영상 측정 보조 (Pro '분석' 탭) — 고전 영상처리, 학습 모델 없음.

모두 '측정값·기록 보조'이며 질환 판정(진단)을 하지 않는다. 결과는 의사가 확인·수정해 쓴다.
  조명 모드 태그   디퓨즈 / 슬릿 / 코발트블루(형광) / IR·흑백 — 색 히스토그램 규칙
  형광 염색 면적   코발트블루 + 플루오레세인 영상에서 녹색 형광 화소의 면적·비율
  충혈 지수        ROI 의 붉은 기 비율과 혈관(적색 우세) 화소 비율 — 0~100 상대 지수
  영상 정렬        경과 비교용으로 이전 영상을 현재 영상에 맞춰 이동·회전 (ECC)
ROI 는 이미지 좌표의 타원 (x1, y1, x2, y2) — Pro 편집의 '원' 주석을 그대로 쓴다.
"""
from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

ILLUMINATION_LABELS = {"diffuse": "디퓨즈", "slit": "슬릿", "cobalt": "코발트블루(형광)", "ir": "IR·흑백"}
_WORK_SIDE = 1200


def _shrink(img: np.ndarray, side: int) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= side:
        return img, 1.0
    s = side / longest
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA), s


def ellipse_mask(shape: tuple, roi: tuple | None, scale: float = 1.0) -> np.ndarray:
    """타원 ROI 마스크 (bool). roi 가 없으면 전체."""
    h, w = shape[:2]
    if roi is None:
        return np.ones((h, w), bool)
    x1, y1, x2, y2 = (v * scale for v in roi)
    m = np.zeros((h, w), np.uint8)
    c = (int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2)))
    ax = (max(1, int(round(abs(x2 - x1) / 2))), max(1, int(round(abs(y2 - y1) / 2))))
    cv2.ellipse(m, c, ax, 0, 0, 360, 1, -1)
    return m > 0


def classify_illumination(frame: np.ndarray) -> str:
    """조명 모드 추정 → 'diffuse' | 'slit' | 'cobalt' | 'ir'."""
    small, _ = _shrink(frame, 200)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    lit = v > 40
    dark = 1.0 - float(lit.mean())
    if not lit.any():
        return "slit"
    sat = float(hsv[..., 1][lit].mean())
    b, g, r = (float(small[..., i][lit].mean()) for i in range(3))
    if sat >= 25 and (b > 1.3 * r and b >= 0.9 * g or (g + b) > 2.6 * max(r, 1.0)):
        return "cobalt"
    if dark > 0.55:                 # 밝은 띠 + 어두운 배경 (백색 슬릿광은 채도가 낮아 IR 보다 먼저 본다)
        return "slit"
    if sat < 25:
        return "ir"
    return "diffuse"


def fluorescein_area(frame: np.ndarray, roi: tuple | None = None, px_per_mm: float = 0.0) -> dict:
    """녹색 형광 화소 면적. {'ratio': ROI 대비 %, 'area_px', 'area_mm2'(보정 시), 'mask'(원본 크기 bool)}."""
    small, s = _shrink(frame, _WORK_SIDE)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    b, g, r = (small[..., i].astype(np.int16) for i in range(3))
    green = (h >= 28) & (h <= 90) & (sat >= 60) & (v >= 80) & (g > r) & (g >= b)
    green = cv2.morphologyEx(green.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    roi_m = ellipse_mask(small.shape, roi, s)
    green &= roi_m
    roi_px = int(roi_m.sum()) or 1
    area_small = int(green.sum())
    area_px = area_small / (s * s)
    out = {"ratio": 100.0 * area_small / roi_px, "area_px": area_px, "area_mm2": None}
    if px_per_mm > 0:
        out["area_mm2"] = area_px / (px_per_mm * px_per_mm)
    fh, fw = frame.shape[:2]
    out["mask"] = cv2.resize(green.astype(np.uint8), (fw, fh), interpolation=cv2.INTER_NEAREST) > 0
    return out


REDNESS_SENS_DEFAULT = 5          # 충혈 민감도 1(가장 붉은 곳만) ~ 10(옅은 붉은 기까지), 5 = 예전과 같은 기준


def redness_thresholds(sensitivity: int = REDNESS_SENS_DEFAULT) -> tuple[float, float]:
    """민감도 → (R/G, R/B) 기준. 5 = (1.45, 1.30) 예전 값, 1 = (1.85, 1.60), 10 = (1.15, 1.08)."""
    s = min(10, max(1, int(sensitivity)))
    if s <= 5:
        return 1.45 + (5 - s) * 0.10, 1.30 + (5 - s) * 0.075
    return 1.45 - (s - 5) * 0.06, 1.30 - (s - 5) * 0.044


def redness_index(frame: np.ndarray, roi: tuple | None = None, sensitivity: int = REDNESS_SENS_DEFAULT) -> dict:
    """충혈 지수 (상대 측정값). {'index': 0~100, 'vessel_pct': 붉은(혈관 · 충혈) 화소 %, 'mask', 'sensitivity'}.

    index = ROI 의 적색 비율 r/(r+g+b) 를 1/3(무채색)~0.6(강한 적색) 사이로 정규화한 평균 (민감도와 무관).
    vessel_pct · mask = R 이 G · B 보다 기준 배 이상 큰 화소 — 기준은 민감도로 조절 (낮을수록 더 붉은 곳만).
    같은 조명·배율 · 같은 민감도로 찍은 경과 영상끼리 비교할 때 의미가 있다 (등급 판정 아님).
    """
    small, s = _shrink(frame, _WORK_SIDE)
    f = small.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    tot = b + g + r + 1e-3
    v = f.max(axis=2)
    roi_m = ellipse_mask(small.shape, roi, s) & (v > 40) & (v < 250)
    if not roi_m.any():
        fh, fw = frame.shape[:2]
        return {"index": 0.0, "vessel_pct": 0.0, "mask": np.zeros((fh, fw), bool)}
    rr = r / tot
    idx = np.clip((rr - 1 / 3) / (0.6 - 1 / 3), 0, 1)
    kg, kb = redness_thresholds(sensitivity)
    vessel = roi_m & (r > kg * g) & (r > kb * b) & (v > 50)
    fh, fw = frame.shape[:2]
    return {"index": float(idx[roi_m].mean() * 100), "vessel_pct": 100.0 * float(vessel.sum()) / float(roi_m.sum()),
            "mask": cv2.resize(vessel.astype(np.uint8), (fw, fh), interpolation=cv2.INTER_NEAREST) > 0,
            "sensitivity": min(10, max(1, int(sensitivity)))}


def align_to(moving: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, bool]:
    """경과 비교용: moving 을 reference 크기·위치에 맞춘다 (이동+회전, ECC). (결과, 정렬 성공)."""
    rh, rw = reference.shape[:2]
    resized = cv2.resize(moving, (rw, rh), interpolation=cv2.INTER_AREA) if moving.shape[:2] != (rh, rw) else moving
    a, s = _shrink(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), 480)
    b, _ = _shrink(cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY), 480)
    a = cv2.GaussianBlur(a, (5, 5), 0).astype(np.float32)
    b = cv2.GaussianBlur(b, (5, 5), 0).astype(np.float32)
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_EUCLIDEAN,
                                        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), None, 5)
    except cv2.error:
        return resized, False
    if not np.isfinite(warp).all() or cc < 0.3:
        return resized, False
    warp[:, 2] /= s                                           # 축소 좌표 → 원본 좌표
    out = cv2.warpAffine(resized, warp, (rw, rh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT)
    return out, True
