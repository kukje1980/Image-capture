"""실시간 프레임을 그리는 위젯 (종횡비 유지, 검은 배경) + 영상 위 HUD(환자·안구·LIVE/정지/REC)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.capture.frame_utils import bgr_to_qimage
from app.ui import icons
from app.ui.theme import EYE_COLORS

_EYE_TEXT = {"OD": "OD 우안", "OS": "OS 좌안", "OU": "OU 양안", "NA": "안구 미지정"}


def draw_chip(p: QPainter, x: float, y: float, text: str, fg: str = "#e7eaf0",
              border: str | None = None, bg: str = "rgba(8,11,16,160)", dot: str | None = None,
              align_right: bool = False) -> float:
    """반투명 칩을 그리고 다음 칩의 x 좌표를 돌려준다 (오른쪽 정렬이면 왼쪽 끝)."""
    fm = p.fontMetrics()
    pad, h = 10, 26
    w = fm.horizontalAdvance(text) + pad * 2 + (14 if dot else 0)
    if align_right:
        x -= w
    r = QRectF(x, y, w, h)
    col = QColor(8, 11, 16, 165) if bg.startswith("rgba") else QColor(bg)
    p.setPen(QPen(QColor(border), 1.2) if border else QPen(QColor(255, 255, 255, 22), 1))
    p.setBrush(col)
    p.drawRoundedRect(r, 7, 7)
    tx = x + pad
    if dot:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(QRectF(tx, y + h / 2 - 3.5, 7, 7))
        tx += 14
    p.setPen(QColor(fg))
    p.drawText(QRectF(tx, y, w - (tx - x), h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    return x - 6 if align_right else x + w + 6


def scaled_font(base: QFont, factor: float, bold: bool = False) -> QFont:
    """QSS 가 px 로 지정한 폰트(pointSize = -1)도 안전하게 배율 조정."""
    f = QFont(base)
    if f.pointSizeF() > 0:
        f.setPointSizeF(max(7.0, f.pointSizeF() * factor))
    else:
        f.setPixelSize(max(9, round((f.pixelSize() if f.pixelSize() > 0 else 13) * factor)))
    f.setBold(bold)
    return f


class VideoView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(480, 360)
        self._placeholder = "카메라 연결 대기 중..."
        self._patient = ""
        self._eye = "NA"
        self._state = "live"          # live | paused | frozen | rec
        self._rec_text = ""

    def set_frame(self, frame: np.ndarray) -> None:
        self._pixmap = QPixmap.fromImage(bgr_to_qimage(frame))
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def set_hud(self, patient: str | None = None, eye: str | None = None,
                state: str | None = None, rec_text: str | None = None) -> None:
        if patient is not None:
            self._patient = patient
        if eye is not None:
            self._eye = eye
        if state is not None:
            self._state = state
        if rec_text is not None:
            self._rec_text = rec_text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._pixmap is None or self._pixmap.isNull():
            self._paint_placeholder(p)
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        p.drawPixmap(x, y, scaled)
        self._paint_hud(p)

    def _paint_placeholder(self, p: QPainter) -> None:
        c = self.rect().center()
        g = QRadialGradient(c, max(self.width(), self.height()) * 0.6)
        g.setColorAt(0, QColor("#121821"))
        g.setColorAt(1, QColor("#000000"))
        p.fillRect(self.rect(), g)
        r = 38
        p.setPen(QPen(QColor("#262e3a"), 1))
        p.setBrush(QColor(51, 194, 177, 18))
        p.drawEllipse(c, r, r)
        p.drawPixmap(int(c.x() - 17), int(c.y() - 17), icons.pixmap("aperture", "#6b7586", 34, 1.4))
        p.setFont(scaled_font(self.font(), 1.15, True))
        p.setPen(QColor("#e7eaf0"))
        p.drawText(QRectF(0, c.y() + r + 10, self.width(), 26), Qt.AlignmentFlag.AlignCenter, "카메라 대기 중")
        p.setFont(self.font())
        p.setPen(QColor("#8a94a6"))
        p.drawText(QRectF(0, c.y() + r + 36, self.width(), 22), Qt.AlignmentFlag.AlignCenter, self._placeholder)

    def _paint_hud(self, p: QPainter) -> None:
        p.setFont(scaled_font(self.font(), 0.92, True))
        x = 12.0
        if self._patient:
            x = draw_chip(p, x, 12, self._patient)
        col = EYE_COLORS.get(self._eye)
        draw_chip(p, x, 12, _EYE_TEXT.get(self._eye, self._eye), fg=col or "#a3acba",
                  border=col)
        right = self.width() - 12.0
        if self._state == "rec":
            draw_chip(p, right, 12, f"REC {self._rec_text}".strip(), dot="#ff6b6b", bg="#7a1414", align_right=True)
        elif self._state == "paused":
            draw_chip(p, right, 12, "PAUSED", fg="#ffd08a", align_right=True)
        elif self._state == "frozen":
            draw_chip(p, right, 12, "FREEZE", fg="#9ccaff", align_right=True)
        else:
            draw_chip(p, right, 12, "LIVE", fg="#c9f5ee", dot="#3ccf7a", align_right=True)
