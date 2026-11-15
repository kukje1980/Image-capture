"""사진 가져오기 → 확인 창: which patient each picked photo goes to, before anything is stored.

The picked files are read in a worker thread (``ImportService.preview_paths`` — the same
extraction as the import, no image analysis) and shown one row per patient:

* photos that name a patient: the id, name, birth date and sex that were read, whether the
  patient is already registered, and a warning when the registered name differs;
* photos that name nobody (``IMG_0001.jpg``): one row per folder (or per name, when only a name
  was found). The id can be typed, or taken with one click from the patient selected in the
  window / the registered patient of that name. Left empty, they go to 미분류 as before.

Every cell can be corrected; what the user changed is handed to the importer as a
:class:`~fundusview.models.PatientAssign` per file and wins over what the file says.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..db import Database
from ..extract.normalize import norm_date, norm_sex
from ..importer import PreviewItem
from ..models import PatientAssign
from . import theme
from .dialogs import SOURCE_LABELS
from .widgets import filling

SEX_TEXT = {"M": "남", "F": "여", "O": "기타"}
COLS = ("환자 ID", "이름", "생년월일", "성별", "사진", "검사일", "파일", "상태", "")
C_ID, C_NAME, C_BIRTH, C_SEX, C_COUNT, C_DATES, C_FILES, C_STATE, C_PICK = range(len(COLS))
EDITABLE = (C_ID, C_NAME, C_BIRTH, C_SEX)


@dataclass
class Group:
    """Photos that go to one patient (or, without an id, came from one folder / carry one name)."""
    patient_id: str = ""
    name: str = ""
    birth_date: str = ""
    sex: str = ""
    items: list[PreviewItem] = field(default_factory=list)
    source: str = ""                  # where the id came from ("folder", "filename", "reticam" …)
    where: str = ""                   # no id: the folder the photos lie in
    suggestion: tuple[str, str] | None = None   # (patient id, label): offered with one click


def group_items(items: list[PreviewItem]) -> list[Group]:
    """Rows of the dialog: by patient id; photos without one by the name read, else by folder."""
    groups: dict[tuple, Group] = {}
    for it in items:
        m = it.meta
        if m.patient_id:
            key = ("id", m.patient_id)
        elif m.name:
            key = ("name", m.name)
        else:
            key = ("dir", os.path.dirname(it.path))
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(patient_id=m.patient_id or "", source=m.sources.get("patient_id", ""),
                                    where=os.path.dirname(it.path))
        g.items.append(it)
        g.name = g.name or (m.name or "")             # the first photo that says it
        g.birth_date = g.birth_date or (m.birth_date or "")
        g.sex = g.sex or (m.sex or "")
    return sorted(groups.values(), key=lambda g: (not g.patient_id, g.patient_id, g.name, g.where))


class ImportReviewDialog(QDialog):
    scanned = Signal(object)          # list[PreviewItem], from the worker thread
    progressed = Signal(int, int)

    def __init__(self, service, db: Database, paths: list[str], parent=None, current_ref: int | None = None):
        super().__init__(parent)
        self.service = service
        self.db = db
        self.current = db.get_patient(current_ref) if isinstance(current_ref, int) and current_ref > 0 else None
        self.items: list[PreviewItem] = []
        self.groups: list[Group] = []
        self.skipped = 0              # already in the library, nothing to do
        self.failed: list[PreviewItem] = []
        self._ready = False
        self._filling = False
        self._cancel = threading.Event()
        self.setWindowTitle("사진 가져오기 — 환자 정보 확인")
        self.setMinimumSize(1040, 480)

        lay = QVBoxLayout(self)
        self.lbl_head = QLabel("사진에서 환자 정보를 읽는 중…")
        self.lbl_head.setWordWrap(True)
        lay.addWidget(self.lbl_head)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)
        self.table = QTableWidget(0, len(COLS))
        self.table.setObjectName("importTable")
        self.table.setHorizontalHeaderLabels(list(COLS))
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)                # long file names are cut at the end, not at a word
        h = self.table.horizontalHeader()
        for c in range(len(COLS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == C_STATE
                                   else QHeaderView.ResizeMode.Interactive if c == C_FILES
                                   else QHeaderView.ResizeMode.Fixed if c == C_PICK
                                   else QHeaderView.ResizeMode.ResizeToContents)
        h.resizeSection(C_FILES, 230)
        h.resizeSection(C_PICK, 0)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color:{theme.TEXT3}")
        lay.addWidget(self.lbl_note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.btn_ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setText("가져오기")
        self.btn_ok.setEnabled(False)
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.scanned.connect(self._on_scanned)
        self.progressed.connect(self._on_progress)
        self._thread = threading.Thread(target=self._scan, args=(list(paths),), name="fundus-preview", daemon=True)
        self._thread.start()

    # -- reading the files (worker thread) -----------------------------------
    def _scan(self, paths: list[str]) -> None:
        last = [0.0]

        def progress(i: int, n: int) -> None:
            import time
            now = time.monotonic()
            if i == n or now - last[0] > 0.1:        # a few updates a second, however many files
                last[0] = now
                self.progressed.emit(i, n)

        try:
            items = self.service.preview_paths(paths, progress, self._cancel.is_set)
        except Exception as exc:                      # an unreadable folder: say so, do not hang
            items = [PreviewItem(paths[0] if paths else "", "error", message=str(exc)[:200])]
        if not self._cancel.is_set():
            self.scanned.emit(items)

    def _on_progress(self, i: int, n: int) -> None:
        self.bar.setRange(0, max(n, 1))
        self.bar.setValue(i)
        self.lbl_head.setText(f"사진에서 환자 정보를 읽는 중… {i} / {n}")

    @property
    def ready(self) -> bool:
        """The files are read and the table is filled."""
        return self._ready

    # -- the table -----------------------------------------------------------
    def _on_scanned(self, items: list[PreviewItem]) -> None:
        self.items = items
        self.failed = [it for it in items if it.status == "error"]
        # an already imported photo is of interest only while it lies in 미분류: it can get its patient
        todo = [it for it in items if it.status == "new" or (it.status == "duplicate" and it.patient_ref is None)]
        self.skipped = len(items) - len(todo) - len(self.failed)
        self.groups = group_items(todo)
        for g in self.groups:
            g.suggestion = self._suggest(g)
        self.bar.hide()
        self._filling = True
        with filling(self.table):
            self.table.setRowCount(len(self.groups))
            for r, g in enumerate(self.groups):
                self._fill_row(r, g)
            for r in range(len(self.groups)):
                self._refresh_state(r)
        self._filling = False
        widths = [b.fontMetrics().horizontalAdvance(b.text()) for r in range(len(self.groups))
                  if (b := self.table.cellWidget(r, C_PICK)) is not None]
        self.table.horizontalHeader().resizeSection(C_PICK, min(max(widths) + 32, 260) if widths else 0)
        self._ready = True
        self._refresh_summary()
        first_open = next((r for r, g in enumerate(self.groups) if not g.patient_id), None)
        if first_open is not None:                   # start where something is to be filled in
            self.table.setCurrentCell(first_open, C_ID)
        self.btn_ok.setFocus()

    def _suggest(self, g: Group) -> tuple[str, str] | None:
        if g.patient_id:
            return None
        if g.name:                                   # only a name was read: the one patient of that name
            same = self.db.patients_named(g.name)
            if len(same) == 1:
                return same[0]["patient_id"], f"{same[0]['name']} ({same[0]['patient_id']})"
            if same:
                return None                          # several of that name: the user says which
        if self.current is not None:
            return self.current["patient_id"], f"{self.current['name'] or '(이름 없음)'} ({self.current['patient_id']})"
        return None

    def _fill_row(self, r: int, g: Group) -> None:
        dates = sorted({it.meta.exam_date for it in g.items if it.meta.exam_date})
        when = dates[0] if len(dates) == 1 else (f"{dates[0]} … {dates[-1]}" if dates else "—")
        names = [os.path.basename(it.path) for it in g.items]
        files = "\n".join(names[:12]) + (f"\n… 외 {len(names) - 12}장" if len(names) > 12 else "")
        shown = f"{os.path.basename(g.where)} › {names[0]}" + (f" 외 {len(names) - 1}장" if len(names) > 1 else "")
        texts = {C_ID: g.patient_id, C_NAME: g.name, C_BIRTH: g.birth_date, C_SEX: SEX_TEXT.get(g.sex, ""),
                 C_COUNT: f"{len(g.items)}장", C_DATES: when, C_FILES: shown, C_STATE: ""}
        for c, text in texts.items():
            it = QTableWidgetItem(text)
            if c not in EDITABLE:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if c == C_COUNT:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if c in (C_COUNT, C_FILES):
                it.setToolTip(f"{g.where}\n{files}")
            if c == C_FILES:
                it.setForeground(QColor(theme.TEXT3))
            if c == C_DATES and any(x.meta.sources.get("exam_date") == "file-time" for x in g.items):
                it.setToolTip("사진에 검사일이 없어 파일을 만든 시각을 씁니다")
            self.table.setItem(r, c, it)
        self.table.item(r, C_ID).setToolTip("환자 ID — 눌러서 고칠 수 있습니다" + (
            f"\n읽은 곳: {SOURCE_LABELS.get(g.source, g.source)}" if g.source else ""))
        if g.suggestion is not None:
            pid, label = g.suggestion
            b = QPushButton(f"← {label}")
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ color:{theme.ACCENT_HI}; background:transparent; border:0; "
                            f"padding:0 8px; min-height:0; text-align:left; }} "
                            f"QPushButton:hover {{ color:{theme.TEXT}; }}")
            b.setToolTip("이 사진들을 이 환자의 사진으로 가져옵니다 (환자 ID 칸에 적어 넣습니다)")
            b.clicked.connect(lambda _=False, r=r, pid=pid: self.set_patient(r, pid))
            self.table.setCellWidget(r, C_PICK, b)

    def _text(self, r: int, c: int) -> str:
        it = self.table.item(r, c)
        return it.text().strip() if it is not None else ""

    def set_patient(self, r: int, patient_id: str) -> None:
        """Give row ``r`` this patient id (as typing it into the cell does)."""
        self.table.item(r, C_ID).setText(patient_id)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        r = item.row()
        if item.column() == C_ID:
            pid = "".join(item.text().split())
            row = self.db.find_patient(pid) if pid else None
            self._filling = True
            if item.text() != pid:
                item.setText(pid)
            if row is not None:                      # a registered patient: their data, as registered
                self.table.item(r, C_NAME).setText(row["name"] or self._text(r, C_NAME))
                self.table.item(r, C_BIRTH).setText(row["birth_date"] or self._text(r, C_BIRTH))
                self.table.item(r, C_SEX).setText(SEX_TEXT.get(row["sex"] or "", "") or self._text(r, C_SEX))
            self._filling = False
        self._refresh_state(r)
        self._refresh_summary()

    def _refresh_state(self, r: int) -> None:
        g = self.groups[r]
        pid = self._text(r, C_ID)
        text, color = "", theme.TEXT2
        if not pid:
            text, color = "환자 정보 없음 — 환자 ID를 적으면 그 환자로, 비우면 미분류로", theme.ORANGE
        else:
            row = self.db.find_patient(pid)
            if row is None:
                text, color = "새 환자로 등록됩니다", theme.GREEN
            else:
                text = "등록된 환자"
                read = (g.name or "").replace(" ", "").lower()
                have = (row["name"] or "").replace(" ", "").lower()
                if pid == g.patient_id and read and have and read != have:
                    text = f"이름이 다릅니다 — 사진: {g.name} / 등록: {row['name']} (등록된 환자로 들어갑니다)"
                    color = theme.ORANGE
            if pid != g.patient_id:
                text += " · 직접 지정"
            elif g.source in ("folder", "filename"):
                text += f" · {SOURCE_LABELS.get(g.source, g.source)}에서 읽음"
        already = sum(1 for it in g.items if it.status == "duplicate")
        if already:
            text += f" · {already}장은 이미 미분류에 있는 사진"
        it = self.table.item(r, C_STATE)
        self._filling = True
        it.setText(text)
        it.setForeground(QColor(color))
        it.setToolTip(text)
        self._filling = False

    def _refresh_summary(self) -> None:
        if not self._ready:
            return
        n = sum(len(g.items) for g in self.groups)
        named = [r for r in range(len(self.groups)) if self._text(r, C_ID)]
        n_named = sum(len(self.groups[r].items) for r in named)
        patients = len({self._text(r, C_ID) for r in named})
        if not self.items:
            head = "가져올 사진 파일이 없습니다."
        elif not n:
            head = "새로 가져올 사진이 없습니다."
        else:
            head = f"사진 {n}장 — 환자 {patients}명"
            if n - n_named:
                head += f" · <span style='color:{theme.ORANGE}'>환자 정보 없음 {n - n_named}장</span>"
            head += ".  환자 정보를 확인하고 [가져오기]를 누르세요. 표의 칸을 눌러 고칠 수 있습니다."
        self.lbl_head.setText(head)
        notes = []
        if self.skipped:
            notes.append(f"이미 가져온 사진 {self.skipped}장은 건너뜁니다.")
        if self.failed:
            names = ", ".join(os.path.basename(it.path) for it in self.failed[:3])
            notes.append(f"읽을 수 없는 파일 {len(self.failed)}개: {names}{' …' if len(self.failed) > 3 else ''}")
        self.lbl_note.setText("  ".join(notes))
        self.lbl_note.setVisible(bool(notes))
        self.btn_ok.setEnabled(n > 0)
        self.btn_ok.setText(f"가져오기 ({n}장)" if n else "가져오기")

    # -- result --------------------------------------------------------------
    def _accept(self) -> None:
        self.table.setCurrentItem(None)              # an edit still open is taken over
        for r in range(len(self.groups)):
            birth, sex = self._text(r, C_BIRTH), self._text(r, C_SEX)
            if birth and not norm_date(birth):
                QMessageBox.warning(self, "생년월일", f"생년월일을 YYYY-MM-DD 형식으로 적어 주세요: {birth}")
                self.table.setCurrentCell(r, C_BIRTH)
                return
            if sex and not norm_sex(sex):
                QMessageBox.warning(self, "성별", f"성별은 남 / 여 로 적어 주세요: {sex}")
                self.table.setCurrentCell(r, C_SEX)
                return
        self.accept()

    def result_items(self) -> list[tuple[PreviewItem, PatientAssign | None]]:
        """The photos to import, each with the patient the user gave it (``None``: as the file says)."""
        out: list[tuple[PreviewItem, PatientAssign | None]] = []
        for r, g in enumerate(self.groups):
            pid = self._text(r, C_ID)
            name, birth = self._text(r, C_NAME), norm_date(self._text(r, C_BIRTH)) or ""
            sex = norm_sex(self._text(r, C_SEX)) or ""
            changed = (pid, name, birth, sex) != (g.patient_id, g.name, g.birth_date, g.sex)
            assign = PatientAssign(pid, name or None, birth or None, sex or None) if pid and changed else None
            for it in g.items:
                if it.status == "duplicate" and not pid:
                    continue                         # already in 미분류 and still nobody's: nothing to do
                out.append((it, assign))
        return out

    def done(self, code: int) -> None:
        self._cancel.set()
        self._thread.join(timeout=5)
        super().done(code)
