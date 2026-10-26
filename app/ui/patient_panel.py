"""상단 환자 배너: 환자 요약(이니셜·이름·차트번호·나이/성별·진단명·담당의) + 검색·선택.

신규 등록·정보 수정 버튼은 상단바(Pro 검토 옆)에 있고 new_patient()/edit_patient() 를 부른다."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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


class PatientPanel(QFrame):
    patientChanged = Signal(object)  # Patient | None

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._patients = []
        self.setObjectName("Banner")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
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

        self.search = QLineEdit()
        self.search.setPlaceholderText("이름 · 차트번호 검색")
        self.search.setFixedWidth(190)
        self.search.addAction(icons.icon("search", ICON, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(210)
        self.combo.setToolTip("환자 선택")
        lay.addWidget(self.search)
        lay.addWidget(self.combo)

        self.search.textChanged.connect(self._reload)
        self.combo.currentIndexChanged.connect(self._on_select)

        self._reload()

    def _render_banner(self, p) -> None:
        if p is None:
            self.avatar.setPixmap(icons.pixmap("user", ICON, 18))
            self.lbl_name.setText("환자를 선택하세요")
            self.lbl_chart.setText("")
            self.lbl_meta.setText("오른쪽에서 검색하거나 상단의 '신규 환자' 를 누르세요")
            return
        self.avatar.setPixmap(QPixmap())
        self.avatar.setText((p.name or "?").strip()[:1])
        self.lbl_name.setText(p.name)
        self.lbl_chart.setText(f"#{p.chart_no}" if p.chart_no else "")
        mute = "color:#8b95a3"
        bits = []
        age = age_of(getattr(p, "birth_date", None))
        sa = " · ".join(x for x in (_SEX.get(p.sex or "", ""), f"{age}세" if age is not None else "") if x)
        if sa:
            bits.append(sa)
        if getattr(p, "birth_date", None):
            bits.append(f"<span style='{mute}'>생년월일</span> {_esc(p.birth_date)}")
        bits.append(f"<span style='{mute}'>진단명</span> <b>{_esc(getattr(p, 'diagnosis', None) or '-')}</b>")
        bits.append(f"<span style='{mute}'>담당의</span> {_esc(getattr(p, 'doctor', None) or '-')}")
        self.lbl_meta.setText("&nbsp;&nbsp;&nbsp;".join(bits))

    def current_patient(self):
        idx = self.combo.currentIndex()
        if 0 <= idx < len(self._patients):
            return self._patients[idx]
        return None

    def refresh_current(self, patient) -> None:
        """현재 선택된 환자 정보만 갱신 (선택 유지)."""
        idx = self.combo.currentIndex()
        if 0 <= idx < len(self._patients) and self._patients[idx].id == patient.id:
            self._patients[idx] = patient
            self.combo.setItemText(idx, f"{patient.name} ({patient.chart_no or '-'})")
            self._render_banner(patient)

    def _reload(self, *_):
        q = self.search.text().strip()
        prev = self.current_patient() if hasattr(self, "_patients") else None
        self._patients = list(self.db.patients.search(q) if q else self.db.patients.list_all())
        # 검색어를 쳐도 지금 환자 선택은 유지 (검색 결과에 없으면 맨 앞에 남겨 둔다) — 다른 환자로 촬영되는 일 방지
        if prev is not None and q and not any(p.id == prev.id for p in self._patients):
            self._patients.insert(0, prev)
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in self._patients:
            self.combo.addItem(f"{p.name} ({p.chart_no or '-'})")
        sel = next((i for i, p in enumerate(self._patients) if prev is not None and p.id == prev.id), 0)
        if self._patients:
            self.combo.setCurrentIndex(sel)
        self.combo.blockSignals(False)
        self._on_select()

    def _on_select(self, *_):
        p = self.current_patient()
        self._render_banner(p)
        self.patientChanged.emit(p)

    def new_patient(self):
        """신규 환자 등록 (상단바 버튼·단축키 N)."""
        dlg = PatientDialog(self.window())
        if not dlg.exec():
            return
        p = dlg.get_patient()
        try:
            p.id = self.db.patients.insert(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", f"저장 실패: {e}\n(차트번호 중복 여부를 확인하세요)")
            return
        self.search.blockSignals(True)
        self.search.setText("")
        self.search.blockSignals(False)
        self._reload()
        for i, pp in enumerate(self._patients):
            if pp.id == p.id:
                self.combo.setCurrentIndex(i)
                break

    def edit_patient(self):
        """현재 환자 정보 수정 (상단바 버튼)."""
        p = self.current_patient()
        if not p:
            QMessageBox.information(self, "확인", "수정할 환자를 선택하세요.")
            return
        dlg = PatientDialog(self.window(), patient=p)
        if not dlg.exec():
            return
        try:
            self.db.patients.update(dlg.get_patient())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", f"수정 실패: {e}")
            return
        self._reload()

    # 이전 이름 호환
    _new_patient = new_patient
    _edit_patient = edit_patient
