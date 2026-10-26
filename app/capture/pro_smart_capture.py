"""스마트 캡처 엔진 — 초점 판정 · Best Shot 버퍼 · 자동 촬영 · 포커스 피킹 · 화질 점검.

Qt 를 쓰지 않는 독립 모듈이라 화면(Pro LIVE)과 분리해 테스트·재사용할 수 있다.

원리
  선명도   ROI(화면 중앙 관심 영역)의 Tenengrad(Sobel 기울기 제곱 평균). 포화된 반사광과
           너무 어두운 부분은 빼고 계산한다 (반사광 경계가 '선명하다'고 속지 않게).
  상대값   조명·배율마다 점수 범위가 달라 고정 기준은 쓰지 않는다. 최근 최고점 대비 %로 판단.
  Best Shot  최근 약 1초 프레임을 메모리에 들고 있다가, 셔터를 누르면 그중 가장 선명한
           프레임을 고른다 (누르는 순간의 흔들림·셔터 지연 제거).
  자동 촬영  초점이 흐렸다가(스윕) 최고점 근처에서 몇 프레임 안정되면 트리거.
           눈 깜빡임(밝기 급변) 직후·반사광 과다·흔들림·쿨다운 중에는 찍지 않는다.

점수는 절대적인 초점 정확도가 아니라 같은 촬영 조건 안에서 비교하는 상대값이다.
진단 기능이 아니라 '촬영 품질' 보조 기능이다.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

AUTO_MODES = ("off", "freeze", "save")          # 끄기 / 자동 정지(Smart Freeze) / 자동 저장
_ANALYSIS_SIDE = 480                            # 선명도 계산용 ROI 축소 크기 (긴 변)
_MOTION_SIDE = 96                               # 흔들림 계산용 축소 크기


def roi_rect(width: int, height: int, frac: float) -> tuple[int, int, int, int]:
    """화면 중앙의 관심 영역 (x, y, w, h). frac = 가로·세로 비율 (0.1~1.0)."""
    frac = min(1.0, max(0.1, float(frac)))
    w, h = max(1, int(width * frac)), max(1, int(height * frac))
    return (width - w) // 2, (height - h) // 2, w, h


def _gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _shrink(img: np.ndarray, side: int) -> np.ndarray:
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= side:
        return img
    s = side / longest
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


@dataclass
class FrameMetrics:
    ts: float
    focus: float = 0.0          # Tenengrad (상대 비교용 원시값)
    brightness: float = 0.0     # ROI 평균 밝기 0~255
    overexposed: float = 0.0    # ROI 중 포화(≥250) 비율 — 반사광·노출 과다
    underexposed: float = 0.0   # ROI 중 너무 어두운(≤15) 비율
    motion: float = 0.0         # 직전 프레임과의 평균 밝기 차 (흔들림)
    valid: float = 1.0          # 선명도 계산에 쓴 화소 비율
    blink: bool = False         # 깜빡임(밝기 급변) 구간


def focus_score(frame: np.ndarray, roi: tuple[int, int, int, int] | None = None) -> float:
    """ROI 선명도 (Tenengrad). 반사광(포화)·암부는 제외. 계산할 화소가 너무 적으면 0."""
    return _measure(frame, roi)[0]


def _measure(frame: np.ndarray, roi) -> tuple[float, float, float, float, float, np.ndarray]:
    if roi is not None:
        x, y, w, h = roi
        frame = frame[y:y + h, x:x + w]
    g = _shrink(_gray(frame), _ANALYSIS_SIDE)
    n = float(g.size) or 1.0
    bright = float(g.mean()) if g.size else 0.0
    over = float(np.count_nonzero(g >= 250)) / n
    under = float(np.count_nonzero(g <= 15)) / n
    gb = cv2.GaussianBlur(g, (3, 3), 0)
    valid = ((gb > 15) & (gb < 245)).astype(np.uint8)
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8)) > 0     # 반사광 테두리의 강한 경계 제외
    ratio = float(valid.mean()) if valid.size else 0.0
    if ratio < 0.2:
        return 0.0, bright, over, under, ratio, g
    gx = cv2.Sobel(gb, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gb, cv2.CV_32F, 0, 1, ksize=3)
    ten = gx * gx + gy * gy
    return float(ten[valid].mean()), bright, over, under, ratio, g


def peaking_mask(frame: np.ndarray, sensitivity: int = 2, max_side: int = 960) -> np.ndarray:
    """포커스 피킹: 초점이 맞은(경계가 날카로운) 곳 = 255 인 축소 마스크.

    sensitivity 1(적게)~3(많이). 포화된 반사광 주변은 제외한다. 표시용이며 원본은 건드리지 않는다.
    """
    g = cv2.GaussianBlur(_gray(_shrink(frame, max_side)), (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    sat = cv2.dilate((g >= 245).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    mag[sat] = 0
    nz = mag[mag > 0]
    if nz.size == 0:
        return np.zeros(g.shape, np.uint8)
    k = {1: 3.0, 2: 2.3, 3: 1.6}.get(int(sensitivity), 2.3)
    thr = max(40.0, float(nz.mean() + k * nz.std()))
    return ((mag > thr) * 255).astype(np.uint8)


def quality(m: FrameMetrics, rel_focus: float) -> dict:
    """화질 점검 — 초점·노출·안정·반사 0~100 점수와 재촬영 안내 문구 (진단 아님)."""
    exp_pen = max(0.0, 40 - m.brightness) * 2.0 + max(0.0, m.brightness - 215) * 2.0
    exposure = 100 - exp_pen - m.underexposed * 60
    reflection = 100 - m.overexposed * 600
    stability = 100 - m.motion * 8
    scores = {"focus": rel_focus, "exposure": exposure, "stability": stability, "reflection": reflection}
    scores = {k: int(round(min(100.0, max(0.0, v)))) for k, v in scores.items()}
    issues = []
    if scores["focus"] < 70:
        issues.append("초점 흐림 — 조이스틱을 앞뒤로 천천히")
    if m.overexposed > 0.04:
        issues.append("반사광/노출 과다 — 조명 각도·밝기 조절")
    elif m.brightness > 215:
        issues.append("노출 과다 — 조명 밝기 낮추기")
    if m.brightness < 35:
        issues.append("노출 부족 — 조명 밝기 올리기")
    if m.motion > 8:
        issues.append("흔들림 — 잠시 고정")
    scores["issues"] = issues
    scores["ok"] = not issues
    return scores


@dataclass
class SmartSettings:
    roi_frac: float = 0.5           # 관심 영역 (화면 중앙 비율)
    auto_mode: str = "off"          # off | freeze | save
    best_window: float = 1.0        # Best Shot 셔터가 돌아보는 시간(초)
    buffer_seconds: float = 1.5     # 메모리에 들고 있는 시간
    buffer_max_mb: int = 400        # 4K 에서도 메모리가 넘치지 않게
    window: float = 2.0             # 자동 촬영 판단 구간(초)
    peak_ratio: float = 0.90        # 최고점의 90% 이상
    stable_frames: int = 6          # 연속 안정 프레임 수
    stable_tol: float = 0.08        # 그 사이 선명도 변동 허용 (8%)
    sweep_ratio: float = 0.80       # 구간 안에 최고점의 80% 이하였던 순간이 있어야 (초점을 맞춰 들어온 것)
    blink_jump: float = 0.12        # 밝기 12% 이상 급변 = 깜빡임
    blink_hold: float = 0.3         # 깜빡임 후 촬영 금지 시간
    max_overexposed: float = 0.25
    min_brightness: float = 20.0
    max_motion: float = 10.0
    cooldown_freeze: float = 1.5
    cooldown_save: float = 3.0      # 자동 저장은 파일이 쌓이지 않게 더 길게
    min_focus: float = 1.0


@dataclass
class SmartResult:
    metrics: FrameMetrics
    rel_focus: float                # 최근 최고점 대비 % (0~100)
    triggered: bool = False         # 자동 촬영 조건 충족 (이번 프레임)
    quality: dict = field(default_factory=dict)


class SmartCaptureEngine:
    """프레임을 push 하면 선명도·화질을 계산하고 Best Shot 버퍼와 자동 촬영 판단을 갱신한다."""

    def __init__(self, settings: SmartSettings | None = None):
        self.s = settings or SmartSettings()
        self._buf: deque = deque()               # (FrameMetrics, frame)
        self._bytes = 0
        self._hist: deque = deque()              # 자동 촬영 판단용 FrameMetrics
        self._ref: deque = deque()               # 상대 초점 기준 (ts, focus) — 최근 5초
        self._prev_small: np.ndarray | None = None
        self._prev_bright: float | None = None
        self._block_until = 0.0
        self._cooldown_until = 0.0
        self.last: SmartResult | None = None

    def reset(self) -> None:
        self._buf.clear()
        self._bytes = 0
        self._hist.clear()
        self._ref.clear()
        self._prev_small = None
        self._prev_bright = None
        self._block_until = 0.0
        self.last = None

    # ---------- 입력 ----------
    def push(self, frame: np.ndarray, ts: float) -> SmartResult:
        h, w = frame.shape[:2]
        roi = roi_rect(w, h, self.s.roi_frac)
        focus, bright, over, under, valid, g = _measure(frame, roi)
        small = cv2.resize(g, (_MOTION_SIDE, max(1, int(_MOTION_SIDE * g.shape[0] / max(1, g.shape[1])))),
                           interpolation=cv2.INTER_AREA).astype(np.int16)
        motion = 0.0
        if self._prev_small is not None and self._prev_small.shape == small.shape:
            motion = float(np.abs(small - self._prev_small).mean())
        self._prev_small = small

        blink = False
        if self._prev_bright is not None:
            jump = abs(bright - self._prev_bright) / max(self._prev_bright, 10.0)
            if jump > self.s.blink_jump:
                self._block_until = ts + self.s.blink_hold
        self._prev_bright = bright
        if ts < self._block_until:
            blink = True

        m = FrameMetrics(ts, focus, bright, over, under, motion, valid, blink)
        self._add_buffer(m, frame)

        self._ref.append((ts, focus))
        while self._ref and self._ref[0][0] < ts - 5.0:
            self._ref.popleft()
        peak = max(f for _, f in self._ref)
        rel = 100.0 * focus / peak if peak > self.s.min_focus else 0.0

        triggered = self._update_auto(m)
        res = SmartResult(m, rel, triggered, quality(m, rel))
        self.last = res
        return res

    def _add_buffer(self, m: FrameMetrics, frame: np.ndarray) -> None:
        self._buf.append((m, frame))
        self._bytes += frame.nbytes
        limit = self.s.buffer_max_mb * 1024 * 1024
        while self._buf and (self._buf[0][0].ts < m.ts - self.s.buffer_seconds
                             or (self._bytes > limit and len(self._buf) > 1)):
            old = self._buf.popleft()
            self._bytes -= old[1].nbytes

    # ---------- Best Shot ----------
    def best(self, window: float | None = None, now: float | None = None):
        """최근 window 초 중 가장 선명한 프레임 (깜빡임 구간 제외). (frame, metrics) 또는 (None, None)."""
        if not self._buf:
            return None, None
        window = self.s.best_window if window is None else window
        now = self._buf[-1][0].ts if now is None else now
        cands = [(m, f) for m, f in self._buf if m.ts >= now - window and not m.blink]
        if not cands:
            m, f = self._buf[-1]
            return f, m
        m, f = max(cands, key=lambda t: t[0].focus)
        return f, m

    def buffered(self) -> int:
        return len(self._buf)

    # ---------- 자동 촬영 ----------
    def _update_auto(self, m: FrameMetrics) -> bool:
        s = self.s
        self._hist.append(m)
        while self._hist and self._hist[0].ts < m.ts - s.window:
            self._hist.popleft()
        if s.auto_mode not in ("freeze", "save"):
            return False
        if m.blink or m.ts < self._cooldown_until:
            return False
        hist = list(self._hist)
        n = s.stable_frames
        if len(hist) < n + 2 or hist[-1].ts - hist[0].ts < 0.4:
            return False
        if m.overexposed > s.max_overexposed or m.brightness < s.min_brightness or m.valid < 0.3:
            return False
        peak = max(h.focus for h in hist)
        if peak <= s.min_focus:
            return False
        recent = hist[-n:]
        rf = [h.focus for h in recent]
        if min(rf) < s.peak_ratio * peak:                       # 최고점 근처가 아님 (아직 오르는 중/지나침)
            return False
        if (max(rf) - min(rf)) / max(rf) > s.stable_tol:        # 아직 흔들림
            return False
        if any(h.blink for h in recent) or max(h.motion for h in recent[1:]) > s.max_motion:
            return False
        if min(h.focus for h in hist) > s.sweep_ratio * peak:   # 초점을 맞춰 들어온 흔적이 없음 (정지 화면)
            return False
        self._cooldown_until = m.ts + (s.cooldown_save if s.auto_mode == "save" else s.cooldown_freeze)
        self._hist.clear()                                       # 다음 자동 촬영은 새 초점 스윕이 필요
        return True
