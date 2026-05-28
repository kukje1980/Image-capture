"""환자 추가/수정 모달 다이얼로그."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from app.models.patient import Patient

_SEX_CODES = [None, "M", "F", "O"]


class PatientDialog(QDialog):
    def __init__(self, parent=None, patient: Patient | None = None):
        super().__init__(parent)
        self.setWindowTitle("환자 정보")
        self.resize(440, 460)
        self._patient = patient or Patient()

        form = QFormLayout()
        self.chart = QLineEdit(self._patient.chart_no or "")
        self.pid = QLineEdit(self._patient.patient_id or "")
        self.name = QLineEdit(self._patient.name or "")
        self.birth = QLineEdit(self._patient.birth_date or "")
        self.birth.setPlaceholderText("YYYY-MM-DD")
        self.sex = QComboBox()
        self.sex.addItems(["미지정", "남(M)", "여(F)", "기타(O)"])
        self.sex.setCurrentIndex({"M": 1, "F": 2, "O": 3}.get(self._patient.sex, 0))
        self.phone = QLineEdit(self._patient.phone or "")
        self.memo = QTextEdit(self._patient.memo or "")
        self.memo.setFixedHeight(56)
        self.symptoms = QTextEdit(self._patient.symptoms or "")
        self.symptoms.setFixedHeight(56)

        form.addRow("차트번호 *", self.chart)
        form.addRow("환자ID", self.pid)
        form.addRow("이름 *", self.name)
        form.addRow("생년월일", self.birth)
        form.addRow("성별", self.sex)
        form.addRow("연락처", self.phone)
        form.addRow("메모", self.memo)
        form.addRow("증상", self.symptoms)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def _on_ok(self) -> None:
        if not self.chart.text().strip():
            QMessageBox.warning(self, "확인", "차트번호는 필수입니다.")
            return
        if not self.name.text().strip():
            QMessageBox.warning(self, "확인", "이름은 필수입니다.")
            return
        self.accept()

    def get_patient(self) -> Patient:
        p = self._patient
        p.chart_no = self.chart.text().strip() or None
        p.patient_id = self.pid.text().strip() or None
        p.name = self.name.text().strip()
        p.birth_date = self.birth.text().strip() or None
        p.sex = _SEX_CODES[self.sex.currentIndex()]
        p.phone = self.phone.text().strip() or None
        p.memo = self.memo.toPlainText().strip() or None
        p.symptoms = self.symptoms.toPlainText().strip() or None
        return p
