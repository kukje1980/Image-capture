"""검사 기록 화면 — 촬영일별 검사 목록(왼쪽) · 그날의 영상 모음과 소견(가운데) · 환자 정보(오른쪽).

참고한 장비 프로그램의 환자 상세(Examinations · Description) 페이지를 따른다.
소견은 환자·촬영일마다 한 건(db.exam_notes)이며, 입력 칸을 벗어나거나 '저장'을 누르면 저장된다.
"""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import brand as app_brand
from app.ui import icons
from app.ui.control_bar import tool_button
from app.ui.patient_panel import age_of
from app.ui.pro import print_util
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT
from app.ui.thumbnail_panel import day_label
from app.ui.thumbnail_widget import ThumbnailWidget

_SEX = {"M": "남", "F": "여", "O": "기타"}

# 검사 종류 서식: 고르면 소견란이 비어 있을 때 틀을 채워 준다
EXAM_TYPES = [
    ("", ""),
    ("세극등 검사", "전안부: \n각막: \n전방: \n홍채/동공: \n수정체: \n"),
    ("각막", "상피: \n실질: \n내피: \n형광 염색: \n"),
    ("결막/공막", "충혈: \n결막 부종: \n분비물: \n"),
    ("안검/마이봄샘", "안검연: \n마이봄샘 개구부: \n분비물 성상: \n탈락 등급: \n"),
    ("건성안", "TBUT: \nSchirmer: \n각막 염색: \n"),
    ("수정체/백내장", "혼탁 위치: \n등급(LOCS): \n"),
    ("경과 관찰", "이전 대비: \n"),
    ("기타", ""),
]


def _esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ExamScreen(QWidget):
    openCapture = Signal(object)          # Capture 클릭 → 보기
    openInPro = Signal()                  # 'Pro 검토에서 열기'
    editPatient = Signal()

    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._patient = None
        self._caps: list = []
        self._days: list[str] = []
        self._day: str | None = None
        self._notes_dirty = False
        self._loading = False
        self._build()

    # ---------------- 구성 ----------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ---- 왼쪽: 검사 기록 목록 ----
        left = QFrame()
        left.setObjectName("Panel")
        left.setFixedWidth(250)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 10, 12, 10)
        ll.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("검사 기록")
        t.setObjectName("ThumbTitle")
        self.badge_days = QLabel("0")
        self.badge_days.setObjectName("CountBadge")
        head.addWidget(t)
        head.addWidget(self.badge_days)
        head.addStretch(1)
        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("HomeLink")
        self.btn_refresh.setIcon(icons.icon("history", ICON, 16))
        self.btn_refresh.setToolTip("다시 읽기")
        self.btn_refresh.clicked.connect(lambda: self.reload())
        head.addWidget(self.btn_refresh)
        ll.addLayout(head)
        self.day_list = QListWidget()
        self.day_list.setObjectName("ExamList")
        self.day_list.setSpacing(2)
        self.day_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.day_list.currentRowChanged.connect(self._on_day_row)
        ll.addWidget(self.day_list, 1)
        self.lbl_empty_days = QLabel("촬영 기록이 없습니다")
        self.lbl_empty_days.setObjectName("Muted")
        self.lbl_empty_days.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.lbl_empty_days)
        root.addWidget(left)

        # ---- 가운데: 영상 모음 + 소견 ----
        center = QVBoxLayout()
        center.setSpacing(12)
        gal = QFrame()
        gal.setObjectName("Panel")
        gl = QVBoxLayout(gal)
        gl.setContentsMargins(12, 10, 12, 8)
        gl.setSpacing(8)
        gh = QHBoxLayout()
        self.lbl_day = QLabel("촬영일을 선택하세요")
        self.lbl_day.setObjectName("ThumbTitle")
        self.lbl_day_meta = QLabel("")
        self.lbl_day_meta.setObjectName("Muted")
        gh.addWidget(self.lbl_day)
        gh.addSpacing(8)
        gh.addWidget(self.lbl_day_meta)
        gh.addStretch(1)
        self.btn_pro = tool_button("Pro 검토", "review", "ToolBtn", tip="이 환자의 영상을 Pro 검토 화면에서 열기", icon_size=20, min_width=56)
        self.btn_print = tool_button("인쇄", "printer", "ToolBtn", tip="이 날의 영상 + 소견을 보고서로 인쇄", icon_size=20, min_width=56)
        self.btn_pdf = tool_button("PDF", "file-pdf", "ToolBtn", tip="이 날의 영상 + 소견을 PDF 보고서로 저장", icon_size=20, min_width=56)
        self.btn_pro.clicked.connect(lambda: self.openInPro.emit())
        self.btn_print.clicked.connect(lambda: self.print_day())
        self.btn_pdf.clicked.connect(lambda: self.export_pdf_dialog())
        for b in (self.btn_pro, self.btn_print, self.btn_pdf):
            gh.addWidget(b)
        gl.addLayout(gh)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("ExamGrid")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 6, 0)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        gl.addWidget(self.scroll, 1)
        self.lbl_empty = QLabel("이 날의 촬영 영상이 없습니다")
        self.lbl_empty.setObjectName("Muted")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl.addWidget(self.lbl_empty)
        center.addWidget(gal, 3)

        desc = QFrame()
        desc.setObjectName("Panel")
        dl = QVBoxLayout(desc)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setSpacing(8)
        dh = QHBoxLayout()
        dt = QLabel("검사 소견")
        dt.setObjectName("ThumbTitle")
        dh.addWidget(dt)
        dh.addSpacing(12)
        dh.addWidget(QLabel("검사 종류"))
        self.cmb_type = QComboBox()
        for name, _tpl in EXAM_TYPES:
            self.cmb_type.addItem(name or "선택 안 함")
        self.cmb_type.setMinimumWidth(170)
        self.cmb_type.currentIndexChanged.connect(self._on_type_changed)
        dh.addWidget(self.cmb_type)
        dh.addStretch(1)
        self.lbl_saved = QLabel("")
        self.lbl_saved.setObjectName("Muted")
        dh.addWidget(self.lbl_saved)
        self.btn_save = QPushButton(icons.gap("저장"))
        self.btn_save.setObjectName("Primary")
        self.btn_save.setIcon(icons.icon("save", ICON_ON_ACCENT, 16))
        self.btn_save.setIconSize(QSize(15, 15))
        self.btn_save.clicked.connect(lambda: self.save_notes())
        dh.addWidget(self.btn_save)
        dl.addLayout(dh)
        self.txt_notes = QPlainTextEdit()
        self.txt_notes.setPlaceholderText("검사 소견·진단·계획을 적으세요. 칸을 벗어나면 자동 저장됩니다.")
        self.txt_notes.setMinimumHeight(96)
        self.txt_notes.textChanged.connect(self._on_notes_changed)
        self.txt_notes.installEventFilter(self)
        dl.addWidget(self.txt_notes, 1)
        center.addWidget(desc, 2)
        root.addLayout(center, 1)

        # ---- 오른쪽: 환자 정보 ----
        right = QFrame()
        right.setObjectName("Panel")
        right.setFixedWidth(250)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(8)
        rh = QHBoxLayout()
        rt = QLabel("환자 정보")
        rt.setObjectName("ThumbTitle")
        rh.addWidget(rt)
        rh.addStretch(1)
        self.btn_edit = QPushButton()
        self.btn_edit.setObjectName("HomeLink")
        self.btn_edit.setIcon(icons.icon("user-edit", ICON, 16))
        self.btn_edit.setToolTip("정보 수정")
        self.btn_edit.clicked.connect(lambda: self.editPatient.emit())
        rh.addWidget(self.btn_edit)
        rl.addLayout(rh)
        self.lbl_patient = QLabel()
        self.lbl_patient.setObjectName("ExamPatient")
        self.lbl_patient.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_patient.setWordWrap(True)
        self.lbl_patient.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.lbl_patient, 1)
        root.addWidget(right)

        self._render_patient()
        self._set_notes_enabled(False)

    # ---------------- 공개 API ----------------
    def set_patient(self, patient) -> None:
        self.flush()
        self._patient = patient
        self._render_patient()
        self.reload()

    def reload(self, keep_day: bool = True) -> None:
        """DB 에서 다시 읽어 촬영일 목록과 현재 날짜의 영상을 갱신."""
        prev = self._day if keep_day else None
        self._caps = (self.db.captures.list_by_patient(self._patient.id, order="desc")
                      if self._patient else [])
        days: list[str] = []
        for c in self._caps:
            d = (c.captured_at or "")[:10]
            if d and d not in days:
                days.append(d)
        self._days = days
        notes = self.db.exam_notes.list_by_patient(self._patient.id) if self._patient else {}
        self.day_list.blockSignals(True)
        self.day_list.clear()
        for d in days:
            caps = [c for c in self._caps if (c.captured_at or "")[:10] == d]
            n_od = sum(1 for c in caps if c.eye == "OD")
            n_os = sum(1 for c in caps if c.eye == "OS")
            n_vid = sum(1 for c in caps if c.media_type == "video")
            bits = [f"{len(caps)}장"]
            if n_od:
                bits.append(f"OD {n_od}")
            if n_os:
                bits.append(f"OS {n_os}")
            if n_vid:
                bits.append(f"동영상 {n_vid}")
            note = notes.get(d)
            tag = f"  ·  {note['exam_type']}" if note and note.get("exam_type") else ""
            it = QListWidgetItem(f"{day_label(d)}{tag}\n" + " · ".join(bits))
            it.setData(Qt.ItemDataRole.UserRole, d)
            it.setIcon(icons.icon("check-circle" if note and (note.get("notes") or note.get("exam_type")) else "clipboard",
                                  ICON_ACCENT if note else ICON, 18))
            it.setSizeHint(QSize(0, 48))
            self.day_list.addItem(it)
        self.day_list.blockSignals(False)
        self.badge_days.setText(str(len(days)))
        self.lbl_empty_days.setVisible(not days)
        if days:
            row = days.index(prev) if prev in days else 0
            self.day_list.setCurrentRow(row)
            self._show_day(days[row])
        else:
            self._show_day(None)

    def current_day(self) -> str | None:
        return self._day

    def day_captures(self) -> list:
        return [c for c in self._caps if self._day and (c.captured_at or "")[:10] == self._day]

    def flush(self) -> None:
        """바뀐 소견이 있으면 저장 (화면·환자·날짜 전환 전에 부른다)."""
        if self._notes_dirty and self._patient and self._day:
            self.save_notes()

    def save_notes(self) -> None:
        if not (self._patient and self._day):
            return
        idx = self.cmb_type.currentIndex()
        exam_type = EXAM_TYPES[idx][0] if 0 <= idx < len(EXAM_TYPES) else ""
        self.db.exam_notes.upsert(self._patient.id, self._day, exam_type, self.txt_notes.toPlainText())
        self._notes_dirty = False
        self.lbl_saved.setText(f"저장됨 {datetime.now():%H:%M}")
        self._refresh_day_item()

    # ---------------- 내부 ----------------
    def _on_day_row(self, row: int) -> None:
        if 0 <= row < len(self._days):
            self.flush()
            self._show_day(self._days[row])

    def _show_day(self, day: str | None) -> None:
        self._day = day
        caps = self.day_captures()
        # 영상 격자
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        cols = 4
        for i, c in enumerate(caps):
            w = ThumbnailWidget(c)
            w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            w.setFixedSize(196, 147)                 # 4:3 고정 (resizeEvent 의 높이 재계산이 되돌이표가 되지 않게)
            w.clicked.connect(self.openCapture.emit)
            self.grid.addWidget(w, i // cols, i % cols)
        self.lbl_empty.setVisible(day is not None and not caps)
        self.scroll.setVisible(bool(caps))
        if day is None:
            self.lbl_day.setText("촬영일을 선택하세요" if self._patient else "환자를 선택하세요")
            self.lbl_day_meta.setText("")
        else:
            self.lbl_day.setText(day_label(day))
            first = caps[-1].captured_at[11:16] if caps and caps[-1].captured_at else ""
            last = caps[0].captured_at[11:16] if caps and caps[0].captured_at else ""
            span = f"{first} ~ {last}" if first and last and first != last else first
            self.lbl_day_meta.setText(f"{len(caps)}장" + (f"  ·  {span}" if span else ""))
        for b in (self.btn_print, self.btn_pdf):
            b.setEnabled(any(c.media_type == "photo" for c in caps))
        self.btn_pro.setEnabled(bool(self._patient))
        # 소견
        self._loading = True
        note = self.db.exam_notes.get(self._patient.id, day) if (self._patient and day) else None
        names = [n for n, _ in EXAM_TYPES]
        self.cmb_type.setCurrentIndex(names.index(note["exam_type"]) if note and note.get("exam_type") in names else 0)
        self.txt_notes.setPlainText((note or {}).get("notes") or "")
        self.lbl_saved.setText(f"저장됨 {note['updated_at'][5:16]}" if note and note.get("updated_at") else "")
        self._loading = False
        self._notes_dirty = False
        self._set_notes_enabled(day is not None)

    def _set_notes_enabled(self, on: bool) -> None:
        for w in (self.cmb_type, self.txt_notes, self.btn_save):
            w.setEnabled(on)

    def _on_type_changed(self, idx: int) -> None:
        if self._loading:
            return
        tpl = EXAM_TYPES[idx][1] if 0 <= idx < len(EXAM_TYPES) else ""
        if tpl and not self.txt_notes.toPlainText().strip():
            self.txt_notes.setPlainText(tpl)
        self._notes_dirty = True
        self.lbl_saved.setText("수정 중…")

    def _on_notes_changed(self) -> None:
        if self._loading:
            return
        self._notes_dirty = True
        self.lbl_saved.setText("수정 중…")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.txt_notes and event.type() == event.Type.FocusOut:
            self.flush()
        return super().eventFilter(obj, event)

    def _refresh_day_item(self) -> None:
        row = self.day_list.currentRow()
        if row < 0 or self._day is None:
            return
        note = self.db.exam_notes.get(self._patient.id, self._day)
        it = self.day_list.item(row)
        if it is None:
            return
        text = it.text().split("\n", 1)
        tag = f"  ·  {note['exam_type']}" if note and note.get("exam_type") else ""
        it.setText(f"{day_label(self._day)}{tag}\n{text[1] if len(text) > 1 else ''}")
        it.setIcon(icons.icon("check-circle" if note and (note.get("notes") or note.get("exam_type")) else "clipboard",
                              ICON_ACCENT if note else ICON, 18))

    def _render_patient(self) -> None:
        p = self._patient
        self.btn_edit.setEnabled(p is not None)
        if p is None:
            self.lbl_patient.setText("<span style='color:#8b95a3'>환자를 선택하세요</span>")
            return
        age = age_of(p.birth_date)
        rows = [
            ("이름", f"<b>{_esc(p.name)}</b>"),
            ("차트번호", _esc(p.chart_no or "-")),
            ("환자ID", _esc(p.patient_id or "-")),
            ("성별 · 나이", " · ".join(x for x in (_SEX.get(p.sex or "", ""), f"{age}세" if age is not None else "") if x) or "-"),
            ("생년월일", _esc(p.birth_date or "-")),
            ("연락처", _esc(p.phone or "-")),
            ("진단명", f"<b>{_esc(p.diagnosis or '-')}</b>"),
            ("담당의", _esc(p.doctor or "-")),
            ("증상", _esc(p.symptoms or "-").replace("\n", "<br>")),
            ("메모", _esc(p.memo or "-").replace("\n", "<br>")),
        ]
        html = "".join(f"<div style='margin:0 0 9px'><span style='color:#8b95a3;font-size:11px'>{k}</span><br>{v}</div>"
                       for k, v in rows)
        self.lbl_patient.setText(html)

    # ---------------- 보고서 ----------------
    def report_items(self) -> list:
        from app.ui.pro.pro_workspace import caption_of, load_bgr
        items = []
        for c in reversed(self.day_captures()):           # 촬영 순서대로
            if c.media_type != "photo":
                continue
            img = load_bgr(c.file_path)
            if img is not None:
                items.append((img, caption_of(c)))
        return items

    def _report_kwargs(self) -> dict:
        b = app_brand.current()
        return dict(clinic=getattr(self.config, "clinic_name", "") or "", title=b["report_title"],
                    rule_color=b.get("report_rule", "#0d9488"), notes=self._notes_for_report())

    def _notes_for_report(self) -> str:
        idx = self.cmb_type.currentIndex()
        t = EXAM_TYPES[idx][0] if 0 <= idx < len(EXAM_TYPES) else ""
        body = self.txt_notes.toPlainText().strip()
        return (f"[{t}]\n" if t else "") + body

    def export_pdf(self, path: str) -> int:
        items = self.report_items()
        if not items:
            return 0
        printer = print_util.make_pdf_printer(path)
        return print_util.render_report(printer, self._patient, items, **self._report_kwargs())

    def export_pdf_dialog(self) -> None:
        if not self.report_items():
            QMessageBox.information(self, "PDF", "출력할 사진이 없습니다.")
            return
        base = getattr(self.config, "export_root", "") or os.path.expanduser("~")
        chart = (self._patient.chart_no if self._patient else None) or "report"
        default = os.path.join(base, f"{chart}_{(self._day or '').replace('-', '')}_검사기록.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "PDF 보고서 저장", default, "PDF (*.pdf)")
        if path:
            n = self.export_pdf(path)
            QMessageBox.information(self, "PDF", f"{n}쪽 보고서를 저장했습니다.\n{path}")

    def print_day(self) -> None:
        items = self.report_items()
        if not items:
            QMessageBox.information(self, "인쇄", "출력할 사진이 없습니다.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec():
            print_util.render_report(printer, self._patient, items, **self._report_kwargs())
