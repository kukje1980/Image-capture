"""우측 세로 썸네일 패널 (환자별, 최신이 위)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.thumbnail_widget import ThumbnailWidget


class ThumbnailPanel(QScrollArea):
    thumbnailClicked = Signal(object)  # Capture

    def __init__(self, db, newest_on_top: bool = True, parent=None):
        super().__init__(parent)
        self.db = db
        self.newest_on_top = newest_on_top
        self._patient_id = None

        self.setObjectName("ThumbnailPanel")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedWidth(184)

        self._container = QWidget()
        self._lay = QVBoxLayout(self._container)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._lay.setContentsMargins(6, 6, 6, 6)
        self._lay.setSpacing(8)
        self._header = QLabel("촬영 이미지 (0)")
        self._header.setObjectName("PanelHeader")
        self._lay.addWidget(self._header)  # index 0 = header
        self.setWidget(self._container)

    def set_patient(self, patient_id) -> None:
        self._patient_id = patient_id
        self._clear()
        if patient_id is not None:
            order = "desc" if self.newest_on_top else "asc"
            for cap in self.db.captures.list_by_patient(patient_id, order=order):
                self._add_widget(cap, prepend=False)
        self._update_header()

    def add_capture(self, capture) -> None:
        if capture.patient_id != self._patient_id:
            return
        self._add_widget(capture, prepend=self.newest_on_top)
        self._update_header()

    def _add_widget(self, capture, prepend: bool) -> None:
        w = ThumbnailWidget(capture)
        w.clicked.connect(self.thumbnailClicked.emit)
        if prepend:
            self._lay.insertWidget(1, w)  # 0은 헤더이므로 1에 삽입
        else:
            self._lay.addWidget(w)

    def _clear(self) -> None:
        while self._lay.count() > 1:
            item = self._lay.takeAt(1)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _count(self) -> int:
        return self._lay.count() - 1

    def _update_header(self) -> None:
        self._header.setText(f"촬영 이미지 ({self._count()})")
