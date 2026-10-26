"""Pro 분석 — 저장된 슬릿램프 영상의 정량 보조 지표 (규칙 기반 영상처리, 학습 모델 아님).

모든 결과는 '같은 촬영 조건에서 비교하기 위한 참고 지표'이며 진단이 아니다. 의사가 오버레이를 보고
확인·수정하는 것을 전제로 한다 (Human-in-the-loop). 등급 기준값은 아래 상수에 모아 두었고,
실제 임상 영상·전문가 라벨로 보정해야 한다.

분석 영역: 원(○) 주석이 있으면 마지막 원(타원) 안, 없으면 영상 전체.

  quality       영상 품질 — 선명도(Tenengrad), 노출, 반사광
  fluorescein   형광염색 — 코발트블루 조명에서 녹황색으로 빛나는 염색 부위 면적·점 개수
  hyperemia     결막 충혈 — 혈관(녹색 채널의 가는 어두운 구조) 면적 비율과 붉은기
  meibography   마이봄샘(적외선 영상) — 샘 구조 면적과 탈락(dropout) 비율, Meiboscore(Arita 0~3)
  lens          수정체 — 밝기(혼탁)·황색도 지수 (핵경화 추적용 상대값)
  align         이전 영상 자동 정렬 — 특징점(ORB) + 유사 변환
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.capture.smart_capture import focus_score, valid_mask

KINDS = ("quality", "fluorescein", "hyperemia", "meibography", "lens")
KIND_LABELS = {"quality": "영상 품질", "fluorescein": "형광염색 (각막 손상)", "hyperemia": "결막 충혈",
               "meibography": "마이봄샘 (IR)", "lens": "수정체 혼탁 (참고)"}

# Oxford 체계의 점(punctate) 개수 구간 — 0, I(1~5), II(6~15), III(16~30), IV(31~100), V(>100)
OXFORD_BOUNDS = (0, 5, 15, 30, 100)
# 충혈 참고 등급: 혈관 면적 % 경계 (0~4)
HYPEREMIA_BOUNDS = (3.0, 7.0, 12.0, 20.0)
# Meiboscore (Arita): 0 = 탈락 없음, 1 < 1/3, 2 = 1/3~2/3, 3 > 2/3
# (0 과 1 의 경계는 영역 가장자리 오차를 감안해 10% 로 둔다)
MEIBO_BOUNDS = (10.0, 100 / 3, 200 / 3)

_RED = (59, 48, 255)        # BGR
_GREEN = (98, 211, 52)
_CYAN = (255, 210, 64)
_ORANGE = (40, 160, 255)


@dataclass
class AnalysisResult:
    kind: str
    title: str
    rows: list = field(default_factory=list)       # [(항목, 값 문자열)]
    summary: str = ""                               # 코멘트에 쓰는 한 줄 요약
    overlay: Optional[np.ndarray] = None            # BGRA (원본 해상도) — 표시·결과 영상 저장용
    values: dict = field(default_factory=dict)      # 수치 (테스트·보고서)
    warning: str = ""


# ================= 공통 =================
def region_mask(shape, circle: Optional[dict] = None) -> np.ndarray:
    """분석 영역 마스크(bool). circle = 원 주석 {x1,y1,x2,y2} (영상 좌표) — 없으면 전체."""
    h, w = shape[:2]
    if not circle:
        return np.ones((h, w), bool)
    x0, x1 = sorted((float(circle["x1"]), float(circle["x2"])))
    y0, y1 = sorted((float(circle["y1"]), float(circle["y2"])))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return np.ones((h, w), bool)
    m = np.zeros((h, w), np.uint8)
    center = (int(round((x0 + x1) / 2)), int(round((y0 + y1) / 2)))
    axes = (max(1, int(round((x1 - x0) / 2))), max(1, int(round((y1 - y0) / 2))))
    cv2.ellipse(m, center, axes, 0, 0, 360, 1, -1)
    return m > 0


def last_circle(annotations: list) -> Optional[dict]:
    circles = [a for a in annotations or [] if a.get("kind") == "circle"]
    return circles[-1] if circles else None


def overlay_from_mask(mask: np.ndarray, color_bgr, alpha: int = 150, outline: Optional[np.ndarray] = None
                      ) -> np.ndarray:
    out = np.zeros(mask.shape + (4,), np.uint8)
    out[mask] = (*color_bgr, alpha)
    if outline is not None:
        edge = cv2.morphologyEx(outline.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
        out[edge] = (255, 255, 255, 200)
    return out


def _area_text(px: float, px_per_mm: float) -> str:
    if px_per_mm and px_per_mm > 0:
        return f"{px / (px_per_mm ** 2):.2f} mm²"
    return f"{int(px):,} px (눈금 보정 시 mm²)"


def _grade(value: float, bounds) -> int:
    return int(sum(value > b for b in bounds))


def _scale_kernel(mask: np.ndarray, frac: float, lo: int = 3, hi: int = 61) -> int:
    """영역 크기에 비례한 홀수 커널 크기."""
    ys, xs = np.nonzero(mask)
    span = max(1, min(int(np.ptp(xs)) if xs.size else 1, int(np.ptp(ys)) if ys.size else 1))
    k = int(span * frac) | 1
    return max(lo | 1, min(hi, k))


# ================= 영상 품질 =================
def quality(img: np.ndarray, region: np.ndarray) -> AnalysisResult:
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    valid, _ = valid_mask(gray)
    valid &= region
    glare = float(((gray >= 245) & region).sum()) / max(1, int(region.sum()))
    sharp = focus_score(gray, valid) if valid.sum() > 100 else 0.0
    p90 = float(np.percentile(gray[region], 90)) if region.any() else 0.0
    exposure = 100.0 * min(1.0, max(0.0, (p90 - 25.0) / 55.0))
    issues = []
    if sharp < 12:
        issues.append("흐림 — 선명한 구조가 거의 없음")
    if glare > 0.08:
        issues.append(f"반사광 {glare * 100:.0f}% — 조명 각도 조절 권장")
    if exposure < 30:
        issues.append("노출 부족")
    verdict = "양호" if not issues else " · ".join(issues)
    rows = [("선명도 (Tenengrad)", f"{sharp:.1f}"), ("노출 (밝은 부분 기준)", f"{exposure:.0f} / 100"),
            ("반사광 (포화 픽셀)", f"{glare * 100:.1f} %"), ("판정", verdict)]
    return AnalysisResult("quality", "영상 품질", rows, f"품질: {verdict} (선명도 {sharp:.0f})",
                          values={"sharpness": sharp, "exposure": exposure, "glare_pct": glare * 100})


def sharpness_of(img: np.ndarray) -> float:
    """영상 한 장의 선명도 (MULTI 의 '가장 선명한 영상' 고르기용)."""
    small = img if img.shape[1] <= 960 else cv2.resize(img, (960, round(img.shape[0] * 960 / img.shape[1])),
                                                       interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    valid, _ = valid_mask(gray)
    return focus_score(gray, valid) if valid.sum() > 100 else 0.0


# ================= 형광염색 =================
def fluorescein(img: np.ndarray, region: np.ndarray, px_per_mm: float = 0.0) -> AnalysisResult:
    """코발트블루 + 황색 차단 필터 영상에서 밝은 녹황색(형광) 부위를 찾는다."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (h >= 25) & (h <= 95) & (s >= 60)               # 황록~녹색 (OpenCV hue 0~180)
    cand = green & region
    if cand.sum() < 20:
        thr = 255
    else:
        vals = v[region].astype(np.uint8).reshape(-1, 1)
        otsu, _ = cv2.threshold(vals, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = max(float(otsu), float(np.percentile(v[region], 75)), 70.0)
    stain = cand & (v >= thr)
    stain = cv2.morphologyEx(stain.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(stain.astype(np.uint8), connectivity=8)
    min_area = max(4, int(region.sum() * 2e-6))
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    stain = np.isin(labels, keep) if keep else np.zeros_like(stain)
    spots = len(keep)
    area = float(stain.sum())
    area_pct = 100.0 * area / max(1, int(region.sum()))
    largest = max((stats[i, cv2.CC_STAT_AREA] for i in keep), default=0)
    grade = _grade(spots, OXFORD_BOUNDS)
    roman = ["0", "I", "II", "III", "IV", "V"][grade]
    rows = [("염색 면적", _area_text(area, px_per_mm)), ("영역 대비", f"{area_pct:.2f} %"),
            ("염색 점/병변 수", f"{spots}"), ("가장 큰 병변", _area_text(largest, px_per_mm)),
            ("참고 등급 (Oxford 점 개수 근사)", roman)]
    warn = ""
    if spots == 0 and float((green & region).sum()) < 0.002 * max(1, int(region.sum())):
        warn = "녹황색 형광이 거의 없습니다 — 코발트블루·황색 필터로 촬영한 영상인지 확인하세요"
    return AnalysisResult("fluorescein", "형광염색 분석", rows,
                          f"형광염색: 면적 {area_pct:.2f}% · 병변 {spots}개 · Oxford≈{roman}",
                          overlay_from_mask(stain, _ORANGE, 170, region if region.mean() < 1 else None),
                          {"area_pct": area_pct, "spots": spots, "grade": grade, "area_px": area}, warn)


# ================= 결막 충혈 =================
def hyperemia(img: np.ndarray, region: np.ndarray) -> AnalysisResult:
    """녹색 채널에서 가는 어두운 구조(혈관)를 black top-hat 으로 찾고, 붉은기와 함께 수치화."""
    b, g, r = (img[..., i].astype(np.float32) for i in range(3))
    k = _scale_kernel(region, 0.04, 7, 41)
    g8 = img[..., 1]
    tophat = cv2.morphologyEx(g8, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    redness = (r - g) / (r + g + 1.0)                        # -1~1, 혈관·충혈일수록 큼
    vals = tophat[region]
    thr = max(12.0, float(np.percentile(vals, 75)) if vals.size else 12.0)
    vessels = (tophat >= thr) & (redness > 0.05) & region
    vessels = cv2.morphologyEx(vessels.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
    vessel_pct = 100.0 * float(vessels.sum()) / max(1, int(region.sum()))
    red_mean = float(np.mean(redness[region])) if region.any() else 0.0
    grade = _grade(vessel_pct, HYPEREMIA_BOUNDS)
    rows = [("혈관 면적 비율", f"{vessel_pct:.1f} %"), ("붉은기 지수 (R−G)/(R+G)", f"{red_mean:.3f}"),
            ("참고 등급 (0~4)", f"{grade}")]
    warn = "같은 조명·배율 영상끼리 비교하세요 (조명·노출에 따라 값이 달라집니다)"
    return AnalysisResult("hyperemia", "결막 충혈 분석", rows,
                          f"결막 충혈: 혈관 {vessel_pct:.1f}% · 붉은기 {red_mean:.3f} · 참고등급 {grade}",
                          overlay_from_mask(vessels, _CYAN, 190, region if region.mean() < 1 else None),
                          {"vessel_pct": vessel_pct, "redness": red_mean, "grade": grade}, warn)


# ================= 마이봄샘 =================
def meibography(img: np.ndarray, region: np.ndarray, glands_dark: bool = False) -> AnalysisResult:
    """적외선 마이봄샘 영상: 밝은 세로 줄무늬(샘)를 분할하고 탈락 비율을 구한다.

    영역에는 눈꺼풀의 샘 부위를 원(타원)으로 지정하는 것을 권장한다.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if glands_dark:
        gray = 255 - gray
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    k = _scale_kernel(region, 0.12, 15, 151)
    local = cv2.blur(clahe.astype(np.float32), (k, k))
    glands = (clahe.astype(np.float32) > local + 6) & region
    # 세로로 긴 구조만 남김 (샘은 눈꺼풀 가장자리에 수직)
    vk = max(5, k // 3)
    glands = cv2.morphologyEx(glands.astype(np.uint8), cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk))) > 0
    # 샘이 덮고 있는 범위 = 이웃한 샘 사이 틈을 가로로 메운 영역
    covered = cv2.morphologyEx(glands.astype(np.uint8), cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, k), max(3, k // 4)))) > 0
    covered &= region
    area = max(1, int(region.sum()))
    gland_pct = 100.0 * float(glands.sum()) / area
    dropout = 100.0 * (1.0 - float(covered.sum()) / area)
    score = _grade(dropout, MEIBO_BOUNDS)
    rows = [("샘 구조 면적", f"{gland_pct:.1f} %"), ("탈락 (dropout)", f"{dropout:.1f} %"),
            ("Meiboscore (Arita 0~3)", f"{score}")]
    warn = "적외선(IR) 마이봄샘 영상 전용 — 샘 부위만 원으로 지정하면 정확해집니다"
    ov = overlay_from_mask(glands, _GREEN, 150, region if region.mean() < 1 else None)
    loss = region & ~covered
    ov[loss & ~glands] = (*_RED, 70)
    return AnalysisResult("meibography", "마이봄샘 분석", rows,
                          f"마이봄샘: 탈락 {dropout:.0f}% · Meiboscore {score}", ov,
                          {"gland_pct": gland_pct, "dropout_pct": dropout, "meiboscore": score}, warn)


# ================= 수정체 =================
def lens(img: np.ndarray, region: np.ndarray) -> AnalysisResult:
    """수정체 핵 부위(원으로 지정)의 밝기(L*)·황색도(b*) — 같은 환자의 경과 비교용 상대값."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0] * 100.0 / 255.0
    bstar = lab[..., 2] - 128.0
    if not region.any():
        region = np.ones(img.shape[:2], bool)
    lm, bm = float(np.mean(L[region])), float(np.mean(bstar[region]))
    rows = [("밝기 L* (혼탁 지수)", f"{lm:.1f} / 100"), ("황색도 b*", f"{bm:+.1f}")]
    warn = "등급 판정이 아닌 상대값입니다 — 같은 조명(광학 절단면)·배율 영상끼리 비교하세요"
    return AnalysisResult("lens", "수정체 혼탁 지수", rows, f"수정체: L* {lm:.1f} · b* {bm:+.1f}",
                          values={"L": lm, "b": bm}, warning=warn)


def analyze(kind: str, img: np.ndarray, annotations: Optional[list] = None, px_per_mm: float = 0.0,
            glands_dark: bool = False) -> AnalysisResult:
    region = region_mask(img.shape, last_circle(annotations or []))
    if kind == "quality":
        return quality(img, region)
    if kind == "fluorescein":
        return fluorescein(img, region, px_per_mm)
    if kind == "hyperemia":
        return hyperemia(img, region)
    if kind == "meibography":
        return meibography(img, region, glands_dark)
    if kind == "lens":
        return lens(img, region)
    raise ValueError(f"unknown analysis: {kind}")


# ================= 이전 영상 정렬 =================
@dataclass
class AlignResult:
    ok: bool
    image: Optional[np.ndarray] = None     # ref 좌표계로 옮긴 mov
    inliers: int = 0
    scale: float = 1.0
    rotation: float = 0.0                  # 도
    shift: tuple = (0.0, 0.0)
    message: str = ""


def align(ref: np.ndarray, mov: np.ndarray, max_side: int = 1024) -> AlignResult:
    """mov 를 ref 에 맞춰 회전·확대·이동(유사 변환). 특징점이 부족하면 ok=False."""
    def prep(img):
        s = min(1.0, max_side / max(img.shape[:2]))
        small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g), s

    g1, s1 = prep(ref)
    g2, s2 = prep(mov)
    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(k1) < 10 or len(k2) < 10:
        return AlignResult(False, message="특징점이 부족해 정렬할 수 없습니다")
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d2, d1)
    if len(matches) < 10:
        return AlignResult(False, message="두 영상의 공통 구조가 부족합니다")
    src = np.float32([k2[m.queryIdx].pt for m in matches]) / s2
    dst = np.float32([k1[m.trainIdx].pt for m in matches]) / s1
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0 / s1,
                                         maxIters=4000, confidence=0.995)
    n_in = int(inl.sum()) if inl is not None else 0
    if M is None or n_in < 12:
        return AlignResult(False, inliers=n_in, message="정렬 신뢰도가 낮습니다 (공통 특징점 부족)")
    scale = float(np.hypot(M[0, 0], M[1, 0]))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    if not 0.5 <= scale <= 2.0:
        return AlignResult(False, inliers=n_in, scale=scale, message="배율 차이가 너무 큽니다")
    h, w = ref.shape[:2]
    warped = cv2.warpAffine(mov, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    msg = f"정렬 완료 · 일치점 {n_in}개 · 배율 {scale:.2f} · 회전 {rot:+.1f}°"
    if abs(scale - 1) > 0.15:
        msg += " — 배율이 달라 크기 비교에 주의"
    return AlignResult(True, warped, n_in, scale, rot, (float(M[0, 2]), float(M[1, 2])), msg)


def exposure_gap(a: np.ndarray, b: np.ndarray) -> float:
    """두 영상의 밝기 차 (중앙값 기준, 0~255) — 비교 전 촬영 조건 확인용."""
    ga, gb = (cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (a, b))
    return abs(float(np.median(ga)) - float(np.median(gb)))
