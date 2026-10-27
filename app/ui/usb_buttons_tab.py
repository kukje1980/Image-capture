"""설정 → 'USB 버튼' 탭: 슬릿램프 USB 버튼의 키 조합 · 기능을 보고 바꾸고, 버튼 신호를 직접 눌러 확인한다.

- 버튼마다 키 조합(칸을 누르고 USB 버튼을 누르면 그 신호가 들어감) · 기능(녹화 · 스틸 · 사진 캡처 · 사용 안 함).
- '신호 확인' 칸: 눌러 둔 뒤 USB 버튼을 누르면 받은 키 조합과 어느 버튼 · 기능인지, 뗌까지 왔는지 보여 준다
  (설정 창에서는 녹화 · 스틸을 실제로 실행하지 않는다).
- 저장은 설정 창 '확인' 때 (config.usb_buttons). 같은 키를 두 버튼 · 단축키에 함께 쓰면 확인을 막고 알려 준다.
"""
from __future__ import annotations

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import shortcuts, usb_buttons

_MOD_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr}


class KeyProbe(QLabel):
    """눌러 둔 뒤 USB 버튼을 누르면 받은 신호를 보여 주는 칸 (동작은 실행하지 않음)."""

    IDLE = "여기를 한 번 누른 뒤 슬릿램프 USB 버튼을 눌러 보세요"

    def __init__(self, tab: "UsbButtonsTab"):
        super().__init__(self.IDLE)
        self.tab = tab
        self.setObjectName("KeyProbe")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWordWrap(True)
        self.setMinimumHeight(52)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.presses = 0
        self.releases = 0
        self._text = ""

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.setFocus()
        super().mousePressEvent(e)

    def focusInEvent(self, e) -> None:  # noqa: N802
        if not self._text:
            self.setText("USB 버튼을 눌러 보세요 …")
        super().focusInEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if Qt.Key(e.key()) in _MOD_KEYS:
            return
        if e.isAutoRepeat():
            return
        self.presses += 1
        combo = QKeySequence(QKeyCombination(e.modifiers(), Qt.Key(e.key())))
        key = combo.toString(QKeySequence.SequenceFormat.PortableText)
        bid = self.tab.button_for(e.key(), e.modifiers())
        who = (f"{usb_buttons.button_label(bid)} · {usb_buttons.action_label(self.tab.action_of(bid))}"
               if bid else "등록된 버튼이 아닙니다")
        self._text = f"받은 신호: {usb_buttons.display(key)}  →  {who}"
        self.setText(self._text + "  (누름)")
        e.accept()

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if Qt.Key(e.key()) in _MOD_KEYS or e.isAutoRepeat() or not self._text:
            return
        self.releases += 1
        self.setText(self._text + "  (누름 · 뗌 확인)")
        e.accept()


class UsbButtonsTab(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        lay = QVBoxLayout(self)
        intro = QLabel("슬릿램프 USB 버튼(키보드 신호를 보내는 버튼)을 촬영 화면 동작에 연결합니다. 버튼은 촬영 화면에서만 동작하고, "
                       "글자 입력칸 · 설정 창 · 다른 프로그램에서는 실행하지 않습니다. 길게 눌러도 한 번만, 뗀 뒤 다시 눌러야 다음 동작입니다.\n"
                       "확인한 장치: VID 04D9 / PID 1203 (MI_00 키보드). 드라이버 · 보드 설정은 바꾸지 않습니다.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for col, text in enumerate(("", "키 조합 (칸을 누르고 버튼을 누름)", "", "기능")):
            h = QLabel(text)
            h.setObjectName("Muted")
            grid.addWidget(h, 0, col)
        self.key_edits: dict[str, QKeySequenceEdit] = {}
        self.action_combos: dict[str, QComboBox] = {}
        cur = usb_buttons.load(config)
        for row, (bid, name) in enumerate(usb_buttons.BUTTONS, start=1):
            ed = QKeySequenceEdit(QKeySequence(cur[bid]["key"]))
            if hasattr(ed, "setMaximumSequenceLength"):
                ed.setMaximumSequenceLength(1)
            b_def = QPushButton("기본값")
            b_def.setToolTip(f"기본: {usb_buttons.display(usb_buttons.DEFAULTS[bid]['key'])} · "
                             f"{usb_buttons.action_label(usb_buttons.DEFAULTS[bid]['action'])}")
            b_def.clicked.connect(lambda _=False, bid=bid: self.reset(bid))
            combo = QComboBox()
            for aid, label in usb_buttons.ACTIONS:
                combo.addItem(label, aid)
            combo.setCurrentIndex(max(0, combo.findData(cur[bid]["action"])))
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(ed, row, 1)
            grid.addWidget(b_def, row, 2)
            grid.addWidget(combo, row, 3)
            self.key_edits[bid] = ed
            self.action_combos[bid] = combo
        lay.addLayout(grid)

        note = QLabel("· 녹화 시작 / 정지: 촬영 도크 '녹화' 버튼과 같습니다 (환자를 먼저 선택).\n"
                      "· 스틸 화면 정지 / 해제: 촬영 도크 '정지영상' 과 같고 사진 파일은 저장하지 않습니다 "
                      "(분할 화면에서는 칸 채우기, 녹화 중에 눌러도 녹화는 계속됩니다).\n"
                      "· 사진 촬영 버튼은 신호를 확인한 뒤 따로 정합니다.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        head = QLabel("신호 확인")
        head.setObjectName("ThumbTitle")
        lay.addWidget(head)
        self.probe = KeyProbe(self)
        lay.addWidget(self.probe)
        lay.addStretch(1)

    # ---- 값 ----
    def reset(self, bid: str) -> None:
        d = usb_buttons.DEFAULTS[bid]
        self.key_edits[bid].setKeySequence(QKeySequence(d["key"]))
        self.action_combos[bid].setCurrentIndex(max(0, self.action_combos[bid].findData(d["action"])))

    def values(self) -> dict:
        return {bid: {"key": self.key_edits[bid].keySequence().toString(QKeySequence.SequenceFormat.PortableText),
                      "action": self.action_combos[bid].currentData() or "none"}
                for bid, _name in usb_buttons.BUTTONS}

    def action_of(self, bid: str) -> str:
        return self.action_combos[bid].currentData() or "none"

    def button_for(self, key, modifiers) -> str | None:
        for bid, v in self.values().items():
            if v["key"] and usb_buttons.matches(v["key"], key, modifiers):
                return bid
        return None

    def problem(self) -> str | None:
        """확인을 막을 문제 (같은 키를 두 곳에) — 없으면 None."""
        vals = self.values()
        keys = [(bid, v["key"]) for bid, v in vals.items() if v["key"]]
        for i, (a, ka) in enumerate(keys):
            for b, kb in keys[i + 1:]:
                if usb_buttons.same_key(ka, kb):
                    return (f"USB {usb_buttons.button_label(a)} 와 {usb_buttons.button_label(b)} 에 같은 키 "
                            f"'{usb_buttons.display(ka)}' 가 지정되어 있습니다.")
        for bid, k in keys:
            if any(usb_buttons.same_key(k, r) for r in shortcuts.RESERVED):
                return f"'{usb_buttons.display(k)}' 는 화면에서 이미 쓰는 키라 USB 버튼에 쓸 수 없습니다."
            for aid, sk in shortcuts.load(self.config).items():
                if usb_buttons.same_key(k, sk):
                    return (f"'{usb_buttons.display(k)}' 는 단축키 '{shortcuts.label(aid)}' 에도 지정되어 있습니다 — "
                            "설정 → 단축키 설정에서 그 단축키를 바꾸거나 USB 버튼에 다른 키를 고르세요.")
        return None
