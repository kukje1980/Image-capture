"""녹내장 3D 보기용 계산·렌더링 (Qt 없음 — numpy/OpenCV 만 사용, 단위 테스트 가능).

두 가지 그림을 만든다.
  1. 3D 안구  : 안저 사진을 안구 안쪽(뒤 반구)에 입혀 돌려 보는 환자 설명용 그림.
                녹내장 단계(정상~말기)에 따라 시신경유두 함몰과 신경섬유층 결손을 덧그리고,
                그 단계에서 환자가 보는 시야(주변부터 좁아짐)를 예시 장면으로 보여 준다.
  2. 유두 3D  : 시신경유두 부분을 밝기로 추정한 입체 지형으로 그리고, 유두·함몰 타원에서 C/D 비율을 계산한다.

주의: 입체 지형은 사진 한 장의 밝기에서 만든 '표현'이다. 실제 깊이 측정값(OCT·HRT)이 아니며
      녹내장 단계 그림도 설명용 모형이다. 진단은 의사가 판단한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

STAGES = ("정상", "초기", "중기", "말기")
# 단계별: 함몰/유두 비율(설명용 모형), 결손 진하기, 시야 반지름(1 = 전체)
_STAGE_CUP = (0.3, 0.5, 0.7, 0.9)
_STAGE_DEFECT = (0.0, 0.35, 0.6, 0.85)
_STAGE_FIELD = (1.0, 0.8, 0.5, 0.22)


@dataclass
class Ellipse:
    """영상 좌표(px) 타원. w·h 는 지름."""
    cx: float
    cy: float
    w: float
    h: float


# ============================================================ 유두 찾기 · C/D
def detect_disc(bgr: np.ndarray) -> Ellipse:
    """시신경유두 위치 추정 — 안저에서 가장 밝고 넓은 덩어리. 찾지 못하면 영상 가운데의 기본 원."""
    h, w = bgr.shape[:2]
    k = 320.0 / max(h, w)
    small = cv2.resize(bgr, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sh, sw = g.shape
    win = max(9, int(min(sh, sw) * 0.12) | 1)
    blur = cv2.GaussianBlur(g, (win, win), 0)
    # 가장자리(조리개 테두리 반사)는 후보에서 뺀다
    m = int(min(sh, sw) * 0.08)
    inner = np.zeros_like(blur)
    inner[m:sh - m, m:sw - m] = blur[m:sh - m, m:sw - m]
    _, peak, _, loc = cv2.minMaxLoc(inner)
    r_default = 0.07 * max(sw, sh)
    if peak <= 0:
        return Ellipse(w / 2, h / 2, 2 * r_default / k, 2 * r_default / k)
    # 봉우리 주변에서 밝기가 (봉우리+배경)/2 를 넘는 영역의 넓이로 반지름을 잡는다
    base = float(np.median(blur[blur > 8])) if np.any(blur > 8) else 0.0
    mask = (blur >= (peak + base) / 2).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    lab = labels[loc[1], loc[0]]
    if lab <= 0:
        cx, cy, r = float(loc[0]), float(loc[1]), r_default
    else:
        area = float(stats[lab, cv2.CC_STAT_AREA])
        cx, cy = float(cents[lab][0]), float(cents[lab][1])
        r = float(np.clip(math.sqrt(area / math.pi) * 1.25, 0.03 * max(sw, sh), 0.16 * max(sw, sh)))
    return _refine_disc(g, cx, cy, r, k)


def _refine_disc(g: np.ndarray, cx: float, cy: float, r: float, k: float) -> Ellipse:
    """대략 찾은 위치 주변에서 유두(밝음)와 망막(어두움)을 갈라 테두리에 맞춘다. g 는 축소한 흑백 영상."""
    rough = Ellipse(cx / k, cy / k, 2 * r / k, 2 * r / k)
    sh, sw = g.shape
    half = int(max(8, r * 2.4))
    x0, y0, x1, y1 = max(0, int(cx) - half), max(0, int(cy) - half), min(sw, int(cx) + half), min(sh, int(cy) + half)
    win = cv2.GaussianBlur(g[y0:y1, x0:x1], (0, 0), 1.2).astype(np.uint8)
    lit = win[win > 8]                                           # 영상 밖(검정)은 빼고 가른다
    if lit.size < 30 or int(lit.max()) - int(lit.min()) < 12:
        return rough
    thr, _ = cv2.threshold(lit.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, labels, stats, cents = cv2.connectedComponentsWithStats((win > thr).astype(np.uint8), 8)
    py, px = min(win.shape[0] - 1, int(cy) - y0), min(win.shape[1] - 1, int(cx) - x0)
    lab = labels[py, px]
    if lab <= 0:
        return rough
    bx, by, bw, bh = (int(stats[lab, i]) for i in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    touches = bx <= 0 or by <= 0 or bx + bw >= win.shape[1] or by + bh >= win.shape[0]
    if touches or bw < 4 or bh < 4:
        return rough
    return Ellipse((x0 + bx + bw / 2) / k, (y0 + by + bh / 2) / k, bw / k, bh / k)


def estimate_cup(bgr: np.ndarray, disc: Ellipse) -> Ellipse:
    """유두 안의 가장 밝은 부분(함몰)을 타원으로 추정. 사용자가 고칠 초깃값이다."""
    h, w = bgr.shape[:2]
    x0, y0 = int(max(0, disc.cx - disc.w / 2)), int(max(0, disc.cy - disc.h / 2))
    x1, y1 = int(min(w, disc.cx + disc.w / 2)), int(min(h, disc.cy + disc.h / 2))
    fallback = Ellipse(disc.cx, disc.cy, disc.w * 0.4, disc.h * 0.4)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return fallback
    roi = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    roi = cv2.GaussianBlur(roi, (0, 0), max(1.0, min(roi.shape) / 30))
    yy, xx = np.mgrid[0:roi.shape[0], 0:roi.shape[1]]
    inside = (((xx + x0 - disc.cx) / (disc.w / 2)) ** 2 + ((yy + y0 - disc.cy) / (disc.h / 2)) ** 2) <= 1
    vals = roi[inside]
    if vals.size < 20 or int(vals.max()) - int(vals.min()) < 8:
        return fallback
    # 유두 안을 테(어두움)와 함몰(밝음) 두 무리로 가르는 경계 (Otsu)
    thr, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = max(float(thr), float(np.percentile(vals, 40)))
    mask = ((roi > thr) & inside).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return fallback
    lab = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    cw = float(np.clip(stats[lab, cv2.CC_STAT_WIDTH], disc.w * 0.15, disc.w * 0.95))
    ch = float(np.clip(stats[lab, cv2.CC_STAT_HEIGHT], disc.h * 0.15, disc.h * 0.95))
    return Ellipse(x0 + float(cents[lab][0]), y0 + float(cents[lab][1]), cw, ch)


def cd_ratios(disc: Ellipse, cup: Ellipse) -> dict:
    """유두·함몰 타원 → 수직·수평·면적 C/D 비율과 테(rim) 면적 비율."""
    if disc.w <= 0 or disc.h <= 0:
        return {"vertical": 0.0, "horizontal": 0.0, "area": 0.0, "rim_area": 1.0}
    v = float(np.clip(cup.h / disc.h, 0, 1))
    hz = float(np.clip(cup.w / disc.w, 0, 1))
    area = float(np.clip((cup.w * cup.h) / (disc.w * disc.h), 0, 1))
    return {"vertical": v, "horizontal": hz, "area": area, "rim_area": 1.0 - area}


def cd_comment(vertical: float) -> str:
    """수직 C/D 에 대한 참고 문구 (진단 아님)."""
    if vertical >= 0.7:
        return "수직 C/D 0.7 이상 — 녹내장성 변화 여부 확인 권장 (참고)"
    if vertical >= 0.6:
        return "수직 C/D 0.6 이상 — 경과 관찰·추가 검사 고려 (참고)"
    return "수직 C/D 0.6 미만 (참고)"


# ============================================================ 유두 3D 지형
def crop_square(bgr: np.ndarray, cx: float, cy: float, half: float, size: int = 240) -> np.ndarray:
    """(cx, cy) 를 중심으로 한 정사각형을 size×size 로 잘라 낸다 (영상 밖은 검정)."""
    half = max(4.0, half)
    m = np.float32([[size / (2 * half), 0, size / 2 - cx * size / (2 * half)],
                    [0, size / (2 * half), size / 2 - cy * size / (2 * half)]])
    return cv2.warpAffine(bgr, m, (size, size), flags=cv2.INTER_AREA if half * 2 > size else cv2.INTER_LINEAR)


def relief_height(tex: np.ndarray) -> np.ndarray:
    """밝기 → 높이(0~1, 1 = 가장 깊음). 유두의 밝은 함몰이 움푹 들어간 것처럼 보이게 한다."""
    g = cv2.cvtColor(tex, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), max(1.5, tex.shape[0] / 28))
    lo, hi = np.percentile(g, 5), np.percentile(g, 99.5)
    if hi - lo < 1e-3:
        return np.zeros_like(g)
    return np.clip((g - lo) / (hi - lo), 0, 1)


def _rot(yaw: float, pitch: float) -> np.ndarray:
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], dtype=np.float32)
    return rx @ ry


def render_relief(tex: np.ndarray, height: np.ndarray, yaw_deg: float = -25.0, pitch_deg: float = 55.0,
                  depth: float = 0.2, size: int = 420, overlays: list | None = None) -> np.ndarray:
    """지형(height)을 입체로 그린다. tex 와 height 는 같은 크기의 정사각형.

    overlays: [(Ellipse(tex 좌표), (b, g, r))] — 지형 위에 테두리 선으로 그린다.
    """
    n = 440
    t = cv2.resize(tex, (n, n), interpolation=cv2.INTER_LINEAR)
    hm = cv2.resize(height, (n, n), interpolation=cv2.INTER_LINEAR)
    if overlays:
        s = n / tex.shape[0]
        for el, color in overlays:
            cv2.ellipse(t, (int(el.cx * s), int(el.cy * s)), (max(1, int(el.w * s / 2)), max(1, int(el.h * s / 2))),
                        0, 0, 360, color, 2, cv2.LINE_AA)
    # 빛: 기울기로 음영
    gy, gx = np.gradient(hm)
    shade = np.clip(0.8 - (gx + gy) * depth * 9.0, 0.35, 1.25)
    col = np.clip(t.astype(np.float32) * shade[..., None], 0, 255).astype(np.uint8)

    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    pts = np.stack([(xs / (n - 1) - 0.5), (ys / (n - 1) - 0.5), -hm * depth], axis=-1).reshape(-1, 3)   # z+ = 보는 쪽으로 솟음, 함몰은 음수
    r = _rot(math.radians(yaw_deg), math.radians(pitch_deg))
    p = pts @ r.T
    scale = size * 0.62
    u = np.round(p[:, 0] * scale + size / 2).astype(np.int32)
    v = np.round(p[:, 1] * scale + size / 2).astype(np.int32)
    ok = (u >= 0) & (u < size) & (v >= 0) & (v < size)
    order = np.argsort(p[:, 2][ok])                    # 먼 것(z 작음)부터 그려 가까운 것이 덮게
    out = np.full((size, size, 3), (16, 13, 11), np.uint8)
    uu, vv, cc = u[ok][order], v[ok][order], col.reshape(-1, 3)[ok][order]
    # 가파른 벽에서 점 사이가 벌어지지 않게 2×2 로 찍는다 (뒤에 찍은 가까운 점이 덮음)
    for du, dv in ((1, 1), (0, 1), (1, 0), (0, 0)):
        out[np.minimum(vv + dv, size - 1), np.minimum(uu + du, size - 1)] = cc
    return out


# ============================================================ 3D 안구
def _disc_dir(disc_uv: tuple[float, float], fov_deg: float) -> np.ndarray:
    """사진 위 유두 위치(0~1) → 안구 좌표의 단위 방향 벡터 (뒤극 = (0, 0, -1))."""
    du, dv = (disc_uv[0] - 0.5) * 2, (disc_uv[1] - 0.5) * 2
    rr = min(1.0, math.hypot(du, dv))
    th = rr * math.radians(fov_deg) / 2
    ph = math.atan2(-dv, du)
    return np.array([math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), -math.cos(th)], dtype=np.float32)


def render_eyeball(tex: np.ndarray, yaw_deg: float = 20.0, pitch_deg: float = -8.0, fov_deg: float = 120.0,
                   size: int = 460, stage: int = 0, disc_uv: tuple[float, float] | None = None,
                   disc_frac: float = 0.09, zoom: float = 1.0) -> np.ndarray:
    """안저 사진(정사각형 tex)을 안구 뒤 반구 안쪽에 입힌 단면 그림.

    fov_deg  사진이 덮는 화각 (일반 안저카메라 45~60°, 광각 200°). 화각 밖은 망막 기본색.
    stage    0~3 녹내장 단계. 1 이상이면 유두 함몰과 활 모양 신경섬유층 결손을 덧그린다.
    disc_uv  사진에서 유두 중심 위치(0~1). disc_frac = 유두 지름 / 사진 한 변.
    """
    stage = int(np.clip(stage, 0, 3))
    rad = size * 0.44 * float(np.clip(zoom, 1.0, 4.0))            # zoom > 1 이면 안구 가운데를 크게
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    x, y = (xs - size / 2) / rad, -(ys - size / 2) / rad
    rr2 = x * x + y * y
    inside = rr2 <= 1.0
    z = -np.sqrt(np.clip(1.0 - rr2, 0, 1))                       # 보는 쪽에서 먼 면(안구 안쪽 벽)
    r = _rot(math.radians(yaw_deg), math.radians(pitch_deg))
    pv = np.stack([x, y, z], axis=-1)
    pe = pv @ r                                                   # 보기 → 안구 좌표 (r 의 역 = 전치)
    ex, ey, ez = pe[..., 0], pe[..., 1], pe[..., 2]
    theta = np.arccos(np.clip(-ez, -1, 1))                        # 뒤극에서의 각
    phi = np.arctan2(ey, ex)
    half = math.radians(fov_deg) / 2
    rho = theta / half
    mx = ((0.5 + 0.5 * rho * np.cos(phi)) * (tex.shape[1] - 1)).astype(np.float32)
    my = ((0.5 - 0.5 * rho * np.sin(phi)) * (tex.shape[0] - 1)).astype(np.float32)
    img = cv2.remap(tex, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0)).astype(np.float32)

    # 화각 밖(또는 사진의 검은 테두리)은 망막 기본색으로 부드럽게 잇는다
    base = np.array([26, 52, 150], np.float32)                    # BGR 적갈색
    lum = img.max(axis=-1)
    w_tex = np.clip((1.02 - rho) / 0.06, 0, 1) * np.clip((lum - 14) / 26, 0, 1)
    img = img * w_tex[..., None] + base * (1 - w_tex[..., None])

    if stage > 0 and disc_uv is not None:
        d = _disc_dir(disc_uv, fov_deg)
        dots = np.clip(ex * d[0] + ey * d[1] + ez * d[2], -1, 1)
        ang = np.arccos(dots)                                     # 유두 중심에서의 각
        disc_ang = max(0.02, disc_frac * half)                    # 유두 반지름(각)
        # 함몰: 유두 안쪽을 희고 창백하게
        cup = np.clip(1 - ang / (disc_ang * _STAGE_CUP[stage]), 0, 1) ** 0.6
        img = img * (1 - 0.8 * cup[..., None]) + np.array([225, 240, 250], np.float32) * (0.8 * cup[..., None])
        # 활 모양 결손: 유두에서 위·아래로 뻗어 황반 쪽으로 휘는 어두운 띠
        pole = np.array([0, 0, -1], np.float32)
        tdir = pole - d * float(pole @ d)                         # 유두 → 뒤극(황반) 방향 접선
        tn = float(np.linalg.norm(tdir)) or 1.0
        tdir /= tn
        up = np.cross(d, tdir)
        a_t = ex * tdir[0] + ey * tdir[1] + ez * tdir[2]
        a_u = ex * up[0] + ey * up[1] + ez * up[2]
        bearing = np.arctan2(a_u, a_t)                            # 0 = 황반 쪽
        width = math.radians(16 + 12 * stage)
        band = np.zeros_like(ang)
        for centre in (math.radians(62), -math.radians(62)):
            curve = centre * np.clip(1 - ang / math.radians(95), 0.25, 1)   # 멀어질수록 황반 쪽으로 휨
            band = np.maximum(band, np.exp(-((bearing - curve) / width) ** 2))
        reach = np.clip((ang - disc_ang) / math.radians(8), 0, 1) * np.clip(1.25 - ang / math.radians(40 + 22 * stage), 0, 1)
        defect = _STAGE_DEFECT[stage] * band * reach
        img = img * (1 - 0.72 * defect[..., None])

    # 입체감: 안쪽 벽의 깊이·가장자리 음영
    shade = 0.55 + 0.45 * (-z)
    img *= shade[..., None]
    # 앞쪽(각막 쪽) 절단면 너머는 어둡게 — 단면 그림 느낌
    front = np.clip((ez - 0.15) / 0.25, 0, 1)
    img = img * (1 - 0.85 * front[..., None]) + np.array([40, 36, 32], np.float32) * (0.85 * front[..., None])

    out = np.full((size, size, 3), (16, 13, 11), np.float32)
    out[inside] = img[inside]
    out = out.astype(np.uint8)
    if rad < size * 0.7:
        cv2.circle(out, (size // 2, size // 2), int(rad), (200, 205, 215), 2, cv2.LINE_AA)   # 공막 테두리
    return out


# ============================================================ 시야 예시
def sample_scene(size: int = 300) -> np.ndarray:
    """시야 예시용 그림 — 길과 건물, 사람이 있는 단순한 거리 풍경."""
    w, h = size, int(size * 0.66)
    img = np.zeros((h, w, 3), np.uint8)
    for yy in range(h):                                           # 하늘 → 지평선
        t = yy / (h * 0.55)
        img[yy] = (235 - 60 * min(t, 1), 200 - 20 * min(t, 1), 150 + 40 * min(t, 1))
    hz = int(h * 0.55)
    img[hz:] = (95, 110, 105)                                     # 땅
    rng = np.random.default_rng(7)
    x = 0
    while x < w:                                                  # 건물
        bw = int(rng.integers(w * 0.07, w * 0.14)); bh = int(rng.integers(h * 0.15, h * 0.42))
        c = int(rng.integers(90, 170))
        cv2.rectangle(img, (x, hz - bh), (x + bw - 3, hz), (c, c - 10, c - 20), -1)
        for wy in range(hz - bh + 6, hz - 6, 12):
            for wx in range(x + 5, x + bw - 8, 10):
                cv2.rectangle(img, (wx, wy), (wx + 4, wy + 6), (190, 225, 240), -1)
        x += bw
    road = np.array([[w * 0.42, hz], [w * 0.58, hz], [w * 0.95, h], [w * 0.05, h]], np.int32)
    cv2.fillPoly(img, [road], (70, 70, 72))
    for i in range(5):                                            # 중앙선
        t0, t1 = i / 5, i / 5 + 0.1
        y0, y1 = int(hz + (h - hz) * t0), int(hz + (h - hz) * t1)
        cv2.line(img, (w // 2, y0), (w // 2, y1), (210, 230, 240), max(1, int(1 + 3 * t0)))
    for px, s in ((0.2, 1.0), (0.8, 0.8), (0.66, 0.5)):          # 사람
        fx, fy, fh = int(w * px), int(hz + (h - hz) * (0.35 + 0.5 * s)), int(h * 0.2 * s)
        cv2.line(img, (fx, fy), (fx, fy - fh), (40, 40, 160), max(2, int(5 * s)))
        cv2.circle(img, (fx, fy - fh - int(4 * s)), max(2, int(5 * s)), (150, 180, 220), -1)
    cv2.circle(img, (int(w * 0.85), int(h * 0.14)), int(h * 0.06), (190, 240, 255), -1)   # 해
    return img


def field_simulation(stage: int, size: int = 300, scene: np.ndarray | None = None) -> np.ndarray:
    """그 단계에서 환자가 보는 모습의 예시 — 주변부터 어두워지고 말기에는 가운데만 남는다."""
    stage = int(np.clip(stage, 0, 3))
    sc = sample_scene(size) if scene is None else scene
    h, w = sc.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = (xs - w / 2) / (w / 2), (ys - h / 2) / (h / 2)
    rad = np.sqrt(nx * nx + ny * ny) / math.sqrt(2)
    keep = np.ones((h, w), np.float32)
    if stage > 0:
        r0 = _STAGE_FIELD[stage]
        keep = np.clip((r0 - rad) / 0.16 + 0.5, 0, 1)
        if stage == 1:                                            # 초기: 위쪽 활 모양 암점
            arc = np.exp(-(((np.sqrt(nx * nx + (ny + 0.05) ** 2) - 0.45) / 0.09) ** 2)) * (ny < 0.0) * (nx > -0.75)
            keep = np.minimum(keep, 1 - 0.85 * arc)
    blur = cv2.GaussianBlur(sc, (0, 0), 6)
    dark = (blur.astype(np.float32) * 0.12 + 14)
    out = sc.astype(np.float32) * keep[..., None] + dark * (1 - keep[..., None])
    return np.clip(out, 0, 255).astype(np.uint8)


def channel_view(bgr: np.ndarray, mode: str) -> np.ndarray:
    """보기 전환 — 'redfree'(감각망막, 녹색 채널) · 'choroid'(맥락막, 적색 채널) 은 흑백으로, 그 밖에는 그대로."""
    if mode == "redfree":
        return cv2.cvtColor(bgr[..., 1], cv2.COLOR_GRAY2BGR)
    if mode == "choroid":
        return cv2.cvtColor(bgr[..., 2], cv2.COLOR_GRAY2BGR)
    return bgr
