"""영상 보정 · 측정 창 — 기본판의 Pro 검토 화면(보정·필터·편집·주석·측정·인쇄)을 그대로 띄운다."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout

from app.ui.pro.pro_workspace import ProWorkspace


class ProDialog(QDialog):
    savedCapture = Signal()
    patientUpdated = Signal(object)

    def __init__(self, db, service, config, patient, capture=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("영상 보정 · 측정")
        self.resize(1360, 860)
        self.pro = ProWorkspace(db, service, config, get_eye=None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(self.pro)
        self.pro.savedCapture.connect(self.savedCapture)
        self.pro.patientUpdated.connect(self.patientUpdated)
        self.pro.set_patient(patient)
        if capture is not None:
            ids = [c.id for c in self.pro.captures()]
            if capture.id in ids:
                self.pro.open_index(ids.index(capture.id))
