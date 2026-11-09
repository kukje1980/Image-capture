"""설정 다이얼로그: 소스 모드, 카메라, 해상도, 사진 형식, export 폴더, 폴더 가져오기(안저 카메라)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
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
from app.services.fundus_filename import parse_filename


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("설정")
        self.resize(560, 640)

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

        self.test_file = QLineEdit(config.test_file_path)

        form.addRow("소스 모드", self.source_mode)
        form.addRow("카메라", self.camera_index)
        form.addRow("가로 해상도", self.width)
        form.addRow("세로 해상도", self.height)
        form.addRow("사진 형식", self.photo_format)
        form.addRow("저장 폴더(export)", exp_w)
        form.addRow("테스트 파일(file 모드)", self.test_file)

        # 폴더 가져오기 (안저 카메라가 사진을 넣는 폴더)
        imp = QGroupBox("폴더 가져오기 — 안저 카메라 사진")
        if_ = QFormLayout(imp)
        self.imp_on = QCheckBox("폴더에 들어온 사진을 자동으로 환자 DB 에 등록")
        self.imp_on.setChecked(bool(config.import_enabled))
        self.imp_dir = QLineEdit(config.import_dir)
        self.imp_dir.setPlaceholderText("안저 카메라가 사진을 저장하는 폴더")
        b2 = QPushButton("폴더 선택")
        b2.clicked.connect(self._browse_import)
        row2 = QHBoxLayout()
        row2.addWidget(self.imp_dir)
        row2.addWidget(b2)
        w2 = QWidget()
        w2.setLayout(row2)
        self.imp_tpl = QLineEdit(config.import_template)
        self.imp_tpl.setPlaceholderText("비우면 자동 인식 · 예: {id}_{name}_{date}_{eye}")
        self.imp_tpl.setToolTip("{id} 아이디(차트번호) · {name} 이름 · {date} 날짜 · {time} 시각 · {eye} 좌우 · {*} 무시\n"
                                "형식 뒤에 붙는 순번(_001 등)은 무시합니다.")
        self.imp_sample = QLineEdit()
        self.imp_sample.setPlaceholderText("카메라 사진 파일 이름을 붙여 넣어 확인 — 예: 12345_홍길동_20261109_R.jpg")
        self.imp_preview = QLabel("")
        self.imp_preview.setWordWrap(True)
        self.imp_preview.setObjectName("Muted")
        self.imp_delete = QCheckBox("등록한 뒤 원본 사진 지우기 (끄면 '_가져옴' 폴더로 옮김)")
        self.imp_delete.setChecked(bool(config.import_delete))
        self.imp_recursive = QCheckBox("하위 폴더도 살펴보기")
        self.imp_recursive.setChecked(bool(config.import_recursive))
        self.imp_switch = QCheckBox("가져오면 그 환자로 바꾸기")
        self.imp_switch.setChecked(bool(config.import_switch_patient))
        if_.addRow(self.imp_on)
        if_.addRow("폴더", w2)
        if_.addRow("파일 이름 형식", self.imp_tpl)
        if_.addRow("확인용 파일 이름", self.imp_sample)
        if_.addRow("", self.imp_preview)
        if_.addRow(self.imp_delete)
        if_.addRow(self.imp_recursive)
        if_.addRow(self.imp_switch)
        if_.addRow(QLabel("읽지 못한 사진·아이디와 이름이 맞지 않는 사진은 지우지 않고 '_확인필요' 폴더로 옮깁니다."))
        self.imp_tpl.textChanged.connect(self._preview)
        self.imp_sample.textChanged.connect(self._preview)
        self._preview()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(imp)
        lay.addWidget(QLabel("※ 확인 시 설정이 저장되고 카메라가 재시작됩니다.\n"
                             "※ 소니 ZV-E10 II · FX3: 카메라 MENU → 설정 → USB → USB 연결 모드 → 'USB 스트리밍' 후\n"
                             "   USB-C 로 연결하면 ★ 표시로 나타납니다 (4K 는 해상도 3840×2160)."))
        lay.addWidget(btns)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.export.text() or "")
        if d:
            self.export.setText(d)

    def _browse_import(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "안저 카메라 사진 폴더 선택", self.imp_dir.text() or "")
        if d:
            self.imp_dir.setText(d)

    def _preview(self, *_) -> None:
        name = self.imp_sample.text().strip()
        if not name:
            self.imp_preview.setText("파일 이름을 넣으면 여기서 읽은 결과를 보여 줍니다.")
            return
        self.imp_preview.setText("→ " + parse_filename(name, self.imp_tpl.text()).summary())

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
        c.test_file_path = self.test_file.text().strip()
        c.import_enabled = self.imp_on.isChecked()
        c.import_dir = self.imp_dir.text().strip()
        c.import_template = self.imp_tpl.text().strip()
        c.import_delete = self.imp_delete.isChecked()
        c.import_recursive = self.imp_recursive.isChecked()
        c.import_switch_patient = self.imp_switch.isChecked()
        c.save()
        return c
