"""썸네일 패널의 단일 항목 (클릭 가능)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.models.capture import Capture


class ThumbnailWidget(QWidget):
    clicked = Signal(object)  # Capture

    def __init__(self, capture: Capture, parent=None):
        super().__init__(parent)
        self.capture = capture
        self.setObjectName("ThumbCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setFixedSize(140, 105)
        pm = self._load_pixmap(capture)
        if pm is not None and not pm.isNull():
            self.img.setStyleSheet("background:#222;border-radius:4px;")
            self.img.setPixmap(
                pm.scaled(140, 105, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.img.setStyleSheet("background:#222;color:#999;border-radius:4px;")
            self.img.setText("이미지\n없음")

        badge = "  ▶동영상" if capture.media_type == "video" else ""
        eye = capture.eye if capture.eye and capture.eye != "NA" else ""
        when = capture.captured_at[-8:] if capture.captured_at else ""
        self.caption = QLabel(f"{when} {eye}{badge}".strip())
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet("font-size:11px;")
        self.caption.setObjectName("Muted")

        lay.addWidget(self.img)
        lay.addWidget(self.caption)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @staticmethod
    def _load_pixmap(capture: Capture):
        path = capture.thumbnail_path
        if not path and capture.media_type == "photo":
            path = capture.file_path
        if path:
            return QPixmap(path)
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.capture)
