"""카메라 스레드 + 녹화 + 카메라 속성을 한 곳에서 관리 (Explorer 판 창이 사용).

    cam = CameraController(config)
    cam.frame.connect(view.set_frame)
    cam.start()
    cam.set_property("gain", 20)        # 장치에 바로 적용 + config.camera_props 에 기억
    cam.start_recording(path)            # 이후 들어오는 프레임을 mp4 로
    count, duration_ms = cam.stop_recording()
"""
from __future__ import annotations

import logging
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from app.capture import camera_props
from app.capture.camera_worker import CameraWorker
from app.capture.frame_utils import device_names
from app.capture.sources import DeviceSource, FileSource, SyntheticSource
from app.capture.video_recorder import VideoRecorder

log = logging.getLogger(__name__)


class CameraController(QObject):
    frame = Signal(np.ndarray)
    opened = Signal(int, int, float)
    error = Signal(str)
    property_set = Signal(str, bool, float)
    recorder_error = Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.thread: QThread | None = None
        self.worker: CameraWorker | None = None
        self.last_frame = None
        self.frame_size = (config.capture_width, config.capture_height)
        self._times = deque(maxlen=60)
        self.recorder = VideoRecorder(fallback_fourcc=config.video_fallback_fourcc)
        self.recorder.error.connect(self.recorder_error)
        self._rec_frames = 0
        self.first_rec_frame = None
        self.rec_started = 0.0

    # ---- 장치 ----
    def _factory(self):
        cfg = self.config
        mode = cfg.source_mode

        def make():
            if mode == "synthetic":
                return SyntheticSource(cfg.capture_width or 1280, cfg.capture_height or 720, 30.0)
            if mode == "file":
                return FileSource(cfg.test_file_path, loop=True)
            return DeviceSource(cfg.camera_index, cfg.camera_backend, cfg.capture_width, cfg.capture_height)

        return make

    def _resolve_device(self) -> None:
        """저장한 카메라 이름으로 번호를 다시 찾는다 (USB 순서가 바뀌어도 같은 카메라)."""
        cfg = self.config
        if cfg.source_mode != "device" or not cfg.camera_name:
            return
        names = device_names()
        if cfg.camera_name in names:
            cfg.camera_index = names.index(cfg.camera_name)

    def start(self) -> None:
        self._resolve_device()
        self.thread = QThread(self)
        self.worker = CameraWorker(self._factory(), camera_props.sanitize(self.config.camera_props))
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.opened.connect(self._on_opened)
        self.worker.error.connect(self.error)
        self.worker.property_set.connect(self.property_set)
        self.worker.stopped.connect(self.thread.quit)
        self.thread.start()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            for sig, slot in ((self.worker.frame_ready, self._on_frame),
                              (self.worker.opened, self._on_opened),
                              (self.worker.error, self.error),
                              (self.worker.property_set, self.property_set)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        if self.thread is not None:
            self.thread.quit()
            if not self.thread.wait(3000):
                log.warning("camera thread did not stop within timeout")
        self.worker = None
        self.thread = None

    def restart(self) -> None:
        self.stop()
        self.last_frame = None
        self.start()

    # ---- 속성 ----
    def set_property(self, key: str, value: float, remember: bool = True) -> None:
        value = camera_props.clamp(key, value)
        if self.worker is not None:
            self.worker.request_property(key, value)
        if remember:
            props = dict(self.config.camera_props or {})
            props[key] = value
            self.config.camera_props = props

    def property_value(self, key: str):
        return self.worker.property_value(key) if self.worker is not None else None

    # ---- 프레임 ----
    def _on_opened(self, w: int, h: int, fps: float) -> None:
        self.frame_size = (w, h)
        self.opened.emit(w, h, fps)

    def _on_frame(self, frame) -> None:
        self.last_frame = frame
        self._times.append(time.monotonic())
        if self.recorder.is_recording:
            self.recorder.feed(frame)
            self._rec_frames += 1
            if self.first_rec_frame is None:
                self.first_rec_frame = frame
        self.frame.emit(frame)

    def estimate_fps(self) -> float:
        if len(self._times) < 2:
            return 30.0
        span = self._times[-1] - self._times[0]
        if span <= 0:
            return 30.0
        return max(5.0, min(60.0, (len(self._times) - 1) / span))

    # ---- 녹화 ----
    @property
    def recording(self) -> bool:
        return self.recorder.is_recording

    def start_recording(self, path) -> None:
        size = self.frame_size
        if self.last_frame is not None:
            size = (self.last_frame.shape[1], self.last_frame.shape[0])
        self.first_rec_frame = None
        self._rec_frames = 0
        self.recorder.start(path, self.estimate_fps(), size, quality=self.config.video_quality)
        self.rec_started = time.monotonic()

    def stop_recording(self) -> tuple[int, int]:
        """(기록된 프레임 수, 길이 ms)."""
        _, count, duration = self.recorder.stop()
        self.rec_started = 0.0
        return count, duration
