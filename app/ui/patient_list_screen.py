"""환자 목록 화면 — 홈의 '환자 목록' 타일(또는 단축키 L)로 연다.

검색(이름 · 차트번호 · 연락처) + 표(이름 · 차트번호 · 성별/나이 · 생년월일 · 진단명 · 담당의 · 사진 수 · 최근 촬영).
행을 한 번 누르면 고르고, 두 번 누르거나 '촬영 시작'을 누르면 그 환자로 촬영 화면에 간다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons
from app.ui.patient_panel import age_of
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT

_SEX = {"M": "남", "F": "여", "O": "기타"}
COLUMNS = ["이름", "차트번호", "성별 · 나이", "생년월일", "진단명", "담당의", "사진", "최근 촬영"]


class PatientListScreen(QWidget):
    openCapture = Signal(int)     # 환자 id → 촬영 화면
    openExam = Signal(int)        # 환자 id → 검사 기록
    newPatient = Signal()
    editPatient = Signal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._rows: list = []        # 표에 보이는 Patient 순서
        self._current_id: int | None = None

        panel = QFrame()
        panel.setObjectName("Panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("환자 목록")
        title.setObjectName("BrandTitle")
        self.badge = QLabel("0")
        self.badge.setObjectName("CountBadge")
        head.addWidget(title)
        head.addWidget(self.badge)
        head.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름 · 차트번호 · 연락처 검색")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(280)
        self.search.addAction(icons.icon("search", ICON, 16), QLineEdit.ActionPosition.LeadingPosition)
        head.addWidget(self.search)
        head.addStretch(1)
        self.btn_new = self._btn("신규 환자", "user-plus", ICON_ON_ACCENT, "Primary")
        self.btn_edit = self._btn("정보 수정", "user-edit", ICON)
        self.btn_exam = self._btn("검사 기록", "clipboard", ICON)
        self.btn_go = self._btn("촬영 시작", "camera", ICON_ON_ACCENT, "Primary")
        for b in (self.btn_new, self.btn_edit, self.btn_exam, self.btn_go):
            head.addWidget(b)
        lay.addLayout(head)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("PatientTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setHighlightSections(False)
        lay.addWidget(self.table, 1)
        self.empty = QLabel("")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        hint = QLabel("행을 두 번 누르면 그 환자로 촬영을 시작합니다")
        hint.setObjectName("Muted")
        lay.addWidget(hint)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(panel)

        self.search.textChanged.connect(lambda _t: self.reload())
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._go(r))
        self.btn_go.clicked.connect(lambda: self._go(self.table.currentRow()))
        self.btn_exam.clicked.connect(lambda: self._emit_selected(self.openExam))
        self.btn_edit.clicked.connect(lambda: self._emit_selected(self.editPatient))
        self.btn_new.clicked.connect(lambda: self.newPatient.emit())
        self.reload()

    @staticmethod
    def _btn(text, icon_name, color, obj=None) -> QPushButton:
        b = QPushButton(icons.gap(text))
        if obj:
            b.setObjectName(obj)
        b.setIcon(icons.icon(icon_name, color, 16))
        b.setIconSize(QSize(16, 16))
        b.setMinimumHeight(36)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    # ---- 공개 ----
    def set_current(self, pid: int | None) -> None:
        """지금 선택된 환자를 표에서 미리 골라 둔다."""
        self._current_id = pid
        self._select_id(pid)

    def reload(self) -> None:
        q = self.search.text().strip()
        self._rows = list(self.db.patients.search(q) if q else self.db.patients.list_all())
        stats = self.db.captures.summary_by_patient()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))
        for r, p in enumerate(self._rows):
            n, last = stats.get(p.id, (0, None))
            age = age_of(p.birth_date)
            sa = " · ".join(x for x in (_SEX.get(p.sex or "", ""), f"{age}세" if age is not None else "") if x)
            vals = [p.name, p.chart_no or "-", sa or "-", p.birth_date or "-", p.diagnosis or "-",
                    p.doctor or "-", str(n), (last or "")[:16] or "-"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, p.id)
                if c == 6:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, it)
        self.badge.setText(str(len(self._rows)))
        self.empty.setVisible(not self._rows)
        self.empty.setText("검색 결과가 없습니다" if q else "등록된 환자가 없습니다 · '신규 환자'로 등록하세요")
        self._select_id(self._current_id)
        self._sync_buttons()

    def selected_id(self) -> int | None:
        r = self.table.currentRow()
        if 0 <= r < len(self._rows) and self.table.selectionModel().hasSelection():
            return self._rows[r].id
        return None

    # ---- 내부 ----
    def _select_id(self, pid) -> None:
        for r, p in enumerate(self._rows):
            if p.id == pid:
                self.table.selectRow(r)
                self.table.scrollToItem(self.table.item(r, 0))
                return
        self.table.clearSelection()

    def _sync_buttons(self) -> None:
        on = self.selected_id() is not None
        for b in (self.btn_edit, self.btn_exam, self.btn_go):
            b.setEnabled(on)

    def _go(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            self.openCapture.emit(self._rows[row].id)

    def _emit_selected(self, signal) -> None:
        pid = self.selected_id()
        if pid is not None:
            signal.emit(pid)
