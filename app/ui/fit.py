"""좁은 창(작은 노트북 · 화면 배율 150% 등)에서 버튼 글자와 아이콘이 서로 겹치지 않게 하는 도우미.

창이 도구줄 최소 폭보다 좁아지면 Qt 는 버튼을 최소 크기보다 작게 눌러 담아 글자가 아이콘 위로 겹쳐 보인다.
HScroll 로 감싼 줄은 눌리지 않고 제 크기를 유지한 채 옆으로 밀어(마우스 휠 · 아래 얇은 스크롤바) 볼 수 있다.
on_compact 를 주면 넘치기 직전에 먼저 그 줄을 '아이콘만' 으로 줄여 보고(on_compact(True)), 넓어지면 되돌린다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy


class HScroll(QScrollArea):
    """가로로만 스크롤되는 한 줄 칸. 높이는 안쪽 줄 높이(+ 넘칠 때만 스크롤바)."""

    def __init__(self, inner, parent=None, on_compact=None):
        super().__init__(parent)
        self.setObjectName("HScroll")
        self._inner = inner
        self._on_compact = on_compact
        self._compact = False
        self._full_w = 0
        self._ready = False                    # 만드는 중(맥은 setFrameShape 등에서 바로 resizeEvent)에는 on_compact 를 부르지 않음
        self.setWidget(inner)
        inner.setAutoFillBackground(False)     # setWidget 이 켜는 바탕 채우기를 끔 — 줄 자체 QSS 바탕만 보이게
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.viewport().setAutoFillBackground(False)
        inner.installEventFilter(self)
        self.setVisible(not inner.isHidden())
        self._sync()
        self._ready = True                     # 이후 크기가 정해질 때(resizeEvent) 줄이기 · 되돌리기

    def inner(self):
        return self._inner

    def overflowing(self) -> bool:
        return self._inner.minimumSizeHint().width() > self.viewport().width()

    def _height(self) -> int:
        h = max(self._inner.sizeHint().height(), self._inner.minimumSizeHint().height())
        if self.overflowing():
            h += self.horizontalScrollBar().sizeHint().height()
        return h

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._inner.sizeHint().width(), self._height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(80, self._height())

    def _sync(self) -> None:
        h = self._height()
        if self.height() != h or self.minimumHeight() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._fit()
        self._sync()

    def _fit(self) -> None:
        if self._on_compact is None or not self._ready:
            return
        vw = self.viewport().width()
        if not self._compact:
            self._full_w = self._inner.minimumSizeHint().width()
            if self._full_w > vw:
                self._compact = True
                self._on_compact(True)
        elif self._full_w <= vw:
            self._compact = False
            self._on_compact(False)

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self._inner:
            t = ev.type()
            if t in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
                # 안쪽 줄을 숨기면(예: Smart 줄 끄기) 감싼 칸도 같이 숨겨 빈 자리가 남지 않게
                self.setVisible(not self._inner.isHidden())
            elif t == QEvent.Type.LayoutRequest:
                self.updateGeometry()
                QTimer.singleShot(0, self._sync)
        return False

    def wheelEvent(self, e) -> None:  # noqa: N802
        if not self.overflowing():
            e.ignore()
            return
        d = e.angleDelta()
        step = d.x() or d.y()
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - step)
        e.accept()
