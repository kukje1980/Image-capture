"""설정 다이얼로그: 소스 모드, 카메라, 해상도, 사진 형식, export 폴더, 가져오기 폴더."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import paths
from app.capture.frame_utils import device_names, enumerate_devices, is_sony
from app.services.folder_import import DONE_DIR, check_import_folder


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("설정")
        self.resize(560, 440)

        form = QFormLayout()
        self.source_mode = QComboBox()
        self.source_mode.addItems(["device", "file", "synthetic"])
        self.source_mode.setCurrentText(config.source_mode)

        self.camera_index = QComboBox()
        self.camera_index.setEditable(True)
        names = device_names() if config.source_mode == "device" else []
        devs = list(range(len(names))) if names else (
            enumerate_devices(backend=config.camera_backend) if config.source_mode == "device" else [])
        self._names = names
        if devs:
            for d in devs:
                label = f"{d}: {'★ ' if is_sony(names[d]) else ''}{names[d]}" if d < len(names) else str(d)
                self.camera_index.addItem(label, d)
            i = self.camera_index.findData(config.camera_index)
            if i >= 0:
                self.camera_index.setCurrentIndex(i)
        else:
            self.camera_index.addItem(str(config.camera_index), config.camera_index)

        self.width = QSpinBox()
        self.width.setRange(320, 7680)
        self.width.setValue(config.capture_width)
        self.height = QSpinBox()
        self.height.setRange(240, 4320)
        self.height.setValue(config.capture_height)

        self.photo_format = QComboBox()
        self.photo_format.addItems(["png", "jpg"])
        self.photo_format.setCurrentText(config.photo_format)

        self.export = QLineEdit(config.export_root)
        exp_w = self._folder_row(self.export, "저장 폴더 선택")

        # 가져오기 폴더: 카메라·다른 장비가 이 폴더에 넣은 사진을 지금 환자에게 가져온다 (비우면 끔)
        self.import_folder = QLineEdit(config.import_folder)
        self.import_folder.setPlaceholderText("비워 두면 사용 안 함")
        self.import_folder.setClearButtonEnabled(True)
        self.import_folder.setToolTip(
            "이 폴더에 새 사진(JPG·PNG·BMP·TIFF)이 들어오면 지금 선택한 환자에게 자동으로 가져옵니다.\n"
            f"가져온 원본은 폴더 안의 '{DONE_DIR}' 폴더로 옮깁니다.")
        imp_w = self._folder_row(self.import_folder, "가져오기 폴더 선택")

        self.test_file = QLineEdit(config.test_file_path)

        form.addRow("소스 모드", self.source_mode)
        form.addRow("카메라", self.camera_index)
        form.addRow("가로 해상도", self.width)
        form.addRow("세로 해상도", self.height)
        form.addRow("사진 형식", self.photo_format)
        form.addRow("저장 폴더(export)", exp_w)
        form.addRow("가져오기 폴더", imp_w)
        form.addRow("테스트 파일(file 모드)", self.test_file)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("※ 확인 시 설정이 저장되고 카메라가 재시작됩니다.\n"
                             "※ 소니 ZV-E10 II · FX3: 카메라 MENU → 설정 → USB → USB 연결 모드 → 'USB 스트리밍' 후\n"
                             "   USB-C 로 연결하면 ★ 표시로 나타납니다 (4K 는 해상도 3840×2160).\n"
                             "※ 가져오기 폴더: 카메라·다른 장비가 이 폴더에 사진을 넣으면 지금 선택한 환자에게\n"
                             f"   자동으로 가져옵니다 (원본은 그 안의 '{DONE_DIR}' 폴더로 옮김)."))
        lay.addWidget(btns)

    def _folder_row(self, edit: QLineEdit, title: str) -> QWidget:
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

    def accept(self) -> None:
        export = self.export.text().strip() or str(paths.get_appdata_dir() / "export")   # 비우면 다음 실행부터 기본 폴더
        msg = check_import_folder(self.import_folder.text(), self.config.media_root, export)
        if msg:
            QMessageBox.warning(self, "가져오기 폴더", msg)
            self.import_folder.setFocus()
            return
        super().accept()

    def apply_to_config(self):
        c = self.config
        c.source_mode = self.source_mode.currentText()
        data = self.camera_index.currentData()
        if data is None:
            try:
                data = int(self.camera_index.currentText() or 0)
            except ValueError:
                data = 0
        c.camera_index = int(data)
        c.camera_name = self._names[c.camera_index] if c.camera_index < len(self._names) else ""
        c.capture_width = self.width.value()
        c.capture_height = self.height.value()
        c.photo_format = self.photo_format.currentText()
        c.export_root = self.export.text().strip()
        c.import_folder = self.import_folder.text().strip()
        c.test_file_path = self.test_file.text().strip()
        c.save()
        return c
