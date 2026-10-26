"""설정 다이얼로그: 소스 모드, 카메라, 해상도, 사진 형식, export 폴더, 효과음."""
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
        self.resize(500, 380)

        form = QFormLayout()
        self.source_mode = QComboBox()
        self.source_mode.addItems(["device", "file", "synthetic"])
        self.source_mode.setCurrentText(config.source_mode)

        self.camera_index = QComboBox()
        self.camera_index.setMinimumWidth(260)
        self._names: list[str] = []
        btn_rescan = QPushButton("다시 찾기")
        btn_rescan.setToolTip("카메라를 연결하거나 USB 스트리밍으로 바꾼 뒤 눌러 목록을 새로 고칩니다")
        btn_rescan.clicked.connect(self._fill_cameras)
        cam_row = QHBoxLayout()
        cam_row.setContentsMargins(0, 0, 0, 0)
        cam_row.addWidget(self.camera_index, 1)
        cam_row.addWidget(btn_rescan)
        self.camera_hint = QLabel()
        self.camera_hint.setWordWrap(True)
        self.camera_hint.setStyleSheet("color: #f5a524;")
        # 줄바꿈 라벨은 폼 안에서 높이를 덜 잡아 잘리므로 3줄 높이를 미리 확보
        self.camera_hint.setMinimumHeight(self.camera_hint.fontMetrics().lineSpacing() * 3 + 4)
        self.camera_hint.setVisible(False)
        cam_col = QVBoxLayout()
        cam_col.setContentsMargins(0, 0, 0, 0)
        cam_col.addLayout(cam_row)
        cam_col.addWidget(self.camera_hint)
        cam_w = QWidget()
        cam_w.setLayout(cam_col)
        self._fill_cameras()
        # synthetic·file 에서 device 로 바꾸면 그때 카메라를 찾는다
        self.source_mode.currentTextChanged.connect(
            lambda m: self._fill_cameras() if m == "device" and not self._names else None)

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

        self.sounds = QCheckBox("사진 캡처 찰칵 · 정지영상 · 녹화 시작/중지 소리")
        self.sounds.setChecked(bool(config.sounds_enabled))
        self.agent = QCheckBox("AI 에이전트 (장면 인식 · 자동 촬영 · 전후 클립 · 추천 프레임)")
        self.agent.setChecked(bool(config.agent_enabled))
        self.agent_clips = QCheckBox("촬영 전후 클립(mp4) 도 환자 영상으로 저장")
        self.agent_clips.setChecked(bool(config.agent_save_clips))
        self.agent_logging = QCheckBox("사용 기록 수집 (익명 세션 · 환자 정보 없음 · 학습용)")
        self.agent_logging.setChecked(bool(config.agent_logging))

        form.addRow("소스 모드", self.source_mode)
        form.addRow("카메라", cam_w)
        form.addRow("가로 해상도", self.width)
        form.addRow("세로 해상도", self.height)
        form.addRow("사진 형식", self.photo_format)
        form.addRow("저장 폴더(export)", exp_w)
        form.addRow("테스트 파일(file 모드)", self.test_file)
        form.addRow("효과음", self.sounds)
        form.addRow("AI 에이전트", self.agent)
        form.addRow("", self.agent_clips)
        form.addRow("", self.agent_logging)

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
        self.adjustSize()

    def _fill_cameras(self) -> None:
        """연결된 카메라를 이름으로 나열한다 (소니 ★). 저장한 카메라가 안 보이면 안내를 띄운다."""
        cfg = self.config
        current = self.camera_index.currentData()
        if current is None:
            current = cfg.camera_index
        names = device_names()
        probe = self.source_mode.currentText() == "device"      # 번호로 열어 보기는 실제 장비 모드에서만
        devs = list(range(len(names))) if names else (
            enumerate_devices(backend=cfg.camera_backend) if probe else [])
        self._names = names
        self.camera_index.clear()
        # 이름을 알면 목록에서 고르기만, 모르면 번호를 직접 칠 수 있게
        self.camera_index.setEditable(not names)
        for d in devs:
            label = f"{d}: {'★ ' if is_sony(names[d]) else ''}{names[d]}" if d < len(names) else str(d)
            self.camera_index.addItem(label, d)
        if not devs:
            self.camera_index.addItem(str(current), current)
        if cfg.camera_name and cfg.camera_name in names:
            current = names.index(cfg.camera_name)
        i = self.camera_index.findData(current)
        if i >= 0:
            self.camera_index.setCurrentIndex(i)
        if cfg.camera_name and names and cfg.camera_name not in names:
            self.camera_hint.setText(
                f"저장된 카메라 '{cfg.camera_name}' 가 지금 연결되어 있지 않습니다. "
                "카메라를 켜고 USB 를 연결한 뒤 '다시 찾기' 를 누르거나, 위 목록에서 다른 카메라를 고르세요.")
            self.camera_hint.setVisible(True)
        elif not devs and probe:
            self.camera_hint.setText("연결된 카메라를 찾지 못했습니다. 카메라를 연결한 뒤 '다시 찾기' 를 누르세요.")
            self.camera_hint.setVisible(True)
        else:
            self.camera_hint.setVisible(False)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.export.text() or "")
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
        c.test_file_path = self.test_file.text().strip()
        c.sounds_enabled = self.sounds.isChecked()
        c.agent_enabled = self.agent.isChecked()
        c.agent_save_clips = self.agent_clips.isChecked()
        c.agent_logging = self.agent_logging.isChecked()
        c.save()
        return c
