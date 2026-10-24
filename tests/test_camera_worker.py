"""카메라 워커: 장치를 여는 도중에 온 정지 요청도 지켜져야 한다 (안 그러면 스레드가 영원히 돈다)."""
from __future__ import annotations

import threading
import time

import numpy as np

from app.capture.camera_worker import CameraWorker


class _SlowSource:
    size = (64, 48)
    fps = 30.0

    def __init__(self):
        self.released = False

    def open(self):
        time.sleep(0.3)                     # DirectShow 장치 열기처럼 느림

    def read(self):
        time.sleep(0.01)
        return True, np.zeros((48, 64, 3), np.uint8)

    def release(self):
        self.released = True


def test_stop_during_open_is_honoured():
    src = _SlowSource()
    w = CameraWorker(lambda: src)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    time.sleep(0.05)
    w.stop()                                # 여는 중에 정지
    t.join(timeout=2)
    assert not t.is_alive() and src.released
