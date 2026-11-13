"""환자 목록 화면 — 앱의 첫 화면.

왼쪽: 검색(이름·차트번호·진단명) + 기간(전체/오늘/최근 7일, 최근 검사일 기준) + 신규 환자 + 환자 표.
      행을 누르면 그 환자가 앱 전체의 '지금 환자'가 되고, 두 번 누르거나 Enter 면 안저 검토 화면이 열린다.
오른쪽: 고른 환자의 정보 + 검사 목록(날짜별, 최신 먼저). 체크한 검사가 검토 화면의 '현재' 검사가 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui import icons
from app.ui.patient_dialog import PatientDialog
from app.ui.patient_panel import _SEX, age_of, edit_patient, sex_age
from app.ui.theme import ICON, ICON_ON_ACCENT
from app.ui.thumbnail_widget import _load_pixmap

COLUMNS = ["차트번호", "이름", "성별 · 나이", "진단명", "최근 검사", "검사 수"]
RANGES = [("all", "전체"), ("today", "오늘"), ("week", "최근 7일")]
FOOT_HINT = "행을 누르면 오른쪽에 검사 목록이 뜨고, 두 번 누르면(또는 Enter) 바로 검토 화면이 열립니다."
_MAX_THUMBS = 7
_THUMB_W, _THUMB_H = 48, 36


def _dot(day: str | None) -> str:
    return (day or "").replace("-", ".")


@dataclass
class Exam:
    """하루치 검사 (그날 찍거나 불러온 영상 묶음)."""
    day: str
    captures: list = field(default_factory=list)

    @property
    def fundus(self) -> int:
        return sum(1 for c in self.captures if c.media_type == "photo" and c.modality == "fundus")

    @property
    def slit(self) -> int:
        return sum(1 for c in self.captures if c.media_type == "photo" and c.modality != "fundus")

    @property
    def videos(self) -> int:
        return sum(1 for c in self.captures if c.media_type == "video")

    def summary(self) -> str:
        """'안저 2장 · 슬릿램프 3장 · 동영상 1개'."""
        bits = []
        if self.fundus:
            bits.append(f"안저 {self.fundus}장")
        if self.slit:
            bits.append(f"슬릿램프 {self.slit}장")
        if self.videos:
            bits.append(f"동영상 {self.videos}개")
        return " · ".join(bits)


def group_exams(captures: list) -> list[Exam]:
    """영상 목록(최신 먼저) → 날짜별 검사 목록(최신 먼저)."""
    exams: dict[str, Exam] = {}
    for c in captures:
        day = (c.captured_at or "")[:10]
        exams.setdefault(day, Exam(day)).captures.append(c)
    return sorted(exams.values(), key=lambda e: e.day, reverse=True)


class _Table(QTableWidget):
    enterPressed = Signal()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enterPressed.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class PatientListScreen(QWidget):
    patientSelected = Signal(object)        # Patient | None — 앱 전체의 지금 환자
    openReviewRequested = Signal()          # 검토 화면 열기 (지금 환자 · 체크한 검사)
    importRequested = Signal()              # 안저 불러오기
    captureRequested = Signal()             # 촬영 화면으로
    patientEdited = Signal(object)          # 정보 수정 저장됨

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setObjectName("PatientListScreen")
        self.db = db
        self._all: list = []                # PatientSummary 전체
        self._shown: list = []              # 조건에 맞는 PatientSummary
        self._patient = None                # 지금 환자
        self._range = "all"
        self._exams: list[Exam] = []
        self._checked_day: str | None = None
        self._build()
        self.reload()

    # ================= UI =================
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ---- 왼쪽: 목록 ----
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 10)
        ll.setSpacing(10)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름 · 차트번호 · 진단명 검색")
        self.search.addAction(icons.icon("search", ICON, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        seg = QFrame()
        seg.setObjectName("ProSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(2)
        self._range_group = QButtonGroup(self)
        self.range_buttons: dict[str, QPushButton] = {}
        for key, text in RANGES:
            b = QPushButton(text)
            b.setObjectName("ProSegBtn")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip("최근 검사일 기준으로 환자 거르기")
            b.clicked.connect(lambda _=False, k=key: self.set_range(k))
            self._range_group.addButton(b)
            self.range_buttons[key] = b
            sl.addWidget(b)
        self.range_buttons["all"].setChecked(True)
        self.btn_new = QPushButton(icons.gap("신규 환자"))
        self.btn_new.setObjectName("Primary")
        self.btn_new.setIcon(icons.icon("plus", ICON_ON_ACCENT, 16))
        self.btn_new.setIconSize(QSize(15, 15))
        self.btn_new.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tools.addWidget(self.search, 1)
        tools.addWidget(seg)
        tools.addWidget(self.btn_new)
        ll.addLayout(tools)

        self.table = _Table(0, len(COLUMNS))
        self.table.setObjectName("PatientTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setTabKeyNavigation(False)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, mode in ((0, QHeaderView.ResizeMode.ResizeToContents), (1, QHeaderView.ResizeMode.Stretch),
                          (2, QHeaderView.ResizeMode.ResizeToContents), (3, QHeaderView.ResizeMode.Stretch),
                          (4, QHeaderView.ResizeMode.ResizeToContents), (5, QHeaderView.ResizeMode.ResizeToContents)):
            hh.setSectionResizeMode(col, mode)
        ll.addWidget(self.table, 1)
        self.lbl_rows_empty = QLabel("조건에 맞는 환자가 없습니다")
        self.lbl_rows_empty.setObjectName("Muted")
        self.lbl_rows_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_rows_empty.setMinimumHeight(120)
        self.lbl_rows_empty.hide()
        ll.addWidget(self.lbl_rows_empty, 1)
        foot = QLabel(FOOT_HINT)
        foot.setObjectName("Muted")
        ll.addWidget(foot)
        root.addWidget(left, 3)

        # ---- 오른쪽: 환자 정보 + 검사 목록 ----
        right = QFrame()
        right.setObjectName("Panel")
        right.setMinimumWidth(380)
        right.setMaximumWidth(520)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 14, 14, 12)
        rl.setSpacing(10)
        self.lbl_no_patient = QLabel("환자를 선택하세요")
        self.lbl_no_patient.setObjectName("Muted")
        self.lbl_no_patient.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(self.lbl_no_patient, 1)

        self.detail = QWidget()
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)
        card = QFrame()
        card.setObjectName("ProCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.avatar = QLabel()
        self.avatar.setObjectName("Avatar")
        self.avatar.setFixedSize(38, 38)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nb = QVBoxLayout()
        nb.setSpacing(0)
        self.lbl_name = QLabel()
        self.lbl_name.setObjectName("PatientName")
        self.lbl_chart = QLabel()
        self.lbl_chart.setObjectName("ChartNo")
        nb.addWidget(self.lbl_name)
        nb.addWidget(self.lbl_chart)
        self.btn_edit = QPushButton(icons.gap("정보 수정"))
        self.btn_edit.setIcon(icons.icon("edit", ICON, 16))
        self.btn_edit.setIconSize(QSize(15, 15))
        self.btn_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.addWidget(self.avatar)
        head.addLayout(nb, 1)
        head.addWidget(self.btn_edit)
        cl.addLayout(head)
        kv = QGridLayout()
        kv.setHorizontalSpacing(14)
        kv.setVerticalSpacing(5)
        kv.setColumnStretch(1, 1)
        self.kv: dict[str, QLabel] = {}
        for r, key in enumerate(("생년월일", "성별", "진단명", "담당의", "메모")):
            k = QLabel(key)
            k.setObjectName("Muted")
            v = QLabel("—")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            kv.addWidget(k, r, 0, Qt.AlignmentFlag.AlignTop)
            kv.addWidget(v, r, 1)
            self.kv[key] = v
        cl.addLayout(kv)
        dl.addWidget(card)

        self.lbl_exams = QLabel()
        self.lbl_exams.setObjectName("PanelHeader")
        dl.addWidget(self.lbl_exams)
        self._exam_scroll = QScrollArea()
        self._exam_scroll.setWidgetResizable(True)
        self._exam_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._exam_box = QWidget()
        self._exam_lay = QVBoxLayout(self._exam_box)
        self._exam_lay.setContentsMargins(0, 0, 4, 0)
        self._exam_lay.setSpacing(6)
        self._exam_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._exam_scroll.setWidget(self._exam_box)
        dl.addWidget(self._exam_scroll, 1)
        self._exam_group = QButtonGroup(self)
        self._exam_group.setExclusive(True)
        self.exam_checks: dict[str, QCheckBox] = {}

        acts = QHBoxLayout()
        acts.setSpacing(8)
        self.btn_open = QPushButton(icons.gap("검토 화면 열기"))
        self.btn_open.setObjectName("Primary")
        self.btn_open.setIcon(icons.icon("eye", ICON_ON_ACCENT, 16, disabled="#4a5262"))
        self.btn_open.setToolTip("체크한 검사를 '현재'로 두고 안저 검토 화면 열기")
        self.btn_import = QPushButton(icons.gap("안저 불러오기"))
        self.btn_import.setIcon(icons.icon("download", ICON, 16))
        self.btn_import.setToolTip("안저 사진(이미지·DICOM) 파일을 이 환자의 기록으로 불러오기")
        self.btn_capture = QPushButton(icons.gap("촬영"))
        self.btn_capture.setIcon(icons.icon("camera", ICON, 16))
        self.btn_capture.setToolTip("이 환자로 촬영 화면 열기")
        for b in (self.btn_open, self.btn_import, self.btn_capture):
            b.setIconSize(QSize(15, 15))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        acts.addWidget(self.btn_open, 1)
        acts.addWidget(self.btn_import)
        acts.addWidget(self.btn_capture)
        dl.addLayout(acts)
        rl.addWidget(self.detail, 1)
        root.addWidget(right, 2)

        self.search.textChanged.connect(lambda _=None: self._apply_filter())
        self.btn_new.clicked.connect(self.new_patient)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.doubleClicked.connect(lambda _=None: self.open_review())
        self.table.enterPressed.connect(self.open_review)
        self.btn_edit.clicked.connect(self._edit_patient)
        self.btn_open.clicked.connect(self.open_review)
        self.btn_import.clicked.connect(self.importRequested.emit)
        self.btn_capture.clicked.connect(self.captureRequested.emit)

    # ================= 목록 =================
    def reload(self) -> None:
        """DB 에서 환자·검사 통계를 다시 읽는다 (지금 환자와 체크한 검사는 유지)."""
        self._all = self.db.patients.list_with_stats()
        if self._patient is not None:
            cur = next((s.patient for s in self._all if s.patient.id == self._patient.id), None)
            self._patient = cur
        first = self._patient is None
        self._apply_filter()
        if first and self._shown:                    # 처음에는 맨 위 환자를 고른다
            self.select_patient(self._shown[0].patient.id)
        elif first:
            self._render_detail()

    def set_query(self, text: str) -> None:
        self.search.setText(text)

    def set_range(self, key: str) -> None:
        self._range = key if key in self.range_buttons else "all"
        self.range_buttons[self._range].setChecked(True)
        self._apply_filter()

    def range(self) -> str:
        return self._range

    def _matches(self, s, q: str, today: str, week: str) -> bool:
        if self._range == "today" and s.last_exam != today:
            return False
        if self._range == "week" and not (s.last_exam and s.last_exam >= week):
            return False
        p = s.patient
        return not q or any(q in (v or "").lower() for v in (p.name, p.chart_no, p.diagnosis))

    def _apply_filter(self) -> None:
        q = self.search.text().strip().lower()
        today = date.today()
        td, wk = today.isoformat(), (today - timedelta(days=7)).isoformat()
        self._shown = [s for s in self._all if self._matches(s, q, td, wk)]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._shown))
        for r, s in enumerate(self._shown):
            p = s.patient
            cells = [p.chart_no or "—", p.name, sex_age(p) or "—", p.diagnosis or "—",
                     _dot(s.last_exam) if s.last_exam else "없음", str(s.exam_count)]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 5:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, it)
        # 지금 환자가 조건에 맞으면 그 행을 표시 (안 맞아도 지금 환자는 그대로 둔다)
        row = next((i for i, s in enumerate(self._shown)
                    if self._patient is not None and s.patient.id == self._patient.id), -1)
        if row >= 0:
            self.table.selectRow(row)
        else:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(False)
        empty = not self._shown
        self.table.setVisible(not empty)
        self.lbl_rows_empty.setVisible(empty)
        self._render_detail()

    def rows(self) -> list[dict]:
        """표에 보이는 내용 (테스트·확인용)."""
        out = []
        for r, s in enumerate(self._shown):
            cells = [self.table.item(r, c).text() for c in range(len(COLUMNS))]
            out.append({"id": s.patient.id, "chart_no": cells[0], "name": cells[1], "sex_age": cells[2],
                        "diagnosis": cells[3], "last_exam": cells[4], "exam_count": int(cells[5])})
        return out

    def _on_row_selected(self) -> None:
        r = self.table.currentRow()
        if not self.table.selectedItems() or not (0 <= r < len(self._shown)):
            return
        p = self._shown[r].patient
        if self._patient is not None and p.id == self._patient.id:
            return
        self._set_current(p)

    def _set_current(self, patient) -> None:
        self._patient = patient
        self._checked_day = None
        self._render_detail()
        self.patientSelected.emit(patient)

    def current_patient(self):
        return self._patient

    def select_patient(self, pid) -> bool:
        """환자를 고른다 (표에 보이면 그 행도 선택). 없는 id 면 False."""
        s = next((x for x in self._all if x.patient.id == pid), None)
        if s is None:
            return False
        row = next((i for i, x in enumerate(self._shown) if x.patient.id == pid), -1)
        if self._patient is None or self._patient.id != pid:
            self._set_current(s.patient)
        if row >= 0:
            self.table.blockSignals(True)
            self.table.selectRow(row)
            self.table.blockSignals(False)
            self.table.scrollToItem(self.table.item(row, 0))
        return True

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # ================= 환자 정보 / 검사 목록 =================
    def exams(self) -> list[Exam]:
        return list(self._exams)

    def checked_exam(self) -> str | None:
        """체크한 검사일 ('YYYY-MM-DD'). 검사가 없으면 None."""
        return self._checked_day

    def set_checked_exam(self, day: str) -> bool:
        cb = self.exam_checks.get(day)
        if cb is None:
            return False
        cb.setChecked(True)
        return True

    def has_fundus(self) -> bool:
        return any(e.fundus for e in self._exams)

    def _render_detail(self) -> None:
        p = self._patient
        self.detail.setVisible(p is not None)
        self.lbl_no_patient.setVisible(p is None)
        for b in list(self._exam_group.buttons()):
            self._exam_group.removeButton(b)
        while self._exam_lay.count():
            w = self._exam_lay.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.exam_checks = {}
        if p is None:
            self._exams, self._checked_day = [], None
            return
        self.avatar.setText((p.name or "?").strip()[:1])
        self.lbl_name.setText(p.name)
        self.lbl_chart.setText(p.chart_no or "")
        age = age_of(p.birth_date)
        self.kv["생년월일"].setText(f"{_dot(p.birth_date)}" + (f" ({age}세)" if age is not None else "")
                                   if p.birth_date else "—")
        self.kv["성별"].setText(_SEX.get(p.sex or "", "—"))
        self.kv["진단명"].setText(p.diagnosis or "—")
        self.kv["담당의"].setText(p.doctor or "—")
        self.kv["메모"].setText(p.memo or "—")

        prev_days = [e.day for e in self._exams]
        prev_checked = self._checked_day
        self._exams = group_exams(self.db.captures.list_by_patient(p.id, order="desc"))
        days = [e.day for e in self._exams]
        # 체크 유지: 사용자가 예전 검사를 골라 둔 경우만 (최근 검사를 보고 있었다면 새 최근 검사로 따라간다)
        keep = prev_checked in days and prev_days and prev_checked != prev_days[0]
        self._checked_day = prev_checked if keep else (days[0] if days else None)
        self.lbl_exams.setText(f"검사 목록 · {len(self._exams)}회")
        if not self._exams:
            empty = QLabel("아직 검사 기록이 없습니다.\n아래 [안저 불러오기]로 사진을 넣거나 [촬영]으로 찍으세요.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(110)
            self._exam_lay.addWidget(empty)
        for i, ex in enumerate(self._exams):
            self._exam_lay.addWidget(self._exam_row(ex, newest=i == 0))
        self.btn_open.setEnabled(self.has_fundus())

    def _exam_row(self, ex: Exam, newest: bool) -> QFrame:
        row = QFrame()
        row.setObjectName("ProCard")
        outer = QVBoxLayout(row)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)
        lay = QHBoxLayout()
        lay.setSpacing(8)
        outer.addLayout(lay)
        cb = QCheckBox()
        cb.setToolTip(f"{_dot(ex.day)} 검사를 검토 화면의 ‘현재’ 검사로")
        cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cb.setChecked(ex.day == self._checked_day)
        self._exam_group.addButton(cb)
        self.exam_checks[ex.day] = cb
        cb.toggled.connect(lambda on, d=ex.day: self._on_exam_checked(d, on))
        text = QLabel(f"<b>{_dot(ex.day)}</b> <span style='color:#8b95a3'>· {ex.summary()}"
                      f"{' · 최근' if newest else ''}</span>")
        text.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(cb)
        lay.addWidget(text, 1)
        photos = [c for c in ex.captures if c.thumbnail_path or c.media_type == "photo"]
        lay = QHBoxLayout()                          # 둘째 줄: 작은 썸네일 띠
        lay.setContentsMargins(24, 0, 0, 0)
        lay.setSpacing(4)
        if photos:
            outer.addLayout(lay)
        for c in photos[:_MAX_THUMBS]:
            pm = _load_pixmap(c)
            t = QLabel()
            t.setFixedSize(_THUMB_W, _THUMB_H)
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet("background:#000000; border-radius:4px;")
            if pm is not None:
                t.setPixmap(pm.scaled(_THUMB_W, _THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
            lay.addWidget(t)
        if len(photos) > _MAX_THUMBS:
            more = QLabel(f"+{len(photos) - _MAX_THUMBS}")
            more.setObjectName("Muted")
            lay.addWidget(more)
        lay.addStretch(1)
        return row

    def _on_exam_checked(self, day: str, on: bool) -> None:
        if on:
            self._checked_day = day

    # ================= 동작 =================
    def open_review(self) -> None:
        """지금 환자의 검토 화면 열기 (안저 사진이 있어야 한다)."""
        if self._patient is not None and self.has_fundus():
            self.openReviewRequested.emit()

    def new_patient(self) -> None:
        dlg = PatientDialog(self)
        if not dlg.exec():
            return
        p = dlg.get_patient()
        try:
            p.id = self.db.patients.insert(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", f"저장 실패: {e}\n(차트번호 중복 여부를 확인하세요)")
            return
        self.add_patient_created(p.id)

    def add_patient_created(self, pid: int) -> None:
        """새로 등록한 환자를 목록에 반영하고 고른다 (검색·기간 조건은 풀어 보이게 한다)."""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._range = "all"
        self.range_buttons["all"].setChecked(True)
        self._all = self.db.patients.list_with_stats()
        self._apply_filter()
        self.select_patient(pid)

    def _edit_patient(self) -> None:
        if self._patient is None:
            return
        p = edit_patient(self.db, self._patient, self)
        if p is not None:
            self.reload()
            self.patientEdited.emit(self._patient)
