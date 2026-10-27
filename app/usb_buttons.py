"""슬릿램프 USB 버튼 — 키보드 신호(키 조합)를 보내는 슬릿램프 버튼을 촬영 동작에 연결한다.

Windows 에서 확인한 장치: VID 04D9 / PID 1203 의 MI_00 키보드 인터페이스. USB 드라이버 · 보드 설정은 건드리지 않고,
장치가 보내는 키 조합을 받아 기존 동작(녹화 · 정지영상 …)을 촬영 도크 버튼과 똑같이 부른다.
  버튼 1: Ctrl + Shift + Alt + F9  → 녹화 시작 / 정지
  버튼 2: Ctrl + Shift + Alt + F10 → 스틸(정지영상) 화면 정지 / 해제 — 사진 파일은 저장하지 않음
config.json 의 "usb_buttons" 에 {"1": {"key": "...", "action": "..."}, ...} 로 저장 (없거나 잘못된 값은 위 기본값).

UsbButtonFilter (앱 전체 이벤트 필터)
- 누름 한 번에 한 번만: 길게 누를 때 오는 자동 반복 · 뗌 없이 다시 온 누름은 무시하고, 뗀 뒤 다시 눌러야 다음 동작.
- 동작 사이 최소 간격(MIN_INTERVAL) — 접점이 튀어 누름 · 뗌이 겹쳐 와도 두 번 실행하지 않게.
- 언제 실행할지(촬영 화면 · 입력칸 아님 등)는 context() 로 묻는다. 실행은 이벤트 처리가 끝난 뒤(QTimer) 한다.
- 프로그램이 다른 창으로 넘어가면 누름 상태를 지운다 (뗌을 못 받아 버튼이 계속 눌린 것으로 남지 않게).
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence

BUTTONS = [("1", "버튼 1"), ("2", "버튼 2")]
DEFAULTS = {"1": {"key": "Ctrl+Shift+Alt+F9", "action": "record"},
            "2": {"key": "Ctrl+Shift+Alt+F10", "action": "freeze"}}
# (동작 id, 이름) — 동작 id 는 메인 창 단축키 동작(app/shortcuts.py)과 같은 이름
ACTIONS = [("none", "사용 안 함"),
           ("record", "녹화 시작 / 정지"),
           ("freeze", "스틸 화면 정지 / 해제 (사진 저장 안 함)"),
           ("capture", "사진 캡처 (저장)")]
MIN_INTERVAL = 0.3                       # 같은 버튼 동작 사이 최소 간격 (초)
_MODS = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
         | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)


def action_label(action: str) -> str:
    return next((name for aid, name in ACTIONS if aid == action), action)


def button_label(bid: str) -> str:
    return next((name for b, name in BUTTONS if b == bid), f"버튼 {bid}")


def load(config) -> dict[str, dict]:
    """{버튼 id: {"key": 키 조합, "action": 동작 id}} — 저장값이 없거나 잘못되면 기본값."""
    saved = getattr(config, "usb_buttons", None) or {}
    out = {}
    actions = {a for a, _ in ACTIONS}
    for bid, _name in BUTTONS:
        d = dict(DEFAULTS[bid])
        s = saved.get(bid) if isinstance(saved, dict) else None
        if isinstance(s, dict):
            if isinstance(s.get("key"), str):
                d["key"] = s["key"]
            if s.get("action") in actions:
                d["action"] = s["action"]
        out[bid] = d
    return out


def same_key(a: str, b: str) -> bool:
    """두 키 조합이 같은가 (쓰는 순서 · 대소문자가 달라도: 'Ctrl+Shift+Alt+F9' == 'ctrl+alt+shift+f9')."""
    if not a or not b:
        return False
    sa, sb = QKeySequence(a), QKeySequence(b)
    return not sa.isEmpty() and sa == sb


def display(key: str) -> str:
    seq = QKeySequence(key or "")
    return seq.toString(QKeySequence.SequenceFormat.NativeText).replace("+", " + ") if not seq.isEmpty() else "없음"


def _combination(key: str):
    seq = QKeySequence(key or "")
    if seq.isEmpty() or seq.count() != 1:
        return None
    return seq[0]


def matches(key: str, qt_key: int, modifiers) -> bool:
    """키 이벤트(키 · 조합키)가 저장한 키 조합과 같은가. 맥은 Qt 가 Ctrl ↔ Command 를 바꿔 읽어 둘 다 받는다."""
    combo = _combination(key)
    if combo is None or int(qt_key) != int(combo.key()):
        return False
    want = combo.keyboardModifiers() & _MODS
    got = Qt.KeyboardModifier(modifiers) & _MODS
    if got == want:
        return True
    if sys.platform == "darwin":
        ctrl, meta = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.MetaModifier
        swapped = want & ~(ctrl | meta)
        if want & ctrl:
            swapped |= meta
        if want & meta:
            swapped |= ctrl
        return got == swapped
    return False


def key_of(key: str) -> int | None:
    """키 조합의 '키' 부분 (F9 등) — 뗌은 조합키를 먼저 놓아도 이 키로 알아본다."""
    combo = _combination(key)
    return int(combo.key()) if combo is not None else None


class UsbButtonFilter(QObject):
    """앱 전체 키 이벤트에서 USB 버튼 조합을 찾아 run(버튼 id, 동작) 을 부른다.

    context() → None 이면 실행, 문자열이면 그 이유로 실행하지 않음(ignored(버튼 id, 이유) 로 알림).
    """

    def __init__(self, buttons: dict, run, context, ignored=None, clock=time.monotonic, parent=None):
        super().__init__(parent)
        self._run = run
        self._context = context
        self._ignored = ignored
        self._clock = clock
        self._held: set[str] = set()
        self._last: dict[str, float] = {}
        self.set_buttons(buttons)

    def set_buttons(self, buttons: dict) -> None:
        self.buttons = {bid: dict(b) for bid, b in (buttons or {}).items()}
        self._held.clear()

    def held(self) -> set:
        return set(self._held)

    def reset(self) -> None:
        self._held.clear()

    def _find(self, ev, release: bool):
        for bid, b in self.buttons.items():
            if not b.get("key"):
                continue
            if release:
                if key_of(b["key"]) == int(ev.key()):
                    return bid
            elif matches(b["key"], ev.key(), ev.modifiers()):
                return bid
        return None

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t == QEvent.Type.ApplicationDeactivate:
            self._held.clear()                      # 다른 프로그램으로 — 뗌을 못 받아도 눌린 채 남지 않게
            return False
        if t == QEvent.Type.KeyRelease:
            if not ev.isAutoRepeat():
                bid = self._find(ev, release=True)
                if bid is not None:
                    self._held.discard(bid)
            return False
        if t != QEvent.Type.KeyPress:
            return False
        bid = self._find(ev, release=False)
        if bid is None:
            return False
        action = self.buttons[bid].get("action", "none")
        if ev.isAutoRepeat() or bid in self._held:
            return True                             # 길게 누름 · 뗌 없이 다시 온 누름: 무시 (다른 곳에도 보내지 않음)
        self._held.add(bid)
        reason = self._context()
        if reason is not None:
            if self._ignored is not None:
                self._ignored(bid, reason)
            return False                            # 입력칸 · 다른 화면: 그대로 흘려보냄 (가로채지 않음)
        now = self._clock()
        if now - self._last.get(bid, -1e9) < MIN_INTERVAL:
            return True                             # 접점 튐 · 겹친 신호
        self._last[bid] = now
        if action != "none":
            QTimer.singleShot(0, lambda bid=bid, action=action: self._run(bid, action))
        return True
