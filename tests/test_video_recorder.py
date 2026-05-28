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
