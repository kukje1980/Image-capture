"""프레임 변환/썸네일/장치 열거 유틸."""
from __future__ import annotations

import re
import subprocess
import sys
from typing import List, Optional

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


# ---------- 장치 이름 (소니 USB 스트리밍 카메라 자동 인식) ----------
SONY_RE = re.compile(r"sony|zv-?e10|ilme|fx30?\b|ilce|alpha", re.IGNORECASE)


def is_sony(name: str | None) -> bool:
    return bool(name and SONY_RE.search(name))


def parse_dshow_devices(text: str) -> List[str]:
    """ffmpeg -list_devices (DirectShow) 출력 → 비디오 장치 이름 (OpenCV CAP_DSHOW 인덱스 순서).

    ffmpeg 는 비디오 장치 범주를 빠짐없이 먼저 출력하고 그 뒤에 오디오 장치를 출력한다.
    새 형식(ffmpeg 4.4+)은 장치마다 핀 종류를 붙인다: (video) · (video, audio) · (none) · (audio).
    HDMI 캡처보드는 (video, audio), 연결 전 가상 카메라(소니 Imaging Edge 등)는 (none) 으로 나오므로
    이들을 빼면 그 뒤 장치들의 번호가 OpenCV 와 어긋나 엉뚱한 카메라가 열린다 → 모두 포함한다.
    오디오 범주는 첫 '(audio)' 전용 장치부터 시작한다고 본다.
    """
    names: List[str] = []
    in_video = False
    legacy = False
    for line in text.splitlines():
        if "DirectShow video devices" in line:
            in_video, legacy = True, True
            continue
        if "DirectShow audio devices" in line:
            break
        if "Alternative name" in line:
            continue
        m = re.search(r'"([^"]+)"\s*(?:\(([^)]*)\))?\s*$', line)
        if not m:
            continue
        kinds = {k.strip() for k in (m.group(2) or "").split(",") if k.strip()}
        if legacy:
            if in_video:
                names.append(m.group(1))
            continue
        if not kinds:
            continue                              # 핀 표시가 없는 줄은 장치 줄이 아님 (새 형식)
        if kinds == {"audio"}:
            break                                 # 여기부터 오디오 장치 범주
        names.append(m.group(1))                  # video · video, audio · none · unknown
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
