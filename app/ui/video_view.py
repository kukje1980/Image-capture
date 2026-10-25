"""실시간 프레임을 그리는 위젯 (종횡비 유지, 검은 배경) + 영상 위 HUD(환자·안구·LIVE/정지/REC)."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QRadialGradient
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
    roiSelected = Signal(object)      # 정규화 (x, y, w, h) — None 이면 기본(중앙)으로

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setMinimumSize(480, 360)
        self._placeholder = "카메라 연결 대기 중..."
        self._patient = ""
        self._eye = "NA"
        self._state = "live"          # live | paused | frozen | rec
        self._rec_text = ""
        # Smart Capture 표시
        self._overlay: QImage | None = None        # 포커스 피킹 (프레임 위에 늘려 그림)
        self._roi = None                           # 정규화 ROI (None = 표시 안 함)
        self._focus = None                         # (초점 %, 초점 맞음 여부)
        self._roi_selecting = False
        self._drag_from: QPointF | None = None
        self._drag_to: QPointF | None = None
        self._img_rect = QRectF()
        self._flash_text = ""
        self._flash_until = 0.0
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self.update)

    def set_frame(self, frame: np.ndarray) -> None:
        self._pixmap = QPixmap.fromImage(bgr_to_qimage(frame))
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self._overlay = None
        self._focus = None
        self.update()

    # ---- Smart Capture ----
    def set_overlay(self, bgra: np.ndarray | None) -> None:
        """포커스 피킹 오버레이 (BGRA, 분석 해상도). None 이면 지운다."""
        if bgra is None:
            if self._overlay is not None:
                self._overlay = None
                self.update()
            return
        h, w = bgra.shape[:2]
        buf = np.ascontiguousarray(bgra)
        self._overlay = QImage(buf.data, w, h, 4 * w, QImage.Format.Format_ARGB32).copy()
        self.update()

    def set_roi(self, roi) -> None:
        self._roi = roi
        self.update()

    def set_focus_meter(self, pct: float | None, in_focus: bool = False) -> None:
        self._focus = None if pct is None else (float(pct), bool(in_focus))
        self.update()

    def flash(self, text: str, seconds: float = 1.6) -> None:
        """자동 촬영 알림 칩을 잠깐 표시."""
        self._flash_text = text
        self._flash_until = time.monotonic() + seconds
        self._flash_timer.start(int(seconds * 1000) + 30)
        self.update()

    def set_roi_selecting(self, on: bool) -> None:
        self._roi_selecting = on
        self._drag_from = self._drag_to = None
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        self.update()

    def _to_norm(self, pt: QPointF) -> tuple[float, float]:
        r = self._img_rect
        if r.width() <= 0 or r.height() <= 0:
            return 0.0, 0.0
        x = min(max((pt.x() - r.x()) / r.width(), 0.0), 1.0)
        y = min(max((pt.y() - r.y()) / r.height(), 0.0), 1.0)
        return x, y

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._roi_selecting and event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = self._drag_to = event.position()
            self.update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None:
            self._drag_to = event.position()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.button() == Qt.MouseButton.LeftButton:
            (x0, y0), (x1, y1) = self._to_norm(self._drag_from), self._to_norm(event.position())
            self._drag_from = self._drag_to = None
            if abs(x1 - x0) >= 0.03 and abs(y1 - y0) >= 0.03:
                self.roiSelected.emit((min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)))
            self.update()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._roi is not None:
            self.roiSelected.emit(None)
            return
        super().mouseDoubleClickEvent(event)

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
        self._img_rect = QRectF(x, y, scaled.width(), scaled.height())
        if self._overlay is not None:
            p.drawImage(self._img_rect, self._overlay)
        self._paint_smart(p)
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

    def _paint_smart(self, p: QPainter) -> None:
        r = self._img_rect
        if self._roi is not None and not self._roi_selecting:
            x, y, w, h = self._roi
            col = QColor("#3ccf7a") if self._focus and self._focus[1] else QColor(255, 255, 255, 150)
            p.setPen(QPen(col, 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(r.x() + x * r.width(), r.y() + y * r.height(), w * r.width(), h * r.height()))
        if self._roi_selecting:
            p.fillRect(r, QColor(0, 0, 0, 70))
            if self._drag_from is not None and self._drag_to is not None:
                p.setPen(QPen(QColor("#33c2b1"), 2))
                p.setBrush(QColor(51, 194, 177, 40))
                p.drawRect(QRectF(self._drag_from, self._drag_to).normalized())
            p.setFont(scaled_font(self.font(), 1.0, True))
            p.setPen(QColor("#e7eaf0"))
            p.drawText(QRectF(r.x(), r.bottom() - 40, r.width(), 28), Qt.AlignmentFlag.AlignCenter,
                       "초점을 볼 영역을 끌어서 지정하세요")
        if self._focus is not None:
            pct, ok = self._focus
            p.setFont(scaled_font(self.font(), 0.92, True))
            col = "#3ccf7a" if ok else ("#f5b94a" if pct >= 60 else "#a3acba")
            y = self.height() - 38.0
            nx = draw_chip(p, 12, y, f"초점 {pct:3.0f}", fg=col, border=col if ok else None)
            # 막대 (최근 최고 선명도 대비)
            bw, bh = 90.0, 6.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRoundedRect(QRectF(nx, y + 10, bw, bh), 3, 3)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(nx, y + 10, bw * max(0.0, min(pct, 100.0)) / 100.0, bh), 3, 3)
        if self._flash_text and time.monotonic() < self._flash_until:
            p.setFont(scaled_font(self.font(), 1.0, True))
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(self._flash_text) + 20 + 14
            draw_chip(p, (self.width() - w) / 2, 12, self._flash_text, fg="#c9f5ee", border="#33c2b1",
                      dot="#33c2b1")

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
