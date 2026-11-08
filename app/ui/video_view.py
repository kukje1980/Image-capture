"""실시간 프레임을 그리는 위젯 (종횡비 유지, 검은 배경) + 영상 위 HUD(환자·안구·LIVE/정지/REC).

확대 모드(set_zoom_mode): 휠 = 커서 기준 확대, 드래그 = 이동, 더블클릭 = 가운데, 오른쪽 아래 미니맵.
확대는 보기 전용이다 — 사진 캡처는 원본 전체 프레임을 저장한다.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
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


ZOOM_MIN, ZOOM_MAX = 1.25, 8.0
ZOOM_STEPS = (1.5, 2.0, 3.0, 4.0, 6.0, 8.0)


class VideoView(QWidget):
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._frame: np.ndarray | None = None       # 지금 보이는 프레임 (3D 화면 시작용)
        self._view = ""                             # HUD 보기 표시 ('확대 ×2.0', '3D')
        self._zoom_on = False
        self.zoom = 2.0
        self.cx = self.cy = 0.5                     # 확대 중심 (영상 좌표 0~1)
        self._pan = None
        self.setMinimumSize(480, 360)
        self._placeholder = "카메라 연결 대기 중..."
        self._patient = ""
        self._eye = "NA"
        self._state = "live"          # live | paused | frozen | rec
        self._rec_text = ""

    def set_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._pixmap = QPixmap.fromImage(bgr_to_qimage(frame))
        self.update()

    def current_frame(self) -> np.ndarray | None:
        return self._frame

    def clear(self) -> None:
        self._pixmap = None
        self._frame = None
        self.update()

    # ---- 확대 ----
    def set_zoom_mode(self, on: bool) -> None:
        self._zoom_on = bool(on)
        self.setCursor(Qt.CursorShape.OpenHandCursor if on else Qt.CursorShape.ArrowCursor)
        self._sync_view_chip()
        self.update()

    def zoom_mode(self) -> bool:
        return self._zoom_on

    def set_zoom(self, z: float, anchor: QPointF | None = None) -> None:
        """확대 배율 (anchor 가 있으면 그 위치의 영상 지점을 그대로 둔다)."""
        z = max(ZOOM_MIN, min(ZOOM_MAX, float(z)))
        g = self._geom()
        if g is not None and anchor is not None:
            W, H, dw, dh = g[0], g[1], g[4], g[5]
            qx = self.cx + (anchor.x() - W / 2) / (self.zoom * dw)
            qy = self.cy + (anchor.y() - H / 2) / (self.zoom * dh)
            self.cx = qx - (anchor.x() - W / 2) / (z * dw)
            self.cy = qy - (anchor.y() - H / 2) / (z * dh)
        changed = abs(z - self.zoom) > 1e-6
        self.zoom = z
        self._sync_view_chip()
        self.update()
        if changed:
            self.zoomChanged.emit(z)

    def step_zoom(self, direction: int) -> None:
        if direction > 0:
            z = next((s for s in ZOOM_STEPS if s > self.zoom + 0.01), ZOOM_MAX)
        else:
            z = next((s for s in reversed(ZOOM_STEPS) if s < self.zoom - 0.01), ZOOM_MIN)
        self.set_zoom(z)

    def center_zoom(self) -> None:
        self.cx = self.cy = 0.5
        self.update()

    def _sync_view_chip(self) -> None:
        if self._zoom_on:
            self._view = f"확대 ×{self.zoom:.1f}"
        elif self._view.startswith("확대"):
            self._view = ""

    def _geom(self):
        """(W, H, ox, oy, dw, dh): 위젯 크기와, 확대 전 영상이 들어가는 사각형."""
        if self._pixmap is None or self._pixmap.isNull():
            return None
        W, H = self.width(), self.height()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if W <= 0 or H <= 0 or pw <= 0 or ph <= 0:
            return None
        k = min(W / pw, H / ph)
        dw, dh = pw * k, ph * k
        return W, H, (W - dw) / 2, (H - dh) / 2, dw, dh

    def _clamp_center(self, g) -> None:
        W, H, dw, dh = g[0], g[1], g[4], g[5]
        hx, hy = W / 2 / (self.zoom * dw), H / 2 / (self.zoom * dh)
        self.cx = 0.5 if hx >= 0.5 else min(1 - hx, max(hx, self.cx))
        self.cy = 0.5 if hy >= 0.5 else min(1 - hy, max(hy, self.cy))

    def _minimap_rect(self) -> QRectF | None:
        g = self._geom()
        if not self._zoom_on or g is None:
            return None
        mw = min(168.0, self.width() * 0.22)
        mh = mw * self._pixmap.height() / self._pixmap.width()
        return QRectF(self.width() - mw - 12, self.height() - mh - 12, mw, mh)

    def set_hud(self, patient: str | None = None, eye: str | None = None,
                state: str | None = None, rec_text: str | None = None,
                view: str | None = None) -> None:
        if view is not None:
            self._view = view
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
        if self._zoom_on:
            self._paint_zoomed(p)
        else:
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        self._paint_hud(p)

    def _paint_zoomed(self, p: QPainter) -> None:
        g = self._geom()
        if g is None:
            return
        self._clamp_center(g)
        W, H, ox, oy, dw, dh = g
        pw, ph = self._pixmap.width(), self._pixmap.height()
        s = self.zoom * dw / pw                                   # 원본 px → 화면 px
        left = W / 2 - s * self.cx * pw
        top = H / 2 - s * self.cy * ph
        img = QRectF(left, top, pw * s, ph * s)
        target = img.intersected(QRectF(0, 0, W, H))
        if target.isEmpty():
            return
        source = QRectF((target.x() - left) / s, (target.y() - top) / s,
                        target.width() / s, target.height() / s)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(target, self._pixmap, source)
        # 미니맵 (전체 영상 + 보이는 영역)
        r = self._minimap_rect()
        if r is None:
            return
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 6, 6)
        p.setClipPath(clip)
        p.drawPixmap(r, self._pixmap, QRectF(self._pixmap.rect()))
        hx, hy = min(0.5, W / 2 / (self.zoom * dw)), min(0.5, H / 2 / (self.zoom * dh))
        vr = QRectF(r.x() + (self.cx - hx) * r.width(), r.y() + (self.cy - hy) * r.height(),
                    2 * hx * r.width(), 2 * hy * r.height())
        shade = QPainterPath()
        shade.addRect(r)
        hole = QPainterPath()
        hole.addRect(vr)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 128))
        p.setPen(QPen(QColor("#33c2b1"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(vr.adjusted(1, 1, -1, -1))
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawRoundedRect(r, 6, 6)

    # ---- 확대 화면 마우스 ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self._zoom_on or e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        r = self._minimap_rect()
        if r is not None and r.contains(e.position()):
            self._pan = "map"
            self._goto_minimap(e.position(), r)
            return
        self._pan = QPointF(e.position())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._zoom_on or self._pan is None:
            return super().mouseMoveEvent(e)
        if self._pan == "map":
            r = self._minimap_rect()
            if r is not None:
                self._goto_minimap(e.position(), r)
            return
        g = self._geom()
        if g is None:
            return
        d = e.position() - self._pan
        self._pan = QPointF(e.position())
        self.cx -= d.x() / (self.zoom * g[4])
        self.cy -= d.y() / (self.zoom * g[5])
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._zoom_on:
            self._pan = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        return super().mouseReleaseEvent(e)

    def _goto_minimap(self, pos: QPointF, r: QRectF) -> None:
        self.cx = (pos.x() - r.x()) / r.width()
        self.cy = (pos.y() - r.y()) / r.height()
        self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if not self._zoom_on:
            return super().wheelEvent(e)
        dy = e.angleDelta().y()
        if dy:
            self.set_zoom(self.zoom * math.exp(dy / 120 * 0.18), e.position())

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if self._zoom_on:
            self.center_zoom()
        else:
            super().mouseDoubleClickEvent(e)

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
        x = draw_chip(p, x, 12, _EYE_TEXT.get(self._eye, self._eye), fg=col or "#a3acba",
                      border=col)
        if self._view:
            draw_chip(p, x, 12, self._view, fg="#c9f5ee", border="#2c8d82")
        right = self.width() - 12.0
        if self._state == "rec":
            draw_chip(p, right, 12, f"REC {self._rec_text}".strip(), dot="#ff6b6b", bg="#7a1414", align_right=True)
        elif self._state == "paused":
            draw_chip(p, right, 12, "PAUSED", fg="#ffd08a", align_right=True)
        elif self._state == "frozen":
            draw_chip(p, right, 12, "FREEZE", fg="#9ccaff", align_right=True)
        else:
            draw_chip(p, right, 12, "LIVE", fg="#c9f5ee", dot="#3ccf7a", align_right=True)
