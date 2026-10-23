"""프레임 변환/썸네일/장치 열거 유틸."""
from __future__ import annotations

import sys
from typing import List

import numpy as np
from PySide6.QtGui import QImage

try:
    import cv2
except ImportError:
    cv2 = None


def bgr_to_qimage(frame: np.ndarray) -> QImage:
    """OpenCV BGR(numpy) → QImage(RGB888).

    numpy 버퍼가 GC된 뒤에도 안전하도록 .copy()로 메모리를 분리한다.
    """
    if cv2 is not None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    else:
        rgb = np.ascontiguousarray(frame[..., ::-1])
    h, w = rgb.shape[:2]
    ch = rgb.shape[2] if rgb.ndim == 3 else 1
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return qimg.copy()


def make_thumbnail(frame: np.ndarray, max_side: int = 120) -> np.ndarray:
    h, w = frame.shape[:2]
    longest = max(h, w)
    if longest <= max_side or longest == 0:
        return frame.copy()
    scale = max_side / longest
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    if cv2 is not None:
        return cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    # cv2 없을 때 단순 보폭 샘플링
    ys = (np.linspace(0, h - 1, nh)).astype(int)
    xs = (np.linspace(0, w - 1, nw)).astype(int)
    return frame[ys][:, xs].copy()


def capture_api(backend: str = "dshow", platform: str | None = None) -> int:
    """설정의 camera_backend → OpenCV 캡처 API 상수.

    dshow 는 Windows 전용이므로 다른 OS에서는 그 OS의 기본 백엔드로 바꾼다
    (macOS = AVFoundation). 'avfoundation'·'any' 를 직접 지정할 수도 있다.
    """
    if cv2 is None:
        return 0
    plat = platform or sys.platform
    b = (backend or "dshow").lower()
    if b == "any":
        return cv2.CAP_ANY
    if b == "avfoundation" or (plat == "darwin" and b == "dshow"):
        return cv2.CAP_AVFOUNDATION
    if b == "dshow" and plat.startswith("win"):
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def enumerate_devices(max_probe: int = 8, backend: str = "dshow") -> List[int]:
    devices: List[int] = []
    if cv2 is None:
        return devices
    flag = capture_api(backend)
    for i in range(max_probe):
        cap = cv2.VideoCapture(i, flag)
        try:
            if cap is not None and cap.isOpened():
                devices.append(i)
        finally:
            if cap is not None:
                cap.release()
    return devices
