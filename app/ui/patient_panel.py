"""상단 환자 선택/검색/추가/수정 스트립."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from app.ui.patient_dialog import PatientDialog


class PatientPanel(QWidget):
    patientChanged = Signal(object)  # Patient | None

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._patients = []
        self.setObjectName("PatientPanel")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        _lbl = QLabel("환자:")
        _lbl.setObjectName("Muted")
        lay.addWidget(_lbl)
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름/차트번호 검색")
        self.search.setFixedWidth(180)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.btn_new = QPushButton("신규 환자")
        self.btn_edit = QPushButton("정보 수정")
        lay.addWidget(self.search)
        lay.addWidget(self.combo)
        lay.addWidget(self.btn_new)
        lay.addWidget(self.btn_edit)
        lay.addStretch(1)

        self.search.textChanged.connect(self._reload)
        self.combo.currentIndexChanged.connect(self._on_select)
        self.btn_new.clicked.connect(self._new_patient)
        self.btn_edit.clicked.connect(self._edit_patient)

        self._reload()

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

    def _reload(self, *_):
        q = self.search.text().strip()
        self._patients = self.db.patients.search(q) if q else self.db.patients.list_all()
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in self._patients:
            self.combo.addItem(f"{p.name} ({p.chart_no or '-'})")
        self.combo.blockSignals(False)
        if self._patients:
            self.combo.setCurrentIndex(0)
        self._on_select()

    def _on_select(self, *_):
        self.patientChanged.emit(self.current_patient())

    def _new_patient(self):
        dlg = PatientDialog(self)
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

    def _edit_patient(self):
        p = self.current_patient()
        if not p:
            QMessageBox.information(self, "확인", "수정할 환자를 선택하세요.")
            return
        dlg = PatientDialog(self, patient=p)
        if not dlg.exec():
            return
        try:
            self.db.patients.update(dlg.get_patient())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", f"수정 실패: {e}")
            return
        self._reload()
