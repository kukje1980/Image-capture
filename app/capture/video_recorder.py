"""동영상 녹화기.

imageio-ffmpeg(번들 ffmpeg, H.264/yuv420p)를 우선 사용하고, 실패 시
cv2.VideoWriter(mp4v)로 폴백한다. 인코딩은 자체 스레드 + 바운디드 큐에서
수행해 GUI 스레드를 막지 않는다. 큐가 가득 차면 가장 최근 프레임을 버린다.

재생 속도가 실제 시간과 같도록, 들어오는 프레임을 실제 경과 시간 기준으로 맞춘다
(카메라가 느리거나 프레임이 버려졌으면 직전 프레임을 반복, 빠르면 건너뜀).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, Signal

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import imageio
except ImportError:
    imageio = None

log = logging.getLogger(__name__)

_QUEUE_MAX = 120
_MAX_REPEAT = 8          # 한 번에 채워 넣을 최대 반복 프레임 수 (긴 멈춤 뒤 폭주 방지)
_SENTINEL = object()


class VideoRecorder(QObject):
    finished = Signal(str, int, int)   # path, frame_count, duration_ms
    error = Signal(str)

    def __init__(self, fallback_fourcc: str = "mp4v"):
        super().__init__()
        self._fallback_fourcc = fallback_fourcc
        self._queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._writer = None
        self._backend: Optional[str] = None
        self._path: Optional[str] = None
        self._fps = 30.0
        self._size = (0, 0)
        self._count = 0
        self._queued = 0
        self._start_ts = 0.0
        self._recording = False
        self._failed = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self, path, fps: float, size: Tuple[int, int]) -> None:
        if self._recording:
            return
        self._path = str(path)
        self._fps = float(fps) if fps and fps > 0 else 30.0
        self._size = (int(size[0]), int(size[1]))
        self._count = 0
        self._queued = 0
        self._failed = False
        self._open_writer()
        self._queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._start_ts = time.time()
        self._recording = True                   # 마지막에 켠다 — 다른 스레드의 feed() 가 준비 안 된 상태를 보지 않게
        log.info("recording started: %s (%s, %sfps, %s)",
                 self._path, self._backend, self._fps, self._size)

    def _open_writer(self) -> None:
        if imageio is not None:
            try:
                self._writer = imageio.get_writer(
                    self._path, format="FFMPEG", mode="I", fps=self._fps,
                    codec="libx264", quality=8, pixelformat="yuv420p",
                    macro_block_size=None, ffmpeg_log_level="error",
                )
                self._backend = "ffmpeg"
                return
            except Exception:  # noqa: BLE001
                log.warning("ffmpeg writer 사용 불가, cv2 폴백 시도", exc_info=True)
                self._writer = None
        if cv2 is not None:
            fourcc = cv2.VideoWriter_fourcc(*self._fallback_fourcc)
            writer = cv2.VideoWriter(self._path, fourcc, self._fps, self._size)
            if not writer.isOpened():
                raise RuntimeError("동영상 writer를 열 수 없습니다 (코덱 문제).")
            self._writer = writer
            self._backend = "cv2"
            return
        raise RuntimeError("사용 가능한 동영상 인코더가 없습니다 (imageio/opencv 필요).")

    def feed(self, frame: np.ndarray) -> None:
        if not self._recording or self._queue is None or self._failed:
            return
        h, w = frame.shape[:2]
        if (w, h) != self._size:                 # 카메라·해상도가 바뀐 프레임은 이 파일에 넣지 않는다
            return
        # 실제 경과 시간에 해당하는 프레임 번호까지 채운다
        target = int((time.time() - self._start_ts) * self._fps) + 1
        need = min(target - self._queued, _MAX_REPEAT)
        for _ in range(need):
            try:
                self._queue.put_nowait(frame)
                self._queued += 1
            except queue.Full:
                break  # 인코더가 못 따라오면 드롭 → 다음 프레임에서 반복으로 메움

    def _worker(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is _SENTINEL:
                    break
                if self._failed:
                    continue                     # 실패 뒤에는 남은 프레임을 버리고 종료 신호만 기다린다
                try:
                    self._write(item)
                except Exception as e:  # noqa: BLE001
                    # imageio 는 첫 프레임에서 ffmpeg 를 띄우므로 실패가 여기서 드러난다 → cv2 로 한 번 폴백
                    if self._backend == "ffmpeg" and self._count == 0 and self._fallback_to_cv2():
                        try:
                            self._write(item)
                            continue
                        except Exception:  # noqa: BLE001
                            pass
                    log.exception("frame write failed")
                    self._failed = True
                    self.error.emit(str(e))
        finally:
            self._close_writer()                 # 쓰는 스레드가 직접 닫는다 (쓰는 중에 다른 스레드가 닫지 않게)

    def _close_writer(self) -> None:
        w, self._writer = self._writer, None
        if w is None:
            return
        try:
            if self._backend == "ffmpeg":
                w.close()
            else:
                w.release()
        except Exception:  # noqa: BLE001
            log.warning("writer close failed", exc_info=True)

    def _fallback_to_cv2(self) -> bool:
        if cv2 is None:
            return False
        try:
            self._writer.close()
        except Exception:  # noqa: BLE001
            pass
        fourcc = cv2.VideoWriter_fourcc(*self._fallback_fourcc)
        writer = cv2.VideoWriter(self._path, fourcc, self._fps, self._size)
        if not writer.isOpened():
            return False
        log.warning("ffmpeg 쓰기 실패 → cv2(%s) 로 녹화 계속", self._fallback_fourcc)
        self._writer, self._backend = writer, "cv2"
        return True

    def _write(self, frame: np.ndarray) -> None:
        if self._backend == "ffmpeg":
            if cv2 is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            else:
                rgb = np.ascontiguousarray(frame[..., ::-1])
            self._writer.append_data(rgb)
        else:
            self._writer.write(frame)
        self._count += 1

    def stop(self) -> Tuple[str, int, int]:
        if not self._recording:
            return (self._path or "", 0, 0)
        self._recording = False
        stop_ts = time.time()                    # 길이는 멈춘 순간 기준 (인코더가 남은 프레임을 쓰는 시간은 빼고)
        try:
            self._queue.put(_SENTINEL, timeout=2)
        except Exception:  # noqa: BLE001
            pass
        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                log.warning("인코더가 아직 쓰는 중 — 끝나면 스레드가 파일을 닫습니다")
        else:
            self._close_writer()
        duration_ms = int((stop_ts - self._start_ts) * 1000)
        if self._failed:                         # 실패한 녹화는 실제로 쓴 길이만큼만
            duration_ms = int(self._count / self._fps * 1000)
        path, count = self._path or "", self._count
        log.info("recording stopped: %s frames=%s duration=%sms", path, count, duration_ms)
        self.finished.emit(path, count, duration_ms)
        return (path, count, duration_ms)
