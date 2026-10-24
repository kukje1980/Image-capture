"""백그라운드 스레드에서 프레임을 읽어 Qt 신호로 전달하는 워커."""
from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from app.capture.sources import FrameSource

log = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILS = 50


class CameraWorker(QObject):
    """QThread로 moveToThread 하여 run()을 실행한다.

    프레임은 항상 .copy()해서 emit한다 (OpenCV는 내부 버퍼를 재사용하므로,
    복사하지 않으면 GUI 스레드가 덮어써진 버퍼를 읽을 수 있다).
    위젯은 절대 건드리지 않는다 — numpy/문자열 신호만 emit.
    """

    frame_ready = Signal(np.ndarray)
    opened = Signal(int, int, float)   # width, height, fps
    error = Signal(str)
    stopped = Signal()

    def __init__(self, source_factory: Callable[[], FrameSource]):
        super().__init__()
        self._factory = source_factory
        self._source: FrameSource | None = None
        self._running = False
        self._stop_requested = False      # 여는 도중(수 초)에 온 정지 요청도 잊지 않도록 따로 기억

    @Slot()
    def run(self) -> None:
        try:
            self._source = self._factory()
            self._source.open()
            if self._stop_requested:
                self._source.release()
                self.stopped.emit()
                return
            w, h = self._source.size
            self.opened.emit(int(w), int(h), float(self._source.fps))
        except Exception as e:  # noqa: BLE001
            log.exception("camera open failed")
            self.error.emit(str(e))
            return

        self._running = True
        fails = 0
        while self._running and not self._stop_requested:
            try:
                ok, frame = self._source.read()
            except Exception as e:  # noqa: BLE001
                log.exception("camera read failed")
                self.error.emit(str(e))
                break
            if not ok or frame is None:
                fails += 1
                if fails > _MAX_CONSECUTIVE_FAILS:
                    self.error.emit("카메라 연결이 끊어졌습니다.")
                    break
                time.sleep(0.03)
                continue
            fails = 0
            self.frame_ready.emit(frame.copy())

        try:
            if self._source is not None:
                self._source.release()
        except Exception:  # noqa: BLE001
            pass
        self.stopped.emit()

    @Slot()
    def stop(self) -> None:
        self._stop_requested = True
        self._running = False
