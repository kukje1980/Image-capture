"""단축키 설정 창 — 동작마다 키를 눌러 지정 (USB 발판 스위치 등 키를 보내는 장치도 가능)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import shortcuts


class ShortcutsDialog(QDialog):
    def __init__(self, keys: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("단축키 설정")
        self.resize(520, 560)
        self.edits: dict[str, QKeySequenceEdit] = {}

        lay = QVBoxLayout(self)
        note = QLabel("칸을 누른 뒤 원하는 키를 누르세요. F1~F12, 숫자패드, Ctrl/Alt/Shift 조합도 됩니다.\n"
                      "USB 발판 스위치처럼 키를 보내는 장치도 같은 방법으로 지정할 수 있습니다.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setColumnStretch(1, 1)
        for row, (aid, name, _default, scope) in enumerate(shortcuts.ACTIONS):
            lbl = QLabel(f"{name}  <span style='color:#8b95a3;font-size:11px'>"
                         f"({'촬영 화면' if scope == 'capture' else '모든 화면'})</span>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            ed = QKeySequenceEdit(QKeySequence(keys.get(aid, "")))
            if hasattr(ed, "setMaximumSequenceLength"):
                ed.setMaximumSequenceLength(1)          # 한 번에 키 하나 (조합 포함)
            clear = QPushButton("지우기")
            clear.clicked.connect(ed.clear)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(ed, row, 1)
            grid.addWidget(clear, row, 2)
            self.edits[aid] = ed
        lay.addWidget(grid_w)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        reset = btns.addButton("기본값으로", QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self._reset)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _reset(self) -> None:
        for aid, key in shortcuts.defaults().items():
            self.edits[aid].setKeySequence(QKeySequence(key))

    def values(self) -> dict[str, str]:
        return {aid: ed.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                for aid, ed in self.edits.items()}

    def _accept(self) -> None:
        vals = self.values()
        bad = [shortcuts.label(a) for a, k in vals.items() if k in shortcuts.RESERVED]
        if bad:
            QMessageBox.warning(self, "단축키", "이 키는 화면에서 이미 쓰고 있어 지정할 수 없습니다:\n" + ", ".join(bad))
            return
        seen: dict[str, str] = {}
        for aid, k in vals.items():
            if k and k in seen:
                QMessageBox.warning(self, "단축키", f"'{k}' 키가 '{shortcuts.label(seen[k])}'와 "
                                                     f"'{shortcuts.label(aid)}'에 함께 지정되어 있습니다.")
                return
            if k:
                seen[k] = aid
        self.accept()
