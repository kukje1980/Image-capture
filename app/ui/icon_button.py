"""아이콘 위 · 이름 아래 형태의 버튼 (QPushButton 기반).

상단 메뉴 · 촬영 도크 · 홈 타일이 함께 쓴다. QToolButton 대신 v1.12.1 까지 문제없이 쓰던 QPushButton 을 바탕으로,
안쪽 아이콘·글자 라벨은 마우스를 통과시켜 클릭은 항상 버튼이 받는다.
QPushButton 과 같은 text()/setText()/setIcon()/setIconSize() 를 지원해 기존 코드를 그대로 쓸 수 있다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout


class IconTextButton(QPushButton):
    def __init__(self, text: str = "", icon: QIcon | None = None, icon_size: int = 20, parent=None):
        super().__init__(parent)
        self.setProperty("iconText", True)
        self._qicon = QIcon(icon) if icon is not None else QIcon()
        self._isz = QSize(icon_size, icon_size)
        self._text_on = True                    # False = 아이콘만 (좁은 창의 상단 메뉴)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 5, 7, 4)
        lay.setSpacing(2)
        self._ic = QLabel()
        self._ic.setObjectName("BtnIcon")
        self._tx = QLabel(text)
        self._tx.setObjectName("BtnText")
        for lb in (self._ic, self._tx):
            lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lb, 0, Qt.AlignmentFlag.AlignHCenter)
        self._tx.setVisible(bool(text))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.toggled.connect(lambda _on: self._refresh())
        self._refresh()

    # ---- QPushButton 과 같은 API ----
    def text(self) -> str:  # noqa: D401
        return self._tx.text()

    def setText(self, text: str) -> None:  # noqa: N802
        self._tx.setText(text)
        self._tx.setVisible(bool(text) and self._text_on)
        self.updateGeometry()

    def set_text_visible(self, on: bool) -> None:
        """글자 칸 보이기/숨기기 — 숨겨도 text() 는 그대로이고, 이름은 풍선 도움말로 보인다."""
        self._text_on = bool(on)
        self._tx.setVisible(bool(self._tx.text()) and self._text_on)
        self.layout().invalidate()              # 바로 다음 크기 계산에 반영되게
        self.updateGeometry()

    def is_text_visible(self) -> bool:
        return self._text_on

    def icon(self) -> QIcon:
        return self._qicon

    def setIcon(self, icon: QIcon) -> None:  # noqa: N802
        self._qicon = QIcon(icon)
        self._refresh()

    def iconSize(self) -> QSize:  # noqa: N802
        return QSize(self._isz)

    def setIconSize(self, size: QSize) -> None:  # noqa: N802
        self._isz = QSize(size)
        self._refresh()
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.layout().sizeHint().expandedTo(self.minimumSize())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.layout().minimumSize()

    # ---- 내부 ----
    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        if e.type() == QEvent.Type.EnabledChange:
            self._refresh()

    def _refresh(self) -> None:
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        state = QIcon.State.On if self.isChecked() else QIcon.State.Off
        pm = (self._qicon.pixmap(self._isz, self.devicePixelRatioF() or 1.0, mode, state)
              if not self._qicon.isNull() else QPixmap())
        self._ic.setPixmap(pm)
        self._ic.setFixedSize(self._isz)
        self._ic.setVisible(not pm.isNull())
        on = self.isChecked()
        for lb in (self._ic, self._tx):
            if lb.property("on") != on:
                lb.setProperty("on", on)
                lb.style().unpolish(lb)
                lb.style().polish(lb)
