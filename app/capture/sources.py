"""프레임 소스 추상화.

DeviceSource  : 실제 캡처 장비(UVC). Windows = DirectShow, macOS = AVFoundation.
FileSource    : 동영상 파일 반복 재생. 하드웨어 없는 개발용.
SyntheticSource: numpy로 합성 프레임 생성. 의존성 없이 CI/리눅스 개발용.
"""
from __future__ import annotations

import abc
import sys
import time
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # 테스트 일부는 cv2 없이도 동작
    cv2 = None

from app.capture import camera_props
from app.capture.frame_utils import capture_api


class FrameSource(abc.ABC):
    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def read(self) -> Tuple[bool, Optional[np.ndarray]]: ...

    @abc.abstractmethod
    def release(self) -> None: ...

    @property
    @abc.abstractmethod
    def size(self) -> Tuple[int, int]: ...  # (width, height)

    @property
    @abc.abstractmethod
    def fps(self) -> float: ...

    # 카메라 속성 (app/capture/camera_props.py) — 지원하지 않는 소스는 False / None
    def set_property(self, key: str, value: float) -> bool:
        return False

    def get_property(self, key: str) -> Optional[float]:
        return None


class DeviceSource(FrameSource):
    def __init__(self, index: int = 0, backend: str = "dshow",
                 width: int = 1920, height: int = 1080):
        self.index = index
        self.backend = backend
        self.width = width
        self.height = height
        self._cap = None
        self._size = (width, height)
        self._fps = 30.0

    def open(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV(cv2)가 설치되어 있지 않습니다.")
        cap = cv2.VideoCapture(self.index, capture_api(self.backend))
        if not cap.isOpened():
            hint = (" macOS: 시스템 설정 > 개인정보 보호 및 보안 > 카메라에서 이 앱(또는 터미널)을 허용하세요."
                    if sys.platform == "darwin" else "")
            raise RuntimeError(f"카메라 장치({self.index})를 열 수 없습니다.{hint}")
        # UVC에서 더 높은 FPS를 위해 MJPG 시도 (실패해도 무시)
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.width
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.height
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if 1 < fps <= 120 else 30.0
        self._size = (w, h)
        self._cap = cap

    def read(self):
        if self._cap is None:
            return False, None
        return self._cap.read()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def set_property(self, key: str, value: float) -> bool:
        pid = camera_props.cv2_id(key)
        if self._cap is None or pid is None:
            return False
        try:
            return bool(self._cap.set(pid, camera_props.device_value(key, value)))
        except Exception:  # noqa: BLE001
            return False

    def get_property(self, key: str) -> Optional[float]:
        pid = camera_props.cv2_id(key)
        if self._cap is None or pid is None:
            return None
        try:
            v = float(self._cap.get(pid))
        except Exception:  # noqa: BLE001
            return None
        if key == "auto_exposure":
            return 1.0 if v > 0.5 else 0.0
        return v

    @property
    def size(self):
        return self._size

    @property
    def fps(self):
        return self._fps


class FileSource(FrameSource):
    def __init__(self, path: str, loop: bool = True):
        self.path = path
        self.loop = loop
        self._cap = None
        self._size = (0, 0)
        self._fps = 30.0

    def open(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV(cv2)가 설치되어 있지 않습니다.")
        if not self.path:
            raise RuntimeError("테스트 파일 경로가 비어 있습니다.")
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise RuntimeError(f"파일을 열 수 없습니다: {self.path}")
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if 1 < fps <= 120 else 30.0
        self._size = (w, h)
        self._cap = cap
        self._frame_interval = 1.0 / self._fps
        self._last = 0.0

    def read(self):
        if self._cap is None:
            return False, None
        # 파일은 실제 재생 속도에 맞춰 약간 지연
        now = time.time()
        wait = self._frame_interval - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        ok, frame = self._cap.read()
        if not ok and self.loop:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        return ok, frame

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def size(self):
        return self._size

    @property
    def fps(self):
        return self._fps


class SyntheticSource(FrameSource):
    """움직이는 그라데이션 + 타임스탬프 + 원을 그려주는 합성 소스."""

    def __init__(self, width: int = 1280, height: int = 720, fps: float = 30.0):
        self._w = int(width)
        self._h = int(height)
        self._fps = float(fps)
        self._n = 0
        self._last = 0.0
        self._props: dict[str, float] = {}

    def open(self) -> None:
        self._n = 0
        self._last = 0.0

    _EMULATED = ("brightness", "gain", "contrast")

    def set_property(self, key: str, value: float) -> bool:
        if key not in self._EMULATED:
            return False
        self._props[key] = float(value)
        return True

    def get_property(self, key: str) -> Optional[float]:
        return self._props.get(key, camera_props.BY_KEY[key].default) if key in self._EMULATED else None

    def read(self):
        target = 1.0 / self._fps
        now = time.time()
        wait = target - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        frame = self._render(self._n)
        self._n += 1
        if self._props:
            gain = 1.0 + self._props.get("gain", 0.0) / 50.0
            contrast = self._props.get("contrast", 50.0) / 50.0
            bright = self._props.get("brightness", 0.0)
            f = (frame.astype(np.float32) - 127.5) * contrast * gain + 127.5 + bright
            frame = np.clip(f, 0, 255).astype(np.uint8)
        return True, frame

    def _render(self, n: int) -> np.ndarray:
        w, h = self._w, self._h
        row = np.linspace(0, 255, w, dtype=np.int16)
        grad = np.tile(row, (h, 1))
        shift = (n * 2) % 256
        b = ((grad + shift) % 256).astype(np.uint8)
        g = ((grad + shift * 2) % 256).astype(np.uint8)
        r = np.full((h, w), 128, dtype=np.uint8)
        frame = np.dstack([b, g, r])
        if cv2 is not None:
            txt = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, f"SYNTHETIC {txt}  #{n}", (30, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
            cx = int(w / 2 + (w / 3) * np.sin(n / 20.0))
            cv2.circle(frame, (cx, int(h / 2)), 40, (0, 0, 255), -1)
        return frame

    def release(self) -> None:
        pass

    @property
    def size(self):
        return (self._w, self._h)

    @property
    def fps(self):
        return self._fps
