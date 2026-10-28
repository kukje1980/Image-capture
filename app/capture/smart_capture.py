"""Smart Capture 엔진 — 초점 판정 · Best Shot 버퍼 · 자동 정지/자동 저장 트리거 · 포커스 피킹.

Qt 에 의존하지 않는 순수 numpy/OpenCV 모듈이다 (스레드·UI 는 smart_worker.py 가 맡는다).

슬릿램프 영상의 특성에 맞춘 점:
- 화면 전체가 아니라 의사가 지정한 ROI(각막·홍채·수정체 등)의 선명도만 본다.
- 슬릿 조명·각막 반사의 포화 영역과 그 테두리는 아주 날카로운 경계를 만들어 선명도를 속이므로
  포화 영역을 넓혀(dilate) 계산에서 뺀다. 너무 어두운 배경도 뺀다.
- 선명도 값은 장면마다 크기가 달라 절대 기준이 없으므로, 최근에 본 가장 선명한 값(기준)에 대한
  상대값(%)으로 판정한다.
- 셔터를 그 순간 누르면 이미 슬릿램프가 움직였을 수 있으므로, 최근 프레임을 버퍼에 두고
  그중 가장 선명한 프레임을 고른다.

자동 촬영 규칙 (상태 머신):
  1) 무장(armed): 최근 몇 초 안에 초점이 기준의 rearm_pct 아래로 벗어난 적이 있어야 한다
     — 의사가 초점을 '맞추는 중'일 때만 동작하고, 가만히 있는 장면을 계속 찍지 않게 한다.
  2) 후보: 쓸 만한 프레임(노출·반사·흔들림 통과)이 기준의 ready_pct 이상이면 후보 구간 시작.
  3) 트리거: 선명도가 후보 최고값에서 peak_drop_pct 이상 떨어지면(정점 통과) 또는
     최고값 근처에서 hold_s 이상 머무르면(의사가 초점에서 멈춤) 후보 구간의 최선 프레임을 내보낸다.
  4) 쿨다운 동안, 그리고 다시 초점이 벗어났다 돌아올 때까지는 다음 트리거를 내지 않는다.

점수(초점·노출·안정·반사)는 같은 촬영 조건에서 비교하는 상대값이지, 절대적인 화질 지표가 아니다.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Deque, Optional, Tuple

import cv2
import numpy as np

MODES = ("off", "freeze", "snapshot")        # 끄기 | 자동 정지(Smart Freeze) | 자동 저장(Auto Snapshot)
DEFAULT_ROI = (0.2, 0.2, 0.6, 0.6)           # 정규화 (x, y, w, h) — 화면 중앙 60%

_SAT_LEVEL = 245                             # 이 밝기 이상 = 포화(반사광)
_DARK_LEVEL = 20                             # 이 밝기 이하 = 배경(계산 제외)


@dataclass
class SmartSettings:
    mode: str = "off"
    roi: Optional[Tuple[float, float, float, float]] = None   # None = DEFAULT_ROI
    analysis_width: int = 640            # 분석용 축소 폭 (속도)
    ready_pct: float = 85.0              # 기준 대비 이 % 이상 = 초점 맞음
    rearm_pct: float = 70.0              # 이 % 아래로 한 번 벗어나야 다음 자동 촬영
    peak_drop_pct: float = 8.0           # 후보 최고값에서 이만큼 떨어지면 '정점 통과'
    plateau_tol_pct: float = 4.0         # 이보다 적게 오르면 같은 고원(plateau)으로 본다
    hold_s: float = 0.35                 # 고원에 이만큼 머무르면 촬영
    cooldown_s: float = 2.5              # 자동 촬영 사이 최소 간격
    arm_window_s: float = 4.0            # 무장 판정에 쓰는 최근 기록 길이
    buffer_s: float = 1.0                # Best Shot 버퍼 길이
    buffer_mb: int = 200                 # 버퍼 메모리 상한 (1080p ≈ 6MB, 4K ≈ 25MB / 프레임)
    motion_max: float = 6.0              # 이보다 크면 흔들림 (30fps 기준 프레임 간 평균 밝기 변화)
    max_glare_frac: float = 0.08         # ROI 중 포화 픽셀 비율 상한
    min_valid_frac: float = 0.25         # 계산에 쓸 수 있는 픽셀 비율 하한
    min_focus: float = 12.0              # 질감 없는 장면(잡음)에서 오작동하지 않게 하는 절대 하한
    ref_decay_per_s: float = 0.04        # 기준(최고 선명도)이 초당 줄어드는 비율 — 장면이 바뀌면 따라감
    peaking_sensitivity: int = 50        # 0~100 (높을수록 더 많은 경계를 표시)

    def roi_or_default(self) -> Tuple[float, float, float, float]:
        return normalize_roi(self.roi) or DEFAULT_ROI


@dataclass
class FrameQuality:
    t: float
    focus: float = 0.0          # 원시 선명도 (장면 상대값)
    focus_pct: float = 0.0      # 기준 대비 % (0~100)
    exposure: float = 0.0       # 0~100
    stability: float = 100.0    # 0~100
    reflection: float = 100.0   # 0~100 (100 = 반사 없음)
    motion: float = 0.0
    glare_frac: float = 0.0
    valid_frac: float = 0.0
    usable: bool = False
    in_focus: bool = False
    armed: bool = False
    hint: str = ""


@dataclass
class BestShot:
    frame: np.ndarray           # 원본 프레임 (보정·가공 없음)
    quality: FrameQuality
    reason: str                 # "peak" | "hold" | "manual"


@dataclass
class _Entry:
    t: float
    focus: float
    usable: bool
    frame: Optional[np.ndarray] = field(repr=False, default=None)
    quality: Optional[FrameQuality] = None


def normalize_roi(roi) -> Optional[Tuple[float, float, float, float]]:
    """(x, y, w, h) 정규화 좌표를 0~1 안으로 자르고, 너무 작거나 잘못되면 None."""
    if not roi or len(roi) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in roi)
    except (TypeError, ValueError):
        return None
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    x0, y0 = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    x1, y1 = min(max(x + w, 0.0), 1.0), min(max(y + h, 0.0), 1.0)
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def roi_pixels(roi, width: int, height: int) -> Tuple[int, int, int, int]:
    x, y, w, h = normalize_roi(roi) or DEFAULT_ROI
    px, py = int(round(x * width)), int(round(y * height))
    pw, ph = max(4, int(round(w * width))), max(4, int(round(h * height)))
    return px, py, min(pw, width - px), min(ph, height - py)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def to_analysis_gray(frame: np.ndarray, width: int = 640) -> np.ndarray:
    """분석용 축소 회색 영상 (가우시안 3x3 으로 센서 잡음 완화)."""
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(frame, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (3, 3), 0)


def valid_mask(gray: np.ndarray) -> Tuple[np.ndarray, float]:
    """계산에 쓸 픽셀 마스크와 포화 픽셀 비율.

    포화(반사광) 영역은 7x7 로 넓혀 그 날카로운 테두리까지 빼고, 아주 어두운 배경도 뺀다.
    """
    sat = (gray >= _SAT_LEVEL).astype(np.uint8)
    glare_frac = float(sat.mean()) if sat.size else 0.0
    sat_wide = cv2.dilate(sat, np.ones((7, 7), np.uint8)) > 0
    dark = cv2.erode((gray > _DARK_LEVEL).astype(np.uint8), np.ones((3, 3), np.uint8)) == 0
    return ~(sat_wide | dark), glare_frac


def gradient_energy(gray: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return gx * gx + gy * gy


def focus_score(gray: np.ndarray, valid: np.ndarray) -> float:
    """ROI 선명도 (Tenengrad): 유효 픽셀의 Sobel 기울기 제곱 평균의 제곱근.

    라플라시안 분산보다 센서 잡음에 덜 민감하다. 제곱근을 취해 값의 범위를 기울기 크기와 같게 맞춘다
    (잡음만 있는 화면 ≈ 3~7, 질감이 선명한 홍채 ≈ 수십~100 이상).
    """
    if valid.size == 0 or not valid.any():
        return 0.0
    return float(math.sqrt(float(np.mean(gradient_energy(gray)[valid]))))


def peaking_mask(gray: np.ndarray, sensitivity: int = 50) -> np.ndarray:
    """포커스 피킹: 초점이 맞은 미세 구조 = 255. 반사광 테두리·어두운 배경은 제외.

    아주 짧은 거리의 밝기 변화(원본 - 가우시안 σ1.5)만 본다 — 초점이 조금만 어긋나도 먼저 사라지는
    성분이라, 흐린 영상에서는 거의 칠해지지 않는다. 문턱값은 절대값(밝기 단위)이므로 화면이 전부
    흐리면 아무것도 표시하지 않는다. 감도 0 → 24, 100 → 6.
    """
    g = gray.astype(np.float32)
    detail = np.abs(g - cv2.GaussianBlur(g, (0, 0), 1.5))
    valid, _ = valid_mask(gray)
    s = min(max(int(sensitivity), 0), 100)
    thr = 24.0 - 0.18 * s
    mask = ((detail >= thr) & valid).astype(np.uint8) * 255
    return cv2.dilate(mask, np.ones((2, 2), np.uint8))


class SmartCaptureEngine:
    """프레임을 하나씩 넣으면 품질을 평가하고, 자동 촬영 순간이면 BestShot 을 돌려준다.

    스레드 안전하지 않다 — 한 스레드(분석 워커)에서만 호출한다.
    """

    def __init__(self, settings: Optional[SmartSettings] = None):
        self.settings = settings or SmartSettings()
        self.reset()

    # ---- 상태 ----
    def reset(self) -> None:
        """기준·기록·버퍼를 비운다 (ROI·카메라가 바뀔 때)."""
        self._ref = 0.0
        self._last_t: Optional[float] = None
        self._prev_small: Optional[np.ndarray] = None
        self._history: Deque[Tuple[float, float]] = deque()      # (t, focus) — 무장 판정용
        self._buffer: Deque[_Entry] = deque()                     # Best Shot 버퍼 (프레임 포함)
        self._buffer_bytes = 0
        self._last_trigger_t = -1e9
        self._cand_best: Optional[_Entry] = None
        self._anchor = 0.0
        self._plateau_t = 0.0
        self.last_quality: Optional[FrameQuality] = None
        self.last_gray: Optional[np.ndarray] = None               # 마지막 분석용 회색 영상 (피킹에 재사용)

    def update_settings(self, settings: SmartSettings) -> None:
        old = self.settings
        self.settings = settings
        if (normalize_roi(old.roi) != normalize_roi(settings.roi) or old.analysis_width != settings.analysis_width):
            self.reset()
        elif old.mode != settings.mode:
            self._cand_best = None            # 모드를 바꾸면 진행 중이던 후보는 버린다

    # ---- 분석 ----
    def measure(self, frame: np.ndarray, t: float) -> Tuple[FrameQuality, np.ndarray]:
        """한 프레임의 품질 측정 (상태: 기준·흔들림 기록 갱신). 분석용 회색 영상도 함께 돌려준다."""
        s = self.settings
        gray_full = to_analysis_gray(frame, s.analysis_width)
        h, w = gray_full.shape[:2]
        x, y, rw, rh = roi_pixels(s.roi, w, h)
        gray = gray_full[y:y + rh, x:x + rw]
        valid, glare_frac = valid_mask(gray)
        valid_frac = float(valid.mean()) if valid.size else 0.0
        focus = focus_score(gray, valid) if valid_frac >= s.min_valid_frac else 0.0

        # 흔들림: 더 작게 줄인 ROI 의 프레임 간 평균 밝기 차 (30fps 기준으로 환산)
        small = cv2.resize(gray, (64, max(1, round(64 * rh / max(rw, 1)))), interpolation=cv2.INTER_AREA)
        small = small.astype(np.float32)
        dt = (t - self._last_t) if self._last_t is not None else 1 / 30
        if self._prev_small is not None and self._prev_small.shape == small.shape:
            per_frame = float(np.mean(np.abs(small - self._prev_small)))
            motion = per_frame * (1 / 30) / min(max(dt, 1 / 120), 0.5)
        else:
            motion = 0.0
        self._prev_small = small
        self._last_t = t

        # 노출: 슬릿램프 영상은 배경이 대부분 어두우므로 평균이 아니라 밝은 부분(상위 10%)을 본다
        p90 = float(np.percentile(gray, 90)) if gray.size else 0.0
        exposure = 100.0 * _clamp01((p90 - 25.0) / (80.0 - 25.0))
        reflection = 100.0 * _clamp01(1.0 - glare_frac / (s.max_glare_frac * 1.5))
        stability = 100.0 * _clamp01(1.0 - motion / (s.motion_max * 2.0))

        usable = (valid_frac >= s.min_valid_frac and glare_frac <= s.max_glare_frac
                  and exposure >= 30.0 and motion <= s.motion_max and focus >= s.min_focus)
        if usable:
            # 기준 = 최근 최고 선명도 (천천히 줄어들어 장면이 바뀌어도 따라간다)
            self._ref = max(focus, self._ref * math.exp(-s.ref_decay_per_s * min(dt, 1.0)))
        elif self._ref > 0:
            self._ref *= math.exp(-s.ref_decay_per_s * min(dt, 1.0))
        focus_pct = min(100.0, 100.0 * focus / self._ref) if self._ref > 0 else 0.0

        q = FrameQuality(t=t, focus=focus, focus_pct=focus_pct, exposure=exposure,
                         stability=stability, reflection=reflection, motion=motion,
                         glare_frac=glare_frac, valid_frac=valid_frac, usable=usable,
                         in_focus=usable and focus_pct >= s.ready_pct)
        q.hint = self._hint(q)
        return q, gray_full

    def _hint(self, q: FrameQuality) -> str:
        s = self.settings
        if q.valid_frac < s.min_valid_frac:
            return "ROI 가 너무 어둡거나 반사광에 가려졌습니다"
        if q.glare_frac > s.max_glare_frac:
            return "반사광 — 조명 각도를 조절하세요"
        if q.exposure < 30:
            return "노출 부족 — 조명을 밝게 하세요"
        if q.motion > s.motion_max:
            return "흔들림 — 잠시 고정하세요"
        if q.focus < s.min_focus:
            return "선명한 구조가 보이지 않습니다"
        if q.focus_pct < s.ready_pct:
            return "초점 조절 중"
        return "초점 양호"

    def process(self, frame: np.ndarray, t: float) -> Tuple[FrameQuality, Optional[BestShot]]:
        """프레임 하나 처리: 품질 측정 → 버퍼 → 자동 촬영 판정."""
        s = self.settings
        q, self.last_gray = self.measure(frame, t)
        entry = _Entry(t=t, focus=q.focus, usable=q.usable, frame=frame, quality=q)
        self._push_buffer(entry)
        self._history.append((t, q.focus))
        while self._history and self._history[0][0] < t - s.arm_window_s:
            self._history.popleft()

        q.armed = self._armed(t)
        shot = self._step(entry, q) if s.mode in ("freeze", "snapshot") else None
        self.last_quality = q
        return q, shot

    # ---- 버퍼 ----
    def _push_buffer(self, entry: _Entry) -> None:
        s = self.settings
        self._buffer.append(entry)
        self._buffer_bytes += entry.frame.nbytes if entry.frame is not None else 0
        limit = max(1, s.buffer_mb) * 1024 * 1024
        while self._buffer and (self._buffer[0].t < entry.t - s.buffer_s or
                                (self._buffer_bytes > limit and len(self._buffer) > 1)):
            old = self._buffer.popleft()
            self._buffer_bytes -= old.frame.nbytes if old.frame is not None else 0

    def best_recent(self, seconds: float = 0.6, now: Optional[float] = None) -> Optional[BestShot]:
        """최근 seconds 초 안의 쓸 만한 프레임 중 가장 선명한 것 (수동 캡처의 Best Shot)."""
        if not self._buffer:
            return None
        end = self._buffer[-1].t if now is None else now
        cands = [e for e in self._buffer if e.t >= end - seconds and e.usable]
        if not cands:
            return None
        best = max(cands, key=lambda e: e.focus)
        return BestShot(frame=best.frame, quality=best.quality, reason="manual")

    # ---- 자동 촬영 상태 머신 ----
    def _armed(self, t: float) -> bool:
        s = self.settings
        if t - self._last_trigger_t < s.cooldown_s or self._ref <= 0:
            return False
        low = self._ref * s.rearm_pct / 100.0
        return any(ft > self._last_trigger_t and f < low for ft, f in self._history)

    def _step(self, entry: _Entry, q: FrameQuality) -> Optional[BestShot]:
        s = self.settings
        t = entry.t
        cand = self._cand_best
        if cand is None:
            if q.armed and q.in_focus:
                self._cand_best = entry
                self._anchor = entry.focus
                self._plateau_t = t
            return None

        if entry.usable and entry.focus > cand.focus:
            self._cand_best = cand = entry
        if entry.usable and entry.focus > self._anchor * (1 + s.plateau_tol_pct / 100.0):
            self._anchor = entry.focus           # 아직 오르는 중 — 고원 시작 시각을 다시 잡는다
            self._plateau_t = t

        passed_peak = entry.focus < cand.focus * (1 - s.peak_drop_pct / 100.0)
        held = t - self._plateau_t >= s.hold_s and entry.focus >= cand.focus * (1 - s.peak_drop_pct / 100.0)
        if not (passed_peak or held):
            return None
        self._cand_best = None
        self._last_trigger_t = t
        best_q = replace(cand.quality) if cand.quality is not None else q
        return BestShot(frame=cand.frame, quality=best_q, reason="peak" if passed_peak else "hold")
