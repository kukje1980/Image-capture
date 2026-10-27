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
PAGE = 120           # 한 번에 그리는 썸네일 수. 장기 추적 환자(수천 장)를 골라도 화면이 멈추지 않게 나눠 그린다


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
        self._limit = PAGE

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
        self._limit = PAGE
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
        self._limit = PAGE
        self._rebuild()

    def show_more(self) -> None:
        """'더 보기': 다음 PAGE 장을 추가로 그린다."""
        self._limit += PAGE
        self._rebuild()

    def shown_count(self) -> int:
        return min(self._limit, len(self.visible_captures()))

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
                w.setParent(None)              # 바로 떼어 내 findChild·메모리에 남지 않게
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
        total, shown = len(shown), shown[:self._limit]
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
        if total > len(shown):
            more = QPushButton(f"이전 {min(PAGE, total - len(shown))}장 더 보기  ({len(shown)} / {total})")
            more.setObjectName("MoreBtn")
            more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            more.clicked.connect(self.show_more)
            self._lay.addWidget(more)
