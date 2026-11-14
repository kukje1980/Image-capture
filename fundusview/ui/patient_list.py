"""환자 목록 — the start screen.

Left: search, the period of the last exam (전체 / 오늘 / 최근 7일) and the table of patients.
Right: the selected patient (card with 정보 수정), the list of exams (검사 목록: one row per
exam date, newest first, one of them checked — the exam the 검토 tab reviews, older ones are
its 이전 검사) and the buttons into the workspace.

The page holds no selection of its own: a click only *asks* the main window for a patient
(``patientSelected``); the window selects it everywhere and calls ``set_current`` back, so this
table and the workspace's patient table always agree.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import review
from ..db import Database
from . import motion, theme
from .thumbs import eye_badge, thumb_pixmap
from .widgets import Segmented, hairline, segment

UNASSIGNED = -1
SEX_LABEL = {"M": "남", "F": "여", "O": "기타"}
PERIODS = (("all", "전체"), ("today", "오늘"), ("week", "최근 7일"))
COLUMNS = ("환자 ID", "이름", "성별 · 나이", "최근 검사", "검사 수", "영상")
EXAM_THUMBS = 6                      # thumbnails shown in an exam row (then "+n")

EMPTY_LIBRARY = (
    "<b style='font-size:15px'>아직 환자가 없습니다</b><br><br>"
    "사진 가져오기는 설정 없이 자동입니다.<br>"
    "감시 폴더(<b>문서 › 안저사진 가져오기</b>, 촬영 장비 폴더)에 사진 파일이 들어오면<br>"
    "파일에서 환자 ID·이름을 읽어 여기에 환자가 나타납니다.<br><br>"
    "오른쪽 <b>[사진 가져오기]</b>로 파일을 고르거나, 이 창에 파일·폴더를 끌어다 놓아도 됩니다.")
EMPTY_MATCH = "조건에 맞는 환자가 없습니다"


def age_on(birth: str | None, on: str | None = None) -> int | None:
    try:
        b = date.fromisoformat(birth)
        d = date.fromisoformat(on) if on else date.today()
    except (TypeError, ValueError):
        return None
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def sex_age(sex: str | None, birth: str | None) -> str:
    age = age_on(birth)
    return " · ".join(x for x in (SEX_LABEL.get(sex or "", ""), f"{age}세" if age is not None else "") if x)


def _restyle(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class _ExamRow(QFrame):
    """One exam: check box · date · what was taken · small photos. A click anywhere checks it."""

    def __init__(self, exam_date: str, rows, newest: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("examRow")
        self.date = exam_date
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.check = QCheckBox()
        self.check.setToolTip("검토 화면의 현재 검사로 — 더 이른 검사는 이전 검사로 비교합니다")
        self.check.toggled.connect(self._on_toggled)
        grid.addWidget(self.check, 0, 0)
        head = QHBoxLayout()
        head.setSpacing(8)
        d = QLabel(exam_date or "날짜 없음")
        d.setObjectName("examDate")
        head.addWidget(d)
        info = QLabel(review.summary(rows))
        info.setObjectName("caption")
        head.addWidget(info, 1)
        if newest:
            tag = QLabel("최근")
            tag.setObjectName("pill")
            head.addWidget(tag)
        grid.addLayout(head, 0, 1)
        thumbs = QHBoxLayout()
        thumbs.setSpacing(4)
        for r in rows[:EXAM_THUMBS]:
            lab = QLabel()
            lab.setObjectName("examThumb")
            lab.setFixedSize(46, 46)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setPixmap(thumb_pixmap(r["thumb_path"], 44))
            lab.setToolTip(f"{eye_badge(r['laterality'])[0]} · {(r['exam_time'] or '')[:5]}".strip(" ·"))
            thumbs.addWidget(lab)
        if len(rows) > EXAM_THUMBS:
            more = QLabel(f"+{len(rows) - EXAM_THUMBS}")
            more.setObjectName("caption")
            thumbs.addWidget(more)
        thumbs.addStretch(1)
        grid.addLayout(thumbs, 1, 1)
        grid.setColumnStretch(1, 1)

    def _on_toggled(self, on: bool) -> None:
        self.setProperty("current", on)
        _restyle(self)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.check.setChecked(True)
        super().mousePressEvent(e)


class PatientListPage(QWidget):
    patientSelected = Signal(object)        # UNASSIGNED / patients.id — asks the window to select
    openRequested = Signal(object, str)     # patient, where: "review" / "2d" / "3d" / "all"
    examChecked = Signal(str)               # the exam date now checked
    editRequested = Signal()                # 정보 수정
    importRequested = Signal()              # 사진 가져오기

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.setObjectName("patientPage")
        self.db = db
        self.today = date.today              # tests set another day
        self._ref = None                     # the patient shown on the right (the window's current one)
        self._exam: str | None = None        # checked exam date
        self._images: list = []
        self._rows: list[_ExamRow] = []
        self._period = "all"

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        # -- left: search · period · table ------------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("환자 목록")
        title.setObjectName("pageTitle")
        head.addWidget(title)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("caption")
        head.addWidget(self.lbl_count)
        head.addStretch(1)
        left.addLayout(head)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("환자 ID · 이름 · 생년월일 검색")
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self, singleShot=True, timeout=self.refresh)
        self.search.textChanged.connect(lambda: self._search_timer.start(200))
        self.search.returnPressed.connect(self._search_enter)
        tools.addWidget(self.search, 1)
        self.period_buttons = {k: segment(label, "가장 최근 검사일로 고르기") for k, label in PERIODS}
        self.period_buttons["all"].setChecked(True)
        seg = Segmented(list(self.period_buttons.values()), on_card=False)
        seg.setFixedWidth(230)
        for k, b in self.period_buttons.items():
            b.toggled.connect(lambda on, k=k: on and self.set_period(k))
        tools.addWidget(seg)
        left.addLayout(tools)

        self.table = QTableWidget(0, len(COLUMNS) + 1)       # + an empty column that takes the spare width
        self.table.setObjectName("patientTable")
        self.table.setHorizontalHeaderLabels(list(COLUMNS) + [""])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setMinimumSectionSize(64)
        for col in range(len(COLUMNS)):      # every column as wide as its text: a long ID never squeezes the name
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(COLUMNS), QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.doubleClicked.connect(lambda _: self._open_selected())
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table, context=Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected)
        self._wheel = motion.SmoothWheel(self.table, step=64.0)
        self.lbl_empty = QLabel(EMPTY_MATCH)
        self.lbl_empty.setObjectName("emptyState")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setWordWrap(True)
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.table)
        self.list_stack.addWidget(self.lbl_empty)
        left.addWidget(self.list_stack, 1)
        hint = QLabel("환자를 누르면 오른쪽에 검사 목록이 나오고, 두 번 누르거나 Enter를 누르면 검토 화면이 열립니다.")
        hint.setObjectName("caption")
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)     # cut, not a wider window
        left.addWidget(hint)
        root.addLayout(left, 1)

        # -- right: patient card · exams · buttons -------------------------------------------
        self.detail = QFrame()
        self.detail.setObjectName("card")
        self.detail.setFixedWidth(392)
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(14, 14, 14, 14)
        dl.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.avatar = QLabel("")
        self.avatar.setObjectName("avatar")
        self.avatar.setFixedSize(44, 44)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.avatar)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.lbl_name = QLabel("")
        self.lbl_name.setObjectName("patientName")
        self.lbl_id = QLabel("")
        self.lbl_id.setObjectName("caption")
        self.lbl_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        names.addWidget(self.lbl_name)
        names.addWidget(self.lbl_id)
        top.addLayout(names, 1)
        self.btn_edit = QPushButton("정보 수정")
        self.btn_edit.setToolTip("환자 ID · 이름 · 생년월일 · 성별 · 메모 고치기")
        self.btn_edit.clicked.connect(self.editRequested.emit)
        top.addWidget(self.btn_edit, 0, Qt.AlignmentFlag.AlignTop)
        dl.addLayout(top)
        self.kv = QGridLayout()
        self.kv.setHorizontalSpacing(14)
        self.kv.setVerticalSpacing(3)
        self.kv.setColumnStretch(1, 1)
        self._kv_labels: dict[str, tuple[QLabel, QLabel]] = {}
        for i, key in enumerate(("생년월일", "성별", "메모")):
            k, v = QLabel(key), QLabel("")
            k.setObjectName("kvKey")
            v.setWordWrap(True)
            self.kv.addWidget(k, i, 0, Qt.AlignmentFlag.AlignTop)
            self.kv.addWidget(v, i, 1)
            self._kv_labels[key] = (k, v)
        dl.addLayout(self.kv)
        self.rule = hairline()
        dl.addWidget(self.rule)
        self.lbl_exams = QLabel("검사 목록")
        self.lbl_exams.setObjectName("cardTitle")
        dl.addWidget(self.lbl_exams)
        self.exam_box = QWidget()
        self.exam_box.setObjectName("examBox")
        self.exam_lay = QVBoxLayout(self.exam_box)
        self.exam_lay.setContentsMargins(0, 0, 4, 0)
        self.exam_lay.setSpacing(6)
        self.exam_scroll = QScrollArea()
        self.exam_scroll.setObjectName("examScroll")
        self.exam_scroll.setWidgetResizable(True)
        self.exam_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.exam_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.exam_scroll.setWidget(self.exam_box)
        dl.addWidget(self.exam_scroll, 1)
        self.exam_group = QButtonGroup(self)
        self.exam_group.setExclusive(True)
        self.lbl_detail_empty = QLabel("")
        self.lbl_detail_empty.setObjectName("emptyState")
        self.lbl_detail_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_detail_empty.setWordWrap(True)
        dl.addWidget(self.lbl_detail_empty, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_open = QPushButton("검토 화면 열기")
        self.btn_open.setObjectName("primary")
        self.btn_open.setToolTip("체크한 검사를 양안(OD | OS)으로 열고, 이전 검사와 비교합니다 (두 번 누르기 · Enter)")
        self.btn_open.clicked.connect(lambda: self._request("review"))
        row.addWidget(self.btn_open, 1)
        self.btn_import = QPushButton("사진 가져오기")
        self.btn_import.setToolTip("사진 파일을 골라 가져옵니다 — 환자는 파일에서 읽은 환자 ID로 정해집니다\n"
                                   "(이 창에 파일·폴더를 끌어다 놓아도 됩니다)")
        self.btn_import.clicked.connect(self.importRequested.emit)
        row.addWidget(self.btn_import)
        dl.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.btn_2d = QPushButton("2D 보기")
        self.btn_3d = QPushButton("3D 안구")
        for b, where, tip in ((self.btn_2d, "2d", "체크한 검사의 사진을 2D 보기로 크게 엽니다"),
                              (self.btn_3d, "3d", "체크한 검사의 사진을 3D 안구 모형으로 엽니다")):
            b.setObjectName("plain")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, where=where: self._request(where))
            row2.addWidget(b)
        row2.addStretch(1)
        dl.addLayout(row2)
        root.addWidget(self.detail)
        self.refresh()

    # -- the table ---------------------------------------------------------------------------
    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def set_period(self, key: str) -> None:
        if key not in dict(PERIODS):
            return
        self._period = key
        if not self.period_buttons[key].isChecked():
            self.period_buttons[key].setChecked(True)
        self.refresh()

    def _in_period(self, last_exam: str | None) -> bool:
        if self._period == "all":
            return True
        today = self.today()
        if not last_exam:
            return False
        if self._period == "today":
            return last_exam == today.isoformat()
        return (today - timedelta(days=7)).isoformat() <= last_exam <= today.isoformat()

    def refresh(self) -> None:
        """Read the patients again (one query) and show the rows that pass the search and the period."""
        text = self.search.text().strip()
        patients = self.db.list_patients(text)
        un = self.db.unassigned_summary()
        entries = []
        if un["n_images"] and not text and self._in_period(un["last_exam"]):
            entries.append((UNASSIGNED, ["★ 미분류", "환자 ID 없음", "", un["last_exam"] or "",
                                         str(un["n_exams"]), str(un["n_images"])]))
        for r in patients:
            if self._in_period(r["last_exam"]):
                entries.append((r["id"], [r["patient_id"], r["name"] or "", sex_age(r["sex"], r["birth_date"]),
                                          r["last_exam"] or "없음", str(r["n_exams"]), str(r["n_images"])]))
        self.table.blockSignals(True)
        self.table.setRowCount(len(entries))
        for i, (ref, cols) in enumerate(entries):
            for j, value in enumerate(cols):
                it = QTableWidgetItem(value)
                it.setData(Qt.ItemDataRole.UserRole, ref)
                if j >= 4:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if ref == UNASSIGNED:
                    it.setForeground(QColor(theme.ORANGE))
                elif (j == 3 and value == "없음") or (j == 2 and not value):
                    it.setForeground(QColor(theme.TEXT4))
                self.table.setItem(i, j, it)
            filler = QTableWidgetItem("")
            filler.setData(Qt.ItemDataRole.UserRole, ref)
            self.table.setItem(i, len(COLUMNS), filler)
        self.table.blockSignals(False)
        self._highlight()
        total = self.db.count_patients() if text else len(patients)
        shown = sum(ref != UNASSIGNED for ref, _ in entries)
        self.lbl_count.setText(f"{shown}명" if shown == total else f"{shown}명 / 전체 {total}명")
        if entries:
            self.list_stack.setCurrentWidget(self.table)
        else:
            library_empty = not text and self._period == "all" and not total and not un["n_images"]
            self.lbl_empty.setText(EMPTY_LIBRARY if library_empty else EMPTY_MATCH)
            self.list_stack.setCurrentWidget(self.lbl_empty)
        self._fill_detail()

    def refs(self) -> list:
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())]

    def _highlight(self) -> None:
        self.table.blockSignals(True)
        self.table.clearSelection()
        for r, ref in enumerate(self.refs()):
            if ref == self._ref:
                self.table.selectRow(r)
                break
        self.table.blockSignals(False)

    def _on_row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.patientSelected.emit(self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def _search_enter(self) -> None:
        """Enter in the search box: the search at once, and the only match gets selected."""
        self._search_timer.stop()
        self.refresh()
        refs = [r for r in self.refs() if r != UNASSIGNED]
        if len(refs) == 1:
            self.patientSelected.emit(refs[0])
            self.table.setFocus()

    def _open_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        ref = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if ref != self._ref:
            self.patientSelected.emit(ref)
        self._request("review")

    def _request(self, where: str) -> None:
        if self._ref is None:
            return
        if self._ref == UNASSIGNED and where == "review":
            where = "all"                     # photos of nobody in particular: look at them, assign them
        self.openRequested.emit(self._ref, where)

    # -- the selected patient ------------------------------------------------------------------
    def current(self):
        return self._ref

    def current_exam(self) -> str | None:
        return self._exam

    def set_current(self, ref, exam: str | None = None) -> None:
        """The window's patient changed (or its photos did): show it here. The checked exam is
        kept for the same patient while it still exists, else the newest one."""
        if ref != self._ref:
            self._exam = None
        self._ref = ref
        if exam is not None:
            self._exam = exam
        self._highlight()
        self._fill_detail()

    def set_exam(self, exam_date: str) -> None:
        """Check the exam of ``exam_date`` (the 검토 tab's timeline picked it)."""
        for row in self._rows:
            if row.date == exam_date:
                row.check.setChecked(True)      # -> _on_exam_checked
                return

    def _on_exam_checked(self, row: _ExamRow, on: bool) -> None:
        if on and row.date != self._exam:
            self._exam = row.date
            self.examChecked.emit(row.date)

    def _fill_detail(self) -> None:
        ref = self._ref
        for b in list(self.exam_group.buttons()):
            self.exam_group.removeButton(b)
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        self._images = []
        patient = self.db.get_patient(ref) if ref not in (None, UNASSIGNED) else None
        if ref is not None and ref != UNASSIGNED and patient is None:
            ref = self._ref = None            # deleted or merged away
        have = ref is not None
        for w in (self.avatar, self.lbl_name, self.lbl_id, self.lbl_exams, self.rule):
            w.setVisible(have)
        self.btn_edit.setVisible(patient is not None)
        for k, v in self._kv_labels.values():
            k.setVisible(patient is not None)
            v.setVisible(patient is not None)
        if not have:
            self._exam = None
            self.exam_scroll.hide()
            self.lbl_detail_empty.setText("환자를 선택하세요")
            self.lbl_detail_empty.show()
            for b in (self.btn_open, self.btn_2d, self.btn_3d):
                b.setEnabled(False)
            return
        self._images = self.db.images_for_patient(None if ref == UNASSIGNED else ref)
        groups = review.exams(self._images)
        if ref == UNASSIGNED:
            self.avatar.setText("★")
            self.lbl_name.setText("미분류")
            self.lbl_id.setText("환자 ID를 찾지 못한 사진 — 사진을 열어 [정보 수정]으로 환자를 지정하세요")
            self.lbl_id.setWordWrap(True)
            self.btn_open.setText("사진 보기")
        else:
            name = patient["name"] or ""
            self.avatar.setText(name[:1] or "?")
            self.lbl_name.setText(name or "(이름 없음)")
            self.lbl_id.setText(patient["patient_id"])
            self.lbl_id.setWordWrap(False)
            age = age_on(patient["birth_date"])
            birth = patient["birth_date"] or "—"
            values = {"생년월일": birth + (f" ({age}세)" if age is not None else ""),
                      "성별": SEX_LABEL.get(patient["sex"] or "", "—"), "메모": patient["note"] or "—"}
            for key, value in values.items():
                self._kv_labels[key][1].setText(value)
            self.btn_open.setText("검토 화면 열기")
        self.lbl_exams.setText(f"검사 목록 · {len(groups)}회 · 사진 {len(self._images)}장")
        dates = [d for d, _ in groups]
        if self._exam not in dates:
            self._exam = dates[0] if dates else None
        for i, (d, rows) in enumerate(groups):
            row = _ExamRow(d, rows, newest=i == 0)
            self.exam_group.addButton(row.check)
            row.check.setChecked(d == self._exam)
            row.check.toggled.connect(lambda on, row=row: self._on_exam_checked(row, on))
            self.exam_lay.insertWidget(i, row)
            self._rows.append(row)
        if not self._rows_have_stretch:
            self.exam_lay.addStretch(1)
            self._rows_have_stretch = True
        self.exam_scroll.setVisible(bool(groups))
        self.lbl_detail_empty.setVisible(not groups)
        if not groups:
            self.lbl_detail_empty.setText("아직 가져온 사진이 없습니다.\n\n아래 [사진 가져오기]로 이 환자의 사진 파일을 넣거나,\n"
                                          "감시 폴더에 사진이 들어오기를 기다리세요.")
        for b in (self.btn_open, self.btn_2d, self.btn_3d):
            b.setEnabled(bool(groups))

    _rows_have_stretch = False

    def exam_rows(self) -> list[_ExamRow]:
        return list(self._rows)

    def shortcut_photo(self):
        """The photo 2D 보기 / 3D 안구 open: from the checked exam."""
        return review.newest_photo(self._images, self._exam)

