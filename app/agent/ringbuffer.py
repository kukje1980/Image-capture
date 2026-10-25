"""프레임 링버퍼 — 최근 N초를 JPEG 로 메모리에 두고,
촬영 순간의 전후 클립과 품질 상위 프레임을 꺼낸다.

1080p BGR 원본을 그대로 두면 초당 180MB 가 들어 몇 초 만에 메모리가 바닥나므로
JPEG(품질 90, 프레임당 200~400KB) 로 보관한다. 8초 × 15fps ≈ 40MB. 꺼낼 때 디코딩한다.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Entry:
    t: float
    jpeg: bytes
    score: float          # 품질 점수 (0~100, 없으면 0)
    usable: bool
    scene: str
    w: int
    h: int


@dataclass
class Candidate:
    t: float
    score: float
    frame: np.ndarray
    scene: str


class FrameRingBuffer:
    def __init__(self, seconds: float = 8.0, max_fps: float = 15.0, jpeg_quality: int = 90):
        self.seconds = float(seconds)
        self._min_dt = 1.0 / max(1.0, max_fps)
        self._q = int(jpeg_quality)
        self._buf: deque[Entry] = deque()
        self._lock = threading.Lock()
        self._last_t = -1e9
        self.bytes = 0

    def add(self, frame: np.ndarray, t: float, score: float = 0.0, usable: bool = True,
            scene: str = "") -> bool:
        if t - self._last_t < self._min_dt:
            return False
        ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._q])
        if not ok:
            return False
        e = Entry(t=t, jpeg=enc.tobytes(), score=float(score), usable=bool(usable), scene=scene,
                  w=frame.shape[1], h=frame.shape[0])
        with self._lock:
            self._buf.append(e)
            self.bytes += len(e.jpeg)
            while self._buf and t - self._buf[0].t > self.seconds:
                old = self._buf.popleft()
                self.bytes -= len(old.jpeg)
        self._last_t = t
        return True

    def __len__(self) -> int:
        return len(self._buf)

    def span(self) -> float:
        with self._lock:
            return (self._buf[-1].t - self._buf[0].t) if len(self._buf) > 1 else 0.0

    def entries(self, t0: float, t1: float) -> List[Entry]:
        with self._lock:
            return [e for e in self._buf if t0 <= e.t <= t1]

    @staticmethod
    def decode(e: Entry) -> np.ndarray:
        return cv2.imdecode(np.frombuffer(e.jpeg, np.uint8), cv2.IMREAD_COLOR)

    def top_k(self, k: int, t0: float, t1: float, min_gap_s: float = 0.25) -> List[Candidate]:
        """구간 안에서 점수 높은 순으로 k 장.

        서로 min_gap_s 이상 떨어진 프레임만 고른다 (같은 순간 중복 방지).
        """
        ents = [e for e in self.entries(t0, t1) if e.usable]
        ents.sort(key=lambda e: e.score, reverse=True)
        out: List[Candidate] = []
        for e in ents:
            if any(abs(e.t - c.t) < min_gap_s for c in out):
                continue
            out.append(Candidate(t=e.t, score=e.score, frame=self.decode(e), scene=e.scene))
            if len(out) >= k:
                break
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def write_clip(self, path, t0: float, t1: float, fps: Optional[float] = None) -> int:
        """구간의 프레임을 mp4 로 쓴다. 기록한 프레임 수를 돌려준다 (0 이면 파일을 만들지 않음)."""
        ents = self.entries(t0, t1)
        if len(ents) < 2:
            return 0
        if fps is None:
            fps = max(5.0, min(30.0, (len(ents) - 1) / max(1e-3, ents[-1].t - ents[0].t)))
        frames = (self.decode(e) for e in ents)
        return write_mp4(path, frames, fps, (ents[0].w, ents[0].h))


def write_mp4(path, frames, fps: float, size) -> int:
    """imageio-ffmpeg(H.264) 우선, 없으면 cv2(mp4v)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    try:
        import imageio

        w = imageio.get_writer(str(path), format="FFMPEG", mode="I", fps=fps, codec="libx264",
                               quality=7, pixelformat="yuv420p", macro_block_size=None,
                               ffmpeg_log_level="error")
        try:
            for fr in frames:
                w.append_data(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
                n += 1
        finally:
            w.close()
        return n
    except Exception:  # noqa: BLE001
        log.warning("ffmpeg 클립 저장 실패 — cv2 로 다시 시도", exc_info=True)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                         tuple(int(x) for x in size))
    try:
        for fr in frames:
            vw.write(fr)
            n += 1
    finally:
        vw.release()
    return n


def frames_to_sequence(frames: Sequence[np.ndarray]):
    return iter(frames)
