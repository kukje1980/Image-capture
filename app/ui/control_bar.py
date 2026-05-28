"""하단 컨트롤 바: 안구 선택 + 일시정지/캡처/녹화 + 상태."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

_EYE_CODES = ["NA", "OD", "OS", "OU"]


class ControlBar(QWidget):
    pauseToggled = Signal(bool)
    captureClicked = Signal()
    recordToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.addWidget(QLabel("안구:"))
        self.eye_combo = QComboBox()
        self.eye_combo.addItems(["미지정", "OD(우안)", "OS(좌안)", "OU(양안)"])
        lay.addWidget(self.eye_combo)

        self.btn_pause = QPushButton("일시정지")
        self.btn_pause.setCheckable(True)
        self.btn_capture = QPushButton("사진 캡처")
        self.btn_record = QPushButton("녹화 시작")
        self.btn_record.setCheckable(True)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_capture)
        lay.addWidget(self.btn_record)
        lay.addStretch(1)
        self.status = QLabel("준비")
        lay.addWidget(self.status)

        self.btn_pause.toggled.connect(self._on_pause)
        self.btn_capture.clicked.connect(self.captureClicked.emit)
        self.btn_record.toggled.connect(self._on_record)
        self.set_capture_enabled(False)

    def _on_pause(self, checked: bool) -> None:
        self.btn_pause.setText("재개" if checked else "일시정지")
        self.pauseToggled.emit(checked)

    def _on_record(self, checked: bool) -> None:
        self.btn_record.setText("녹화 중지" if checked else "녹화 시작")
        self.recordToggled.emit(checked)

    def current_eye(self) -> str:
        return _EYE_CODES[self.eye_combo.currentIndex()]

    def set_capture_enabled(self, on: bool) -> None:
        self.btn_capture.setEnabled(on)
        self.btn_record.setEnabled(on)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def reset_record_button(self) -> None:
        self.btn_record.blockSignals(True)
        self.btn_record.setChecked(False)
        self.btn_record.setText("녹화 시작")
        self.btn_record.blockSignals(False)
