"""상단 환자 배너 (촬영 · Pro 검토 화면): 지금 환자 요약(이니셜·차트번호·성별/나이·진단명·담당의).

환자를 찾고 고르는 일은 '환자 목록' 화면(app/ui/patient_list.py)이 맡는다 — 여기서는
지금 환자를 보여 주고, 환자 목록으로 가기 · 정보 수정만 한다.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.ui import icons
from app.ui.patient_dialog import PatientDialog
from app.ui.theme import ICON

_SEX = {"M": "남", "F": "여", "O": "기타"}


def _esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def age_of(birth: str | None, today: date | None = None) -> int | None:
    """'YYYY-MM-DD' → 만 나이. 형식이 다르면 None."""
    try:
        y, m, d = (int(x) for x in (birth or "")[:10].split("-"))
        b = date(y, m, d)
    except (ValueError, TypeError):
        return None
    t = today or date.today()
    a = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    return a if 0 <= a < 150 else None


def sex_age(p) -> str:
    """'남 · 67세' (없는 값은 생략)."""
    age = age_of(getattr(p, "birth_date", None))
    return " · ".join(x for x in (_SEX.get(p.sex or "", ""), f"{age}세" if age is not None else "") if x)


def edit_patient(db, patient, parent=None):
    """환자 정보 수정 창을 띄우고 저장한다. 저장했으면 갱신된 Patient, 아니면 None."""
    dlg = PatientDialog(parent, patient=patient)
    if not dlg.exec():
        return None
    p = dlg.get_patient()
    try:
        db.patients.update(p)
    except Exception as e:  # noqa: BLE001
        QMessageBox.warning(parent, "오류", f"수정 실패: {e}\n(차트번호 중복 여부를 확인하세요)")
        return None
    return db.patients.get(p.id) or p


class PatientPanel(QFrame):
    listRequested = Signal()             # '환자 목록' 눌림
    patientEdited = Signal(object)       # 정보 수정 저장됨 (갱신된 Patient)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._patient = None
        self.setObjectName("Banner")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        self.avatar = QLabel()
        self.avatar.setObjectName("Avatar")
        self.avatar.setFixedSize(38, 38)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.avatar)
        box = QVBoxLayout()
        box.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_name = QLabel()
        self.lbl_name.setObjectName("PatientName")
        self.lbl_chart = QLabel()
        self.lbl_chart.setObjectName("ChartNo")
        row.addWidget(self.lbl_name)
        row.addWidget(self.lbl_chart)
        row.addStretch(1)
        self.lbl_meta = QLabel()
        self.lbl_meta.setObjectName("PatientMeta")
        self.lbl_meta.setTextFormat(Qt.TextFormat.RichText)
        box.addLayout(row)
        box.addWidget(self.lbl_meta)
        lay.addLayout(box, 1)

        self.btn_list = QPushButton(icons.gap("환자 목록"))
        self.btn_list.setIcon(icons.icon("list", ICON, 16))
        self.btn_list.setToolTip("환자 목록 화면에서 환자 찾기 · 바꾸기 · 신규 등록")
        self.btn_edit = QPushButton(icons.gap("정보 수정"))
        self.btn_edit.setIcon(icons.icon("edit", ICON, 16))
        for b in (self.btn_list, self.btn_edit):
            b.setIconSize(QSize(15, 15))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(b)

        self.btn_list.clicked.connect(self.listRequested.emit)
        self.btn_edit.clicked.connect(self._edit_patient)
        self._render_banner(None)

    def _render_banner(self, p) -> None:
        self.btn_edit.setEnabled(p is not None)
        if p is None:
            self.avatar.setText("")
            self.avatar.setPixmap(icons.pixmap("user", ICON, 18))
            self.lbl_name.setText("환자를 선택하세요")
            self.lbl_chart.setText("")
            self.lbl_meta.setText("환자 목록에서 환자를 고르거나 신규 환자를 등록하세요")
            return
        self.avatar.setPixmap(QPixmap())
        self.avatar.setText((p.name or "?").strip()[:1])
        self.lbl_name.setText(p.name)
        self.lbl_chart.setText(f"#{p.chart_no}" if p.chart_no else "")
        mute = "color:#8b95a3"
        bits = []
        sa = sex_age(p)
        if sa:
            bits.append(sa)
        if getattr(p, "birth_date", None):
            bits.append(f"<span style='{mute}'>생년월일</span> {_esc(p.birth_date)}")
        bits.append(f"<span style='{mute}'>진단명</span> <b>{_esc(getattr(p, 'diagnosis', None) or '-')}</b>")
        bits.append(f"<span style='{mute}'>담당의</span> {_esc(getattr(p, 'doctor', None) or '-')}")
        self.lbl_meta.setText("&nbsp;&nbsp;&nbsp;".join(bits))

    def set_patient(self, patient) -> None:
        self._patient = patient
        self._render_banner(patient)

    def current_patient(self):
        return self._patient

    def refresh_current(self, patient) -> None:
        """현재 환자 정보만 갱신 (같은 환자일 때)."""
        if self._patient is not None and patient is not None and self._patient.id == patient.id:
            self.set_patient(patient)

    def _edit_patient(self):
        if self._patient is None:
            QMessageBox.information(self, "확인", "수정할 환자를 선택하세요.")
            return
        p = edit_patient(self.db, self._patient, self)
        if p is not None:
            self.set_patient(p)
            self.patientEdited.emit(p)
