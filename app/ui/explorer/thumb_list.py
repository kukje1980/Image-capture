"""썸네일 목록 (Explorer 판 아래쪽, 또는 오른쪽 세로) — 여러 장 선택(Ctrl/Shift)해서 겹쳐보기·비교·보고서에 쓴다.

가로(아래 칸): 왼쪽 → 오른쪽으로 채우고 줄바꿈.  세로(오른쪽 칸): 위 → 아래 한 줄, 필터는 제목 아래 줄.

각 썸네일에는 안구 배지(OD 파랑 / OS 주황 / OU 보라), 동영상 표시, 촬영 시각이 그려진다.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons
from app.ui.theme import EYE_COLORS

FILTERS = [("all", "전체"), ("OD", "OD"), ("OS", "OS"), ("video", "동영상")]
THUMB = QSize(176, 132)


def thumb_pixmap(cap, size: QSize = THUMB) -> QPixmap:
    src = QPixmap(cap.thumbnail_path or (cap.file_path if cap.media_type == "photo" else ""))
    pm = QPixmap(size)
    pm.fill(QColor("#05070a"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if not src.isNull():
        s = src.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(0, 0, s, (s.width() - size.width()) // 2, (s.height() - size.height()) // 2,
                     size.width(), size.height())
    f = QFont()
    f.setPointSizeF(8.5)
    f.setBold(True)
    p.setFont(f)
    eye = cap.eye if cap.eye in EYE_COLORS else None
    if eye:
        r = QRectF(6, 6, 30, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(EYE_COLORS[eye]))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor("#0b0e13"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, eye)
    if cap.media_type == "video":
        p.drawPixmap(size.width() - 26, 6, icons.pixmap("play", "#ffffff", 18))
    band = QRectF(0, size.height() - 20, size.width(), 20)
    p.fillRect(band, QColor(0, 0, 0, 150))
    p.setPen(QColor("#e7eaf0"))
    f.setBold(False)
    p.setFont(f)
    text = (cap.captured_at or "")[5:16]
    if cap.note:
        text += f"  {cap.note}"
    p.drawText(band.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.end()
    return pm


class ThumbList(QFrame):
    currentChanged = Signal(object)        # Capture | None (방향키 이동 포함)
    picked = Signal(object)                # 사용자가 클릭한 영상 → 크게 보기
    activated = Signal(object)             # 더블클릭 → 보정·측정
    selectionChanged = Signal(list)        # [Capture]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ExplorerThumbs")
        self._all: list = []
        self._caps: list = []
        self._filter = "all"
        self._vertical = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        self.head = QHBoxLayout()
        self.title = QLabel("영상")
        self.title.setObjectName("ThumbTitle")
        self.head.addWidget(self.title)
        self.sel = QLabel("")
        self.sel.setObjectName("Muted")
        self.head.addWidget(self.sel)
        self.head.addStretch(1)
        self.chips = QWidget()                   # 필터 버튼 묶음 — 세로 배치에서는 제목 아래 줄로 내려간다
        cl = QHBoxLayout(self.chips)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.filter_group = QButtonGroup(self)
        self.filter_buttons = {}
        for key, label in FILTERS:
            b = QPushButton(label)
            b.setObjectName("FilterChip")
            b.setCheckable(True)
            b.setMinimumWidth(44)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            self.filter_group.addButton(b)
            self.filter_buttons[key] = b
            cl.addWidget(b)
        self.filter_buttons["all"].setChecked(True)
        self.head.addWidget(self.chips)
        lay.addLayout(self.head)
        self.chips_row = QHBoxLayout()           # 세로 배치일 때 필터가 들어갈 줄
        lay.addLayout(self.chips_row)

        self.list = QListWidget()
        self.list.setObjectName("ThumbList")
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setFlow(QListWidget.Flow.LeftToRight)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setIconSize(THUMB)
        self.list.setSpacing(4)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.list, 1)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemSelectionChanged.connect(self._on_sel)
        self.list.itemClicked.connect(lambda it: self.picked.emit(self._caps[self.list.row(it)]))
        self.list.itemDoubleClicked.connect(lambda it: self.activated.emit(self._caps[self.list.row(it)]))

    # ---- 배치 ----
    def is_vertical(self) -> bool:
        return self._vertical

    def set_vertical(self, on: bool) -> None:
        """True = 오른쪽 세로 칸 (위→아래 한 줄), False = 아래 가로 칸 (왼→오른쪽, 줄바꿈)."""
        self._vertical = bool(on)
        if on:
            self.head.removeWidget(self.chips)
            self.chips_row.addWidget(self.chips)
            self.chips_row.addStretch(1)
            self.list.setFlow(QListWidget.Flow.TopToBottom)
            self.list.setWrapping(False)
            self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            while self.chips_row.count():
                self.chips_row.takeAt(0)
            self.head.addWidget(self.chips)
            self.list.setFlow(QListWidget.Flow.LeftToRight)
            self.list.setWrapping(True)
            self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chips.show()
        self.list.doItemsLayout()

    # ---- 데이터 ----
    def set_captures(self, caps: list, title: str = "영상", keep: bool = False) -> None:
        keep_ids = {c.id for c in self.selected()} if keep else set()
        self._all = list(caps)
        self.title.setText(title)
        self._rebuild(keep_ids)

    def set_filter(self, key: str) -> None:
        self._filter = key
        self.filter_buttons[key].setChecked(True)
        self._rebuild({c.id for c in self.selected()})

    def _rebuild(self, keep_ids: set) -> None:
        f = self._filter
        self._caps = [c for c in self._all
                      if f == "all" or (f == "video" and c.media_type == "video") or c.eye == f]
        self.list.blockSignals(True)
        self.list.clear()
        for c in self._caps:
            it = QListWidgetItem(QIcon(thumb_pixmap(c)), "")
            it.setSizeHint(QSize(THUMB.width() + 10, THUMB.height() + 10))
            it.setToolTip(" · ".join(x for x in (c.captured_at, c.eye if c.eye != "NA" else "", c.note or "") if x))
            self.list.addItem(it)
            if c.id in keep_ids:
                it.setSelected(True)
        self.list.blockSignals(False)
        if self._caps and not keep_ids:
            self.list.setCurrentRow(0)
        self._on_sel()
        self._on_row(self.list.currentRow())

    def captures(self) -> list:
        return list(self._caps)

    def count(self) -> int:
        return len(self._caps)

    def current(self):
        i = self.list.currentRow()
        return self._caps[i] if 0 <= i < len(self._caps) else None

    def selected(self) -> list:
        rows = sorted(self.list.row(it) for it in self.list.selectedItems())
        return [self._caps[r] for r in rows if 0 <= r < len(self._caps)]

    def select_ids(self, ids: list) -> None:
        self.list.clearSelection()
        for i, c in enumerate(self._caps):
            if c.id in ids:
                self.list.item(i).setSelected(True)
                self.list.setCurrentRow(i, self.list.selectionModel().SelectionFlag.Select)

    def _on_row(self, row: int) -> None:
        self.currentChanged.emit(self._caps[row] if 0 <= row < len(self._caps) else None)

    def _on_sel(self) -> None:
        sel = self.selected()
        self.sel.setText(f"· {len(self._caps)}장" + (f" · 선택 {len(sel)}" if len(sel) > 1 else ""))
        self.selectionChanged.emit(sel)
