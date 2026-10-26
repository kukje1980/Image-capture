"""전송 확인 창 — 고른 사진 수 · 전송 방법 · 위치를 보여 주고, 이번에 보낼 파일 형식을 고른다 (기본값 = 설정)."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.services import send_service as ss
from app.ui import icons
from app.ui.theme import ICON_ON_ACCENT


class SendDialog(QDialog):
    def __init__(self, config, count: int, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("전송")
        method = getattr(config, "send_method", "folder")
        method_text = dict(ss.METHODS).get(method, method)
        dest = ss.destination(config) or "(설정에서 위치를 고르세요)"

        lay = QVBoxLayout(self)
        title = QLabel(f"사진 {count}장을 보냅니다")
        title.setObjectName("BrandTitle")
        lay.addWidget(title)
        form = QFormLayout()
        form.addRow("방법", QLabel(method_text))
        d = QLabel(dest)
        d.setWordWrap(True)
        form.addRow("위치", d)
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        self.formats: dict = {}
        chosen = set(getattr(config, "send_formats", ["original"]) or [])
        for code, text in ss.FORMATS:
            cb = QCheckBox(text)
            if method == "pacs":
                cb.setChecked(code == "dicom")
                cb.setEnabled(False)
            else:
                cb.setChecked(code in chosen)
            self.formats[code] = cb
            h.addWidget(cb)
        form.addRow("파일 형식", box)
        lay.addLayout(form)
        hint = QLabel("위치 · 방법 · 기본 형식은 설정 → 전송 탭에서 바꿉니다.")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self.btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = self.btns.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(icons.gap("보내기"))
        ok.setObjectName("Primary")
        ok.setIcon(icons.icon("send", ICON_ON_ACCENT, 16))
        ok.setIconSize(QSize(15, 15))
        self.btns.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)
        lay.addWidget(self.btns)
        for cb in self.formats.values():
            cb.toggled.connect(lambda _on: self._sync())
        self._sync()

    def _sync(self) -> None:
        self.btns.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.selected_formats()))

    def selected_formats(self) -> list:
        return [k for k, cb in self.formats.items() if cb.isChecked()]
