"""썸네일 패널의 단일 항목 (클릭 가능): 4:3 영상 + 안구 배지 + 시각·코멘트 오버레이."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.models.capture import Capture
from app.ui import icons
from app.ui.theme import EYE_COLORS
from app.ui.video_view import scaled_font

_cache: dict[str, QPixmap] = {}


def _load_pixmap(capture: Capture) -> QPixmap | None:
    path = capture.thumbnail_path
    if not path and capture.media_type == "photo":
        path = capture.file_path
    if not path:
        return None
    pm = _cache.get(path)
    if pm is None:
        pm = QPixmap(path)
        if pm.isNull():
            return None
        if pm.width() > 480:
            pm = pm.scaledToWidth(480, Qt.TransformationMode.SmoothTransformation)
        _cache[path] = pm
    return pm


class ThumbnailWidget(QWidget):
    clicked = Signal(object)  # Capture

    def __init__(self, capture: Capture, parent=None):
        super().__init__(parent)
        self.capture = capture
        self.setObjectName("ThumbCard")
        self._pm = _load_pixmap(capture)
        self._hover = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        eye = capture.eye if capture.eye and capture.eye != "NA" else ""
        self.setToolTip(" · ".join(x for x in (capture.captured_at, eye, capture.note or "") if x))

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return int(w * 3 / 4)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def resizeEvent(self, e) -> None:  # noqa: N802
        self.setFixedHeight(self.heightForWidth(self.width()))
        super().resizeEvent(e)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        c = self.capture
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(r, 9, 9)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 9, 9)
        p.setClipPath(clip)
        if self._pm is not None:
            s = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s)
        else:
            p.drawPixmap(self.width() // 2 - 15, self.height() // 2 - 15,
                         icons.pixmap("play" if c.media_type == "video" else "image", "#6b7586", 30))
        # 하단 그라데이션 + 시각·코멘트
        gh = 44
        g = QLinearGradient(0, self.height() - gh, 0, self.height())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 215))
        p.fillRect(QRectF(0, self.height() - gh, self.width(), gh), g)
        f = scaled_font(self.font(), 0.85, True)
        p.setFont(f)
        when = c.captured_at[-8:] if c.captured_at else ""
        note = c.note or ""
        y = self.height() - (32 if note else 20)
        p.setPen(QColor("#e7eaf0"))
        p.drawText(QRectF(8, y, self.width() - 16, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, when)
        if note:
            p.setFont(scaled_font(self.font(), 0.85))
            p.setPen(QColor("#a3acba"))
            el = p.fontMetrics().elidedText(note, Qt.TextElideMode.ElideRight, self.width() - 16)
            p.drawText(QRectF(8, y + 15, self.width() - 16, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, el)
        # 배지 (안구 · 동영상)
        p.setFont(f)
        bx = 6.0
        badges = []
        if c.eye and c.eye != "NA":
            badges.append((c.eye, EYE_COLORS.get(c.eye, "#a3acba")))
        if c.media_type == "video":
            badges.append((f"▶ {round((c.duration_ms or 0) / 1000)}s", "#ff8a87"))
        for text, col in badges:
            w = p.fontMetrics().horizontalAdvance(text) + 12
            br = QRectF(bx, 6, w, 18)
            p.setPen(QPen(QColor(col), 1))
            p.setBrush(QColor(8, 11, 16, 190))
            p.drawRoundedRect(br, 5, 5)
            p.setPen(QColor(col))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, text)
            bx += w + 4
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#33c2b1"), 2) if self._hover else QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.capture)
