"""환자 › 검사 트리 (Explorer 판 왼쪽 패널).

검색: 항목(전체 · 이름 · 차트번호 · 진단명 · 병력·소견)을 고르고 입력 — 검사 소견·메모까지 찾는다.
환자를 고르면 모든 영상, 검사를 고르면 그 검사의 영상만 아래 썸네일 목록에 나온다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from app.db.patients_dao import PatientsDAO
from app.ui import icons
from app.ui.patient_panel import age_of
from app.ui.theme import ICON

_SEX = {"M": "남", "F": "여", "O": "기타"}
ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_OBJ = Qt.ItemDataRole.UserRole + 1


def _esc(v) -> str:
    return (str(v) if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class PatientTree(QFrame):
    selectionChanged = Signal(object, object)    # Patient | None, Exam | None

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setObjectName("ExplorerSide")
        self.db = db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.field = QComboBox()
        for k, label in PatientsDAO.SEARCH_FIELDS.items():
            self.field.addItem(label, k)
        self.field.setFixedWidth(96)
        self.search = QLineEdit()
        self.search.setPlaceholderText("환자 검색")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", ICON, 16), QLineEdit.ActionPosition.LeadingPosition)
        row.addWidget(self.field)
        row.addWidget(self.search, 1)
        lay.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        lay.addWidget(self.tree, 1)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        lay.addWidget(self.count)
        self.info = QLabel()
        self.info.setObjectName("ExplorerInfo")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.info.setMinimumHeight(120)
        lay.addWidget(self.info)

        self.search.textChanged.connect(lambda *_: self.reload())
        self.field.currentIndexChanged.connect(lambda *_: self.reload())
        self.tree.itemExpanded.connect(self._fill_exams)
        self.tree.currentItemChanged.connect(self._on_current)
        self.reload()

    # ---- 목록 ----
    def reload(self, patient_id: int | None = None, exam_id: int | None = None) -> None:
        if patient_id is None:
            p, e = self.current_patient(), self.current_exam()
            patient_id, exam_id = (p.id if p else None), (e.id if e else exam_id)
        self.tree.blockSignals(True)
        self.tree.clear()
        patients = self.db.patients.search_by(self.search.text(), self.field.currentData())
        for p in patients:
            it = QTreeWidgetItem([self._patient_text(p)])
            it.setData(0, ROLE_KIND, "patient")
            it.setData(0, ROLE_OBJ, p)
            it.setIcon(0, icons.icon("user", ICON, 16))
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self.tree.addTopLevelItem(it)
        self.count.setText(f"환자 {len(patients)}명")
        self.tree.blockSignals(False)
        if not self.select(patient_id, exam_id) and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        elif not self.tree.topLevelItemCount():
            self._on_current(None, None)

    @staticmethod
    def _patient_text(p) -> str:
        return f"{p.name}   {p.chart_no or ''}".rstrip()

    @staticmethod
    def _exam_text(e) -> str:
        diag = f"  · {e.diagnosis}" if e.diagnosis else ""
        return f"{e.exam_date}  {e.title or ''}  ({e.n_captures}){diag}"

    def _fill_exams(self, item: QTreeWidgetItem) -> None:
        if item.data(0, ROLE_KIND) != "patient" or item.childCount():
            return
        p = item.data(0, ROLE_OBJ)
        blk = self.tree.blockSignals(True)
        for e in self.db.exams.list_by_patient(p.id):
            ch = QTreeWidgetItem([self._exam_text(e)])
            ch.setData(0, ROLE_KIND, "exam")
            ch.setData(0, ROLE_OBJ, e)
            ch.setIcon(0, icons.icon("folder", ICON, 16))
            item.addChild(ch)
        if not item.childCount():
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
        self.tree.blockSignals(blk)

    def select(self, patient_id, exam_id=None) -> bool:
        if patient_id is None:
            return False
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, ROLE_OBJ).id != patient_id:
                continue
            target = it
            if exam_id is not None:
                self._fill_exams(it)
                it.setExpanded(True)
                for j in range(it.childCount()):
                    if it.child(j).data(0, ROLE_OBJ).id == exam_id:
                        target = it.child(j)
            if self.tree.currentItem() is target:
                self._on_current(target, None)
            else:
                self.tree.setCurrentItem(target)          # → currentItemChanged → _on_current
            return True
        return False

    def refresh_exams(self) -> None:
        """현재 환자의 검사 목록(장수 등)만 다시 읽는다."""
        p, e = self.current_patient(), self.current_exam()
        item = self._patient_item()
        if item is None:
            return
        blk = self.tree.blockSignals(True)
        item.takeChildren()
        item.setData(0, ROLE_OBJ, self.db.patients.get(p.id) or p)
        item.setText(0, self._patient_text(item.data(0, ROLE_OBJ)))
        self._fill_exams(item)
        item.setExpanded(True)
        target = item
        for j in range(item.childCount()):
            if e is not None and item.child(j).data(0, ROLE_OBJ).id == e.id:
                target = item.child(j)
        self.tree.setCurrentItem(target)
        self.tree.blockSignals(blk)
        self._render_info()

    # ---- 선택 ----
    def _patient_item(self):
        it = self.tree.currentItem()
        if it is not None and it.data(0, ROLE_KIND) == "exam":
            it = it.parent()
        return it

    def current_patient(self):
        it = self._patient_item()
        return it.data(0, ROLE_OBJ) if it is not None else None

    def current_exam(self):
        it = self.tree.currentItem()
        return it.data(0, ROLE_OBJ) if it is not None and it.data(0, ROLE_KIND) == "exam" else None

    def _on_current(self, cur, _prev) -> None:
        if cur is not None and cur.data(0, ROLE_KIND) == "patient":
            self._fill_exams(cur)
            cur.setExpanded(True)
        self._render_info()
        self.selectionChanged.emit(self.current_patient(), self.current_exam())

    def _render_info(self) -> None:
        p, e = self.current_patient(), self.current_exam()
        if p is None:
            self.info.setText("환자를 선택하거나 <b>새 환자</b>를 등록하세요.")
            return
        meta = [x for x in (_SEX.get(p.sex or "", ""), p.birth_date or "") if x]
        age = age_of(p.birth_date)
        if age is not None:
            meta.append(f"{age}세")
        rows = [f"<b style='font-size:14px'>{_esc(p.name)}</b> &nbsp;<span>{_esc(p.chart_no or '')}</span>",
                " · ".join(_esc(m) for m in meta) or "-",
                f"진단명: <b>{_esc(p.diagnosis or '-')}</b>  · 담당의: {_esc(p.doctor or '-')}"]
        if p.symptoms:
            rows.append(f"증상: {_esc(p.symptoms)}")
        if e is not None:
            rows.append("<hr>")
            rows.append(f"<b>{_esc(e.exam_date)}</b> {_esc(e.title or '')} · 영상 {e.n_captures}장")
            if e.diagnosis:
                rows.append(f"소견: <b>{_esc(e.diagnosis)}</b>")
            if e.memo:
                rows.append(f"메모: {_esc(e.memo)}")
        self.info.setText("<br>".join(rows))
