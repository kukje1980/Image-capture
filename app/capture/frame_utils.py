"""프레임 변환/썸네일/장치 열거 유틸."""
from __future__ import annotations

import re
import subprocess
import sys
from typing import List, Optional

import numpy as np
from PySide6.QtGui import QImage, QPixmap

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


def fit_size(w: int, h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """(w, h) 를 비율을 지키며 (max_w, max_h) 안에 맞춘 크기. 더 작으면 그대로."""
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return (max(1, w), max(1, h))
    scale = min(max_w / w, max_h / h, 1.0)
    return (max(1, int(w * scale)), max(1, int(h * scale)))


def shrink_for_display(frame: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    """표시 영역보다 큰 프레임을 먼저 축소한다 (QImage 변환·QPixmap 스무스 스케일보다 훨씬 싸다).

    4K 프레임을 그대로 QImage 로 바꾸고 위젯 크기로 매 프레임 스케일하면 GUI 스레드가 밀린다.
    표시 크기로 줄인 뒤 변환하면 복사·변환량이 1/10 이하가 된다.
    """
    h, w = frame.shape[:2]
    tw, th = fit_size(w, h, max_w, max_h)
    if (tw, th) == (w, h) or cv2 is None:
        return frame
    interp = cv2.INTER_AREA if w / tw >= 2.0 else cv2.INTER_LINEAR
    return cv2.resize(frame, (tw, th), interpolation=interp)


def frame_to_pixmap(frame: np.ndarray, max_w: int, max_h: int) -> QPixmap:
    """BGR 프레임 → 표시 영역에 맞춘 QPixmap (비율 유지). GUI 스레드에서 호출."""
    return QPixmap.fromImage(bgr_to_qimage(shrink_for_display(frame, max_w, max_h)))


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


# ---------- 장치 이름 (소니 USB 스트리밍 카메라 자동 인식) ----------
SONY_RE = re.compile(r"sony|zv-?e10|ilme|fx30?\b|ilce|alpha", re.IGNORECASE)


def is_sony(name: str | None) -> bool:
    return bool(name and SONY_RE.search(name))


def parse_dshow_devices(text: str) -> List[str]:
    """ffmpeg -list_devices (DirectShow) 출력 → 비디오 장치 이름 (OpenCV CAP_DSHOW 인덱스 순서)."""
    names: List[str] = []
    in_video = False
    for line in text.splitlines():
        if "DirectShow video devices" in line:
            in_video = True
            continue
        if "DirectShow audio devices" in line:
            in_video = False
            continue
        m = re.search(r'"([^"]+)"\s*(\((video|audio|none)\))?', line)
        if not m or "Alternative name" in line:
            continue
        kind = m.group(3)
        if kind == "video" or (kind is None and in_video):
            names.append(m.group(1))
    return names


def parse_avfoundation_devices(text: str) -> List[str]:
    """ffmpeg -f avfoundation -list_devices 출력 → 비디오 장치 이름 (인덱스 순서, 화면 캡처 제외)."""
    names: List[str] = []
    in_video = False
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            break
        m = re.search(r"\]\s*\[(\d+)\]\s*(.+)$", line)
        if in_video and m:
            names.append(m.group(2).strip())
    return [n for n in names if not n.lower().startswith("capture screen")]


def device_names(platform: str | None = None, timeout: float = 8.0) -> List[str]:
    """연결된 카메라 이름 목록 (Windows DirectShow / macOS AVFoundation). 실패하면 빈 목록."""
    plat = platform or sys.platform
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return []
    if plat.startswith("win"):
        args, parse = [exe, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], parse_dshow_devices
    elif plat == "darwin":
        args, parse = [exe, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""], parse_avfoundation_devices
    else:
        return []
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                             encoding="utf-8", errors="replace", creationflags=flags)
        return parse((out.stderr or "") + (out.stdout or ""))
    except Exception:  # noqa: BLE001
        return []


def find_sony_index(names: List[str]) -> Optional[int]:
    for i, n in enumerate(names):
        if is_sony(n):
            return i
    return None
