"""안저판 설정: 안저카메라 사진 폴더(감시) · 안구 자동 인식 · 원본 정리 · 저장 폴더."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.capture.folder_watch import IMPORTED_DIR

HELP = (
    "※ 안저카메라(또는 카메라 프로그램)가 촬영한 사진을 저장하는 폴더를 고르세요. 네트워크 공유 폴더도 됩니다.\n"
    "※ 새 사진이 저장되면 몇 초 안에 지금 선택한 환자에게 등록됩니다. 환자를 고르기 전에 들어온 사진은\n"
    "   환자를 선택할 때 등록할지 묻습니다. 프로그램을 켜기 전부터 폴더에 있던 사진은 가져오지 않습니다.\n"
    "※ 지원 형식: JPG · PNG · TIFF · BMP (DICOM 은 지원하지 않습니다). 원본 파일은 화질 그대로 복사합니다."
)


class FundusSettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("설정")
        self.resize(620, 400)

        form = QFormLayout()
        self.watch = QLineEdit(config.watch_folder)
        self.watch.setPlaceholderText("예: D:\\FundusCamera\\Export  또는  \\\\카메라PC\\공유폴더")
        form.addRow("안저카메라 사진 폴더", self._with_browse(self.watch, "안저카메라 사진 폴더 선택"))

        self.subfolders = QCheckBox("하위 폴더(날짜별 폴더 등)도 감시")
        self.subfolders.setChecked(config.watch_subfolders)
        self.eye_from_name = QCheckBox("파일 이름으로 안구 자동 지정 (R/L · OD/OS · RIGHT/LEFT · 우안/좌안)")
        self.eye_from_name.setChecked(config.watch_eye_from_name)
        self.move_imported = QCheckBox(f"가져온 원본을 사진 폴더 안의 '{IMPORTED_DIR}' 폴더로 옮기기 (폴더 정리)")
        self.move_imported.setChecked(config.watch_move_imported)
        self.move_imported.setToolTip("카메라 프로그램이 원본 위치를 기억하는 경우에는 끄세요.")
        for w in (self.subfolders, self.eye_from_name, self.move_imported):
            form.addRow("", w)

        self.interval = QSpinBox()
        self.interval.setRange(1, 30)
        self.interval.setSuffix(" 초")
        self.interval.setValue(max(1, round(config.watch_interval_ms / 1000)))
        form.addRow("확인 간격", self.interval)

        self.export = QLineEdit(config.export_root)
        form.addRow("동시 저장 폴더(export)", self._with_browse(self.export, "저장 폴더 선택"))

        self.photo_format = QComboBox()
        self.photo_format.addItems(["png", "jpg"])
        self.photo_format.setCurrentText(config.photo_format)
        self.photo_format.setToolTip("Pro 검토에서 보정·주석을 넣어 '편집본 저장' 할 때의 형식")
        form.addRow("편집본 저장 형식", self.photo_format)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        note = QLabel(HELP)
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addWidget(btns)

    def _with_browse(self, edit: QLineEdit, title: str) -> QWidget:
        btn = QPushButton("폴더 선택")
        btn.clicked.connect(lambda: self._browse(edit, title))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        row.addWidget(btn)
        w = QWidget()
        w.setLayout(row)
        return w

    def _browse(self, edit: QLineEdit, title: str) -> None:
        d = QFileDialog.getExistingDirectory(self, title, edit.text() or "")
        if d:
            edit.setText(d)

    def apply_to_config(self):
        c = self.config
        c.watch_folder = self.watch.text().strip()
        c.watch_subfolders = self.subfolders.isChecked()
        c.watch_eye_from_name = self.eye_from_name.isChecked()
        c.watch_move_imported = self.move_imported.isChecked()
        c.watch_interval_ms = self.interval.value() * 1000
        c.export_root = self.export.text().strip()
        c.photo_format = self.photo_format.currentText()
        c.save()
        return c
