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


class _FastSource:
    size = (32, 24)
    fps = 1000.0

    def __init__(self, n=200):
        self.n = n
        self.i = 0

    def open(self):
        pass

    def read(self):
        if self.i >= self.n:
            time.sleep(0.01)
            return False, None
        self.i += 1
        return True, np.full((24, 32, 3), self.i % 256, np.uint8)

    def release(self):
        pass


def test_gui_backpressure_drops_frames_but_sink_gets_all():
    """GUI 가 frame_done 을 부르지 않으면 표시 프레임은 한 장만 대기(나머지는 버림), 녹화 sink 는 전부 받는다."""
    from PySide6.QtCore import Qt
    sunk, shown = [], []
    w = CameraWorker(lambda: _FastSource(200), sink=sunk.append)
    w.frame_ready.connect(shown.append, Qt.ConnectionType.DirectConnection)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    time.sleep(0.5)
    w.stop()
    t.join(timeout=3)
    assert len(sunk) == 200                      # 녹화용은 한 장도 빠지지 않는다
    assert len(shown) == 1 and w.dropped >= 190  # 화면용은 ack 가 없으니 한 장만


def test_frame_done_allows_next_frame():
    from PySide6.QtCore import Qt
    shown = []

    def on_frame(f):
        shown.append(f)
        w.frame_done()                            # GUI 가 처리를 끝냈다고 알림

    w = CameraWorker(lambda: _FastSource(50))
    w.frame_ready.connect(on_frame, Qt.ConnectionType.DirectConnection)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(timeout=3)
    w.stop()
    assert len(shown) == 50 and w.dropped == 0


def test_open_failure_emits_stopped():
    from PySide6.QtCore import Qt

    class _Bad:
        def open(self):
            raise RuntimeError("no device")

    got = {"err": None, "stopped": False}
    w = CameraWorker(lambda: _Bad())
    w.error.connect(lambda m: got.__setitem__("err", m), Qt.ConnectionType.DirectConnection)
    w.stopped.connect(lambda: got.__setitem__("stopped", True), Qt.ConnectionType.DirectConnection)
    w.run()
    assert got["err"] == "no device" and got["stopped"]
