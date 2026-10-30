"""환자 배너 오른쪽 빈 공간의 작은 질환 아이콘 줄. 누르면 아래 DxPanel 에 그 질환의 참고 사진이 나온다."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

from app import dx_library
from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT


class DxBar(QFrame):
    diseaseClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DxBar")
        self.setToolTip("질환별 참고 사진 — 아이콘을 누르면 아래에 참고 사진이 나옵니다")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.buttons: dict[str, QPushButton] = {}
        for d in dx_library.diseases():
            b = QPushButton()
            b.setObjectName("DxBtn")
            b.setCheckable(True)
            b.setFixedSize(30, 30)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            ic = icons.icon(d["icon"], ICON, 18)
            ic.addPixmap(icons.pixmap(d["icon"], ICON_ACCENT, 18), ic.Mode.Normal, ic.State.On)
            b.setIcon(ic)
            b.setIconSize(QSize(18, 18))
            b.setToolTip(f"<b>{d['name']}</b> · {d['en']}<br>{d['summary']}<br>"
                         "<span style='color:#8b95a3'>누르면 아래에 참고 사진</span>")
            b.setAccessibleName(d["name"])
            b.clicked.connect(lambda _=False, did=d["id"]: self.diseaseClicked.emit(did))
            self.buttons[d["id"]] = b
            lay.addWidget(b)
        if not self.buttons:
            self.hide()

    def set_active(self, disease_id: str | None) -> None:
        for did, b in self.buttons.items():
            b.setChecked(did == disease_id)

    def active(self) -> str | None:
        return next((did for did, b in self.buttons.items() if b.isChecked()), None)
