"""동영상 녹화기.

imageio-ffmpeg(번들 ffmpeg, H.264/yuv420p)를 우선 사용하고, 실패 시
cv2.VideoWriter(mp4v)로 폴백한다. 인코딩은 자체 스레드 + 바운디드 큐에서
수행해 GUI 스레드를 막지 않는다. 큐가 가득 차면 가장 최근 프레임을 버린다.

재생 속도가 실제 시간과 같도록, 들어오는 프레임을 실제 경과 시간 기준으로 맞춘다
(카메라가 느리거나 프레임이 버려졌으면 직전 프레임을 반복, 빠르면 건너뜀).
경과 시간은 time.monotonic() 으로 잰다 — 녹화 중 윈도우 시간 동기화로 시계가 바뀌어도 길이가 틀어지지 않는다.

stop() 은 인코더가 늦어도 무한정 기다리지 않는다. 그때는 인코더 스레드가 남은 프레임을 다 쓰고 직접 파일을
닫는다(is_finalizing). 마무리가 끝나기 전에는 새 녹화를 시작하지 않는다 (두 파일이 서로 섞이지 않게).
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
_STOP_WAIT = 10.0        # stop() 이 인코더 마무리를 기다리는 최대 시간 (그 뒤엔 백그라운드에서 마무리)
_SENTINEL = object()


class VideoRecorder(QObject):
    finished = Signal(str, int, int)   # path, frame_count, duration_ms — 파일을 다 닫은 뒤 (인코더 스레드에서)
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
        self._stop_ts = 0.0
        self._recording = False
        self._failed = False
        self._stopping = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_finalizing(self) -> bool:
        """멈췄지만 인코더가 아직 남은 프레임을 쓰고 파일을 닫는 중."""
        return not self._recording and self._thread is not None and self._thread.is_alive()

    def wait_finalized(self, timeout: Optional[float] = None) -> bool:
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        return not self.is_finalizing

    def result(self) -> Tuple[str, int, int]:
        """(경로, 기록한 프레임 수, 길이 ms) — 마무리가 끝난 뒤에 확정값."""
        duration_ms = int(max(0.0, self._stop_ts - self._start_ts) * 1000)
        if self._failed:                         # 실패한 녹화는 실제로 쓴 길이만큼만
            duration_ms = int(self._count / self._fps * 1000)
        return (self._path or "", self._count, duration_ms)

    def start(self, path, fps: float, size: Tuple[int, int]) -> None:
        if self._recording:
            return
        if self.is_finalizing:
            raise RuntimeError("이전 녹화를 아직 저장하는 중입니다. 잠시 후 다시 시작하세요.")
        self._path = str(path)
        self._fps = float(fps) if fps and fps > 0 else 30.0
        self._size = (int(size[0]), int(size[1]))
        self._count = 0
        self._queued = 0
        self._failed = False
        self._stopping = threading.Event()
        self._open_writer()
        self._queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._recording = True
        self._start_ts = self._stop_ts = time.monotonic()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
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
        target = int((time.monotonic() - self._start_ts) * self._fps) + 1
        need = min(target - self._queued, _MAX_REPEAT)
        for _ in range(need):
            try:
                self._queue.put_nowait(frame)
                self._queued += 1
            except queue.Full:
                break  # 인코더가 못 따라오면 드롭 → 다음 프레임에서 반복으로 메움

    def _worker(self) -> None:
        q, stopping = self._queue, self._stopping
        try:
            while True:
                try:
                    item = q.get(timeout=0.2)
                except queue.Empty:
                    if stopping.is_set():            # 종료 표시를 큐에 못 넣었어도(가득 참) 다 쓰면 끝낸다
                        break
                    continue
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
            self.finished.emit(*self.result())

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
        self._stop_ts = time.monotonic()         # 길이는 멈춘 순간 기준 (인코더가 남은 프레임을 쓰는 시간은 빼고)
        self._stopping.set()
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass                                 # 인코더가 큐를 다 비우면 _stopping 을 보고 스스로 끝낸다
        if self._thread is not None:
            self._thread.join(timeout=_STOP_WAIT)
            if self._thread.is_alive():
                log.warning("인코더가 아직 쓰는 중 — 끝나면 스레드가 파일을 닫습니다")
        else:
            self._close_writer()
        path, count, duration_ms = self.result()
        log.info("recording stopped: %s frames=%s duration=%sms", path, count, duration_ms)
        return (path, count, duration_ms)
