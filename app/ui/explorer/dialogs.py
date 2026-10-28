"""Explorer 판의 작은 입력 창 — 검사(내원) 정보, 참조 영상 등록."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

from app.db.exams_dao import DEFAULT_TITLE
from app.models.exam import Exam

# 참조 영상 기본 분류 (사용자가 새 분류를 직접 입력할 수도 있음)
REF_CATEGORIES = ["각막", "결막", "공막", "전방", "홍채", "수정체 · 백내장", "눈꺼풀", "누관",
                  "녹내장", "망막 · 안저", "콘택트렌즈", "수술 후", "기타"]


def _buttons(dlg: QDialog) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class ExamDialog(QDialog):
    """검사(내원) 추가 / 수정 — 검사일·검사명·진단·병력 메모."""

    def __init__(self, parent=None, exam: Exam | None = None, patient_id: int = 0):
        super().__init__(parent)
        self.setWindowTitle("검사 정보" if exam and exam.id else "새 검사")
        self.resize(420, 360)
        self._exam = exam or Exam(patient_id=patient_id, exam_date=date.today().isoformat(), title=DEFAULT_TITLE)
        form = QFormLayout()
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        d = QDate.fromString(self._exam.exam_date or "", "yyyy-MM-dd")
        self.date.setDate(d if d.isValid() else QDate.currentDate())
        self.title = QComboBox()
        self.title.setEditable(True)
        self.title.addItems([DEFAULT_TITLE, "전안부 검사", "수술 전 검사", "수술 후 경과", "콘택트렌즈 피팅", "재진"])
        self.title.setCurrentText(self._exam.title or DEFAULT_TITLE)
        self.diagnosis = QLineEdit(self._exam.diagnosis or "")
        self.diagnosis.setPlaceholderText("예: 핵경화 백내장 2+, 점상각막염")
        self.memo = QTextEdit(self._exam.memo or "")
        self.memo.setPlaceholderText("병력 · 주호소 · 메모")
        form.addRow("검사일", self.date)
        form.addRow("검사명", self.title)
        form.addRow("진단 · 소견", self.diagnosis)
        form.addRow("병력 · 메모", self.memo)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(_buttons(self))

    def get_exam(self) -> Exam:
        e = self._exam
        e.exam_date = self.date.date().toString("yyyy-MM-dd")
        e.title = self.title.currentText().strip() or DEFAULT_TITLE
        e.diagnosis = self.diagnosis.text().strip() or None
        e.memo = self.memo.toPlainText().strip() or None
        return e


class ReferenceDialog(QDialog):
    """참조 영상 등록 / 수정 — 분류·제목·설명."""

    def __init__(self, parent=None, categories: list | None = None, category: str = "",
                 title: str = "", description: str = ""):
        super().__init__(parent)
        self.setWindowTitle("참조 영상")
        self.resize(420, 300)
        form = QFormLayout()
        self.category = QComboBox()
        self.category.setEditable(True)
        names = list(dict.fromkeys([*REF_CATEGORIES, *(categories or [])]))
        self.category.addItems(names)
        if category:
            self.category.setCurrentText(category)
        self.title = QLineEdit(title)
        self.title.setPlaceholderText("예: 핵경화 백내장 3+ 대표 사례")
        self.description = QTextEdit(description)
        self.description.setPlaceholderText("관찰 소견 · 조명법 · 배율 등")
        form.addRow("분류", self.category)
        form.addRow("제목", self.title)
        form.addRow("설명", self.description)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(_buttons(self))

    def values(self) -> tuple[str, str, str]:
        return (self.category.currentText().strip() or "기타", self.title.text().strip(),
                self.description.toPlainText().strip())
