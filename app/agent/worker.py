"""에이전트 백그라운드 스레드 — 장면 인식·링버퍼·판단을 GUI 밖에서 돌리고 결과를 Qt 신호로 보낸다.

GUI 는 submit(frame, t, quality, eye) 로 최신 프레임만 넘긴다
(Smart Capture 워커와 같은 방식: 밀리면 건너뜀).
클립 요청(request_clip) 은 '뒤 after_s 초'가 더 쌓일 때까지 기다렸다가
먼저 후보 프레임(candidatesReady) 을 내고, 그 다음 클립 파일을 쓴다(clipReady).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

from app.agent.core import AgentCore, AgentSettings, Decision
from app.agent.ringbuffer import Candidate, FrameRingBuffer
from app.agent.scene import SceneClassifier, SceneResult

log = logging.getLogger(__name__)


@dataclass
class ClipRequest:
    t_event: float
    before_s: float
    after_s: float
    path: Optional[Path]          # None 이면 클립 파일은 안 쓰고 후보만
    k: int
    tag: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class ClipResult:
    request: ClipRequest
    path: Optional[Path]
    frames_written: int
    candidates: List[Candidate]
    duration_ms: int
    thumb: Optional[np.ndarray] = None


class AgentWorker(QObject):
    sceneUpdated = Signal(object)       # SceneResult
    decided = Signal(object)            # list[Decision]
    candidatesReady = Signal(object)    # ClipResult (후보 프레임만, 클립 파일 전)
    clipReady = Signal(object)          # ClipResult (클립 파일 저장 뒤)

    def __init__(self, settings: Optional[AgentSettings] = None, model_path: Optional[str] = None,
                 buffer_s: float = 8.0, scene_fps: float = 8.0, buffer_fps: float = 15.0):
        super().__init__()
        self.core = AgentCore(settings)
        self.buffer = FrameRingBuffer(seconds=buffer_s, max_fps=buffer_fps)
        self.classifier = SceneClassifier(model_path)
        self._scene_dt = 1.0 / max(1.0, scene_fps)
        self._last_scene_t = -1e9
        self._last_scene: SceneResult = SceneResult()
        self._cond = threading.Condition()
        self._pending: Optional[tuple] = None
        self._clips: List[ClipRequest] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.live = True

    # ---- 수명 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="Agent", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._running = False
            self._pending = None
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    # ---- GUI 에서 호출 ----
    def submit(self, frame: np.ndarray, t: float, quality, eye: str) -> None:
        with self._cond:
            self._pending = (frame, t, quality, eye)
            self._cond.notify()

    def request_clip(self, t_event: float, before_s: float, after_s: float, path, k: int = 4,
                     tag: str = "", **payload) -> None:
        with self._cond:
            self._clips.append(ClipRequest(t_event, before_s, after_s, Path(path) if path else None,
                                           k, tag, payload))
            self._cond.notify()

    def update_settings(self, s: AgentSettings) -> None:
        with self._lock:
            self.core.update_settings(s)

    def new_session(self) -> None:
        with self._lock:
            self.core.new_session(time.monotonic())

    def reset_checklist(self) -> None:
        with self._lock:
            self.core.reset_checklist()

    def note_capture(self, scene_label: str, eye: str, auto: bool = False) -> List[Decision]:
        with self._lock:
            return self.core.note_capture(scene_label, eye, time.monotonic(), auto=auto)

    def scene(self) -> SceneResult:
        return self._last_scene

    # ---- 스레드 ----
    def _loop(self) -> None:
        while True:
            with self._cond:
                while self._running and self._pending is None and not self._clips_due():
                    self._cond.wait(timeout=0.25)
                if not self._running:
                    return
                item, self._pending = self._pending, None
                due = [c for c in self._clips if self._clip_is_due(c)]
                for c in due:
                    self._clips.remove(c)
            if item is not None:
                try:
                    self._process(*item)
                except Exception:  # noqa: BLE001
                    log.exception("agent frame processing failed")
            for c in due:
                try:
                    self._finish_clip(c)
                except Exception:  # noqa: BLE001
                    log.exception("agent clip failed")

    def _clip_is_due(self, c: ClipRequest) -> bool:
        return time.monotonic() >= c.t_event + c.after_s + 0.05

    def _clips_due(self) -> bool:
        return any(self._clip_is_due(c) for c in self._clips)

    def _process(self, frame: np.ndarray, t: float, quality, eye: str) -> None:
        score = float(quality.focus_pct) if quality is not None else 0.0
        usable = bool(quality.usable) if quality is not None else True
        if t - self._last_scene_t >= self._scene_dt:
            self._last_scene_t = t
            self._last_scene = self.classifier.classify(frame)
            self.sceneUpdated.emit(self._last_scene)
        self.buffer.add(frame, t, score=score, usable=usable, scene=self._last_scene.label)
        with self._lock:
            decisions = self.core.decide(quality, self._last_scene, t, eye, live=self.live)
        if decisions:
            self.decided.emit(decisions)

    def _finish_clip(self, c: ClipRequest) -> None:
        t0, t1 = c.t_event - c.before_s, c.t_event + c.after_s
        ents = self.buffer.entries(t0, t1)
        dur = int((ents[-1].t - ents[0].t) * 1000) if len(ents) > 1 else 0
        cands = self.buffer.top_k(c.k, t0, t1) if c.k > 0 else []
        thumb = cands[0].frame if cands else (self.buffer.decode(ents[0]) if ents else None)
        if cands:
            self.candidatesReady.emit(ClipResult(request=c, path=None, frames_written=0,
                                                 candidates=cands, duration_ms=dur, thumb=thumb))
        if c.path is None:
            return
        n = self.buffer.write_clip(c.path, t0, t1)
        self.clipReady.emit(ClipResult(request=c, path=c.path if n > 0 else None, frames_written=n,
                                       candidates=[], duration_ms=dur, thumb=thumb))
