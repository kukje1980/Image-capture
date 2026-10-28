"""Windows Raw Input 으로 슬릿램프 장치(VID 04D9 / PID 1203 · MI_00 키보드 인터페이스)의 키 신호만 가려낸다.

Qt 의 키 이벤트에는 어느 키보드에서 왔는지가 없다. Windows 는 같은 키 입력을 WM_INPUT(Raw Input, 장치 핸들 포함)으로
먼저 보내고 그 다음 WM_KEYDOWN(→ Qt 키 이벤트)을 보내므로, 여기서 WM_INPUT 을 받아 '이 키가 방금 슬릿램프 장치에서
눌렸다' 를 기억해 두고, 뒤이어 온 Qt 키 이벤트에서 UsbButtonFilter 가 classify(키) 로 묻는다.
- 등록: 키보드(usage page 1 · usage 6), hwndTarget 없음(키보드 초점을 따라감 — 이 프로그램이 앞에 있을 때만),
  RIDEV_DEVNOTIFY 로 장치 꽂힘 · 빠짐 알림. RIDEV_INPUTSINK 는 쓰지 않는다 (다른 프로그램에서 치는 글자는 받지 않는다).
- 기록하는 것: 감시하는 키(USB 버튼 · 좌우 신호에 지정한 F6 · F7 · F9 · F10 등)의 마지막 누름 시각과 슬릿램프 장치
  여부뿐. 그 밖의 키는 장치 이름도 보지 않고 바로 버린다. 글자 입력은 어디에도 저장 · 기록하지 않는다.
- 장치 이름(경로)은 핸들마다 한 번만 읽어 캐시 — 다시 꽂으면 핸들이 바뀌어 다시 읽는다 (재연결 시 장치 경로 재확인).
맥 · 리눅스 · 등록 실패: available() False, classify() None → 필터는 모든 키보드 신호를 받는다 (예전과 같음).
실제 Windows 장치로는 아직 시험하지 못했다 — 장치 이름 판정 · 시각 창 · 키 변환은 tests/test_usb_buttons.py 로 검사.
"""
from __future__ import annotations

import ctypes
import logging
import re
import sys
import time

from PySide6.QtCore import QAbstractNativeEventFilter, Qt

log = logging.getLogger(__name__)

VENDOR_PRODUCT = ("04D9", "1203")        # 확인한 슬릿램프 버튼 장치
INTERFACE = "MI_00"                      # 키보드 인터페이스
MATCH_WINDOW_S = 0.25                    # WM_INPUT 뒤 Qt 키 이벤트가 이 안에 오면 같은 누름으로 본다

WM_INPUT = 0x00FF
WM_INPUT_DEVICE_CHANGE = 0x00FE
RIM_TYPEKEYBOARD = 1
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDEV_DEVNOTIFY = 0x00002000
RI_KEY_BREAK = 0x01
GIDC_ARRIVAL, GIDC_REMOVAL = 1, 2
_INVALID = 0xFFFFFFFF


def is_slitlamp_device(name: str, vid_pid: tuple = VENDOR_PRODUCT, interface: str = INTERFACE) -> bool:
    r"""Raw Input 장치 이름(예: \\?\HID#VID_04D9&PID_1203&MI_00#7&2d9f0b6&0&0000#{...})이 슬릿램프 장치인가."""
    n = (name or "").upper()
    vid, pid = (x.upper() for x in vid_pid)
    if f"VID_{vid}&PID_{pid}" not in n:
        return False
    if not interface:
        return True
    return re.search(rf"&{re.escape(interface.upper())}(?![0-9A-Z])", n) is not None


def qt_key_to_vk(qt_key: int) -> int | None:
    """Qt 키 → Windows 가상 키 코드 (F1~F24 · A~Z · 0~9 만; 그 밖은 None = 장치 확인 못 함)."""
    k = int(qt_key)
    f1, f24 = int(Qt.Key.Key_F1), int(Qt.Key.Key_F24)
    if f1 <= k <= f24:
        return 0x70 + (k - f1)
    a, z = int(Qt.Key.Key_A), int(Qt.Key.Key_Z)
    if a <= k <= z:
        return 0x41 + (k - a)
    d0, d9 = int(Qt.Key.Key_0), int(Qt.Key.Key_9)
    if d0 <= k <= d9:
        return 0x30 + (k - d0)
    return None


class RawKeyLog:
    """감시하는 가상 키마다 마지막 누름(시각 · 슬릿램프 장치 여부)을 둔다 — 글자 입력은 기록하지 않는다."""

    def __init__(self, clock=time.monotonic, window: float = MATCH_WINDOW_S):
        self._clock = clock
        self._window = window
        self._watch: set[int] = set()
        self._last: dict[int, tuple[float, bool]] = {}
        self.last_device: bool | None = None       # 마지막으로 감시 키를 보낸 장치 (설정 창 '신호 확인' 표시용)

    def watch(self, vks) -> None:
        self._watch = {int(v) for v in vks if v is not None}
        self._last.clear()

    def watching(self, vk: int) -> bool:
        return int(vk) in self._watch

    def note(self, vk: int, from_slitlamp: bool, now: float | None = None) -> None:
        if int(vk) not in self._watch:
            return
        self._last[int(vk)] = (self._clock() if now is None else now, bool(from_slitlamp))
        self.last_device = bool(from_slitlamp)

    def classify(self, vk: int | None, now: float | None = None) -> bool | None:
        """True = 방금 슬릿램프 장치가 누른 키, False = 다른 키보드, None = 모름(기록 없음 · 너무 오래됨)."""
        if vk is None:
            return None
        entry = self._last.get(int(vk))
        if entry is None:
            return None
        t, dev = entry
        if (self._clock() if now is None else now) - t > self._window:
            return None
        return dev


class NullRawInput:
    """Raw Input 을 못 쓰는 환경(맥 · 리눅스 · 등록 실패) — 모든 키보드 신호를 받는다."""

    reason = "이 운영체제에서는 쓰지 않음"

    def available(self) -> bool:
        return False

    def watch(self, qt_keys) -> None:
        pass

    def classify(self, qt_key: int) -> bool | None:
        return None

    def last_device_text(self) -> str:
        return "장치 확인 없음"

    def status_text(self) -> str:
        return f"장치 확인(Raw Input) 사용 안 함 — {self.reason}. 모든 키보드의 같은 키 조합을 받습니다."

    def uninstall(self, app) -> None:
        pass


if sys.platform == "win32":  # pragma: no cover — 리눅스 · 맥에서는 만들지 않는다
    from ctypes import wintypes

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                    ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                    ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]

    class RAWKEYBOARD(ctypes.Structure):
        _fields_ = [("MakeCode", wintypes.USHORT), ("Flags", wintypes.USHORT), ("Reserved", wintypes.USHORT),
                    ("VKey", wintypes.USHORT), ("Message", wintypes.UINT), ("ExtraInformation", wintypes.ULONG)]

    class RAWINPUTKBD(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]

    _user32 = ctypes.windll.user32
    _user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
    _user32.RegisterRawInputDevices.restype = wintypes.BOOL
    _user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                        ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    _user32.GetRawInputData.restype = wintypes.UINT
    _user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                               ctypes.POINTER(wintypes.UINT)]
    _user32.GetRawInputDeviceInfoW.restype = wintypes.UINT

    def _device_name(hdev) -> str:
        size = wintypes.UINT(0)
        _user32.GetRawInputDeviceInfoW(hdev, RIDI_DEVICENAME, None, ctypes.byref(size))
        if size.value == 0:
            return ""
        buf = ctypes.create_unicode_buffer(size.value + 1)
        n = _user32.GetRawInputDeviceInfoW(hdev, RIDI_DEVICENAME, buf, ctypes.byref(size))
        if n == _INVALID or n == 0:
            return ""
        return buf.value

    class WinRawInput(QAbstractNativeEventFilter):
        """WM_INPUT 을 받아 감시 키의 장치를 RawKeyLog 에 적고, 장치 꽂힘 · 빠짐을 알린다."""

        def __init__(self, keylog: RawKeyLog, on_device_change=None):
            super().__init__()
            self.keylog = keylog
            self._on_device_change = on_device_change
            self._names: dict[int, bool] = {}         # 장치 핸들 → 슬릿램프 장치인가 (핸들이 바뀌면 다시 읽음)
            self._installed = False
            self.reason = ""
            self._app = None

        # ---- 등록 ----
        def install(self, app) -> bool:
            if self._installed:
                return True
            for flags, hwnd in ((RIDEV_DEVNOTIFY, None), (0, None)):
                dev = RAWINPUTDEVICE(1, 6, flags, hwnd)
                try:
                    ok = bool(_user32.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(RAWINPUTDEVICE)))
                except Exception:  # noqa: BLE001
                    log.warning("RegisterRawInputDevices 호출 실패", exc_info=True)
                    ok = False
                if ok:
                    app.installNativeEventFilter(self)
                    self._app = app
                    self._installed = True
                    log.info("Raw Input 등록 (flags=0x%x)", flags)
                    return True
                self.reason = f"RegisterRawInputDevices 실패 (오류 {ctypes.GetLastError()})"
            log.warning("Raw Input 을 등록하지 못했습니다: %s", self.reason)
            return False

        def uninstall(self, app) -> None:
            if self._installed:
                try:
                    app.removeNativeEventFilter(self)
                except Exception:  # noqa: BLE001
                    pass
                self._installed = False

        def available(self) -> bool:
            return self._installed

        # ---- UsbButtonFilter 가 묻는 것 ----
        def watch(self, qt_keys) -> None:
            self.keylog.watch(qt_key_to_vk(k) for k in qt_keys if k is not None)

        def classify(self, qt_key: int) -> bool | None:
            return self.keylog.classify(qt_key_to_vk(qt_key))

        def last_device_text(self) -> str:
            d = self.keylog.last_device
            if d is None:
                return "아직 감시 키 신호 없음"
            return "슬릿램프 장치 확인" if d else "다른 키보드 (슬릿램프 아님)"

        def status_text(self) -> str:
            vid, pid = VENDOR_PRODUCT
            if self._installed:
                return (f"장치 확인(Raw Input) 사용 중 — VID {vid} / PID {pid} · {INTERFACE} 의 신호만 좌우 신호로 받습니다. "
                        f"마지막 감시 키: {self.last_device_text()}")
            return f"장치 확인(Raw Input) 등록 실패 — {self.reason or '알 수 없음'}. 모든 키보드의 같은 키 조합을 받습니다."

        # ---- 장치 ----
        def _is_slitlamp(self, hdev) -> bool:
            key = int(hdev or 0)
            if key == 0:
                return False                         # SendInput 등 가짜 입력: 장치 없음
            hit = self._names.get(key)
            if hit is None:
                hit = is_slitlamp_device(_device_name(hdev))
                if len(self._names) > 64:            # 핸들은 꽂을 때마다 바뀜 — 오래된 것은 비움
                    self._names.clear()
                self._names[key] = hit
            return hit

        # ---- 메시지 ----
        def nativeEventFilter(self, event_type, message):  # noqa: N802
            try:
                if bytes(event_type) != b"windows_generic_MSG":
                    return False, 0
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_INPUT:
                    self._on_input(msg.lParam)
                elif msg.message == WM_INPUT_DEVICE_CHANGE:
                    self._on_change(int(msg.wParam), msg.lParam)
            except Exception:  # noqa: BLE001
                log.debug("raw input 메시지 처리 실패", exc_info=True)
            return False, 0                          # 메시지는 늘 Qt 에 그대로 넘긴다

        def _on_input(self, hraw) -> None:
            size = wintypes.UINT(0)
            if _user32.GetRawInputData(hraw, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)) == _INVALID:
                return
            if size.value < ctypes.sizeof(RAWINPUTKBD):
                return
            buf = ctypes.create_string_buffer(size.value)
            if _user32.GetRawInputData(hraw, RID_INPUT, buf, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER)) == _INVALID:
                return
            head = RAWINPUTHEADER.from_buffer(buf)
            if head.dwType != RIM_TYPEKEYBOARD:
                return                               # 마우스 · 그 밖의 HID: 보지 않음
            kbd = RAWINPUTKBD.from_buffer(buf).keyboard
            if kbd.Flags & RI_KEY_BREAK:
                return                               # 뗌은 Qt 쪽에서 처리
            vk = int(kbd.VKey)
            if not self.keylog.watching(vk):
                return                               # 감시 키가 아니면 장치도 보지 않고 버린다 (글자 입력 비수집)
            self.keylog.note(vk, self._is_slitlamp(head.hDevice))

        def _on_change(self, what: int, hdev) -> None:
            key = int(hdev or 0)
            if what == GIDC_ARRIVAL:
                self._names.pop(key, None)
                if self._is_slitlamp(hdev) and self._on_device_change is not None:
                    self._on_device_change(True)
            elif what == GIDC_REMOVAL:
                was = self._names.pop(key, None)
                if was and self._on_device_change is not None:
                    self._on_device_change(False)


def create(app, on_device_change=None):
    """플랫폼에 맞는 장치 확인 객체 — Windows 에서 등록되면 WinRawInput, 아니면 NullRawInput."""
    if sys.platform == "win32":  # pragma: no cover
        try:
            raw = WinRawInput(RawKeyLog(), on_device_change)
            if raw.install(app):
                return raw
            null = NullRawInput()
            null.reason = raw.reason or "등록 실패"
            return null
        except Exception:  # noqa: BLE001
            log.warning("Raw Input 초기화 실패 — 장치 확인 없이 진행", exc_info=True)
            null = NullRawInput()
            null.reason = "초기화 실패"
            return null
    return NullRawInput()
