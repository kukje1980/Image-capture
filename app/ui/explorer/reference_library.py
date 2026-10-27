"""참조 영상 라이브러리 — 분류별 대표 영상을 모아 두고, 지금 환자 영상과 나란히 비교한다.

왼쪽: 분류 목록   가운데: 썸네일   오른쪽: 큰 미리보기 · 제목 · 설명
  전체               등록한 참조 영상 + 샘플 사진
  (등록한 분류들)     메인 창에서 '참조 등록' 한 영상 (라이브러리 폴더 사본)
  ── 샘플 사진 ──     설정·파일 메뉴의 '샘플 사진 가져오기' 로 등록한 질환별 샘플 (원본 그대로, 읽기 전용)
'현재 영상과 비교' 는 메인 창에서 고른 환자 영상과 참조 영상을 비교 창으로 연다.
"""
from __future__ import annotations

import html
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

from app.services import sample_import
from app.ui.explorer.compare_dialog import CompareDialog
from app.ui.explorer.dialogs import ReferenceDialog
from app.ui.pro.image_canvas import ImageCanvas
from app.ui.pro.pro_workspace import load_bgr

ALL = ("all", None)
LIBRARY = "library"
SAMPLE = "sample"
_GRID_TITLE_MAX = 34


def _short(text: str, n: int = _GRID_TITLE_MAX) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


class ReferenceLibraryDialog(QDialog):
    def __init__(self, db, parent=None, current=None, on_import_samples=None, on_register=None):
        """current: (bgr, caption) — 비교할 환자 영상 (없으면 비교 버튼 비활성).
        on_import_samples(parent) — '샘플 사진 가져오기' 를 실행하고 가져왔으면 True (없으면 버튼 숨김).
        on_register(parent) — 현재 환자 영상을 참조로 등록하고 등록했으면 True (없으면 버튼 숨김)."""
        super().__init__(parent)
        self.setWindowTitle("참조 영상 라이브러리")
        self.resize(1180, 740)
        self.db = db
        self._current = current
        self._on_import_samples = on_import_samples
        self._on_register = on_register
        self._refs = []

        self.cats = QListWidget()
        self.b_samples = QPushButton("샘플 사진 가져오기…")
        self.b_samples.setToolTip("받아 둔 질환별 샘플 사진 폴더(질환별 하위 폴더 + metadata.json)를 골라 등록합니다")
        self.b_samples.setVisible(on_import_samples is not None)
        self.b_register = QPushButton("현재 영상 참조 등록…")
        self.b_register.setToolTip("지금 고른 환자 영상을 분류·제목·설명과 함께 참조 영상으로 등록합니다 (사본 보관)")
        self.b_register.setVisible(on_register is not None and current is not None)
        left = QWidget()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.cats, 1)
        ll.addWidget(self.b_register)
        ll.addWidget(self.b_samples)

        self.search = QLineEdit()
        self.search.setPlaceholderText("제목 · 설명 · 질환 검색")
        self.search.setClearButtonEnabled(True)
        self.grid = QListWidget()
        self.grid.setObjectName("ThumbList")
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(160, 120))
        self.grid.setGridSize(QSize(176, 168))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSpacing(6)
        self.grid.setWordWrap(True)

        self.preview = ImageCanvas()
        self.preview._placeholder = ("참조 영상이 없습니다 — 메인 창에서 영상을 고르고 '참조 등록' 하거나 "
                                     "'샘플 사진 가져오기'")
        self.info = QLabel()
        self.info.setObjectName("ExplorerInfo")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setOpenExternalLinks(True)
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
        lay.addWidget(left)
        lay.addWidget(split, 1)

        self.cats.currentRowChanged.connect(lambda *_: self._load_refs())
        self.search.textChanged.connect(lambda *_: self._load_refs())
        self.grid.currentRowChanged.connect(self._on_pick)
        self.grid.itemDoubleClicked.connect(lambda *_: self.compare())
        self.b_compare.clicked.connect(self.compare)
        self.b_edit.clicked.connect(self.edit_current)
        self.b_delete.clicked.connect(self.delete_current)
        self.b_samples.clicked.connect(self.import_samples)
        self.b_register.clicked.connect(self.register_current)
        self.reload()

    # ---- 목록 ----
    def _add_cat(self, text: str, key, selectable: bool = True) -> QListWidgetItem:
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, key)
        if not selectable:                       # 구역 제목 (고를 수 없음)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        self.cats.addItem(it)
        return it

    def reload(self) -> None:
        keep = self.current_key()
        self.cats.blockSignals(True)
        self.cats.clear()
        lib_cats = [(c, len(self.db.references.list(category=c))) for c in self.db.references.categories()]
        sample_cats = sample_import.sample_categories(self.db)
        total = sum(n for _, n in lib_cats) + sum(n for _, n in sample_cats)
        self._add_cat(f"전체  ({total})", ALL)
        if lib_cats and sample_cats:
            self._add_cat("등록한 참조 영상", None, selectable=False)
        for c, n in lib_cats:
            self._add_cat(f"{c}  ({n})", (LIBRARY, c))
        if sample_cats:
            self._add_cat("샘플 사진", None, selectable=False)
            for c, n in sample_cats:
                self._add_cat(f"{c}  ({n})", (SAMPLE, c))
        row = 0
        for i in range(self.cats.count()):
            if self.cats.item(i).data(Qt.ItemDataRole.UserRole) == keep:
                row = i
        self.cats.setCurrentRow(row)
        self.cats.blockSignals(False)
        self._load_refs()

    def current_key(self):
        it = self.cats.currentItem()
        key = it.data(Qt.ItemDataRole.UserRole) if it else None
        return tuple(key) if key else ALL

    def current_category(self):
        """지금 고른 분류 이름 (전체면 None)."""
        return self.current_key()[1]

    def select_category(self, source: str, category: str) -> bool:
        for i in range(self.cats.count()):
            key = self.cats.item(i).data(Qt.ItemDataRole.UserRole)
            if key and tuple(key) == (source, category):
                self.cats.setCurrentRow(i)
                return True
        return False

    def _load_refs(self) -> None:
        source, category = self.current_key()
        q = self.search.text().strip()
        refs = []
        if source in ("all", LIBRARY):
            refs += self.db.references.list(category=category, q=q)
        if source in ("all", SAMPLE):
            refs += sample_import.sample_references(self.db, category=category, q=q)
        self._refs = refs
        self.grid.clear()
        for r in self._refs:
            pm = QPixmap(r.thumbnail_path or r.file_path)
            label = r.title or r.category or ""
            it = QListWidgetItem(QIcon(pm), _short(f"샘플 · {label}" if r.is_sample else label))
            it.setToolTip("\n".join(x for x in (r.category, r.title, r.description) if x))
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
        editable = has and not r.is_sample          # 샘플 사진은 원본 그대로 (수정·삭제는 환자 화면에서)
        self.b_edit.setEnabled(editable)
        self.b_delete.setEnabled(editable)
        tip = "샘플 사진은 원본 그대로 보관됩니다 (정보 수정·삭제는 '샘플 · 질환명' 환자에서)" if has and r.is_sample else ""
        self.b_edit.setToolTip(tip)
        self.b_delete.setToolTip(tip)
        if not has:
            self.preview.set_image(None)
            self.info.setText("")
            return
        self.preview.set_image(load_bgr(r.file_path))
        self.info.setText(self._info_html(r))

    @staticmethod
    def _info_html(r) -> str:
        e = html.escape
        rows = [f"<b>{e(r.title or '(제목 없음)')}</b>"]
        if r.is_sample:
            rows.append(f"분류: 샘플 사진 · {e(r.category or '-')} &nbsp;(교육·참고용, 실제 환자 아님)")
        else:
            rows.append(f"분류: {e(r.category or '-')}<br>등록: {e(r.created_at or '-')}")
        for line in (r.description or "").splitlines():
            line = line.strip()
            if line.startswith(("http://", "https://")):
                rows.append(f'<a href="{e(line)}" style="color:#5aa2ff">{e(line)}</a>')
            elif line:
                rows.append(e(line))
        return "<br>".join(rows)

    # ---- 동작 ----
    def compare(self):
        r = self.current_ref()
        if r is None or self._current is None:
            return None
        img = load_bgr(r.file_path)
        if img is None:
            QMessageBox.warning(self, "참조 영상", "이미지를 불러올 수 없습니다.")
            return None
        head = "샘플" if r.is_sample else "참조"
        cap = " · ".join(x for x in (head, r.category, _short(r.title or "", 48)) if x)
        self._compare_dlg = CompareDialog([self._current, (img, cap)], self, title="환자 영상 ↔ 참조 영상")
        self._compare_dlg.show()
        return self._compare_dlg

    def import_samples(self) -> None:
        if self._on_import_samples is not None and self._on_import_samples(self):
            self.reload()

    def register_current(self) -> None:
        if self._on_register is not None and self._on_register(self):
            self.reload()

    def edit_current(self) -> None:
        r = self.current_ref()
        if r is None or r.is_sample:
            return
        dlg = ReferenceDialog(self, self.db.references.categories(), r.category or "", r.title or "",
                              r.description or "")
        if dlg.exec():
            r.category, r.title, r.description = dlg.values()
            self.db.references.update(r)
            self.reload()

    def delete_current(self, confirm: bool = True) -> None:
        r = self.current_ref()
        if r is None or r.is_sample:
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
