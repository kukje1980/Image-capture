"""DICOM windows: 워크리스트 (the day's orders of the worklist server) and DICOM 전송 (photos to the PACS).

Both talk to the network in a worker thread (``dicomnet``) and never block the window; the
servers are set in 설정 → DICOM.

* **워크리스트** — the orders of a day; a double click (Enter · [환자 열기]) registers the patient
  if new, keeps the order for that patient and day, and opens the patient in the main window.
  Photos imported next are offered that patient with one click (사진 가져오기 → 확인 창), and
  the photos of that day are sent under the order (Accession Number).
* **DICOM 전송** — the photos chosen, each with its patient and the order it goes under; the
  result of each is shown in its row and remembered with the photo.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from .. import dicomnet
from ..config import Settings
from ..models import MODALITY_LABELS, ExtractedMeta
from . import theme
from .widgets import filling

SEX_TEXT = {"M": "남", "F": "여", "O": "기타"}


def _table(columns, stretch: int) -> QTableWidget:
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(list(columns))
    t.verticalHeader().hide()
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    h = t.horizontalHeader()
    for c in range(len(columns)):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == stretch
                               else QHeaderView.ResizeMode.ResizeToContents)
    return t


def _plain_buttons(dialog: QDialog) -> None:
    for b in dialog.findChildren(QPushButton):       # Enter belongs to the table, not to a button
        b.setAutoDefault(False)
        b.setDefault(False)


# =============================================================================================
# 워크리스트
# =============================================================================================
W_COLS = ("시각", "환자 ID", "이름", "생년월일", "성별", "검사", "Accession No.", "의뢰의", "상태")
W_TIME, W_ID, W_NAME, W_BIRTH, W_SEX, W_WHAT, W_ACC, W_DOC, W_STATE = range(len(W_COLS))


class WorklistDialog(QDialog):
    opened = Signal(object)                 # patients.id — the patient to open in the main window
    answered = Signal(int, object, str)     # query number, list[Order] | None, error — from the worker

    def __init__(self, db, settings: Settings, parent=None):
        super().__init__(parent)
        self.setObjectName("worklistWindow")
        self.setWindowTitle("워크리스트")
        self.setWindowFlags(Qt.WindowType.Window)    # a window of its own, not modal (as 환자 목록)
        self.setModal(False)
        self.resize(1040, 560)
        self.db, self.settings = db, settings
        self.find = dicomnet.find_worklist           # tests put their own here
        self.orders: list[dicomnet.Order] = []       # as answered
        self.shown: list[dicomnet.Order] = []        # … through the search box, as listed
        self._asked = 0                              # number of the newest query: older answers are dropped
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("워크리스트")
        title.setObjectName("pageTitle")
        head.addWidget(title)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("caption")
        head.addWidget(self.lbl_count)
        head.addStretch(1)
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("하루 전")
        self.btn_prev.clicked.connect(lambda: self.set_day(self.day.date().addDays(-1)))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("yyyy-MM-dd")
        self.day.dateChanged.connect(lambda _: self.refresh())
        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("하루 뒤")
        self.btn_next.clicked.connect(lambda: self.set_day(self.day.date().addDays(1)))
        self.btn_today = QPushButton("오늘")
        self.btn_today.clicked.connect(lambda: self.set_day(QDate.currentDate()))
        self.search = QLineEdit()
        self.search.setPlaceholderText("환자 ID · 이름으로 찾기")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        self.btn_refresh = QPushButton("조회")
        self.btn_refresh.setToolTip("워크리스트 서버에서 다시 읽습니다 (F5)")
        self.btn_refresh.clicked.connect(self.refresh)
        for w in (self.btn_prev, self.day, self.btn_next, self.btn_today):
            bar.addWidget(w)
        bar.addSpacing(10)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.btn_refresh)
        root.addLayout(bar)

        self.table = _table(W_COLS, W_WHAT)
        self.table.setObjectName("worklistTable")
        self.table.itemDoubleClicked.connect(lambda _: self.open_selected())
        self.table.itemSelectionChanged.connect(self._on_selection)
        root.addWidget(self.table, 1)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.lbl_info)

        row = QHBoxLayout()
        hint = QLabel("두 번 누르기 / Enter: 환자 열기 — 새 환자는 등록되고, 이 날의 사진은 이 검사(Accession No.)로 전송됩니다")
        hint.setObjectName("caption")
        row.addWidget(hint, 1)
        self.btn_open = QPushButton("환자 열기")
        self.btn_open.setObjectName("primary")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_selected)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.hide)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_close)
        root.addLayout(row)
        _plain_buttons(self)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QShortcut(QKeySequence(key), self.table, activated=self.open_selected,
                      context=Qt.ShortcutContext.WidgetShortcut)
        self.answered.connect(self._on_answer)

    # -- asking the server ------------------------------------------------------------------
    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(0, self.refresh)           # every time it comes up: the list as it is now

    def set_day(self, day: QDate) -> None:
        self.day.setDate(day)                        # -> refresh (dateChanged); the same day: asked again
        if not self._busy:
            self.refresh()

    def iso_day(self) -> str:
        return self.day.date().toString("yyyy-MM-dd")

    def refresh(self) -> None:
        node = dicomnet.worklist_node(self.settings)
        if not node.ok:
            self.orders = []
            self._fill()
            self._say("워크리스트 서버가 설정되지 않았습니다 — 설정 → DICOM 에서 서버 주소 · 포트 · AE Title을 "
                      "입력하세요.", theme.ORANGE)
            return
        self._asked += 1
        self._busy = True
        self.btn_refresh.setEnabled(False)
        self._say(f"워크리스트를 읽는 중… ({node.label})", theme.TEXT3)
        threading.Thread(target=self._ask, args=(self._asked, self.iso_day()), name="fundus-worklist",
                         daemon=True).start()

    def _ask(self, number: int, day: str) -> None:
        try:
            orders, error = self.find(self.settings, day), ""
        except dicomnet.DicomError as exc:
            orders, error = None, str(exc)
        except Exception as exc:                     # anything the network library throws
            orders, error = None, f"{type(exc).__name__}: {exc}"[:300]
        try:
            self.answered.emit(number, orders, error)
        except RuntimeError:                         # the window is gone
            pass

    def _on_answer(self, number: int, orders, error: str) -> None:
        if number != self._asked:
            return                                   # the answer to an older question
        self._busy = False
        self.btn_refresh.setEnabled(True)
        if orders is None:
            self.orders = []
            self._fill()
            self._say(f"워크리스트를 읽지 못했습니다 — {error}", theme.RED)
            return
        self.orders = orders
        self._fill()
        modality = (self.settings.mwl_modality or "").strip().upper()
        what = f" ({modality})" if modality else ""
        self._say(f"{self.iso_day()} 예약 검사{what} {len(orders)}건 — {datetime.now():%H:%M:%S} 조회"
                  if orders else f"{self.iso_day()}에 예약된 검사{what}가 없습니다.", theme.TEXT3)

    def _say(self, text: str, color: str) -> None:
        self.lbl_info.setText(text)
        self.lbl_info.setStyleSheet(f"color:{color}")

    # -- the list ---------------------------------------------------------------------------
    def _state(self, o: dicomnet.Order) -> tuple[str, str]:
        if not o.patient_id:
            return "환자 ID 없음", theme.ORANGE
        row = self.db.find_patient(o.patient_id)
        if row is None:
            return "새 환자", theme.GREEN
        n = sum(1 for r in self.db.images_for_patient(row["id"]) if r["exam_date"] == o.date)
        text = f"등록된 환자 · 이 날 사진 {n}장" if n else "등록된 환자"
        have, read = (row["name"] or "").replace(" ", ""), o.name.replace(" ", "")
        if have and read and have != read:
            return f"{text} · 이름이 다릅니다 (등록: {row['name']})", theme.ORANGE
        return text, theme.TEXT2

    def _fill(self) -> None:
        words = self.search.text().lower().split()
        self.shown = [o for o in self.orders
                      if all(w in f"{o.patient_id} {o.name} {o.pn}".lower() for w in words)]
        with filling(self.table):
            self.table.setRowCount(len(self.shown))
            for r, o in enumerate(self.shown):
                state, color = self._state(o)
                texts = {W_TIME: o.time[:5], W_ID: o.patient_id, W_NAME: o.name, W_BIRTH: o.birth_date,
                         W_SEX: SEX_TEXT.get(o.sex, ""), W_WHAT: o.description, W_ACC: o.accession,
                         W_DOC: o.physician, W_STATE: state}
                for c, text in texts.items():
                    it = QTableWidgetItem(text)
                    if c == W_STATE:
                        it.setForeground(QColor(color))
                    if c == W_WHAT and (o.modality or o.station):
                        it.setToolTip(" · ".join(filter(None, (o.description, o.modality, o.station))))
                    self.table.setItem(r, c, it)
        n, m = len(self.orders), len(self.shown)
        self.lbl_count.setText(f"{m}건" if m == n else f"{m} / {n}건")
        if self.shown:
            self.table.selectRow(0)
        self._on_selection()

    def _on_selection(self) -> None:
        o = self.selected()
        self.btn_open.setEnabled(o is not None and bool(o.patient_id))

    def selected(self) -> dicomnet.Order | None:
        r = self.table.currentRow()
        return self.shown[r] if 0 <= r < len(self.shown) and self.table.selectedItems() else None

    # -- opening a patient ------------------------------------------------------------------
    def open_selected(self) -> None:
        o = self.selected()
        if o is None or not o.patient_id:
            return
        ref = self.register(o)
        if ref is not None:
            self.opened.emit(ref)

    def register(self, o: dicomnet.Order):
        """The patient of the order (registered now if new), the order kept for that patient and day."""
        ref = self.db.upsert_patient(ExtractedMeta(patient_id=o.patient_id, name=o.name or None,
                                                   birth_date=o.birth_date or None, sex=o.sex or None))
        if ref is None:                              # a server that cannot be reached (공유)
            self._say("환자를 등록하지 못했습니다 — 서버 연결을 확인하세요.", theme.RED)
            return None
        self.db.save_order(o.as_dict())
        self.db.log("info", f"워크리스트 — {o.patient_id} {o.name} ({o.date} {o.accession})".rstrip())
        return ref

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)


# =============================================================================================
# DICOM 전송
# =============================================================================================
S_COLS = ("사진", "환자", "검사일", "Accession No.", "상태")
S_PHOTO, S_PATIENT, S_DATE, S_ACC, S_STATE = range(len(S_COLS))


def sent_note(row) -> str:
    """"2026-11-21 10:15 전송함" when the photo was sent before, else ""."""
    try:
        sent = json.loads(row["meta_json"] or "{}").get("dicom_sent")
    except (ValueError, TypeError):
        sent = None
    if not isinstance(sent, dict) or not sent.get("at"):
        return ""
    return f"{str(sent['at'])[:16].replace('T', ' ')} 전송함"


def photo_label(row) -> str:
    kind = MODALITY_LABELS.get(row["modality"] or "", row["modality"] or "")
    return " ".join(filter(None, (row["laterality"] or "", kind, f"#{row['id']}")))


class DicomSendDialog(QDialog):
    progressed = Signal(int, int, object)   # done, of, SendResult | None — from the worker
    finished_all = Signal(object, str)      # list[SendResult] | None, error

    def __init__(self, db, settings: Settings, rows, parent=None, scopes=None):
        """``scopes``: ``[(label, rows), …]`` — 보낼 범위 to choose from in the window (the first: ``rows``)."""
        super().__init__(parent)
        self.setWindowTitle("DICOM 전송 (PACS)")
        self.setMinimumSize(820, 420)
        self.db, self.settings = db, settings
        self.send = dicomnet.send                    # tests put their own here
        self.rows: list = []                         # the photos that can be sent …
        self.items: list[dicomnet.Item] = []         # … and what is sent for each
        self.results: dict[int, dicomnet.SendResult] = {}
        self._batch: list[int] = []                  # the rows being sent ([다시 전송]: those not through yet)
        self.skipped = 0                             # photos of nobody (미분류): never sent
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._take(rows)
        self._build(scopes)

    def _take(self, rows) -> None:
        """The photos to send: those of a patient (미분류 photos are counted in ``skipped``)."""
        self.rows, self.items, self.results, self.skipped = [], [], {}, 0
        patients: dict = {}
        for row in rows:
            ref = row["patient_ref"]
            if ref is None:
                self.skipped += 1
                continue
            if ref not in patients:
                patients[ref] = self.db.get_patient(ref)
            patient = patients[ref]
            if patient is None:
                self.skipped += 1
                continue
            order = dicomnet.order_of(self.db.order_for(patient["patient_id"], row["exam_date"] or ""))
            # the file is looked up when it is sent (공유: it may have to be fetched first)
            self.items.append(dicomnet.item_of(row, patient, order, photo_label(row), path=""))
            self.rows.append(row)

    def _build(self, scopes) -> None:
        lay = QVBoxLayout(self)
        self.scope = None
        if scopes and len(scopes) > 1:
            self._scopes = list(scopes)
            self.scope = QComboBox()
            self.scope.setObjectName("dicomScope")
            for label, rows in self._scopes:
                self.scope.addItem(f"{label} ({len(rows)}장)")
            self.scope.currentIndexChanged.connect(self._on_scope)
            line = QHBoxLayout()
            line.addWidget(QLabel("보낼 범위"))
            line.addWidget(self.scope, 1)
            lay.addLayout(line)
        self.lbl_head = QLabel("")
        self.lbl_head.setWordWrap(True)
        lay.addWidget(self.lbl_head)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, max(len(self.items), 1))
        lay.addWidget(self.bar)
        self.table = _table(S_COLS, S_STATE)
        self.table.setObjectName("dicomSendTable")
        lay.addWidget(self.table, 1)
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet(f"color:{theme.TEXT3}")
        lay.addWidget(self.lbl_note)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_send = QPushButton("전송")
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self.start)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_send)
        row.addWidget(self.btn_close)
        lay.addLayout(row)
        self.progressed.connect(self._on_progress)
        self.finished_all.connect(self._on_finished)
        self._fill()

    def _on_scope(self, index: int) -> None:
        if self._thread is None and 0 <= index < len(self._scopes):
            self._take(self._scopes[index][1])
            self.bar.setRange(0, max(len(self.items), 1))
            self.bar.setValue(0)
            self._fill()

    def _fill(self) -> None:
        with filling(self.table):
            self.table.setRowCount(len(self.items))
            for r, (row, item) in enumerate(zip(self.rows, self.items)):
                who = " ".join(filter(None, (item.patient_id, item.name)))
                order = item.order
                texts = {S_PHOTO: item.label, S_PATIENT: who, S_DATE: item.exam_date or "날짜 없음",
                         S_ACC: order.accession if order else "", S_STATE: sent_note(row)}
                for c, text in texts.items():
                    it = QTableWidgetItem(text)
                    if c == S_STATE:
                        it.setForeground(QColor(theme.TEXT3))
                    if c == S_ACC:
                        it.setToolTip(f"워크리스트의 검사: {order.description or order.accession}" if order else
                                      "워크리스트에서 연 검사가 없습니다 — 환자 ID와 검사일로 전송됩니다")
                    self.table.setItem(r, c, it)
        node = dicomnet.pacs_node(self.settings)
        n = len(self.items)
        if not node.ok:
            head = (f"<span style='color:{theme.ORANGE}'>PACS가 설정되지 않았습니다</span> — 설정 → DICOM 에서 "
                    "서버 주소 · 포트 · AE Title을 입력하세요.")
        elif not n:
            head = "전송할 사진이 없습니다."
        else:
            head = (f"사진 {n}장을 <b>{node.label}</b> 로 전송합니다 "
                    f"(이 프로그램의 AE Title: {dicomnet.own_ae(self.settings)}).")
        self.lbl_head.setText(head)
        notes = []
        if self.skipped:
            notes.append(f"환자가 지정되지 않은 사진 {self.skipped}장은 전송하지 않습니다 (미분류).")
        again = sum(1 for row in self.rows if sent_note(row))
        if again:
            notes.append(f"이미 전송한 사진 {again}장은 다시 보내도 PACS에 한 장으로 남습니다.")
        self.lbl_note.setText("  ".join(notes))
        self.lbl_note.setVisible(bool(notes))
        self.btn_send.setEnabled(node.ok and n > 0)
        self.btn_send.setText(f"전송 ({n}장)" if n else "전송")

    # -- sending (worker thread) ------------------------------------------------------------
    @property
    def sending(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.sending or not self.items:
            return
        self._batch = [r for r, item in enumerate(self.items)
                       if not (item.image_id in self.results and self.results[item.image_id].ok)]
        if not self._batch:
            return
        self._cancel.clear()
        if self.scope is not None:
            self.scope.setEnabled(False)             # (what was sent stays on the list)
        self.btn_send.setEnabled(False)
        self.btn_close.setText("중지")
        self.bar.setRange(0, len(self._batch))
        self.bar.setValue(0)
        for r in self._batch:
            self._set_state(r, "대기 중", theme.TEXT3)
        self._thread = threading.Thread(target=self._run, name="fundus-dicom-send", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        def emit(*args) -> None:
            try:
                self.progressed.emit(*args)
            except RuntimeError:                     # the window is gone
                pass

        try:
            batch = []
            for r in self._batch:
                row, item = self.rows[r], self.items[r]
                path = row["file_path"] or ""
                if not (path and os.path.isfile(path)) and row["original_path"]:
                    path = row["original_path"]
                item.path = path
                batch.append(item)
            results, error = self.send(self.settings, batch, emit, self._cancel.is_set), ""
        except dicomnet.DicomError as exc:
            results, error = None, str(exc)
        except Exception as exc:
            results, error = None, f"{type(exc).__name__}: {exc}"[:300]
        try:
            self.finished_all.emit(results, error)
        except RuntimeError:
            pass

    def _set_state(self, r: int, text: str, color: str) -> None:
        it = self.table.item(r, S_STATE)
        it.setText(text)
        it.setToolTip(text)
        it.setForeground(QColor(color))

    def _on_progress(self, done: int, of: int, result) -> None:
        if result is None:                           # photo number ``done`` of the batch is on its way
            if done < len(self._batch):
                r = self._batch[done]
                self._set_state(r, "전송 중…", theme.ACCENT_HI)
                self.table.scrollToItem(self.table.item(r, S_STATE))
            return
        self.bar.setValue(done)
        r = self._batch[done - 1]
        self.results[result.image_id] = result
        if result.ok:
            self._set_state(r, "전송됨" + (f" ({result.message})" if result.message else ""), theme.GREEN)
            self._remember(self.rows[r], result)
        else:
            self._set_state(r, f"실패 — {result.message}", theme.RED)

    def _remember(self, row, result) -> None:
        """With the photo: when and where to it was sent."""
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except (ValueError, TypeError):
            meta = {}
        meta["dicom_sent"] = {"at": datetime.now().isoformat(timespec="seconds"),
                              "to": dicomnet.pacs_node(self.settings).label, "sop_uid": result.sop_uid}
        self.db.update_image(row["id"], meta_json=meta)

    def _on_finished(self, results, error: str) -> None:
        self.btn_close.setText("닫기")
        node = dicomnet.pacs_node(self.settings)
        if results is None:
            for r in self._batch:
                self._set_state(r, "전송하지 못함", theme.TEXT3)
            self.lbl_head.setText(f"<span style='color:{theme.RED}'>전송하지 못했습니다</span> — {error}")
            self.btn_send.setEnabled(True)
            self.btn_send.setText("다시 전송")
            self.db.log("error", f"DICOM 전송 실패 ({node.label}) — {error}")
            return
        ok = sum(1 for r in results if r.ok)
        failed = len(results) - ok
        left = len(self._batch) - len(results)       # stopped before these
        for r in self._batch[len(results):]:
            self._set_state(r, "보내지 않음 (중지)", theme.TEXT3)
        head = f"<span style='color:{theme.GREEN}'>{ok}장을 전송했습니다</span> — {node.label}"
        if failed:
            head += f" · <span style='color:{theme.RED}'>실패 {failed}장</span>"
        if left:
            head += f" · 중지 {left}장"
        self.lbl_head.setText(head)
        self.btn_send.setEnabled(bool(failed or left))
        self.btn_send.setText("다시 전송")
        self.db.log("error" if failed else "info",
                    f"DICOM 전송 ({node.label}) — {ok}장" + (f", 실패 {failed}장" if failed else ""))

    def reject(self) -> None:
        if self.sending:                             # [중지]: the photo on its way is finished, no more
            self._cancel.set()
            return
        super().reject()

    def done(self, code: int) -> None:
        self._cancel.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        super().done(code)
