"""우측 썸네일 패널: 헤더(개수) + 필터(전체/OD/OS/동영상) + 촬영일별 묶음 목록.

사진은 왼쪽 클릭으로 여러 장 선택(토글)하고, 오른쪽 클릭 메뉴(또는 선택 막대의 버튼)로
전송 폴더에 **보내기** / **삭제** 한다. 더블클릭은 크게 보기.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT, ICON_RECORD
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
    thumbnailClicked = Signal(object)       # Capture — 더블클릭(크게 보기)
    selectionChanged = Signal(int)          # 선택 개수
    sendRequested = Signal(list)            # [Capture] — 전송 폴더로 보내기
    deleteRequested = Signal(list)          # [Capture] — 삭제
    deleteAfterSendToggled = Signal(bool)   # 메뉴의 '보내기 후 원본 삭제' 체크 변경

    def __init__(self, db, newest_on_top: bool = True, delete_after_send: bool = False, parent=None):
        super().__init__(parent)
        self.db = db
        self.newest_on_top = newest_on_top
        self.delete_after_send = delete_after_send
        self._patient_id = None
        self._filter = "all"
        self._items: list = []
        self._selected: set[int] = set()
        self._widgets: dict[int, ThumbnailWidget] = {}

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

        # 선택 막대: 선택이 있을 때만 보임 — "N장 선택" + 보내기 / 삭제 / 해제
        self.select_bar = QFrame()
        self.select_bar.setObjectName("SelectBar")
        sb = QHBoxLayout(self.select_bar)
        sb.setContentsMargins(8, 4, 4, 4)
        sb.setSpacing(2)
        self.lbl_selected = QLabel("0장 선택")
        self.lbl_selected.setObjectName("SelectCount")
        sb.addWidget(self.lbl_selected)
        sb.addStretch(1)
        self.btn_send = self._bar_button("send", ICON_ACCENT, "선택한 사진을 전송 폴더로 보내기", self._emit_send)
        self.btn_delete = self._bar_button("trash", ICON_RECORD, "선택한 사진 삭제", self._emit_delete)
        self.btn_clear = self._bar_button("x", ICON, "선택 해제", self.clear_selection)
        for b in (self.btn_send, self.btn_delete, self.btn_clear):
            sb.addWidget(b)
        self.select_bar.hide()
        outer.addWidget(self.select_bar)

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
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    @staticmethod
    def _bar_button(icon_name: str, color: str, tip: str, slot) -> QPushButton:
        b = QPushButton()
        b.setObjectName("SelectBarBtn")
        b.setIcon(icons.icon(icon_name, color, 16))
        b.setIconSize(QSize(16, 16))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ---- 공개 API ----
    def set_patient(self, patient_id) -> None:
        if patient_id != self._patient_id:
            self._selected.clear()
        self._patient_id = patient_id
        order = "desc" if self.newest_on_top else "asc"
        self._items = self.db.captures.list_by_patient(patient_id, order=order) if patient_id is not None else []
        self._rebuild()

    def reload(self) -> None:
        """DB 에서 현재 환자의 목록을 다시 읽는다 (보내기·삭제 뒤)."""
        self.set_patient(self._patient_id)

    def add_capture(self, capture) -> None:
        if capture.patient_id != self._patient_id:
            return
        if self.newest_on_top:
            self._items.insert(0, capture)
        else:
            self._items.append(capture)
        self._rebuild()

    def remove_captures(self, captures) -> None:
        ids = {c.id for c in captures}
        self._items = [c for c in self._items if c.id not in ids]
        self._selected -= ids
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

    # ---- 선택 ----
    def selected_captures(self) -> list:
        """선택된 영상 (목록 순서대로)."""
        return [c for c in self._items if c.id in self._selected]

    def selected_count(self) -> int:
        return len(self._selected)

    def is_selected(self, capture) -> bool:
        return capture.id in self._selected

    def set_selected(self, capture, on: bool) -> None:
        if on:
            self._selected.add(capture.id)
        else:
            self._selected.discard(capture.id)
        w = self._widgets.get(capture.id)
        if w is not None:
            w.set_selected(on)
        self._sync_selection_ui()

    def toggle_selected(self, capture) -> None:
        self.set_selected(capture, capture.id not in self._selected)

    def select_all(self) -> None:
        """지금 보이는(필터 적용) 영상을 모두 선택."""
        for c in self.visible_captures():
            self._selected.add(c.id)
            w = self._widgets.get(c.id)
            if w is not None:
                w.set_selected(True)
        self._sync_selection_ui()

    def clear_selection(self) -> None:
        self._selected.clear()
        for w in self._widgets.values():
            w.set_selected(False)
        self._sync_selection_ui()

    def set_delete_after_send(self, on: bool) -> None:
        self.delete_after_send = bool(on)

    # ---- 메뉴 ----
    def build_menu(self, capture=None) -> QMenu:
        """오른쪽 클릭 메뉴. capture 가 아직 선택돼 있지 않으면 먼저 선택에 넣는다."""
        if capture is not None and capture.id not in self._selected:
            self.set_selected(capture, True)
        n = len(self._selected)
        suffix = f" ({n}장)" if n else ""
        m = QMenu(self)
        m.setObjectName("ThumbMenu")
        act_send = QAction(icons.icon("send", ICON_ACCENT, 16), f"전송 폴더로 보내기{suffix}", m)
        act_send.setEnabled(n > 0)
        act_send.triggered.connect(self._emit_send)
        act_del = QAction(icons.icon("trash", ICON_RECORD, 16), f"삭제{suffix}", m)
        act_del.setEnabled(n > 0)
        act_del.triggered.connect(self._emit_delete)
        m.addAction(act_send)
        m.addAction(act_del)
        m.addSeparator()
        act_all = QAction(icons.icon("check-all", ICON, 16), "모두 선택", m)
        act_all.setEnabled(bool(self.visible_captures()))
        act_all.triggered.connect(self.select_all)
        act_none = QAction(icons.icon("deselect", ICON, 16), "선택 해제", m)
        act_none.setEnabled(n > 0)
        act_none.triggered.connect(self.clear_selection)
        m.addAction(act_all)
        m.addAction(act_none)
        m.addSeparator()
        act_auto = QAction("보내기 후 원본 삭제", m)
        act_auto.setCheckable(True)
        act_auto.setChecked(self.delete_after_send)
        act_auto.setToolTip("켜면 보낸 사진은 목록·기본 저장 폴더에서 자동으로 지워지고 전송 폴더에만 남습니다")
        act_auto.toggled.connect(self._on_auto_toggled)
        m.addAction(act_auto)
        self.menu_actions = {"send": act_send, "delete": act_del, "select_all": act_all,
                             "clear": act_none, "delete_after_send": act_auto}
        return m

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.build_menu().exec(event.globalPos())

    # ---- 내부 ----
    def _on_auto_toggled(self, on: bool) -> None:
        self.delete_after_send = on
        self.deleteAfterSendToggled.emit(on)

    def _emit_send(self) -> None:
        caps = self.selected_captures()
        if caps:
            self.sendRequested.emit(caps)

    def _emit_delete(self) -> None:
        caps = self.selected_captures()
        if caps:
            self.deleteRequested.emit(caps)

    def _on_thumb_context(self, capture, pos: QPoint) -> None:
        self.build_menu(capture).exec(pos)

    def _sync_selection_ui(self) -> None:
        n = len(self._selected)
        self.lbl_selected.setText(f"{n}장 선택")
        self.select_bar.setVisible(n > 0)
        self.selectionChanged.emit(n)

    def _rebuild(self) -> None:
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None and w is not self._empty:
                w.deleteLater()
        self._widgets = {}
        existing = {c.id for c in self._items}
        self._selected &= existing                       # 사라진 항목은 선택에서도 제외
        self._badge.setText(str(len(self._items)))
        shown = self.visible_captures()
        if not shown:
            self._empty.setText("환자를 선택하세요" if self._patient_id is None
                                else ("조건에 맞는 영상이 없습니다" if self._items else "촬영 이미지가 없습니다"))
            self._lay.addWidget(self._empty)
            self._empty.show()
            self._sync_selection_ui()
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
            w = ThumbnailWidget(c, selected=c.id in self._selected)
            w.clicked.connect(self.toggle_selected)
            w.activated.connect(self.thumbnailClicked.emit)
            w.contextRequested.connect(self._on_thumb_context)
            self._widgets[c.id] = w
            self._lay.addWidget(w)
        self._sync_selection_ui()
