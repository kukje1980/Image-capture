"""실시간 프레임을 그리는 위젯 (종횡비 유지, 검은 배경)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.capture.frame_utils import bgr_to_qimage


class VideoView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(480, 360)
        self._placeholder = "카메라 연결 대기 중..."

    def set_frame(self, frame: np.ndarray) -> None:
        self._pixmap = QPixmap.fromImage(bgr_to_qimage(frame))
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._pixmap is None or self._pixmap.isNull():
            p.setPen(QColor("#888888"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        p.drawPixmap(x, y, scaled)
