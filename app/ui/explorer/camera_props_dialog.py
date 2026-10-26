"""카메라 속성 창 — 노출·게인·밝기·대비·채도·선명도·화이트밸런스를 실시간으로 조절.

값을 바꾸면 바로 장치에 적용되고(라이브 화면에서 확인), 닫을 때 설정에 저장되어 다음 실행에도 쓰인다.
장치가 지원하지 않는 항목은 '미지원' 으로 표시된다 (캡처보드·드라이버마다 다름).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from app.capture import camera_props

log = logging.getLogger(__name__)


class CameraPropsDialog(QDialog):
    def __init__(self, camera, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("카메라 속성")
        self.resize(480, 460)
        self.camera = camera
        self.config = config
        self.widgets: dict = {}
        self.values: dict = {}
        self.state: dict[str, QLabel] = {}
        saved = camera_props.sanitize(config.camera_props)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for row, p in enumerate(camera_props.PROPS):
            v = saved.get(p.key)
            if v is None:
                cur = camera.property_value(p.key)
                v = camera_props.clamp(p.key, cur) if cur is not None else p.default
            self.values[p.key] = v
            st = QLabel("")
            st.setObjectName("Muted")
            self.state[p.key] = st
            if p.toggle:
                w = QCheckBox(p.label)
                w.setChecked(bool(v))
                w.toggled.connect(lambda on, k=p.key: self.set_value(k, 1.0 if on else 0.0))
                grid.addWidget(w, row, 0, 1, 3)
            else:
                grid.addWidget(QLabel(p.label), row, 0)
                w = QSlider(Qt.Orientation.Horizontal)
                w.setRange(int(p.lo / p.step), int(p.hi / p.step))
                w.setValue(int(round(v / p.step)))
                val = QLabel(self._fmt(p, v))
                val.setMinimumWidth(52)
                val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                w.valueChanged.connect(lambda n, k=p.key, lbl=val: self._on_slider(k, n, lbl))
                grid.addWidget(w, row, 1)
                grid.addWidget(val, row, 2)
            grid.addWidget(st, row, 3)
            self.widgets[p.key] = w

        note = QLabel("값은 바로 적용됩니다. 장치가 지원하지 않는 항목은 바뀌지 않습니다.\n"
                      "노출·색온도를 직접 맞추려면 '자동' 을 먼저 끄세요.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        b_reset = QPushButton("기본값")
        b_close = QPushButton("닫기")
        b_close.setObjectName("Primary")
        b_reset.clicked.connect(self.reset)
        b_close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addWidget(b_reset)
        btns.addStretch(1)
        btns.addWidget(b_close)
        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addWidget(note)
        lay.addStretch(1)
        lay.addLayout(btns)

        camera.property_set.connect(self._on_result)
        self._sync_enabled()

    @staticmethod
    def _fmt(p, v) -> str:
        return f"{int(v)}" if p.step >= 1 else f"{v:.1f}"

    def _on_slider(self, key: str, n: int, lbl: QLabel) -> None:
        p = camera_props.BY_KEY[key]
        v = n * p.step
        lbl.setText(self._fmt(p, v))
        self.set_value(key, v)

    def set_value(self, key: str, value: float) -> None:
        self.values[key] = camera_props.clamp(key, value)
        self.camera.set_property(key, self.values[key])
        self.state[key].setText("…")
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        self.widgets["exposure"].setEnabled(not self.values.get("auto_exposure", 1))
        self.widgets["wb_temperature"].setEnabled(not self.values.get("auto_wb", 1))

    def _on_result(self, key: str, ok: bool, _now: float) -> None:
        if key in self.state:
            self.state[key].setText("적용" if ok else "미지원")

    def reset(self) -> None:
        for p in camera_props.PROPS:
            w = self.widgets[p.key]
            if p.toggle:
                w.setChecked(bool(p.default))
            else:
                w.setValue(int(round(p.default / p.step)))      # 바뀌면 숫자 표시도 함께 갱신
            self.set_value(p.key, p.default)

    def done(self, r: int) -> None:
        try:
            self.camera.property_set.disconnect(self._on_result)
        except (RuntimeError, TypeError):
            pass
        try:
            self.config.save()
        except Exception:  # noqa: BLE001
            log.warning("camera props save failed", exc_info=True)
        super().done(r)
