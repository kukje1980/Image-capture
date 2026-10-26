"""우측 썸네일 패널: 헤더(개수) + 필터(전체/OD/OS/동영상) + 촬영일별 묶음 목록."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.thumbnail_widget import ThumbnailWidget

_DOW = "월화수목금토일"
_FILTERS = [("all", "전체"), ("OD", "OD"), ("OS", "OS"), ("video", "동영상")]


def day_label(day: str) -> str:
    """'2026-10-23' → '2026.10.23 (금)'."""
    try:
        y, m, d = (int(x) for x in day.split("-"))
        return f"{y:04d}.{m:02d}.{d:02d} ({_DOW[date(y, m, d).weekday()]})"
    except (ValueError, TypeError):
        return day or "-"


class ThumbnailPanel(QFrame):
    thumbnailClicked = Signal(object)  # Capture

    def __init__(self, db, newest_on_top: bool = True, parent=None):
        super().__init__(parent)
        self.db = db
        self.newest_on_top = newest_on_top
        self._patient_id = None
        self._filter = "all"
        self._items: list = []

        self.setObjectName("ThumbnailPanel")
        self.setFixedWidth(248)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 6, 8)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 6, 0)
        title = QLabel("촬영 이미지")
        title.setObjectName("ThumbTitle")
        self._badge = QLabel("0")
        self._badge.setObjectName("CountBadge")
        head.addWidget(title)
        head.addWidget(self._badge)
        head.addStretch(1)
        outer.addLayout(head)

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 6, 0)
        chips.setSpacing(4)
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
            chips.addWidget(b)
        self.filter_buttons["all"].setChecked(True)
        outer.addLayout(chips)
        sep = QFrame()
        sep.setObjectName("ThumbSep")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 세로 스크롤바는 항상 표시: 필요할 때만 보이게 하면 목록 높이가 경계값일 때
        # 스크롤바 생김→너비 감소→카드 높이 감소→스크롤바 사라짐→… 무한 재배치로 앱이 죽을 수 있다
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._container = QWidget()
        self._container.setObjectName("ThumbList")
        self._lay = QVBoxLayout(self._container)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._lay.setContentsMargins(0, 0, 6, 6)
        self._lay.setSpacing(8)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)
        self._empty = QLabel()
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)

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

    # ---- 내부 ----
    def _rebuild(self) -> None:
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None and w is not self._empty:
                w.hide()                     # 지워지기 전까지 옛 자리에 그려지지 않게
                w.setParent(None)
                w.deleteLater()
        self._badge.setText(str(len(self._items)))
        shown = self.visible_captures()
        if not shown:
            self._empty.setText("환자를 선택하세요" if self._patient_id is None
                                else ("조건에 맞는 영상이 없습니다" if self._items else "촬영 이미지가 없습니다"))
            self._lay.addWidget(self._empty)
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
                h = QLabel(f"{day_label(d)}   ·   {per_day[d]}장")
                h.setObjectName("DayHeader")
                self._lay.addWidget(h)
            w = ThumbnailWidget(c)
            w.clicked.connect(self.thumbnailClicked.emit)
            self._lay.addWidget(w)
