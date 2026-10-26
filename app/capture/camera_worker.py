"""백그라운드 스레드에서 프레임을 읽어 Qt 신호로 전달하는 워커."""
from __future__ import annotations

import logging
import threading
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
    property_set = Signal(str, bool, float)   # 속성, 적용 여부, 적용 후 값 (카메라 속성 창)

    def __init__(self, source_factory: Callable[[], FrameSource], initial_props: dict | None = None):
        super().__init__()
        self._factory = source_factory
        self._source: FrameSource | None = None
        self._running = False
        self._stop_requested = False      # 여는 도중(수 초)에 온 정지 요청도 잊지 않도록 따로 기억
        # 카메라 속성 요청 — GUI 스레드에서 넣고 읽기 루프에서 적용 (OpenCV 장치는 한 스레드에서만 다룸)
        self._prop_lock = threading.Lock()
        self._pending_props: dict[str, float] = dict(initial_props or {})

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
            self._apply_pending_props()
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

    def request_property(self, key: str, value: float) -> None:
        """스레드 안전: 다음 프레임을 읽기 전에 장치에 적용된다."""
        with self._prop_lock:
            self._pending_props[key] = float(value)

    def property_value(self, key: str):
        src = self._source
        return src.get_property(key) if src is not None else None

    def _apply_pending_props(self) -> None:
        if not self._pending_props or self._source is None:
            return
        with self._prop_lock:
            pending, self._pending_props = self._pending_props, {}
        # 자동 노출·자동 WB 를 먼저 바꿔야 수동 값이 먹힌다
        for key in sorted(pending, key=lambda k: 0 if k.startswith("auto") else 1):
            ok = False
            try:
                ok = self._source.set_property(key, pending[key])
            except Exception:  # noqa: BLE001
                log.warning("camera property %s failed", key, exc_info=True)
            now = self._source.get_property(key)
            self.property_set.emit(key, bool(ok), float(now if now is not None else pending[key]))

    @Slot()
    def stop(self) -> None:
        self._stop_requested = True
        self._running = False
