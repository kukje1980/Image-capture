"""TBUT(눈물막 파괴 시간) 분석 — 형광염색 동영상에서 마지막 눈깜빡임 이후 첫 건조 반점까지의 시간.

1) 분석 영역(기본: 중앙 50%)의 녹색 채널 밝기를 프레임마다 측정
2) 눈깜빡임 = 밝기가 평소(중앙값)의 BLINK_DROP 이하로 떨어졌다 회복하는 구간
3) 깜빡임 직후 BASELINE_S 동안의 평균 영상을 기준으로, 기준보다 DARK_RATIO 이하로 어두워진
   픽셀(눈물막이 끊어진 검은 반점)의 비율을 추적
4) 그 비율이 BREAK_FRAC 이상으로 SUSTAIN 프레임 연속되면 파괴 시점 → TBUT = 파괴 − 깜빡임 끝

결과는 의사가 그래프·시점 프레임을 보고 확인하는 보조값이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

BLINK_DROP = 0.6        # 평소 밝기의 60% 이하 = 눈꺼풀이 덮음
BASELINE_S = 0.3
DARK_RATIO = 0.6
BREAK_FRAC = 0.01       # 영역의 1%
SUSTAIN = 3
WIDTH = 320


@dataclass
class TBUTResult:
    ok: bool
    tbut_s: Optional[float] = None
    blink_end_s: Optional[float] = None
    breakup_s: Optional[float] = None
    times: list = field(default_factory=list)
    brightness: list = field(default_factory=list)     # 영역 평균 밝기 (0~255)
    dark_frac: list = field(default_factory=list)      # 건조 반점 비율 (0~1)
    fps: float = 30.0
    breakup_index: Optional[int] = None
    breakup_frame: Optional[np.ndarray] = None         # 파괴 시점 프레임 (원본 해상도, BGR)
    message: str = ""


def _roi(shape, roi):
    h, w = shape[:2]
    x, y, rw, rh = roi or (0.25, 0.25, 0.5, 0.5)
    return int(x * w), int(y * h), max(4, int(rw * w)), max(4, int(rh * h))


def analyze_frames(frames, fps: float, roi=None) -> TBUTResult:
    """frames: BGR 프레임 반복자. 테스트·동영상 공통.

    메모리를 아끼려고 영역의 축소 녹색 채널(uint8)만 보관한다 (1분 1080p 동영상 ≈ 수십 MB).
    """
    times, bright, smalls = [], [], []
    for i, f in enumerate(frames):
        h, w = f.shape[:2]
        s = WIDTH / w if w > WIDTH else 1.0
        small = cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else f
        x, y, rw, rh = _roi(small.shape, roi)
        g = cv2.GaussianBlur(small[y:y + rh, x:x + rw, 1], (5, 5), 0)
        smalls.append(g)
        times.append(i / fps)
        bright.append(float(g.mean()))
    res = TBUTResult(ok=False, times=times, brightness=bright, fps=fps)
    if len(bright) < int(fps):
        res.message = "동영상이 너무 짧습니다 (1초 이상 필요)"
        res.dark_frac = [0.0] * len(bright)
        return res
    typical = float(np.median(bright))
    closed = np.array(bright) < typical * BLINK_DROP
    # 마지막 눈깜빡임의 끝 (눈을 뜬 첫 프레임). 깜빡임이 없으면 처음부터
    start = 0
    blink_found = False
    for i in range(1, len(closed)):
        if closed[i - 1] and not closed[i]:
            start, blink_found = i, True
    # 마지막 깜빡임 뒤 다시 감기 전까지만 본다
    end = len(closed)
    base_n = max(1, int(round(BASELINE_S * fps)))
    if end - start <= base_n + SUSTAIN:
        res.message = "깜빡임 뒤 영상이 너무 짧습니다"
        res.dark_frac = [0.0] * len(bright)
        return res
    baseline = np.mean(np.stack(smalls[start:start + base_n]).astype(np.float32), axis=0)
    valid = baseline > 25                                   # 너무 어두운 곳(동공 반사 없음 등)은 제외
    dark = [0.0] * len(bright)
    for i in range(start, end):
        d = (smalls[i] < baseline * DARK_RATIO) & valid
        dark[i] = float(d.sum()) / max(1, int(valid.sum()))
    res.dark_frac = dark
    res.blink_end_s = start / fps
    run = 0
    for i in range(start + base_n, end):
        run = run + 1 if dark[i] >= BREAK_FRAC else 0
        if run >= SUSTAIN:
            k = i - SUSTAIN + 1
            res.breakup_s = k / fps
            res.tbut_s = res.breakup_s - res.blink_end_s
            res.breakup_index = k
            res.ok = True
            res.message = (f"TBUT {res.tbut_s:.1f}초" + ("" if blink_found else " (영상 시작 기준 — 깜빡임 미검출)"))
            return res
    res.message = (f"파괴 반점이 보이지 않습니다 — TBUT > {(end - 1 - start) / fps:.1f}초"
                   + ("" if blink_found else " (깜빡임 미검출)"))
    return res


def analyze_video(path: str, roi=None, max_seconds: float = 60.0) -> TBUTResult:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return TBUTResult(ok=False, message="동영상을 열 수 없습니다")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if not 1 <= fps <= 240:
        fps = 30.0
    limit = int(max_seconds * fps)

    def frames():
        n = 0
        while n < limit:
            ok, f = cap.read()
            if not ok or f is None:
                break
            n += 1
            yield f

    try:
        res = analyze_frames(frames(), fps, roi)
    finally:
        cap.release()
    if res.breakup_index is not None:                      # 파괴 시점 프레임만 다시 읽어 온다
        cap = cv2.VideoCapture(path)
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, res.breakup_index)
            ok, f = cap.read()
            res.breakup_frame = f if ok else None
        finally:
            cap.release()
    return res
