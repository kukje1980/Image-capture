"""환자 목록 — a window of its own (VK-2 OPEN LIST · Database List), the first one the program shows.

VK-2 opens a patient from a list of all the patient records, sorted by ID and searched by patient
ID, name or date, whose Last Visit column sorts either way; a double click on a patient opens its
photos. This window is laid out the same way, from top to bottom:

* 검색 조건 — 환자 ID · 이름 · 생년월일, 검사일 (전체 / 오늘 / 최근 7일 / 기간 from ~ to) and [지우기].
  Typing filters at once; Enter picks the only match.
* left: the patient table — 환자 ID · 이름 · 성별 · 생년월일 · 나이 · 최근 검사 · 검사 수 · 영상, sorted
  by 환자 ID. A click on a column header sorts by that column, a second click the other way.
  ★ 미분류 (photos without a patient ID) stays on top. Under it the selected patient's 검사 목록:
  one row per exam day, newest first — the selected row is the current exam.
* right: the selected patient (name, ID, sex, birth date (age), memo, [정보 수정] · [환자 삭제]) and
  its photos, **16 to a screen** (4 × 4, newest first, ◀ ▶ for more; an exam picked on the left
  comes first). A click on a photo opens it large in the main window.
* [사진 가져오기] · [3D] · [사진 보기] · [닫기].

One click on a patient selects it (here and in the main window) and shows its 16 photos; a double
click, Enter or [사진 보기] opens them in the main window (16 to a screen there as well) and puts
this window away — 환자 목록 (Ctrl+0) brings it back.

The window holds no selection of its own: a click only *asks* the main window for a patient
(``patientSelected``); the main window selects it and calls ``set_current`` back, so the list and
the photos always agree.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from PySide6.QtCore import QDate, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDateEdit, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import review
from ..db import Database
from ..models import MODALITY_LABELS
from . import motion, theme
from .thumbs import eye_badge, eye_badge_html, thumb_pixmap
from .widgets import Segmented, filling, segment

UNASSIGNED = -1
SEX_LABEL = {"M": "남", "F": "여", "O": "기타"}
PERIODS = (("all", "전체"), ("today", "오늘"), ("week", "최근 7일"), ("range", "기간"))
# the patient table (VK-2: ID, name, sex, birth date, last visit …)
COLUMNS = ("환자 ID", "이름", "성별", "생년월일", "나이", "최근 검사", "검사 수", "영상")
COL_ID, COL_NAME, COL_SEX, COL_BIRTH, COL_AGE, COL_LAST, COL_EXAMS, COL_IMAGES = range(len(COLUMNS))
NUMERIC = (COL_AGE, COL_EXAMS, COL_IMAGES)
NEWEST_FIRST = (COL_LAST, COL_EXAMS, COL_IMAGES)     # the first click on these sorts the largest first
EXAM_COLUMNS = ("검사일", "눈", "사진", "촬영")
GRID = (4, 4)                                        # the photos of a patient: 16 to a screen
GRID_N = GRID[0] * GRID[1]
SELECT_DELAY_MS = 150      # stepping through the table with the keys: the photos follow once it pauses

EMPTY_LIBRARY = (
    "<b style='font-size:15px'>아직 환자가 없습니다</b><br><br>"
    "사진 가져오기는 설정 없이 자동입니다.<br>"
    "감시 폴더(<b>문서 › 안저사진 가져오기</b>, 촬영 장비 폴더)에 사진 파일이 들어오면<br>"
    "파일에서 환자 ID·이름을 읽어 여기에 환자가 나타납니다.<br><br>"
    "아래 <b>[사진 가져오기]</b>로 파일을 고르거나, 이 창에 파일·폴더를 끌어다 놓아도 됩니다.")
EMPTY_MATCH = "조건에 맞는 환자가 없습니다"
NO_PATIENT = "환자를 선택하세요\n\n환자를 누르면 그 환자의 사진이 한 화면에 16장씩 나옵니다."
NO_PHOTOS = ("아직 가져온 사진이 없습니다.\n\n아래 [사진 가져오기]로 이 환자의 사진 파일을 넣거나,\n"
             "감시 폴더에 사진이 들어오기를 기다리세요.")


def age_on(birth: str | None, on: str | None = None) -> int | None:
    try:
        b = date.fromisoformat(birth)
        d = date.fromisoformat(on) if on else date.today()
    except (TypeError, ValueError):
        return None
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def window_start(index: int, total: int, n: int) -> int:
    """The first of ``n`` photos on screen when the ``index``-th of ``total`` should be on it:
    that one first, but never fewer than ``n`` on screen (the main window's 다중 보기 does the same)."""
    return max(0, min(index, total - n)) if total > n else 0


def _natural(text: str) -> tuple:
    """Sort key: the numbers in IDs by value (``P9`` before ``P10``), the rest without case."""
    parts = re.split(r"(\d+)", text.lower())
    return tuple((int(p), p) if i % 2 else p for i, p in enumerate(parts))


def _exam_eyes(rows) -> str:
    eyes = {r["laterality"] for r in rows}
    return " · ".join(e for e in ("OD", "OS", "OU") if e in eyes) or "—"


class _PhotoCell(QFrame):
    """One photo of the 16: the stored thumbnail, its eye and day under it. A click opens it."""
    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("photoCell")
        self.image_id: int | None = None
        self._path: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.pic = QLabel()
        self.pic.setObjectName("photoPic")
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic.setMinimumSize(40, 32)
        self.pic.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.cap = QLabel()
        self.cap.setObjectName("photoCaption")
        self.cap.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.pic, 1)
        lay.addWidget(self.cap)

    def set_photo(self, row) -> None:
        if row is None:
            self.image_id, self._path = None, None
            self.pic.clear()
            self.cap.setText("")
            self.setToolTip("")
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setProperty("filled", False)
        else:
            self.image_id, self._path = row["id"], row["thumb_path"]
            mod = MODALITY_LABELS.get(row["modality"] or "", "")
            self.cap.setText(f"{eye_badge_html(row['laterality'])}&nbsp;{row['exam_date'] or '날짜 없음'}")
            self.setToolTip(f"{eye_badge(row['laterality'])[0]} · {row['exam_date'] or ''} "
                            f"{(row['exam_time'] or '')[:5]} · {mod}\n누르면 크게 봅니다".replace("  ", " "))
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setProperty("filled", True)
            self._scale()
        self.style().unpolish(self)
        self.style().polish(self)

    def _scale(self) -> None:
        if self.image_id is None:
            return
        side = max(8, min(self.pic.width(), self.pic.height()))
        pm = thumb_pixmap(self._path, 0)
        if pm.isNull():
            self.pic.setText("사진 없음")
            return
        self.pic.setPixmap(pm.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._scale()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.image_id is not None:
            self.clicked.emit(self.image_id)
        super().mousePressEvent(e)


class PhotoGrid(QWidget):
    """The selected patient's photos, 16 to a screen (4 × 4), newest first; ◀ ▶ page through."""
    photoClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []
        self.start = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.lbl_title = QLabel("사진 · 한 화면 16장")
        self.lbl_title.setObjectName("cardTitle")
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        self.lbl_pos = QLabel("")
        self.lbl_pos.setObjectName("caption")
        self.btn_prev = QToolButton()
        self.btn_prev.setText("◀")
        self.btn_prev.setToolTip("앞의 16장")
        self.btn_prev.clicked.connect(lambda: self.page(-1))
        self.btn_next = QToolButton()
        self.btn_next.setText("▶")
        self.btn_next.setToolTip("다음 16장")
        self.btn_next.clicked.connect(lambda: self.page(1))
        for w in (self.lbl_pos, self.btn_prev, self.btn_next):
            head.addWidget(w)
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.cells: list[_PhotoCell] = []
        for i in range(GRID_N):
            cell = _PhotoCell()
            cell.clicked.connect(self.photoClicked.emit)
            grid.addWidget(cell, i // GRID[1], i % GRID[1])
            self.cells.append(cell)
        for r in range(GRID[0]):
            grid.setRowStretch(r, 1)
        for c in range(GRID[1]):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid, 1)
        self._show()

    def set_photos(self, rows, start: int | None = None) -> None:
        self.rows = list(rows)
        self.start = window_start(self.start if start is None else start, len(self.rows), GRID_N)
        self._show()

    def show_photo(self, image_id: int) -> None:
        """The screen of 16 that holds this photo (the first photo of an exam: that exam first)."""
        ids = [r["id"] for r in self.rows]
        if image_id in ids and not self.start <= ids.index(image_id) < self.start + GRID_N:
            self.start = window_start(ids.index(image_id), len(ids), GRID_N)
            self._show()

    def page(self, d: int) -> None:
        start = window_start(self.start + d * GRID_N, len(self.rows), GRID_N)
        if start != self.start:
            self.start = start
            self._show()

    def shown_ids(self) -> list[int]:
        return [c.image_id for c in self.cells if c.image_id is not None]

    def first_id(self) -> int | None:
        ids = self.shown_ids()
        return ids[0] if ids else None

    def _show(self) -> None:
        page = self.rows[self.start:self.start + GRID_N]
        for i, cell in enumerate(self.cells):
            cell.set_photo(page[i] if i < len(page) else None)
        n = len(self.rows)
        many = n > GRID_N
        self.lbl_pos.setText(f"{self.start + 1}–{self.start + len(page)} / {n}장" if many else (f"{n}장" if n else ""))
        self.btn_prev.setVisible(many)
        self.btn_next.setVisible(many)
        self.btn_prev.setEnabled(self.start > 0)
        self.btn_next.setEnabled(self.start + GRID_N < n)


class PatientListWindow(QDialog):
    patientSelected = Signal(object)        # UNASSIGNED / patients.id — asks the main window to select
    openRequested = Signal(object, str)     # patient, where: "multi" (16 to a screen) / "3d"
    photoRequested = Signal(int)            # a photo of the 16: open it large
    examChecked = Signal(str)               # the exam date now selected
    editRequested = Signal()                # 정보 수정
    deleteRequested = Signal()              # 환자 삭제
    importRequested = Signal()              # 사진 가져오기
    filesDropped = Signal(list)             # files / folders dropped on the window
    shown = Signal(bool)                    # the window came up / went away

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.setObjectName("patientWindow")
        self.setWindowTitle("환자 목록")
        # a window of its own over the main window (VK-2 OPEN LIST), not modal: the photos stay usable
        self.setWindowFlags(Qt.WindowType.Window)      # the usual title bar: minimise · maximise · close
        self.setModal(False)
        self.setAcceptDrops(True)
        self.setSizeGripEnabled(True)
        self.db = db
        self.today = date.today              # tests set another day
        self.select_delay = SELECT_DELAY_MS  # tests set 0: a selection goes through at once
        self._ref = None                     # the patient shown on the right (the main window's current one)
        self._exam: str | None = None        # selected exam date
        self._images: list = []
        self._exam_dates: list[str] = []
        self._period = "all"
        self._sort = (COL_ID, True)          # VK-2: sorted by patient ID
        self._placed = False                 # put over the main window the first time it is shown
        self._pending = None                 # the row picked with the keys, sent once the stepping pauses
        self._pressing = False               # the mouse is down on the table (a click: no waiting)
        self._select_timer = QTimer(self, singleShot=True, timeout=self._send_selection)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # -- 검색 조건 -------------------------------------------------------------------------
        head = QHBoxLayout()
        title = QLabel("환자 목록")
        title.setObjectName("pageTitle")
        head.addWidget(title)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("caption")
        head.addWidget(self.lbl_count)
        head.addStretch(1)
        root.addLayout(head)
        cond = QFrame()
        cond.setObjectName("card")
        cl = QGridLayout(cond)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setHorizontalSpacing(8)
        cl.setVerticalSpacing(8)
        self._search_timer = QTimer(self, singleShot=True, timeout=self.refresh)
        self.f_id, self.f_name, self.f_birth = QLineEdit(), QLineEdit(), QLineEdit()
        for c, (label, edit, hint) in enumerate((("환자 ID", self.f_id, "환자 ID (일부만 적어도 됨)"),
                                                 ("이름", self.f_name, "이름"),
                                                 ("생년월일", self.f_birth, "예: 1958-03-12 · 1958"))):
            lab = QLabel(label)
            lab.setObjectName("kvKey")
            cl.addWidget(lab, 0, 2 * c)
            edit.setPlaceholderText(hint)
            edit.setClearButtonEnabled(True)
            edit.setMinimumWidth(120)
            edit.textChanged.connect(lambda: self._search_timer.start(200))
            edit.returnPressed.connect(self._search_enter)
            cl.addWidget(edit, 0, 2 * c + 1)
        self.btn_clear = QPushButton("지우기")
        self.btn_clear.setObjectName("plain")
        self.btn_clear.setToolTip("검색 조건을 모두 지우고 전체 환자를 봅니다")
        self.btn_clear.clicked.connect(self.clear_search)
        cl.addWidget(self.btn_clear, 0, 6)
        lab = QLabel("검사일")
        lab.setObjectName("kvKey")
        cl.addWidget(lab, 1, 0)
        self.period_buttons = {k: segment(label, "이 기간에 검사(촬영)한 환자") for k, label in PERIODS}
        self.period_buttons["all"].setChecked(True)
        seg = Segmented(list(self.period_buttons.values()))
        seg.setFixedWidth(300)
        for k, b in self.period_buttons.items():
            b.toggled.connect(lambda on, k=k: on and self.set_period(k))
        cl.addWidget(seg, 1, 1, 1, 2)
        span = QHBoxLayout()
        span.setSpacing(6)
        self.d_from, self.d_to = QDateEdit(), QDateEdit()
        today = QDate.currentDate()
        for d, value in ((self.d_from, today.addDays(-30)), (self.d_to, today)):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
            d.setDate(value)
            d.dateChanged.connect(lambda _: self._period == "range" and self._search_timer.start(200))
        span.addWidget(self.d_from)
        self.lbl_tilde = QLabel("~")
        span.addWidget(self.lbl_tilde)
        span.addWidget(self.d_to)
        span.addStretch(1)
        self.range_w = QWidget()
        self.range_w.setLayout(span)
        span.setContentsMargins(0, 0, 0, 0)
        self.range_w.setVisible(False)              # only with 기간
        cl.addWidget(self.range_w, 1, 3, 1, 4)
        cl.setColumnStretch(7, 1)
        root.addWidget(cond)

        # -- the patient table · the selected patient ---------------------------------------------
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.table = QTableWidget(0, len(COLUMNS) + 1)       # + an empty column that takes the spare width
        self.table.setObjectName("patientTable")
        self.table.setHorizontalHeaderLabels(list(COLUMNS) + [""])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setMinimumSectionSize(24)        # (the empty last column may shrink away)
        for col in range(len(COLUMNS)):      # every column as wide as its text: a long ID never squeezes the name
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(COLUMNS), QHeaderView.ResizeMode.Stretch)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.setToolTip("제목을 누르면 그 열로 정렬 (한 번 더 누르면 반대로)")
        hdr.sectionClicked.connect(self._on_header)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.viewport().installEventFilter(self)
        self.table.doubleClicked.connect(lambda _: self._open_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self.table, context=Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._open_selected)
        sc = QShortcut(QKeySequence("Ctrl+F"), self)
        sc.activated.connect(self.focus_search)
        self._wheel = motion.SmoothWheel(self.table, step=64.0)
        self.lbl_empty = QLabel(EMPTY_MATCH)
        self.lbl_empty.setObjectName("emptyState")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setWordWrap(True)
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.table)
        self.list_stack.addWidget(self.lbl_empty)
        self.left = QSplitter(Qt.Orientation.Vertical)
        self.left.setChildrenCollapsible(False)
        self.left.addWidget(self.list_stack)
        exam_box = QWidget()
        el = QVBoxLayout(exam_box)
        el.setContentsMargins(0, 6, 0, 0)
        el.setSpacing(4)
        self.split.addWidget(self.left)

        self.detail = QFrame()
        self.detail.setObjectName("card")
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(14, 12, 14, 12)
        dl.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        names = QVBoxLayout()
        names.setSpacing(1)
        line = QHBoxLayout()
        line.setSpacing(8)
        self.lbl_name = QLabel("")
        self.lbl_name.setObjectName("patientName")
        self.lbl_id = QLabel("")
        self.lbl_id.setObjectName("caption")
        self.lbl_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        line.addWidget(self.lbl_name)
        line.addWidget(self.lbl_id, 1, Qt.AlignmentFlag.AlignBottom)
        names.addLayout(line)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        names.addWidget(self.lbl_info)
        top.addLayout(names, 1)
        self.btn_edit = QPushButton("정보 수정")
        self.btn_edit.setToolTip("환자 ID · 이름 · 생년월일 · 성별 · 메모 고치기")
        self.btn_edit.clicked.connect(self.editRequested.emit)
        self.btn_delete = QPushButton("환자 삭제")
        self.btn_delete.setObjectName("plain")
        self.btn_delete.setToolTip("이 환자를 목록에서 지웁니다 — 사진은 지워지지 않고 ★ 미분류로 옮겨집니다")
        self.btn_delete.clicked.connect(self.deleteRequested.emit)
        top.addWidget(self.btn_edit, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.btn_delete, 0, Qt.AlignmentFlag.AlignTop)
        dl.addLayout(top)
        self.lbl_exams = QLabel("검사 목록")
        self.lbl_exams.setObjectName("cardTitle")
        el.addWidget(self.lbl_exams)
        self.exams = QTableWidget(0, len(EXAM_COLUMNS))
        self.exams.setObjectName("examTable")
        self.exams.setHorizontalHeaderLabels(list(EXAM_COLUMNS))
        self.exams.verticalHeader().setVisible(False)
        self.exams.verticalHeader().setDefaultSectionSize(28)
        self.exams.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.exams.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.exams.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.exams.setShowGrid(False)
        self.exams.setToolTip("검사(촬영한 날)를 고르면 사진이 그 검사부터 나옵니다 — 두 번 누르면 엽니다")
        ehdr = self.exams.horizontalHeader()
        ehdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col in range(len(EXAM_COLUMNS) - 1):
            ehdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        ehdr.setSectionResizeMode(len(EXAM_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self.exams.setMinimumHeight(28 * 2 + 32)
        self.exams.itemSelectionChanged.connect(self._on_exam_selected)
        self.exams.doubleClicked.connect(lambda _: self._request("multi"))
        el.addWidget(self.exams, 1)
        self.left.addWidget(exam_box)
        self.left.setStretchFactor(0, 3)
        self.left.setStretchFactor(1, 1)
        self.left.setSizes([440, 170])
        self.photos = PhotoGrid()
        self.photos.photoClicked.connect(self._on_photo_clicked)
        dl.addWidget(self.photos, 1)
        self.lbl_detail_empty = QLabel(NO_PATIENT)
        self.lbl_detail_empty.setObjectName("emptyState")
        self.lbl_detail_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_detail_empty.setWordWrap(True)
        dl.addWidget(self.lbl_detail_empty, 1)
        self.split.addWidget(self.detail)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([770, 510])
        root.addWidget(self.split, 1)

        # -- buttons ---------------------------------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(8)
        hint = QLabel("한 번 누르기: 사진 16장 · 두 번 누르기 / Enter: 열기 · 사진을 누르면 크게 · Esc: 닫기")
        hint.setObjectName("caption")
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)     # cut, not a wider window
        row.addWidget(hint, 1)
        self.btn_import = QPushButton("사진 가져오기")
        self.btn_import.setToolTip("사진 파일을 골라 가져옵니다 — 사진에서 읽은 환자 정보를 먼저 보여 주고,\n"
                                   "환자 정보가 없는 사진은 그 자리에서 환자를 지정할 수 있습니다\n"
                                   "(이 창에 파일·폴더를 끌어다 놓아도 됩니다)")
        self.btn_import.clicked.connect(self.importRequested.emit)
        self.btn_3d = QPushButton("3D")
        self.btn_3d.setToolTip("선택한 검사의 사진을 3D 안구 모형으로 엽니다")
        self.btn_3d.clicked.connect(lambda: self._request("3d"))
        self.btn_open = QPushButton("사진 보기")
        self.btn_open.setObjectName("primary")
        self.btn_open.setToolTip("이 환자의 사진을 주 화면에 엽니다 (두 번 누르기 · Enter) — 고른 검사의 최신 OD | OS 두 장,\n"
                                 "설정 → 일반 → 환자를 열면 이 VK-2 방식이면 사진 16장(16장 보기)")
        self.btn_open.clicked.connect(lambda: self._request("multi"))
        self.btn_close = QPushButton("닫기")
        self.btn_close.setToolTip("환자 목록 창을 닫습니다 — 다시 열기: 환자 목록 (Ctrl+0)")
        self.btn_close.clicked.connect(self.hide)
        for b in (self.btn_import, self.btn_3d, self.btn_open, self.btn_close):
            row.addWidget(b)
        root.addLayout(row)
        for b in self.findChildren(QPushButton):     # Enter belongs to the table (open), not to a button
            b.setAutoDefault(False)
            b.setDefault(False)
        self.resize(1280, 800)
        self.refresh()

    # -- the window ---------------------------------------------------------------------------
    def place_over(self, window: QWidget) -> None:
        """The first time: centred over the main window, as large as fits on its screen."""
        if self._placed:
            return
        self._placed = True
        screen = (window.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = min(1280, screen.width() - 40), min(800, screen.height() - 60)
        self.resize(w, h)
        centre = window.frameGeometry().center() if window.isVisible() else screen.center()
        x = min(max(screen.left(), centre.x() - w // 2), screen.right() - w)
        y = min(max(screen.top(), centre.y() - h // 2), screen.bottom() - h)
        self.move(x, y)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.shown.emit(True)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._select_timer.stop()
        self._send_selection()                 # a patient stepped to just before: it still counts
        self.shown.emit(False)

    def eventFilter(self, obj, e) -> bool:
        if obj is self.table.viewport():
            if e.type() == QEvent.Type.MouseButtonPress:
                self._pressing = True
            elif e.type() == QEvent.Type.MouseButtonRelease:
                self._pressing = False
        return False

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            # after the drop has returned: the file manager must not wait for the dialog
            QTimer.singleShot(0, lambda: self.filesDropped.emit(paths))

    # -- search -------------------------------------------------------------------------------
    def focus_search(self) -> None:
        self.f_id.setFocus()
        self.f_id.selectAll()

    def clear_search(self) -> None:
        self._search_timer.stop()
        for e in (self.f_id, self.f_name, self.f_birth):
            e.blockSignals(True)
            e.clear()
            e.blockSignals(False)
        self.set_period("all")
        self.refresh()

    def set_period(self, key: str) -> None:
        if key not in dict(PERIODS):
            return
        self._period = key
        if not self.period_buttons[key].isChecked():
            self.period_buttons[key].setChecked(True)
        self.range_w.setVisible(key == "range")
        self.refresh()

    def set_range(self, start: date, end: date) -> None:
        """검사일 기간 (from ~ to) — and the period becomes 기간."""
        for d, value in ((self.d_from, start), (self.d_to, end)):
            d.blockSignals(True)
            d.setDate(QDate(value.year, value.month, value.day))
            d.blockSignals(False)
        self.set_period("range")

    def _span(self) -> tuple[str, str] | None:
        """The days of 검사일 (ISO, both included), None for 전체."""
        today = self.today()
        if self._period == "today":
            return today.isoformat(), today.isoformat()
        if self._period == "week":
            return (today - timedelta(days=7)).isoformat(), today.isoformat()
        if self._period == "range":
            a, b = (d.date().toString("yyyy-MM-dd") for d in (self.d_from, self.d_to))
            return (a, b) if a <= b else (b, a)
        return None

    def refresh(self) -> None:
        """Read the patients again (one query) and show those that pass the search, in the chosen order."""
        qid = self.f_id.text().strip().lower()
        qname = self.f_name.text().strip().lower()
        qbirth = re.sub(r"\D", "", self.f_birth.text())
        searching = bool(qid or qname or qbirth)
        patients = self.db.list_patients()
        span = self._span()
        seen = self.db.patients_examined(*span) if span else None
        entries = []
        for r in patients:
            if qid and qid not in (r["patient_id"] or "").lower():
                continue
            if qname and qname not in (r["name"] or "").lower():
                continue
            if qbirth and qbirth not in (r["birth_date"] or "").replace("-", ""):
                continue
            if seen is not None and r["id"] not in seen:
                continue
            age = age_on(r["birth_date"])
            entries.append((r["id"], [r["patient_id"], r["name"] or "", SEX_LABEL.get(r["sex"] or "", ""),
                                      r["birth_date"] or "", "" if age is None else str(age),
                                      r["last_exam"] or "", str(r["n_exams"]), str(r["n_images"])]))
        entries = self._sorted(entries)
        un = self.db.unassigned_summary()
        if un["n_images"] and not searching and (seen is None or None in seen):
            entries.insert(0, (UNASSIGNED, ["★ 미분류", "환자 ID 없음", "", "", "", un["last_exam"] or "",
                                            str(un["n_exams"]), str(un["n_images"])]))
        with filling(self.table):
            self.table.setRowCount(len(entries))
            for i, (ref, cols) in enumerate(entries):
                for j, value in enumerate(cols):
                    it = QTableWidgetItem(value)
                    it.setData(Qt.ItemDataRole.UserRole, ref)
                    if j in NUMERIC:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if ref == UNASSIGNED:
                        it.setForeground(QColor(theme.ORANGE))
                    self.table.setItem(i, j, it)
                filler = QTableWidgetItem("")
                filler.setData(Qt.ItemDataRole.UserRole, ref)
                self.table.setItem(i, len(COLUMNS), filler)
        col, asc = self._sort
        self.table.horizontalHeader().setSortIndicator(
            col, Qt.SortOrder.AscendingOrder if asc else Qt.SortOrder.DescendingOrder)
        self._highlight()
        total = len(patients)
        shown = sum(ref != UNASSIGNED for ref, _ in entries)
        self.lbl_count.setText(f"{shown}명" if shown == total else f"{shown}명 / 전체 {total}명")
        if entries:
            self.list_stack.setCurrentWidget(self.table)
        else:
            library_empty = not searching and span is None and not total and not un["n_images"]
            self.lbl_empty.setText(EMPTY_LIBRARY if library_empty else EMPTY_MATCH)
            self.list_stack.setCurrentWidget(self.lbl_empty)
        self._fill_detail()

    # -- order -----------------------------------------------------------------------------------
    def sort_by(self, col: int, ascending: bool | None = None) -> None:
        """Sort the patients by a column; ``None``: the column's first way (names A→Z, the latest
        exam and the largest counts first), or the other way when it is sorted already."""
        if not 0 <= col < len(COLUMNS):
            return
        if ascending is None:
            cur, asc = self._sort
            ascending = (not asc) if cur == col else col not in NEWEST_FIRST
        self._sort = (col, ascending)
        self.refresh()

    def sort_order(self) -> tuple[int, bool]:
        return self._sort

    def _on_header(self, col: int) -> None:
        if col < len(COLUMNS):
            self.sort_by(col)
        else:                                  # the empty column: keep the order (and the arrow)
            c, asc = self._sort
            self.table.horizontalHeader().setSortIndicator(
                c, Qt.SortOrder.AscendingOrder if asc else Qt.SortOrder.DescendingOrder)

    def _sorted(self, entries: list) -> list:
        """By the chosen column (rows without a value last, either way), then by ID."""
        col, asc = self._sort

        def key(entry):
            v = entry[1][col]
            return int(v) if col in NUMERIC else _natural(v)

        filled = [e for e in entries if e[1][col] != ""]
        empty = [e for e in entries if e[1][col] == ""]
        by_id = (lambda e: _natural(e[1][COL_ID]))
        filled.sort(key=by_id)
        filled.sort(key=key, reverse=not asc)        # (stable: equal values stay in ID order)
        empty.sort(key=by_id)
        return filled + empty

    # -- the table -----------------------------------------------------------------------------
    def refs(self) -> list:
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())]

    def row_of(self, ref) -> int:
        return next((r for r, x in enumerate(self.refs()) if x == ref), -1)

    def _highlight(self) -> None:
        self.table.blockSignals(True)
        self.table.clearSelection()
        r = self.row_of(self._ref)
        if r >= 0:
            self.table.selectRow(r)
        self.table.blockSignals(False)

    def _selected_ref(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def _on_row_selected(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        self._pending = ref
        # a click goes through at once; the arrow keys go through when the stepping pauses (every
        # patient passed would otherwise read its photos)
        if self.select_delay <= 0 or self._pressing:
            self._select_timer.stop()
            self._send_selection()
        else:
            self._select_timer.start(self.select_delay)

    def _send_selection(self) -> None:
        ref, self._pending = self._pending, None
        if ref is not None and ref != self._ref:
            self.patientSelected.emit(ref)

    def _search_enter(self) -> None:
        """Enter in a search box: the search at once, and the only match gets selected."""
        self._search_timer.stop()
        self.refresh()
        refs = [r for r in self.refs() if r != UNASSIGNED]
        if len(refs) == 1:
            self.patientSelected.emit(refs[0])
            self.table.setFocus()

    def _open_selected(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        self._select_timer.stop()
        self._pending = None
        if ref != self._ref:
            self.patientSelected.emit(ref)
        self._request("multi")

    def _row_menu(self, pos) -> None:
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        ref = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
        if ref != self._ref:
            self.table.selectRow(r)
            self._select_timer.stop()
            self._send_selection()
        menu = QMenu(self)
        menu.addAction("사진 보기", lambda: self._request("multi"))
        menu.addAction("3D로 보기", lambda: self._request("3d"))
        if ref != UNASSIGNED:
            menu.addSeparator()
            menu.addAction("환자 정보 수정…", self.editRequested.emit)
            menu.addAction("환자 삭제 (사진은 미분류로)…", self.deleteRequested.emit)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _request(self, where: str) -> None:
        if self._ref is None:
            return
        self.openRequested.emit(self._ref, where)

    def _on_photo_clicked(self, image_id: int) -> None:
        if self._ref is not None:
            self.photoRequested.emit(image_id)

    # -- the selected patient ------------------------------------------------------------------
    def current(self):
        return self._ref

    def current_exam(self) -> str | None:
        return self._exam

    def exam_dates(self) -> list[str]:
        return list(self._exam_dates)

    def set_current(self, ref, exam: str | None = None) -> None:
        """The main window's patient changed (or its photos did): show it here. The selected exam
        is kept for the same patient while it still exists, else the newest one."""
        if ref != self._ref:
            self._exam = None
            self.photos.start = 0
        self._ref = ref
        if exam is not None:
            self._exam = exam
        self._highlight()
        self._fill_detail()

    def set_exam(self, exam_date: str) -> None:
        """Select the exam of ``exam_date`` (its photos come first in the 16)."""
        if exam_date in self._exam_dates:
            self.exams.selectRow(self._exam_dates.index(exam_date))    # -> _on_exam_selected

    def _on_exam_selected(self) -> None:
        rows = self.exams.selectionModel().selectedRows()
        if not rows:
            return
        d = self._exam_dates[rows[0].row()]
        first = next((r["id"] for r in self._images if (r["exam_date"] or "") == d), None)
        if first is not None:
            self.photos.show_photo(first)
        if d != self._exam:
            self._exam = d
            self.examChecked.emit(d)

    def first_shown_photo(self) -> int | None:
        """The first of the 16 photos on screen (the main window opens its 16 from the same photo)."""
        return self.photos.first_id()

    def _fill_detail(self) -> None:
        ref = self._ref
        patient = self.db.get_patient(ref) if ref not in (None, UNASSIGNED) else None
        if ref is not None and ref != UNASSIGNED and patient is None:
            ref = self._ref = None            # deleted or merged away
        have = ref is not None
        for w in (self.lbl_name, self.lbl_id, self.lbl_info):
            w.setVisible(have)
        self.btn_edit.setVisible(patient is not None)
        self.btn_delete.setVisible(patient is not None)
        self._images = self.db.images_for_patient(None if ref == UNASSIGNED else ref) if have else []
        groups = review.exams(self._images)
        self._exam_dates = [d for d, _ in groups]
        if self._exam not in self._exam_dates:
            self._exam = self._exam_dates[0] if self._exam_dates else None
        if ref == UNASSIGNED:
            self.lbl_name.setText("★ 미분류")
            self.lbl_id.setText("")
            self.lbl_info.setText("환자 ID를 찾지 못한 사진 — 사진을 열어 [정보 수정]으로 환자를 지정하세요")
        elif patient is not None:
            name = patient["name"] or ""
            self.lbl_name.setText(name or "(이름 없음)")
            self.lbl_id.setText(patient["patient_id"])
            age = age_on(patient["birth_date"])
            bits = [SEX_LABEL.get(patient["sex"] or "", ""),
                    (patient["birth_date"] or "") + (f" ({age}세)" if age is not None else "")]
            info = " · ".join(b for b in bits if b) or "성별 · 생년월일 없음"
            if patient["note"]:
                info += f"\n메모: {patient['note']}"
            self.lbl_info.setText(info)
        self.lbl_exams.setText(f"검사 목록 · {len(groups)}회 · 사진 {len(self._images)}장" if have else "검사 목록")
        self.exams.blockSignals(True)
        self.exams.setRowCount(len(groups))
        for i, (d, rows) in enumerate(groups):
            values = (f"{d or '날짜 없음'}" + ("  · 최근" if i == 0 and d else ""), _exam_eyes(rows),
                      str(len(rows)), review.summary(rows))
            for j, v in enumerate(values):
                it = QTableWidgetItem(v)
                if j == 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.exams.setItem(i, j, it)
        self.exams.clearSelection()
        if self._exam in self._exam_dates:
            self.exams.selectRow(self._exam_dates.index(self._exam))
        self.exams.blockSignals(False)
        self.photos.set_photos(self._images)
        self.photos.setVisible(bool(groups))
        self.lbl_detail_empty.setVisible(not groups)
        self.lbl_detail_empty.setText(NO_PATIENT if not have else NO_PHOTOS)
        for b in (self.btn_open, self.btn_3d):
            b.setEnabled(bool(groups))

    def shortcut_photo(self):
        """The photo 3D opens: the newest of the selected exam."""
        return review.newest_photo(self._images, self._exam)
