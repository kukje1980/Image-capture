from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from app.capture.video_recorder import VideoRecorder


def _frame(h=240, w=320):
    return np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)


def test_record_short_clip(tmp_path):
    out = tmp_path / "clip.mp4"
    rec = VideoRecorder()
    try:
        rec.start(out, fps=15.0, size=(320, 240))
    except Exception as e:  # pragma: no cover - 인코더가 전혀 없는 환경
        pytest.skip(f"사용 가능한 인코더 없음: {e}")

    for _ in range(15):
        rec.feed(_frame())
        time.sleep(0.005)
    path, count, duration = rec.stop()

    assert Path(path).exists()
    assert Path(path).stat().st_size > 0
    assert count > 0
    assert duration >= 0


def test_recording_matches_real_time(tmp_path):
    """카메라가 설정 fps 보다 느려도 영상 길이가 실제 시간과 맞아야 한다 (빨리 감기 방지)."""
    rec = VideoRecorder()
    try:
        rec.start(tmp_path / "slow.mp4", fps=30.0, size=(160, 120))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"사용 가능한 인코더 없음: {e}")
    t0 = time.time()
    while time.time() - t0 < 1.0:          # 약 10fps 로만 공급
        rec.feed(_frame(120, 160))
        time.sleep(0.1)
    _, count, duration = rec.stop()
    expected = duration / 1000 * 30
    assert abs(count - expected) <= 0.25 * expected, (count, expected)


def test_wrong_size_frames_dropped(tmp_path):
    """카메라·해상도가 바뀌어 크기가 다른 프레임은 녹화 파일에 넣지 않는다."""
    rec = VideoRecorder()
    try:
        rec.start(tmp_path / "s.mp4", fps=15.0, size=(320, 240))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"사용 가능한 인코더 없음: {e}")
    rec.feed(_frame(480, 640))
    time.sleep(0.05)
    rec.feed(_frame())
    _, count, _ = rec.stop()
    assert count >= 1


def test_writer_error_stops_cleanly(tmp_path):
    rec = VideoRecorder()
    try:
        rec.start(tmp_path / "e.mp4", fps=15.0, size=(320, 240))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"사용 가능한 인코더 없음: {e}")
    errors = []
    from PySide6.QtCore import Qt
    rec.error.connect(errors.append, Qt.ConnectionType.DirectConnection)   # 이벤트 루프 없이 바로 받기

    def boom(_):
        raise RuntimeError("disk full")
    rec._write = boom
    rec._fallback_to_cv2 = lambda: False
    rec.feed(_frame())
    for _ in range(50):
        if errors:
            break
        time.sleep(0.02)
    for _ in range(200):                     # 실패 뒤에도 큐가 막혀 stop 이 멈추지 않는다
        rec.feed(_frame())
    t = time.time()
    _, count, duration = rec.stop()
    assert errors and count == 0 and duration == 0
    assert time.time() - t < 3


def test_stop_with_full_queue_still_closes_file(tmp_path):
    """인코더가 멈춰 큐가 가득 차 종료 신호가 못 들어가도, 풀리면 남은 프레임을 쓰고 파일을 닫는다."""
    import threading

    rec = VideoRecorder()
    try:
        rec.start(tmp_path / "full.mp4", fps=30.0, size=(160, 120))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"사용 가능한 인코더 없음: {e}")
    gate = threading.Event()
    real_write = rec._write

    def slow_write(frame):
        gate.wait(5)
        real_write(frame)
    rec._write = slow_write
    rec._start_ts -= 100                      # 경과 시간 기준으로 많은 프레임이 필요하도록 → 큐가 바로 가득 찬다
    for _ in range(40):
        rec.feed(_frame(120, 160))
    assert rec._queue.full()
    t0 = time.time()
    path, count, _ = rec.stop()               # 종료 신호 put 은 2초 뒤 포기하지만 _stop_evt 는 설정됨
    assert rec.is_finalizing
    gate.set()
    assert rec.wait_finalized(15)
    assert not rec.is_finalizing and rec._writer is None
    assert Path(path).stat().st_size > 0 and rec.frame_count > 0
    assert time.time() - t0 < 14


def test_start_waits_for_previous_finalize(tmp_path):
    rec = VideoRecorder()
    try:
        rec.start(tmp_path / "a.mp4", fps=15.0, size=(160, 120))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"사용 가능한 인코더 없음: {e}")
    for _ in range(5):
        rec.feed(_frame(120, 160))
        time.sleep(0.01)
    rec.stop()
    assert rec.wait_finalized(10) and not rec.is_finalizing
    rec.start(tmp_path / "b.mp4", fps=15.0, size=(160, 120))     # 바로 다음 녹화 가능
    rec.feed(_frame(120, 160))
    path, count, _ = rec.stop()
    rec.wait_finalized(10)
    assert Path(path).name == "b.mp4" and count >= 1
