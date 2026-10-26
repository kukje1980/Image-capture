"""보고서 만들기 — 실을 영상을 고르고 소견을 적어 Word(.docx) · PDF · 인쇄로 내보낸다."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app import brand as app_brand
from app.services import report_docx
from app.ui.pro import print_util
from app.ui.pro.pro_workspace import caption_of, load_bgr

_PER_PAGE = [(1, "1장 (크게)"), (2, "2장"), (4, "4장 (2×2)")]


class ReportDialog(QDialog):
    def __init__(self, config, patient, captures: list, exam=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("보고서 만들기")
        self.resize(760, 640)
        self.config = config
        self.patient = patient
        self.exam = exam
        self._caps = [c for c in captures if c.media_type == "photo"]

        self.list = QListWidget()
        self.list.setObjectName("ThumbList")
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(120, 90))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        for c in self._caps:
            it = QListWidgetItem(QIcon(QPixmap(c.thumbnail_path or c.file_path)), (c.captured_at or "")[5:16])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setToolTip(caption_of(c))
            self.list.addItem(it)
        self.c_per = QComboBox()
        for n, label in _PER_PAGE:
            self.c_per.addItem(label, n)
        per = getattr(config, "report_per_page", 2)
        self.c_per.setCurrentIndex(next((i for i, (n, _) in enumerate(_PER_PAGE) if n == per), 1))
        self.doctor = QLineEdit((patient.doctor if patient else "") or "")
        self.findings = QTextEdit()
        self.findings.setPlaceholderText("소견을 입력하세요 (보고서 소견란에 들어갑니다)")
        seed = [x for x in ((exam.diagnosis if exam else None), (patient.diagnosis if patient else None)) if x]
        if seed:
            self.findings.setPlainText(seed[0])
        self.findings.setFixedHeight(110)

        form = QFormLayout()
        form.addRow("한 쪽 영상 수 (Word)", self.c_per)
        form.addRow("판독의 / 확인자", self.doctor)
        form.addRow("소견", self.findings)

        sel = QHBoxLayout()
        b_all = QPushButton("모두 선택")
        b_none = QPushButton("모두 해제")
        sel.addWidget(QLabel("실을 영상 (체크한 순서대로)"))
        sel.addStretch(1)
        sel.addWidget(b_all)
        sel.addWidget(b_none)
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none.clicked.connect(lambda: self._check_all(False))

        btns = QHBoxLayout()
        self.b_word = QPushButton("Word 로 저장")
        self.b_word.setObjectName("Primary")
        self.b_pdf = QPushButton("PDF 로 저장")
        self.b_print = QPushButton("인쇄")
        b_close = QPushButton("닫기")
        btns.addWidget(b_close)
        btns.addStretch(1)
        for b in (self.b_print, self.b_pdf, self.b_word):
            btns.addWidget(b)
        b_close.clicked.connect(self.reject)
        self.b_word.clicked.connect(lambda: self._save_dialog("docx"))
        self.b_pdf.clicked.connect(lambda: self._save_dialog("pdf"))
        self.b_print.clicked.connect(self.print_report)

        lay = QVBoxLayout(self)
        lay.addLayout(sel)
        lay.addWidget(self.list, 1)
        lay.addLayout(form)
        lay.addLayout(btns)

    def _check_all(self, on: bool) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def items(self) -> list:
        out = []
        for i, c in enumerate(self._caps):
            if self.list.item(i).checkState() == Qt.CheckState.Checked:
                img = load_bgr(c.file_path)
                if img is not None:
                    out.append((img, caption_of(c)))
        return out

    def _common(self) -> dict:
        b = app_brand.current()
        return dict(title=b["report_title"], clinic=getattr(self.config, "clinic_name", "") or "",
                    rule_color=b.get("report_rule", "#0d9488"))

    # ---- 내보내기 ----
    def export_docx(self, path: str) -> int:
        per = self.c_per.currentData()
        self.config.report_per_page = per
        return report_docx.build_docx(path, self.patient, self.items(), exam=self.exam,
                                      findings=self.findings.toPlainText().strip(),
                                      doctor=self.doctor.text().strip(), per_page=per, **self._common())

    def export_pdf(self, path: str) -> int:
        items = self.items()
        if not items:
            return 0
        return print_util.render_report(print_util.make_pdf_printer(path), self.patient, items,
                                        notes=self.findings.toPlainText().strip(), **self._common())

    def default_path(self, ext: str) -> str:
        base = getattr(self.config, "export_root", "") or os.path.expanduser("~")
        chart = (self.patient.chart_no if self.patient else None) or "report"
        return os.path.join(base, f"{chart}_{datetime.now():%Y%m%d_%H%M}.{ext}")

    def _save_dialog(self, ext: str) -> None:
        if not self.items():
            QMessageBox.information(self, "보고서", "실을 영상을 하나 이상 체크하세요.")
            return
        flt = "Word 문서 (*.docx)" if ext == "docx" else "PDF (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "보고서 저장", self.default_path(ext), flt)
        if not path:
            return
        try:
            n = self.export_docx(path) if ext == "docx" else self.export_pdf(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "보고서", f"저장하지 못했습니다.\n{e}")
            return
        unit = "장" if ext == "docx" else "쪽"
        QMessageBox.information(self, "보고서", f"보고서를 저장했습니다 ({n}{unit}).\n{path}")

    def print_report(self) -> None:
        items = self.items()
        if not items:
            QMessageBox.information(self, "인쇄", "실을 영상을 하나 이상 체크하세요.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec():
            print_util.render_report(printer, self.patient, items,
                                     notes=self.findings.toPlainText().strip(), **self._common())
