"""설정 다이얼로그: 소스 모드, 카메라, 해상도, 사진 형식, 전송(export) 폴더와 보내기 동작."""
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

from app.capture.frame_utils import device_names, enumerate_devices, is_sony


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("설정")
        self.resize(520, 440)

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
        btn_browse = QPushButton("폴더 선택")
        btn_browse.clicked.connect(self._browse)
        exp_row = QHBoxLayout()
        exp_row.addWidget(self.export)
        exp_row.addWidget(btn_browse)
        exp_w = QWidget()
        exp_w.setLayout(exp_row)

        self.export_on_capture = QCheckBox("촬영하면 바로 전송 폴더에도 복사")
        self.export_on_capture.setChecked(bool(config.export_on_capture))
        self.export_on_capture.setToolTip("끄면 촬영 사진은 기본 저장 폴더에만 남고, 우측 목록에서 골라 '보내기' 할 때만 전송됩니다")

        self.after_send = QComboBox()
        self.after_send.addItem("원본을 남겨둠 (목록에 그대로)", False)
        self.after_send.addItem("원본을 자동 삭제 (전송 폴더에만 남김)", True)
        self.after_send.setCurrentIndex(1 if config.send_delete_after else 0)
        self.after_send.setToolTip("우측 목록에서 사진을 선택해 '보내기' 한 뒤의 동작")

        self.test_file = QLineEdit(config.test_file_path)

        form.addRow("소스 모드", self.source_mode)
        form.addRow("카메라", self.camera_index)
        form.addRow("가로 해상도", self.width)
        form.addRow("세로 해상도", self.height)
        form.addRow("사진 형식", self.photo_format)
        form.addRow("전송 폴더(export)", exp_w)
        form.addRow("촬영 시 자동 전송", self.export_on_capture)
        form.addRow("보내기 후 사진", self.after_send)
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
                             "   USB-C 로 연결하면 ★ 표시로 나타납니다 (4K 는 해상도 3840×2160)."))
        lay.addWidget(btns)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "전송 폴더 선택", self.export.text() or "")
        if d:
            self.export.setText(d)

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
        c.export_on_capture = self.export_on_capture.isChecked()
        c.send_delete_after = bool(self.after_send.currentData())
        c.test_file_path = self.test_file.text().strip()
        c.save()
        return c
