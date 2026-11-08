"""촬영 화면 아래쪽 촬영 이미지 띠: 왼쪽 머리(제목·개수·접기 + 전체/OD/OS/동영상 필터)
+ 가로로 넘기는 촬영일별 목록 (최신이 왼쪽, 마우스 휠로 좌우 이동)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

from app.ui import icons
from app.ui.theme import ICON
from app.ui.thumbnail_widget import CARD_H, ThumbnailWidget

_DOW = "월화수목금토일"
_FILTERS = [("all", "전체"), ("OD", "OD"), ("OS", "OS"), ("video", "동영상")]
STRIP_H = CARD_H + 32                     # 띠 높이 (카드 + 여백·가로 스크롤바)


def day_label(day: str) -> str:
    """'2026-10-23' → '2026.10.23 (금)'."""
    try:
        y, m, d = (int(x) for x in day.split("-"))
        return f"{y:04d}.{m:02d}.{d:02d} ({_DOW[date(y, m, d).weekday()]})"
    except (ValueError, TypeError):
        return day or "-"


def day_chip(day: str, count: int) -> str:
    """가로 띠의 촬영일 표시 (세 줄): '2026' / '10.23' / '금 · 5장'."""
    try:
        y, m, d = (int(x) for x in day.split("-"))
        return f"{y:04d}\n{m:02d}.{d:02d}\n{_DOW[date(y, m, d).weekday()]} · {count}장"
    except (ValueError, TypeError):
        return f"-\n\n{count}장"


class _HScroll(QScrollArea):
    """세로 휠을 가로 이동으로 바꾸는 스크롤 영역."""

    def wheelEvent(self, e) -> None:  # noqa: N802
        d = e.angleDelta()
        if abs(d.y()) > abs(d.x()):
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - d.y())
            e.accept()
            return
        super().wheelEvent(e)


class ThumbnailPanel(QFrame):
    thumbnailClicked = Signal(object)  # Capture
    foldedChanged = Signal(bool)

    def __init__(self, db, newest_on_top: bool = True, parent=None):
        super().__init__(parent)
        self.db = db
        self.newest_on_top = newest_on_top     # 가로 띠에서는 '최신이 왼쪽'
        self._patient_id = None
        self._filter = "all"
        self._items: list = []
        self._folded = False

        self.setObjectName("ThumbnailPanel")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 왼쪽 머리: 제목·개수·접기 + 필터 (접으면 한 줄로)
        self._side = QFrame()
        self._side.setObjectName("ThumbSide")
        self._side_lay = QBoxLayout(QBoxLayout.Direction.TopToBottom, self._side)
        self._side_lay.setContentsMargins(10, 8, 10, 8)
        self._side_lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("촬영 이미지")
        title.setObjectName("ThumbTitle")
        self._badge = QLabel("0")
        self._badge.setObjectName("CountBadge")
        self.btn_fold = QPushButton()
        self.btn_fold.setObjectName("ThumbFold")
        self.btn_fold.setFixedSize(24, 24)
        self.btn_fold.setIconSize(QSize(14, 14))
        self.btn_fold.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_fold.clicked.connect(lambda: self.set_folded(not self._folded))
        head.addWidget(title)
        head.addWidget(self._badge)
        head.addStretch(1)
        head.addWidget(self.btn_fold)
        self._side_lay.addLayout(head)

        self._chips = QGridLayout()
        self._chips.setSpacing(4)
        self._chip_group = QButtonGroup(self)
        self.filter_buttons = {}
        for key, text in _FILTERS:
            b = QPushButton(text)
            b.setObjectName("FilterChip")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._chip_group.addButton(b)
            self.filter_buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
        self.filter_buttons["all"].setChecked(True)
        self._side_lay.addLayout(self._chips)
        self._side_lay.addStretch(1)
        outer.addWidget(self._side)

        sep = QFrame()
        sep.setObjectName("ThumbSep")
        sep.setFixedWidth(1)
        self._sep = sep
        outer.addWidget(sep)

        # 가로 목록
        self._scroll = _HScroll()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._container = QWidget()
        self._container.setObjectName("ThumbList")
        self._lay = QHBoxLayout(self._container)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._lay.setContentsMargins(0, 8, 10, 4)
        self._lay.setSpacing(8)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)
        self._empty = QLabel()
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setMinimumHeight(CARD_H)
        self._apply_fold()

    # ---- 공개 API ----
    def set_patient(self, patient_id) -> None:
        self._patient_id = patient_id
        order = "desc" if self.newest_on_top else "asc"
        self._items = self.db.captures.list_by_patient(patient_id, order=order) if patient_id is not None else []
        self._rebuild()

    def add_capture(self, capture) -> None:
        if capture.patient_id != self._patient_id:
            return
        if self.newest_on_top:
            self._items.insert(0, capture)
        else:
            self._items.append(capture)
        self._rebuild()

    def set_filter(self, key: str) -> None:
        self._filter = key if key in self.filter_buttons else "all"
        self.filter_buttons[self._filter].setChecked(True)
        self._rebuild()

    def count(self) -> int:
        return len(self._items)

    def visible_captures(self) -> list:
        f = self._filter
        return [c for c in self._items
                if f == "all" or (c.media_type == "video" if f == "video" else c.eye == f)]

    def set_folded(self, on: bool) -> None:
        """목록 접기 — 제목·필터 한 줄만 남기고 영상을 더 크게."""
        on = bool(on)
        if on == self._folded:
            return
        self._folded = on
        self._apply_fold()
        self.foldedChanged.emit(on)

    def is_folded(self) -> bool:
        return self._folded

    # ---- 내부 ----
    def _apply_fold(self) -> None:
        on = self._folded
        self._scroll.setVisible(not on)
        self._sep.setVisible(not on)
        d = QBoxLayout.Direction
        self._side_lay.setDirection(d.LeftToRight if on else d.TopToBottom)
        self._side_lay.setSpacing(14 if on else 6)
        for i, (key, _text) in enumerate(_FILTERS):
            b = self.filter_buttons[key]
            if on:
                self._chips.addWidget(b, 0, i)
            else:
                self._chips.addWidget(b, i // 2, i % 2)
        if on:
            self._side.setMinimumWidth(0)
            self._side.setMaximumWidth(16777215)
        else:
            self._side.setFixedWidth(166)
        self.setFixedHeight(46 if on else STRIP_H)
        # 펼침 = ▾(접기), 접힘 = ▴(펼치기)
        pm = icons.pixmap("chev-l", ICON, 14).transformed(QTransform().rotate(90 if on else -90))
        self.btn_fold.setIcon(pm)
        self.btn_fold.setToolTip("촬영 이미지 목록 펼치기" if on
                                 else "촬영 이미지 목록 접기 (영상을 더 크게)")

    def _rebuild(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._empty:
                w.deleteLater()
        self._badge.setText(str(len(self._items)))
        shown = self.visible_captures()
        if not shown:
            self._empty.setText("환자를 선택하세요" if self._patient_id is None
                                else ("조건에 맞는 영상이 없습니다" if self._items else "촬영 이미지가 없습니다"))
            self._lay.addWidget(self._empty, 1)
            self._empty.show()
            return
        self._empty.hide()
        per_day: dict[str, int] = {}
        for c in shown:
            d = (c.captured_at or "")[:10]
            per_day[d] = per_day.get(d, 0) + 1
        day = None
        for c in shown:
            d = (c.captured_at or "")[:10]
            if d != day:
                day = d
                h = QLabel(day_chip(d, per_day[d]))
                h.setObjectName("DayHeader")
                h.setAlignment(Qt.AlignmentFlag.AlignCenter)
                h.setFixedSize(58, CARD_H)
                h.setToolTip(f"{day_label(d)} · {per_day[d]}장")
                self._lay.addWidget(h)
            w = ThumbnailWidget(c)
            w.clicked.connect(self.thumbnailClicked.emit)
            self._lay.addWidget(w)
        self._lay.addStretch(1)
        # 최신 촬영이 보이게 (최신이 왼쪽이면 맨 앞, 아니면 맨 끝)
        QTimer.singleShot(0, self, self._scroll_to_newest)

    def _scroll_to_newest(self) -> None:
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.minimum() if self.newest_on_top else bar.maximum())
