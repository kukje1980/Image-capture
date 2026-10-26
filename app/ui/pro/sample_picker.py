"""샘플과 비교 — 가져온 질환별 샘플 사진(SAMPLE-NN 환자)에서 비교할 사진 1장을 고르는 창."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from app.services.sample_import import CHART_PREFIX


def sample_patients(db) -> list:
    """샘플 가져오기로 만든 환자 (차트번호 SAMPLE-NN) — 번호 순."""
    pats = [p for p in db.patients.list_all(limit=10000) if (p.chart_no or "").startswith(CHART_PREFIX)]
    return sorted(pats, key=lambda p: p.chart_no)


def is_sample_capture(db, cap) -> bool:
    if cap is None:
        return False
    p = db.patients.get(cap.patient_id)
    return bool(p and (p.chart_no or "").startswith(CHART_PREFIX))


class SamplePicker(QDialog):
    """왼쪽 질환 목록 → 오른쪽 그 질환의 샘플 사진. 사진을 더블클릭하거나 '비교' 를 누르면 고른다."""

    def __init__(self, db, patients: list, prefer: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("샘플과 비교 — 샘플 사진 고르기")
        self.resize(820, 520)
        self.db = db
        self._chosen = None

        self.diseases = QListWidget()
        self.diseases.setFixedWidth(250)
        self.photos = QListWidget()
        self.photos.setViewMode(QListWidget.ViewMode.IconMode)
        self.photos.setIconSize(QSize(160, 120))
        self.photos.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.photos.setMovement(QListWidget.Movement.Static)
        self.photos.setSpacing(6)
        self.photos.setWordWrap(True)
        self.note = QLabel("사진을 고르면 원문 진단·출처가 여기에 보입니다.")
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        for p in patients:
            it = QListWidgetItem(f"{p.chart_no.removeprefix(CHART_PREFIX)}  {p.diagnosis or p.name}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.diseases.addItem(it)

        self.btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.btns.button(QDialogButtonBox.StandardButton.Ok).setText("비교")
        self.btns.accepted.connect(self._accept)
        self.btns.rejected.connect(self.reject)

        self.diseases.currentRowChanged.connect(self._fill_photos)
        self.photos.currentItemChanged.connect(self._show_note)
        self.photos.itemDoubleClicked.connect(lambda _it: self._accept())

        right = QVBoxLayout()
        right.addWidget(self.photos, 1)
        right.addWidget(self.note)
        body = QHBoxLayout()
        body.addWidget(self.diseases)
        body.addLayout(right, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("왼쪽 영상(현재 환자)과 나란히 볼 샘플 사진을 고르세요. 샘플은 참고용이며 진단이 아닙니다."))
        lay.addLayout(body, 1)
        lay.addWidget(self.btns)

        # 현재 환자 진단명과 같은 질환이 있으면 그 질환부터
        row = 0
        if prefer:
            for i, p in enumerate(patients):
                d = p.diagnosis or ""
                if d and (d in prefer or prefer in d):
                    row = i
                    break
        if patients:
            self.diseases.setCurrentRow(row)

    def _fill_photos(self, row: int) -> None:
        self.photos.clear()
        it = self.diseases.item(row)
        if it is None:
            return
        p = it.data(Qt.ItemDataRole.UserRole)
        for c in self.db.captures.list_by_patient(p.id, order="asc"):
            if c.media_type != "photo":
                continue
            title = (c.note or "").splitlines()[0].removeprefix("[샘플] ") if c.note else ""
            item = QListWidgetItem(title[:40])
            pm = QPixmap(c.thumbnail_path or c.file_path)
            if not pm.isNull():
                item.setIcon(QIcon(pm))
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setToolTip(c.note or "")
            self.photos.addItem(item)
        if self.photos.count():
            self.photos.setCurrentRow(0)

    def _show_note(self, item, _prev=None) -> None:
        c = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.note.setText((c.note or "-") if c else "")

    def _accept(self) -> None:
        item = self.photos.currentItem()
        if item is None:
            return
        self._chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def chosen(self) -> Optional[object]:
        return self._chosen
