"""Pro 모드 MULTI 그리드 — 한 환자의 영상을 16장(4×4) / 36장(6×6) 페이지로 표시.

- 클릭: 비교용 선택 (최대 2장, '선택 1/2' 배지)
- 더블클릭: 해당 영상을 단일 보기로 열기
- 썸네일은 원본에서 축소 디코딩(QImageReader.setScaledSize)해 메모리 사용을 억제
"""
from __future__ import annotations

import html
import time
from collections import OrderedDict

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from app.ui.theme import EYE_COLORS

_PREVIEW_MAX = 640
_cache: "OrderedDict[str, QPixmap]" = OrderedDict()


def load_preview(path: str | None) -> QPixmap:
    if not path:
        return QPixmap()
    if path in _cache:
        _cache.move_to_end(path)
        return _cache[path]
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > _PREVIEW_MAX:
        reader.setScaledSize(size.scaled(_PREVIEW_MAX, _PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio))
    pm = QPixmap.fromImage(reader.read())
    _cache[path] = pm
    while len(_cache) > 160:
        _cache.popitem(last=False)
    return pm


class _Cell(QFrame):
    clicked = Signal(int)
    doubleClicked = Signal(int)

    def __init__(self, cap, index: int, number: int, sel_rank: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("MultiCell")
        self.index = index
        self.setProperty("selected", bool(sel_rank))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setMinimumSize(QSize(40, 30))
        self._img.setStyleSheet("background:#000;")
        self._src = load_preview(cap.file_path or cap.thumbnail_path) if cap else QPixmap()
        lay.addWidget(self._img, 1)

        if cap is not None:
            when = (cap.captured_at or "")[2:16].replace("-", ".")
            eye = cap.eye if cap.eye and cap.eye != "NA" else ""
            note = f"&nbsp; <span style='color:#8a94a6'>{html.escape(cap.note)}</span>" if cap.note else ""
            eye_html = (f"<b style='color:{EYE_COLORS.get(eye, '#a3acba')}'>{eye}</b>&nbsp; " if eye else "")
            cap_lbl = QLabel(f"<span style='color:#6b7586'><b>{number}</b></span>&nbsp; {eye_html}{when}{note}")
            cap_lbl.setObjectName("MultiCaption")
            cap_lbl.setTextFormat(Qt.TextFormat.RichText)
            cap_lbl.setToolTip(" · ".join(x for x in (str(number), cap.captured_at or "", eye, cap.note or "") if x))
            lay.addWidget(cap_lbl)
        self._badge = QLabel("", self)
        self._badge.setObjectName("SelBadge")
        self._badge.move(8, 8)
        self.set_rank(sel_rank)
        if cap is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_rank(self, rank: int) -> None:
        """선택 순서(0=미선택) 갱신 — 위젯을 다시 만들지 않아 더블클릭이 유지된다."""
        self.setProperty("selected", bool(rank))
        self._badge.setText(f"선택 {rank}" if rank else "")
        self._badge.adjustSize()
        self._badge.setVisible(bool(rank))
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._src.isNull():
            self._img.setPixmap(self._src.scaled(self._img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.index >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.index >= 0:
            self.doubleClicked.emit(self.index)


class MultiGrid(QWidget):
    openRequested = Signal(int)
    selectionChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._caps: list = []
        self._per = 16
        self._page = 0
        self._sel: list = []
        self._cells: list = []
        self._last_click = None          # (idx, t, 클릭 전 선택) — 더블클릭 시 선택 복원용
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(4)

    # ---- 데이터 ----
    def set_captures(self, caps: list, keep_page: bool = False) -> None:
        self._caps = list(caps)
        self._sel = [i for i in self._sel if i < len(self._caps)] if keep_page else []
        if not keep_page:
            self._page = max(0, self.page_count() - 1)   # 최신 영상이 있는 마지막 페이지
        self._page = min(self._page, max(0, self.page_count() - 1))
        self._rebuild()

    def set_per_page(self, n: int) -> None:
        self._per = 36 if n == 36 else 16
        self._page = min(self._page, max(0, self.page_count() - 1))
        self._rebuild()

    def per_page(self) -> int:
        return self._per

    def page_count(self) -> int:
        return max(1, (len(self._caps) + self._per - 1) // self._per)

    def page(self) -> int:
        return self._page

    def go_page(self, delta: int) -> bool:
        new = min(max(0, self._page + delta), self.page_count() - 1)
        if new == self._page:
            return False
        self._page = new
        self._rebuild()
        return True

    def show_index(self, idx: int) -> None:
        if 0 <= idx < len(self._caps):
            self._page = idx // self._per
            self._rebuild()

    def selection(self) -> list:
        return list(self._sel)

    def page_indices(self) -> list:
        start = self._page * self._per
        return list(range(start, min(start + self._per, len(self._caps))))

    def set_selection(self, idxs: list) -> None:
        self._sel = [i for i in idxs if 0 <= i < len(self._caps)][:2]
        self._rebuild()
        self.selectionChanged.emit(list(self._sel))

    def clear_selection(self) -> None:
        self._sel = []
        self._rebuild()
        self.selectionChanged.emit([])

    # ---- 선택 ----
    def _on_click(self, idx: int) -> None:
        self._last_click = (idx, time.monotonic(), list(self._sel))
        self._toggle(idx)

    def _on_double(self, idx: int) -> None:
        # 더블클릭은 '열기' — 첫 클릭으로 바뀐 선택을 되돌린다
        lc = self._last_click
        if lc and lc[0] == idx and time.monotonic() - lc[1] < 1.0:
            self._sel = lc[2]
            self._refresh_ranks()
            self.selectionChanged.emit(list(self._sel))
        self.openRequested.emit(idx)

    def _toggle(self, idx: int) -> None:
        if idx in self._sel:
            self._sel.remove(idx)
        else:
            self._sel.append(idx)
            if len(self._sel) > 2:
                self._sel.pop(0)
        self._refresh_ranks()
        self.selectionChanged.emit(list(self._sel))

    def _refresh_ranks(self) -> None:
        for cell in self._cells:
            cell.set_rank(self._sel.index(cell.index) + 1 if cell.index in self._sel else 0)

    # ---- 렌더 ----
    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cells = []
        cols = 4 if self._per == 16 else 6
        start = self._page * self._per
        for k in range(self._per):
            idx = start + k
            cap = self._caps[idx] if idx < len(self._caps) else None
            rank = (self._sel.index(idx) + 1) if idx in self._sel else 0
            cell = _Cell(cap, idx if cap else -1, idx + 1, rank)
            if cap is not None:
                cell.clicked.connect(self._on_click)
                cell.doubleClicked.connect(self._on_double)
                self._cells.append(cell)
            r, c = divmod(k, cols)
            self._grid.addWidget(cell, r, c)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        for r in range(self._per // cols):
            self._grid.setRowStretch(r, 1)
