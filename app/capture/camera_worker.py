"""백그라운드 스레드에서 프레임을 읽어 Qt 신호로 전달하는 워커.

GUI 가 느려도 프레임이 이벤트 큐에 쌓이지 않도록(메모리 폭증·지연 누적 방지)
'한 장만 대기' 방식으로 보낸다: GUI 가 직전 프레임을 다 처리했다고 알리기(frame_done)
전에는 새 프레임을 보내지 않고 버린다. 녹화처럼 모든 프레임이 필요한 소비자는
sink 콜백으로 워커 스레드에서 직접 받는다.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from app.capture.sources import FrameSource

log = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILS = 50
_ACK_TIMEOUT = 1.0          # GUI 가 이 시간 안에 frame_done 을 안 부르면 막힌 것으로 보고 다시 보낸다


class CameraWorker(QObject):
    """QThread로 moveToThread 하여 run()을 실행한다.

    프레임은 항상 .copy()해서 내보낸다 (OpenCV는 내부 버퍼를 재사용하므로,
    복사하지 않으면 GUI 스레드가 덮어써진 버퍼를 읽을 수 있다).
    위젯은 절대 건드리지 않는다 — numpy/문자열 신호만 emit.
    """

    frame_ready = Signal(object)        # np.ndarray (BGR) — GUI 표시용, 한 장만 대기
    opened = Signal(int, int, float)    # width, height, fps
    error = Signal(str)
    stopped = Signal()

    def __init__(self, source_factory: Callable[[], FrameSource],
                 sink: Optional[Callable[[np.ndarray], None]] = None):
        super().__init__()
        self._factory = source_factory
        self._sink = sink                 # 모든 프레임을 받는 콜백 (녹화기). 워커 스레드에서 호출됨
        self._source: FrameSource | None = None
        self._running = False
        self._stop_requested = False      # 여는 도중(수 초)에 온 정지 요청도 잊지 않도록 따로 기억
        self._lock = threading.Lock()
        self._pending = False             # GUI 가 아직 처리하지 않은 프레임이 있음
        self._pending_since = 0.0
        self.dropped = 0                  # GUI 가 바빠서 표시를 건너뛴 프레임 수 (통계)
        self.frames = 0

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
            self.stopped.emit()
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
            frame = frame.copy()
            self.frames += 1
            if self._sink is not None:
                try:
                    self._sink(frame)
                except Exception:  # noqa: BLE001
                    log.exception("frame sink failed")
            self._offer(frame)

        try:
            if self._source is not None:
                self._source.release()
        except Exception:  # noqa: BLE001
            pass
        self.stopped.emit()

    def _offer(self, frame: np.ndarray) -> None:
        """GUI 에 프레임을 한 장만 대기시킨다. 직전 프레임이 아직 처리 중이면 버린다."""
        now = time.monotonic()
        with self._lock:
            if self._pending and now - self._pending_since < _ACK_TIMEOUT:
                self.dropped += 1
                return
            self._pending = True
            self._pending_since = now
        self.frame_ready.emit(frame)

    @Slot()
    def frame_done(self) -> None:
        """GUI 가 frame_ready 로 받은 프레임을 다 처리했을 때 호출 (다음 프레임 허용)."""
        with self._lock:
            self._pending = False

    @Slot()
    def stop(self) -> None:
        self._stop_requested = True
        self._running = False
