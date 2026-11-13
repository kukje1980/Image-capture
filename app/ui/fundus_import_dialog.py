"""안저 불러오기 창 — 파일(이미지·DICOM)을 골라 촬영 일시·안구 방향을 확인하고 환자 기록으로 저장."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.capture.frame_utils import bgr_to_qimage, make_thumbnail
from app.services import fundus_import
from app.services.fundus_import import FundusImportError

log = logging.getLogger(__name__)

_EYES = [("OD", "OD 우안"), ("OS", "OS 좌안"), ("NA", "미지정")]
_COLS = ["미리보기", "파일 이름", "촬영 일시", "안구", "상태"]
_THUMB = 72


@dataclass
class _Row:
    path: str
    name: str
    captured_at: Optional[datetime] = None
    error: str = ""
    combo: Optional[QComboBox] = None


def pick_files(parent=None) -> list[str]:
    files, _ = QFileDialog.getOpenFileNames(parent, "안저 사진 불러오기", "", fundus_import.FILE_FILTER)
    return files


class FundusImportDialog(QDialog):
    """가져오기를 누르면 imported(저장된 Capture 목록)·failed((파일 이름, 오류) 목록)가 채워진다."""

    def __init__(self, service, patient, parent=None, files: Optional[list] = None):
        super().__init__(parent)
        self.service = service
        self.patient = patient
        self.imported: list = []
        self.failed: list[tuple[str, str]] = []
        self._rows: list[_Row] = []
        self.setWindowTitle("안저 불러오기")
        self.resize(820, 560)

        lay = QVBoxLayout(self)
        who = f"{patient.name}  ·  {patient.chart_no}" if patient.chart_no else patient.name
        head = QLabel(f"<b>{who}</b> 환자의 기록으로 안저 사진을 불러옵니다. "
                      "촬영 일시와 안구 방향을 확인하세요.")
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        lay.addWidget(head)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setObjectName("ImportTable")
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(_THUMB + 10)
        self.table.setIconSize(QSize(_THUMB, _THUMB))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, _THUMB + 20)
        self.table.setColumnWidth(3, 130)
        lay.addWidget(self.table, 1)

        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        lay.addWidget(self.summary)

        row = QHBoxLayout()
        self.b_all_od = QPushButton("모두 OD")
        self.b_all_os = QPushButton("모두 OS")
        self.b_add = QPushButton("파일 추가")
        self.b_import = QPushButton("가져오기")
        self.b_import.setObjectName("Primary")
        self.b_import.setDefault(True)
        self.b_cancel = QPushButton("취소")
        self.b_all_od.setToolTip("목록의 모든 사진을 우안(OD)으로 지정")
        self.b_all_os.setToolTip("목록의 모든 사진을 좌안(OS)으로 지정")
        row.addWidget(self.b_all_od)
        row.addWidget(self.b_all_os)
        row.addWidget(self.b_add)
        row.addStretch(1)
        row.addWidget(self.b_cancel)
        row.addWidget(self.b_import)
        lay.addLayout(row)

        self.b_all_od.clicked.connect(lambda: self.set_all_eyes("OD"))
        self.b_all_os.clicked.connect(lambda: self.set_all_eyes("OS"))
        self.b_add.clicked.connect(self._pick)
        self.b_import.clicked.connect(self._on_import)
        self.b_cancel.clicked.connect(self.reject)

        self.add_files(files or [])

    # ---- 목록 ----
    def _pick(self) -> None:
        self.add_files(pick_files(self))

    def add_files(self, files) -> None:
        """파일을 읽어 목록에 추가한다 (읽지 못한 파일은 오류와 함께 표시하고 건너뜀)."""
        have = {r.path for r in self._rows}
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for f in files:
                path = str(f)
                if path in have:
                    continue
                have.add(path)
                self._add_row(path)
        finally:
            QApplication.restoreOverrideCursor()
        self._update_summary()

    def _add_row(self, path: str) -> None:
        row = _Row(path=path, name=os.path.basename(path))
        eye, pm = None, None
        try:
            item = fundus_import.read_image(path)
            row.captured_at = item.captured_at
            eye = item.eye
            # 원본은 들고 있지 않는다 (큰 안저 사진 여러 장이면 메모리가 커짐) — 가져올 때 다시 읽는다
            pm = QPixmap.fromImage(bgr_to_qimage(make_thumbnail(item.image, _THUMB * 2)))
        except FundusImportError as e:
            row.error = str(e)
        except Exception as e:  # noqa: BLE001
            log.exception("fundus read failed: %s", path)
            row.error = f"읽기 실패: {e}"

        r = self.table.rowCount()
        self.table.insertRow(r)
        thumb = QLabel()
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pm is not None:
            thumb.setPixmap(pm.scaled(_THUMB, _THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        self.table.setCellWidget(r, 0, thumb)
        name = QTableWidgetItem(row.name)
        name.setToolTip(path)
        self.table.setItem(r, 1, name)
        when = row.captured_at.strftime("%Y-%m-%d %H:%M:%S") if row.captured_at else "-"
        self.table.setItem(r, 2, QTableWidgetItem(when))
        if row.error:
            st = QTableWidgetItem(f"건너뜀 — {row.error}")
            st.setToolTip(row.error)
            st.setForeground(Qt.GlobalColor.red)
            self.table.setItem(r, 3, QTableWidgetItem("-"))
        else:
            combo = QComboBox()
            for code, text in _EYES:
                combo.addItem(text, code)
            combo.setCurrentIndex([c for c, _ in _EYES].index(eye or "NA"))
            cell = QWidget()                     # 칸 가운데에 보통 높이로
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(6, 0, 6, 0)
            cl.addWidget(combo, 0, Qt.AlignmentFlag.AlignVCenter)
            self.table.setCellWidget(r, 3, cell)
            row.combo = combo
            st = QTableWidgetItem("안구 자동 인식" if eye else "안구를 지정하세요")
        self.table.setItem(r, 4, st)
        self._rows.append(row)

    def set_all_eyes(self, eye: str) -> None:
        idx = [c for c, _ in _EYES].index(eye)
        for r in self._rows:
            if r.combo is not None:
                r.combo.setCurrentIndex(idx)

    def rows(self) -> list[dict]:
        """현재 목록 (테스트·확인용): 파일 이름·촬영 일시·안구·오류."""
        return [{"name": r.name, "captured_at": r.captured_at, "error": r.error,
                 "eye": (r.combo.currentData() if r.combo is not None else None)}
                for r in self._rows]

    def _update_summary(self) -> None:
        ok = sum(1 for r in self._rows if not r.error)
        bad = len(self._rows) - ok
        text = f"가져올 사진 {ok}장" + (f"  ·  읽지 못한 파일 {bad}개 (건너뜀)" if bad else "")
        self.summary.setText(text if self._rows else "‘파일 추가’로 안저 사진(이미지·DICOM)을 고르세요.")
        self.b_import.setEnabled(ok > 0)
        self.b_all_od.setEnabled(ok > 0)
        self.b_all_os.setEnabled(ok > 0)

    # ---- 가져오기 ----
    def import_all(self) -> list:
        """목록의 사진을 저장한다. 저장된 Capture 목록을 돌려주고 imported·failed 를 채운다."""
        self.imported, self.failed = [], [(r.name, r.error) for r in self._rows if r.error]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for r in self._rows:
                if r.error:
                    continue
                try:
                    cap = fundus_import.import_file(self.service, self.patient, r.path,
                                                    eye=r.combo.currentData())
                    self.imported.append(cap)
                except Exception as e:  # noqa: BLE001
                    log.exception("fundus import failed: %s", r.path)
                    self.failed.append((r.name, str(e)))
        finally:
            QApplication.restoreOverrideCursor()
        return self.imported

    def _on_import(self) -> None:
        self.import_all()
        self.accept()
