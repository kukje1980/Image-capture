"""환자 추가/수정 모달 다이얼로그 — 자주 쓰는 항목(차트번호·이름·생년월일·성별)을 위에, 나머지는 아래에.

db 를 주면 '저장' 때 차트번호 중복을 먼저 확인한다.
- 신규 등록인데 같은 차트번호 환자가 있으면: 등록된 환자 정보를 보여주고 (이름이 다르면 경고)
  '기존 환자로 계속'(→ self.existing 에 그 환자, 새로 등록하지 않음) / '차트번호 다시 입력' 중에서 고른다.
- 수정인데 다른 환자가 쓰는 차트번호로 바꾸면 막는다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.models.patient import Patient
from app.ui import icons
from app.ui.date_field import DateField
from app.ui.theme import ICON_ACCENT, ICON_ON_ACCENT

_SEX_CODES = [None, "M", "F", "O"]


class PatientDialog(QDialog):
    def __init__(self, parent=None, patient: Patient | None = None, db=None):
        super().__init__(parent)
        editing = patient is not None
        self._db = db
        self.existing: Patient | None = None   # 같은 차트번호의 기존 환자로 이어서 하기로 했으면 그 환자
        self.setWindowTitle("환자 정보 수정" if editing else "신규 환자")
        self.resize(520, 560)
        self._patient = patient or Patient()

        head = QHBoxLayout()
        head.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("user-edit" if editing else "user-plus", ICON_ACCENT, 26))
        ic.setFixedSize(30, 30)
        title = QLabel("환자 정보 수정" if editing else "신규 환자 등록")
        title.setObjectName("BrandTitle")
        head.addWidget(ic)
        head.addWidget(title)
        head.addStretch(1)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setVerticalSpacing(10)
        self.chart = QLineEdit(self._patient.chart_no or "")
        self.chart.setPlaceholderText("필수")
        self.name = QLineEdit(self._patient.name or "")
        self.name.setPlaceholderText("필수")
        self.birth = DateField(self._patient.birth_date or "")
        self.sex = QComboBox()
        self.sex.addItems(["미지정", "남", "여", "기타"])
        self.sex.setCurrentIndex({"M": 1, "F": 2, "O": 3}.get(self._patient.sex, 0))
        self.pid = QLineEdit(self._patient.patient_id or "")
        self.pid.setPlaceholderText("선택 (병원 환자번호 등)")
        self.phone = QLineEdit(self._patient.phone or "")
        self.diagnosis = QLineEdit(self._patient.diagnosis or "")
        self.diagnosis.setPlaceholderText("예: 백내장, 각막염")
        self.doctor = QLineEdit(self._patient.doctor or "")
        self.symptoms = QTextEdit(self._patient.symptoms or "")
        self.symptoms.setFixedHeight(52)
        self.memo = QTextEdit(self._patient.memo or "")
        self.memo.setFixedHeight(52)

        form.addRow("차트번호 *", self.chart)
        form.addRow("이름 *", self.name)
        form.addRow("생년월일", self.birth)
        form.addRow("성별", self.sex)
        sep = QFrame()
        sep.setObjectName("ThumbSep")
        sep.setFixedHeight(1)
        form.addRow(sep)
        form.addRow("환자ID", self.pid)
        form.addRow("연락처", self.phone)
        form.addRow("진단명", self.diagnosis)
        form.addRow("담당의", self.doctor)
        form.addRow("증상", self.symptoms)
        form.addRow("메모", self.memo)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton("취소")
        self.btn_ok = QPushButton(icons.gap("저장"))
        self.btn_ok.setObjectName("Primary")
        self.btn_ok.setIcon(icons.icon("save", ICON_ON_ACCENT, 16))
        self.btn_ok.setIconSize(QSize(15, 15))
        self.btn_ok.setDefault(True)
        self.btn_ok.setMinimumWidth(110)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_ok)
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_cancel.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)
        lay.addLayout(head)
        lay.addLayout(form)
        lay.addStretch(1)
        lay.addLayout(btns)
        (self.name if self.chart.text() else self.chart).setFocus()

    def _on_ok(self) -> None:
        if not self.chart.text().strip():
            QMessageBox.warning(self, "확인", "차트번호는 필수입니다.")
            self.chart.setFocus()
            return
        if not self.name.text().strip():
            QMessageBox.warning(self, "확인", "이름은 필수입니다.")
            self.name.setFocus()
            return
        self.birth.normalize()
        if not self.birth.is_valid():
            QMessageBox.warning(self, "확인", "생년월일을 알아볼 수 없습니다.\n숫자 8자리(19800315) 또는 달력에서 선택하세요.")
            self.birth.edit.setFocus()
            return
        if not self._check_chart_duplicate():
            return
        self.accept()

    # ---- 차트번호 중복 ----
    def _check_chart_duplicate(self) -> bool:
        """True = 저장(또는 기존 환자로 계속) 진행, False = 창에 남아 다시 입력."""
        self.existing = None
        chart = self.chart.text().strip()
        if self._db is None or not chart:
            return True
        other = self._db.patients.find_by_chart(chart)
        if other is None or other.id == self._patient.id:
            return True
        name = self.name.text().strip()
        if self._patient.id is not None:              # 수정: 다른 환자가 쓰는 번호로는 바꿀 수 없음
            QMessageBox.warning(self, "차트번호 중복",
                                f"차트번호 '{chart}' 은(는) 이미 '{other.name}' 환자가 쓰고 있습니다.\n"
                                "다른 차트번호를 입력하세요.")
            self._focus_chart()
            return False
        if self._ask_continue(other, chart, name):
            self.existing = other
            return True
        self._focus_chart()
        return False

    @staticmethod
    def duplicate_message(other: Patient, chart: str, name: str) -> tuple[str, str]:
        """(본문, 안내) — 이름이 다르면 중복을 분명히 알린다."""
        info = " · ".join(x for x in (other.birth_date or "", {"M": "남", "F": "여", "O": "기타"}.get(other.sex or "", ""),
                                      other.diagnosis or "") if x)
        who = f"{other.name}" + (f" ({info})" if info else "")
        if (other.name or "").strip() == name:
            text = (f"차트번호 '{chart}' 환자는 이미 등록되어 있습니다.\n\n등록된 환자: {who}\n\n"
                    "기존 환자에 이어서 촬영할까요?")
        else:
            text = (f"차트번호(아이디) '{chart}' 이(가) 중복됩니다.\n"
                    f"이 번호는 이미 다른 이름의 환자로 등록되어 있습니다.\n\n"
                    f"등록된 환자: {who}\n입력한 이름: {name}\n\n"
                    f"기존 환자 '{other.name}' 에 이어서 촬영할까요?")
        hint = ("'기존 환자로 계속' 을 누르면 새로 등록하지 않고 기존 환자를 선택합니다 (기존 환자 정보는 그대로).\n"
                "다른 환자라면 '차트번호 다시 입력' 을 눌러 번호를 바꾸세요.")
        return text, hint

    def _ask_continue(self, other: Patient, chart: str, name: str) -> bool:
        text, hint = self.duplicate_message(other, chart, name)
        box = QMessageBox(self)
        box.setWindowTitle("차트번호 중복")
        same = (other.name or "").strip() == name
        box.setIcon(QMessageBox.Icon.Question if same else QMessageBox.Icon.Warning)
        box.setText(text)
        box.setInformativeText(hint)
        b_go = box.addButton("기존 환자로 계속", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("차트번호 다시 입력", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_go)
        box.exec()
        return box.clickedButton() is b_go

    def _focus_chart(self) -> None:
        self.chart.setFocus()
        self.chart.selectAll()

    def get_patient(self) -> Patient:
        p = self._patient
        p.chart_no = self.chart.text().strip() or None
        p.patient_id = self.pid.text().strip() or None
        p.name = self.name.text().strip()
        p.birth_date = self.birth.value() or None
        p.sex = _SEX_CODES[self.sex.currentIndex()]
        p.phone = self.phone.text().strip() or None
        p.memo = self.memo.toPlainText().strip() or None
        p.symptoms = self.symptoms.toPlainText().strip() or None
        p.diagnosis = self.diagnosis.text().strip() or None
        p.doctor = self.doctor.text().strip() or None
        return p
