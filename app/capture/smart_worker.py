"""Smart Capture 분석 스레드 — 실시간 프리뷰를 막지 않고 백그라운드에서 프레임을 분석한다.

GUI 스레드는 submit() 으로 최신 프레임만 넘긴다(대기 중인 프레임이 있으면 덮어씀). 분석이 프레임
속도를 못 따라가면 중간 프레임은 건너뛰므로 화면이 끊기지 않는다 (PC 성능에 맞춰 분석 속도가 자동 조절).
결과는 Qt 신호로 보낸다 — 수신 객체가 GUI 스레드에 있으므로 큐 연결로 GUI 스레드에서 처리된다.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

from app.capture.smart_capture import (
    BestShot,
    FrameQuality,
    SmartCaptureEngine,
    SmartSettings,
    peaking_mask,
)

log = logging.getLogger(__name__)

PEAKING_COLORS = {"red": (255, 59, 48), "green": (52, 211, 98), "yellow": (255, 214, 10),
                  "cyan": (64, 210, 255)}          # RGB


@dataclass
class Analysis:
    quality: FrameQuality
    peaking: Optional[np.ndarray] = None    # (h, w, 4) BGRA 오버레이 (분석 해상도) — 꺼져 있으면 None


def peaking_overlay(gray: np.ndarray, sensitivity: int, color: str) -> np.ndarray:
    """피킹 마스크 → 반투명 BGRA 오버레이 (QImage Format_ARGB32 와 같은 바이트 순서)."""
    mask = peaking_mask(gray, sensitivity)
    r, g, b = PEAKING_COLORS.get(color, PEAKING_COLORS["red"])
    out = np.zeros(gray.shape + (4,), np.uint8)
    on = mask > 0
    out[on] = (b, g, r, 230)
    return out


class SmartCaptureWorker(QObject):
    analyzed = Signal(object)        # Analysis
    bestShot = Signal(object)        # BestShot (자동 정지/자동 저장 순간)

    def __init__(self, settings: Optional[SmartSettings] = None, max_fps: float = 20.0):
        super().__init__()
        self._engine = SmartCaptureEngine(settings)
        self._peaking = False
        self._peaking_color = "red"
        self._min_interval = 1.0 / max(1.0, max_fps)
        self._cond = threading.Condition()
        self._pending: Optional[tuple] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()            # 엔진 접근 (분석 스레드 ↔ GUI 의 best_recent)

    # ---- 수명 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="SmartCapture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._cond:
            self._running = False
            self._pending = None
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    # ---- GUI 스레드에서 호출 ----
    def submit(self, frame: np.ndarray, t: Optional[float] = None) -> None:
        with self._cond:
            self._pending = (frame, time.monotonic() if t is None else t)
            self._cond.notify()

    def settings(self) -> SmartSettings:
        with self._lock:
            return replace(self._engine.settings)

    def update(self, settings: Optional[SmartSettings] = None, peaking: Optional[bool] = None,
               peaking_color: Optional[str] = None) -> None:
        with self._lock:
            if settings is not None:
                self._engine.update_settings(settings)
            if peaking is not None:
                self._peaking = peaking
            if peaking_color is not None:
                self._peaking_color = peaking_color

    def reset(self) -> None:
        """카메라가 바뀌면 기준·버퍼를 비운다 (다른 장면의 선명도와 섞이지 않게)."""
        with self._lock:
            self._engine.reset()

    def best_recent(self, seconds: float = 0.6) -> Optional[BestShot]:
        with self._lock:
            return self._engine.best_recent(seconds)

    # ---- 분석 스레드 ----
    def _loop(self) -> None:
        last = 0.0
        while True:
            with self._cond:
                while self._running and self._pending is None:
                    self._cond.wait(0.5)
                if not self._running:
                    return
                frame, t = self._pending
                self._pending = None
            try:
                self._analyze(frame, t)
            except Exception:  # noqa: BLE001 — 분석 오류로 촬영 화면이 멈추면 안 된다
                log.exception("smart capture analysis failed")
            # 너무 자주 분석하지 않게 (CPU 를 녹화·화면 그리기에 남겨 둔다)
            wait = self._min_interval - (time.monotonic() - last)
            last = time.monotonic()
            if wait > 0:
                time.sleep(wait)

    def _analyze(self, frame: np.ndarray, t: float) -> None:
        with self._lock:
            quality, shot = self._engine.process(frame, t)
            peaking, color = self._peaking, self._peaking_color
            sens = self._engine.settings.peaking_sensitivity
            gray = self._engine.last_gray
        overlay = peaking_overlay(gray, sens, color) if peaking and gray is not None else None
        self.analyzed.emit(Analysis(quality=quality, peaking=overlay))
        if shot is not None:
            self.bestShot.emit(shot)

