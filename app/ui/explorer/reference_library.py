"""참조 영상 라이브러리 — 분류별 대표 영상을 모아 두고, 지금 환자 영상과 나란히 비교한다.

왼쪽: 분류 목록(전체 + 각 분류, 장수)   가운데: 썸네일   오른쪽: 큰 미리보기 · 제목 · 설명
'현재 영상과 비교' 는 메인 창에서 고른 환자 영상과 참조 영상을 비교 창으로 연다.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.explorer.compare_dialog import CompareDialog
from app.ui.explorer.dialogs import ReferenceDialog
from app.ui.pro.image_canvas import ImageCanvas
from app.ui.pro.pro_workspace import load_bgr

ALL = "__all__"


class ReferenceLibraryDialog(QDialog):
    def __init__(self, db, parent=None, current=None):
        """current: (bgr, caption) — 비교할 환자 영상 (없으면 비교 버튼 비활성)."""
        super().__init__(parent)
        self.setWindowTitle("참조 영상 라이브러리")
        self.resize(1180, 740)
        self.db = db
        self._current = current
        self._refs = []

        self.cats = QListWidget()
        self.cats.setFixedWidth(200)
        self.search = QLineEdit()
        self.search.setPlaceholderText("제목 · 설명 검색")
        self.search.setClearButtonEnabled(True)
        self.grid = QListWidget()
        self.grid.setObjectName("ThumbList")
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(160, 120))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSpacing(6)
        self.grid.setWordWrap(True)

        self.preview = ImageCanvas()
        self.preview._placeholder = "참조 영상이 없습니다 — 메인 창에서 영상을 고르고 '참조 등록'"
        self.info = QLabel()
        self.info.setObjectName("ExplorerInfo")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.b_compare = QPushButton("현재 영상과 비교")
        self.b_compare.setObjectName("Primary")
        self.b_compare.setEnabled(False)
        self.b_edit = QPushButton("정보 수정")
        self.b_delete = QPushButton("삭제")
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.preview, 1)
        rl.addWidget(self.info)
        br = QHBoxLayout()
        br.addWidget(self.b_edit)
        br.addWidget(self.b_delete)
        br.addStretch(1)
        br.addWidget(self.b_compare)
        rl.addLayout(br)

        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.search)
        ml.addWidget(self.grid, 1)
        split = QSplitter()
        split.addWidget(mid)
        split.addWidget(right)
        split.setSizes([620, 420])

        lay = QHBoxLayout(self)
        lay.addWidget(self.cats)
        lay.addWidget(split, 1)

        self.cats.currentRowChanged.connect(lambda *_: self._load_refs())
        self.search.textChanged.connect(lambda *_: self._load_refs())
        self.grid.currentRowChanged.connect(self._on_pick)
        self.grid.itemDoubleClicked.connect(lambda *_: self.compare())
        self.b_compare.clicked.connect(self.compare)
        self.b_edit.clicked.connect(self.edit_current)
        self.b_delete.clicked.connect(self.delete_current)
        self.reload()

    # ---- 목록 ----
    def reload(self) -> None:
        keep = self.current_category()
        self.cats.blockSignals(True)
        self.cats.clear()
        total = len(self.db.references.list())
        it = QListWidgetItem(f"전체  ({total})")
        it.setData(Qt.ItemDataRole.UserRole, ALL)
        self.cats.addItem(it)
        row = 0
        for i, c in enumerate(self.db.references.categories(), start=1):
            n = len(self.db.references.list(category=c))
            ci = QListWidgetItem(f"{c}  ({n})")
            ci.setData(Qt.ItemDataRole.UserRole, c)
            self.cats.addItem(ci)
            if c == keep:
                row = i
        self.cats.setCurrentRow(row)
        self.cats.blockSignals(False)
        self._load_refs()

    def current_category(self):
        it = self.cats.currentItem()
        v = it.data(Qt.ItemDataRole.UserRole) if it else ALL
        return None if v == ALL else v

    def _load_refs(self) -> None:
        self._refs = self.db.references.list(category=self.current_category(), q=self.search.text().strip())
        self.grid.clear()
        for r in self._refs:
            pm = QPixmap(r.thumbnail_path or r.file_path)
            it = QListWidgetItem(QIcon(pm), r.title or r.category or "")
            it.setToolTip(f"{r.category}\n{r.description or ''}")
            self.grid.addItem(it)
        if self._refs:
            self.grid.setCurrentRow(0)
        else:
            self._on_pick(-1)

    def refs(self) -> list:
        return list(self._refs)

    def current_ref(self):
        i = self.grid.currentRow()
        return self._refs[i] if 0 <= i < len(self._refs) else None

    def _on_pick(self, row: int) -> None:
        r = self.current_ref()
        has = r is not None
        self.b_compare.setEnabled(has and self._current is not None)
        self.b_edit.setEnabled(has)
        self.b_delete.setEnabled(has)
        if not has:
            self.preview.set_image(None)
            self.info.setText("")
            return
        self.preview.set_image(load_bgr(r.file_path))
        self.info.setText(f"<b>{r.title or '(제목 없음)'}</b><br>분류: {r.category or '-'}"
                          f"<br>등록: {r.created_at or '-'}<br>{(r.description or '').replace(chr(10), '<br>')}")

    # ---- 동작 ----
    def compare(self) -> None:
        r = self.current_ref()
        if r is None or self._current is None:
            return
        img = load_bgr(r.file_path)
        if img is None:
            QMessageBox.warning(self, "참조 영상", "이미지를 불러올 수 없습니다.")
            return
        cap = f"참조 · {r.category} · {r.title or ''}".rstrip(" ·")
        self._compare_dlg = CompareDialog([self._current, (img, cap)], self, title="환자 영상 ↔ 참조 영상")
        self._compare_dlg.show()

    def edit_current(self) -> None:
        r = self.current_ref()
        if r is None:
            return
        dlg = ReferenceDialog(self, self.db.references.categories(), r.category or "", r.title or "",
                              r.description or "")
        if dlg.exec():
            r.category, r.title, r.description = dlg.values()
            self.db.references.update(r)
            self.reload()

    def delete_current(self, confirm: bool = True) -> None:
        r = self.current_ref()
        if r is None:
            return
        if confirm and QMessageBox.question(self, "삭제", "이 참조 영상을 라이브러리에서 지울까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        paths = self.db.references.delete(r.id) or {}
        for p in paths.values():
            try:
                if p and os.path.isfile(p):
                    os.remove(p)                     # 라이브러리 사본 (환자 원본은 그대로)
            except OSError:
                pass
        self.reload()
