"""촬영 화면의 영상 영역 — 보기에 따라 화면을 배치한다.

- 큰 화면 · 멀티 화면 · 확대 화면 · 3D 화면: 그 화면 하나를 크게
- 모두 보기: 왼쪽 큰 화면(라이브) + 오른쪽 작은 화면 3개(멀티 · 확대 · 3D).
  작은 화면 제목을 누르면 expandRequested(보기) 로 그 화면을 크게 보라고 알린다.

같은 위젯(4분할 상태·3D 시점·확대 위치)을 옮겨 쓰므로 보기를 바꿔도 내용이 이어진다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton, QVBoxLayout, QWidget

from app.ui import icons
from app.ui.view_bar import VIEW_LABEL

PANES = ("multi", "zoom", "3d")
_PANE_ICON = {"multi": "quad", "zoom": "zin", "3d": "cube"}
_HEAD_H = 28
_GAP = 8
FULL_MIN = (480, 300)          # 크게 볼 때 최소 크기
PANE_MIN = (120, 68)           # 작은 화면 최소 크기


class Stage(QWidget):
    expandRequested = Signal(str)

    def __init__(self, single: QWidget, multi: QWidget, zoom: QWidget, surface: QWidget,
                 parent=None):
        super().__init__(parent)
        self.views = {"single": single, "multi": multi, "zoom": zoom, "3d": surface}
        self.mode = ""
        self.aspect = 16 / 9
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(_GAP)

        self._side = QWidget()
        self._side.setObjectName("SidePanes")
        side = QVBoxLayout(self._side)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(_GAP)
        self._panes: dict[str, tuple[QFrame, QVBoxLayout, QPushButton]] = {}
        for key in PANES:
            pane = QFrame()
            pane.setObjectName("Pane")
            lay = QVBoxLayout(pane)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            head = QPushButton(icons.gap(VIEW_LABEL[key]))
            head.setObjectName("PaneHead")
            head.setIcon(icons.icon(_PANE_ICON[key], "#c7cdd8", 14))
            head.setIconSize(QSize(14, 14))
            head.setFixedHeight(_HEAD_H)
            head.setCursor(Qt.CursorShape.PointingHandCursor)
            head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            head.setToolTip(f"{VIEW_LABEL[key]}을 크게 보기")
            head.clicked.connect(lambda _=False, k=key: self.expandRequested.emit(k))
            lay.addWidget(head)
            side.addWidget(pane, 1)
            self._panes[key] = (pane, lay, head)
        self._side.hide()
        for w in self.views.values():
            w.hide()
        self.set_mode("single")

    # ---- 공개 API ----
    def set_mode(self, mode: str) -> None:
        if mode not in self.views and mode != "all":
            mode = "single"
        if mode == self.mode:
            return
        self.mode = mode
        # 모든 화면을 지금 자리에서 빼고
        for w in self.views.values():
            self._grid.removeWidget(w)
            for _pane, lay, _head in self._panes.values():
                lay.removeWidget(w)
            w.hide()
        self._grid.removeWidget(self._side)
        self._side.hide()
        # 새 자리에
        if mode == "all":
            big = self.views["single"]
            big.setMinimumSize(*FULL_MIN)
            self._grid.addWidget(big, 0, 0)
            big.show()
            for key in PANES:
                w = self.views[key]
                w.setMinimumSize(*PANE_MIN)
                self._panes[key][1].addWidget(w, 1)
                w.show()
            self._grid.addWidget(self._side, 0, 1)
            self._side.show()
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
            self._fit_side()
        else:
            w = self.views[mode]
            w.setMinimumSize(*FULL_MIN)
            self._grid.addWidget(w, 0, 0)
            w.show()
            self._grid.setColumnStretch(1, 0)
        for key, w in self.views.items():           # 작은 화면은 HUD 없이 영상만
            if hasattr(w, "set_compact"):
                w.set_compact(mode == "all" and key != "single")

    def current(self) -> QWidget | None:
        """크게 보이는 화면 (모두 보기면 왼쪽 큰 화면)."""
        return self.views["single"] if self.mode == "all" else self.views.get(self.mode)

    def pane_head(self, key: str) -> QPushButton:
        return self._panes[key][2]

    def set_pane_title(self, key: str, text: str) -> None:
        self._panes[key][2].setText(icons.gap(text))

    def set_aspect(self, aspect: float) -> None:
        if aspect > 0:
            self.aspect = aspect
            self._fit_side()

    # ---- 내부 ----
    def _fit_side(self) -> None:
        """작은 화면 3개가 영상 비율에 맞게 — 오른쪽 열 폭을 높이에서 계산."""
        if self.mode != "all":
            return
        pane_h = (self.height() - 2 * _GAP) / 3 - _HEAD_H
        w = max(200, min(self.width() * 0.36, pane_h * self.aspect))
        self._side.setFixedWidth(int(w))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._fit_side()


__all__ = ["Stage", "PANES"]
