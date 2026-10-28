"""Smart Capture 엔진: 초점 정점에서 가장 선명한 프레임을 고르고, 가만히 있는 장면은 다시 찍지 않는다."""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from app.capture.smart_capture import (
    SmartCaptureEngine,
    SmartSettings,
    focus_score,
    normalize_roi,
    peaking_mask,
    to_analysis_gray,
    valid_mask,
)

FPS = 30.0


def _scene(seed: int = 0) -> np.ndarray:
    """홍채처럼 질감이 있는 장면 (1280x720 BGR)."""
    rng = np.random.default_rng(seed)
    tex = (rng.random((90, 160)) * 120 + 40).astype(np.uint8)
    tex = cv2.resize(tex, (1280, 720), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(tex, cv2.COLOR_GRAY2BGR)


@pytest.fixture(scope="module")
def blurred():
    img = _scene()
    cache: dict[float, np.ndarray] = {}

    def get(sigma: float) -> np.ndarray:
        key = round(float(sigma), 1)
        if key not in cache:
            cache[key] = img if key < 0.3 else cv2.GaussianBlur(img, (0, 0), key)
        return cache[key]

    return get


def _run(engine, frames, t0=0.0):
    """프레임마다 번호를 [0,0,0] 픽셀에 새겨 어느 프레임이 골라졌는지 알 수 있게 한다."""
    shots = []
    for i, f in enumerate(frames):
        f = f.copy()
        f[0, 0, 0] = i % 256
        q, shot = engine.process(f, t0 + i / FPS)
        if shot is not None:
            shots.append((i, shot))
    return shots, q


def _sweep(blurred, a=8.0, b=0.0, n=30):
    return [blurred(s) for s in np.linspace(a, b, n)]


def test_focus_score_orders_by_sharpness(blurred):
    scores = []
    for s in (0, 1, 2, 4, 8):
        g = to_analysis_gray(blurred(s))
        v, _ = valid_mask(g)
        scores.append(focus_score(g, v))
    assert scores == sorted(scores, reverse=True)
    noise = np.clip(np.random.default_rng(1).normal(90, 5, (720, 1280, 3)), 0, 255).astype(np.uint8)
    g = to_analysis_gray(noise)
    v, _ = valid_mask(g)
    assert focus_score(g, v) < SmartSettings().min_focus      # 잡음만 있는 화면은 '선명한 장면'이 아니다


def test_glare_edges_do_not_fool_focus():
    """흐린 장면 위 포화 반사광의 날카로운 테두리는 선명도에 들어가면 안 된다."""
    img = np.full((720, 1280, 3), 90, np.uint8)
    cv2.circle(img, (640, 360), 60, (255, 255, 255), -1)
    g = to_analysis_gray(img)
    v, glare = valid_mask(g)
    assert glare > 0
    assert focus_score(g, v) < 2.0
    assert focus_score(g, np.ones_like(v)) > 10.0          # 마스크 없이 재면 속는다


def test_sweep_triggers_at_sharpest_frame(blurred):
    """흐림 → 초점 → 흐림으로 지나가면 정점을 지난 직후 가장 선명한 프레임을 고른다."""
    e = SmartCaptureEngine(SmartSettings(mode="freeze"))
    frames = _sweep(blurred, 8, 0, 30) + _sweep(blurred, 0, 8, 30)
    shots, _ = _run(e, frames)
    assert len(shots) == 1
    i, shot = shots[0]
    assert shot.reason == "peak" and 29 <= i <= 40
    assert 28 <= int(shot.frame[0, 0, 0]) <= 31          # 가장 선명한 프레임들 중 하나 (원본)
    assert shot.quality.focus_pct >= 99


def test_hold_at_focus_triggers(blurred):
    """초점을 맞추고 멈추면(고원) hold_s 뒤에 촬영."""
    e = SmartCaptureEngine(SmartSettings(mode="snapshot"))
    frames = _sweep(blurred, 8, 0, 30) + [blurred(0)] * 40
    shots, _ = _run(e, frames)
    assert len(shots) == 1
    i, shot = shots[0]
    assert shot.reason == "hold"
    assert i <= 30 + int(SmartSettings().hold_s * FPS) + 3


def test_static_focused_scene_never_triggers(blurred):
    e = SmartCaptureEngine(SmartSettings(mode="snapshot"))
    shots, q = _run(e, [blurred(0)] * 150)
    assert shots == [] and q.in_focus and not q.armed


def test_rearm_needs_leaving_focus_and_cooldown(blurred):
    e = SmartCaptureEngine(SmartSettings(mode="snapshot", cooldown_s=1.0))
    first = _sweep(blurred, 8, 0, 30) + [blurred(0)] * 60         # 촬영 후 계속 초점 → 다시 찍지 않음
    shots, _ = _run(e, first)
    assert len(shots) == 1
    again = _sweep(blurred, 0, 8, 20) + _sweep(blurred, 8, 0, 20) + [blurred(0)] * 30
    shots2, _ = _run(e, again, t0=len(first) / FPS)
    assert len(shots2) == 1                                          # 벗어났다 다시 맞추면 또 찍음


def test_off_mode_measures_but_never_triggers(blurred):
    e = SmartCaptureEngine(SmartSettings(mode="off"))
    shots, q = _run(e, _sweep(blurred, 8, 0, 30) + _sweep(blurred, 0, 8, 30))
    assert shots == [] and q.focus > 0


def test_motion_blocks_usable(blurred):
    e = SmartCaptureEngine()
    a, b = blurred(0), _scene(seed=7)
    e.process(a, 0.0)
    q, _ = e.process(b, 1 / FPS)                    # 장면이 통째로 바뀜 = 크게 흔들림
    assert q.motion > SmartSettings().motion_max and not q.usable and "흔들림" in q.hint


def test_best_recent_picks_sharpest(blurred):
    e = SmartCaptureEngine()
    _run(e, [blurred(4), blurred(0), blurred(2), blurred(3)])
    best = e.best_recent(1.0)
    assert best is not None and int(best.frame[0, 0, 0]) == 1


def test_buffer_respects_memory_limit(blurred):
    e = SmartCaptureEngine(SmartSettings(buffer_mb=10, buffer_s=10))
    _run(e, [blurred(0)] * 20)                      # 1280x720x3 ≈ 2.6MB → 최대 3장
    assert len(e._buffer) <= 4 and e._buffer_bytes <= 10 * 1024 * 1024


def test_roi_limits_analysis(blurred):
    """ROI 밖이 선명해도 ROI 안이 흐리면 선명도가 낮다."""
    img = blurred(6).copy()
    img[:, :640] = blurred(0)[:, :640]              # 왼쪽 절반만 선명
    left = SmartCaptureEngine(SmartSettings(roi=(0.05, 0.2, 0.4, 0.6)))
    right = SmartCaptureEngine(SmartSettings(roi=(0.55, 0.2, 0.4, 0.6)))
    ql, _ = left.process(img, 0.0)
    qr, _ = right.process(img, 0.0)
    assert ql.focus > 2 * qr.focus


def test_normalize_roi():
    assert normalize_roi(None) is None and normalize_roi([]) is None
    assert normalize_roi((0.5, 0.5, -0.2, -0.2)) == pytest.approx((0.3, 0.3, 0.2, 0.2))
    assert normalize_roi((0.9, 0.9, 0.5, 0.5)) == pytest.approx((0.9, 0.9, 0.1, 0.1))
    assert normalize_roi((0.1, 0.1, 0.001, 0.5)) is None
    assert normalize_roi(("a", 0, 1, 1)) is None


def test_peaking_marks_sharp_not_blurry(blurred):
    sharp = peaking_mask(to_analysis_gray(blurred(0)), 50)
    soft = peaking_mask(to_analysis_gray(blurred(8)), 50)
    assert (sharp > 0).mean() > 0.01
    assert (soft > 0).mean() < (sharp > 0).mean() / 5
    flat = peaking_mask(to_analysis_gray(np.full((360, 640, 3), 80, np.uint8)), 100)
    assert not flat.any()


def test_analysis_is_fast_enough(blurred):
    """4K 프레임도 한 장 분석이 프리뷰를 따라갈 만큼 빨라야 한다 (넉넉한 상한)."""
    big = cv2.resize(blurred(0), (3840, 2160))
    e = SmartCaptureEngine()
    e.process(big, 0.0)
    t = time.perf_counter()
    for i in range(10):
        e.process(big, (i + 1) / FPS)
    assert (time.perf_counter() - t) / 10 < 0.1
