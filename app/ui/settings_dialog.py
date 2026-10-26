"""설정 다이얼로그: 소스 모드, 카메라, 해상도, 사진 형식, export 폴더, 효과음."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
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

SOURCE_MODES = (
    ("device", "실제 카메라 (device)"),
    ("file", "동영상 파일 재생 (file)"),
    ("synthetic", "합성 테스트 영상 (synthetic)"),
)


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("설정")
        self.resize(500, 380)

        form = QFormLayout()
        self.source_mode = QComboBox()
        for key, label in SOURCE_MODES:
            self.source_mode.addItem(label, key)
        i = self.source_mode.findData(config.source_mode)
        self.source_mode.setCurrentIndex(i if i >= 0 else 0)

        # 카메라 목록: 소스 모드와 관계없이 항상 보여 준다 (합성/파일 모드에서도 고를 수 있게)
        self.camera_index = QComboBox()
        self.camera_index.activated.connect(self._on_camera_picked)
        self.btn_rescan = QPushButton("새로고침")
        self.btn_rescan.setToolTip("카메라를 연결·분리한 뒤 목록을 다시 읽습니다")
        self.btn_rescan.clicked.connect(self._rescan)
        cam_row = QHBoxLayout()
        cam_row.setContentsMargins(0, 0, 0, 0)
        cam_row.addWidget(self.camera_index, 1)
        cam_row.addWidget(self.btn_rescan)
        cam_w = QWidget()
        cam_w.setLayout(cam_row)
        self.camera_note = QLabel()
        self.camera_note.setObjectName("Muted")
        self.camera_note.setWordWrap(True)
        self.camera_note.hide()
        self._names: list[str] = []
        self._fill_cameras(device_names())

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
        form.addRow("", self.camera_note)
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

    # ---- 카메라 목록 ----
    def _fill_cameras(self, names: list[str]) -> None:
        cfg = self.config
        prev = self.camera_index.currentData()
        self._names = list(names)
        self.camera_index.clear()
        devs = list(range(len(names)))
        if not devs and self.source_mode.currentData() == "device":
            # 이름을 못 읽는 환경: 번호로 열어 보며 찾는다 (느릴 수 있음)
            devs = enumerate_devices(backend=cfg.camera_backend)
        for d in devs:
            if d < len(names):
                self.camera_index.addItem(f"{d}: {'★ ' if is_sony(names[d]) else ''}{names[d]}", d)
            else:
                self.camera_index.addItem(f"{d}: 카메라 {d}", d)
        # 이름을 아예 못 읽으면 번호를 직접 입력할 수 있게
        self.camera_index.setEditable(not names)
        if self.camera_index.count() == 0:
            self.camera_index.addItem(str(cfg.camera_index), cfg.camera_index)
        # 선택: 저장된 이름 → 이전 선택 → 저장된 번호
        want = None
        if cfg.camera_name and cfg.camera_name in names:
            want = names.index(cfg.camera_name)
        elif prev is not None:
            want = prev
        else:
            want = cfg.camera_index
        i = self.camera_index.findData(want)
        if i >= 0:
            self.camera_index.setCurrentIndex(i)
        # 저장된 카메라가 지금 목록에 없으면 분명히 알린다 (다른 장치로 몰래 바뀌지 않게)
        if cfg.camera_name and names and cfg.camera_name not in names:
            self.camera_note.setText(
                f"⚠ 저장된 카메라 '{cfg.camera_name}' 가 지금 연결되어 있지 않습니다. "
                "카메라를 켜고 연결한 뒤 '새로고침'을 누르거나, "
                "위 목록에서 다른 카메라를 고르세요.")
            self.camera_note.show()
        elif not names and not devs:
            self.camera_note.setText(
                "⚠ 카메라를 찾지 못했습니다. 연결을 확인하고 '새로고침'을 누르세요.")
            self.camera_note.show()
        else:
            self.camera_note.hide()

    def _rescan(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._fill_cameras(device_names())
        finally:
            QApplication.restoreOverrideCursor()

    def _on_camera_picked(self, _index: int) -> None:
        # 카메라를 고르면 실제 장치 모드로 (합성/파일 모드에 머물러 고른 카메라가 안 나오는 일 방지)
        if self.source_mode.currentData() != "device":
            self.source_mode.setCurrentIndex(self.source_mode.findData("device"))

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.export.text() or "")
        if d:
            self.export.setText(d)

    def apply_to_config(self):
        c = self.config
        c.source_mode = self.source_mode.currentData() or "device"
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
