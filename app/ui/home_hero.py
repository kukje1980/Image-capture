"""홈 화면 큰 사진 칸 — 사용자가 고른 사진 > 브랜드 기본 사진 > (둘 다 없으면) 슬릿 빛줄기 그림.

그림은 슬릿램프로 본 눈(홍채·동공 위로 비스듬히 지나는 좁은 빛줄기)을 브랜드 색으로 그린 것이다.
Keeler 판은 로고 K 의 4색 — 하늘 · 파랑 · 네이비 · 주황 — 을 쓴다.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from app import brand as app_brand

# 브랜드에 k_colors 가 없을 때: 하늘 · 파랑 · 바탕 · 포인트
_DEFAULT_COLORS = ["#5eead4", "#0f8f84", "#0b1220", "#f59e0b"]


class HomeHero(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeHero")
        self.setMinimumSize(280, 170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        b = app_brand.current()
        self._colors = list(b.get("k_colors") or _DEFAULT_COLORS)
        self._caption = "SLIT LAMP IMAGING"
        self._logo = app_brand.asset(b.get("header_logo") or b.get("logo_dark") or b.get("logo"))
        self._pm = QPixmap()

    def set_image(self, path: str | None) -> bool:
        """사진 파일을 보여준다. 없거나 열 수 없으면 그림으로 돌아가고 False."""
        self._pm = QPixmap(path) if path else QPixmap()
        self.update()
        return not self._pm.isNull()

    def has_photo(self) -> bool:
        return not self._pm.isNull()

    # ---- 그리기 ----
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 18, 18)
        p.setClipPath(clip)
        if self.has_photo():
            s = self._pm.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            p.drawPixmap(QRectF((r.width() - s.width()) / 2, (r.height() - s.height()) / 2, s.width(), s.height()),
                         self._pm, QRectF(self._pm.rect()))
            # 아래쪽을 살짝 어둡게 — 글자가 사진 위에서도 읽히게
            g = QLinearGradient(0, r.height() * 0.55, 0, r.height())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 170))
            p.fillRect(r, g)
        else:
            self._paint_art(p, r)
        self._paint_caption(p, r)
        p.end()

    def _paint_art(self, p: QPainter, r: QRectF) -> None:
        sky, blue, navy, orange = (QColor(c) for c in self._colors)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        bg.setColorAt(0, navy)
        bg.setColorAt(1, navy.lighter(170))
        p.fillRect(r, bg)

        # 로고 K 의 두 곡선처럼 — 오른쪽 위 하늘색, 오른쪽 아래 주황 호
        R0 = max(r.width(), r.height())
        for col, cy, start, span, w in ((sky, r.top() - R0 * 0.15, 200, 90, 0.05),
                                        (orange, r.bottom() + R0 * 0.15, 70, 90, 0.035)):
            c = QColor(col)
            c.setAlpha(150)
            p.setPen(QPen(c, R0 * w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rad = R0 * 0.55
            p.drawArc(QRectF(r.right() - rad * 0.9, cy - rad, rad * 2, rad * 2), start * 16, span * 16)

        # 눈 — 홍채(파랑 → 하늘) · 동공 · 결
        cx, cy = r.left() + r.width() * 0.42, r.top() + r.height() * 0.48
        R = min(r.width(), r.height()) * 0.30
        glow = QRadialGradient(QPointF(cx, cy), R * 1.6)
        glow.setColorAt(0, QColor(blue.red(), blue.green(), blue.blue(), 90))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), R * 1.6, R * 1.6)
        iris = QRadialGradient(QPointF(cx, cy), R)
        iris.setColorAt(0.0, QColor("#000000"))
        iris.setColorAt(0.36, QColor("#000000"))
        iris.setColorAt(0.42, blue.darker(160))
        iris.setColorAt(0.75, blue)
        iris.setColorAt(0.93, sky)
        iris.setColorAt(1.0, navy.lighter(130))
        p.setBrush(iris)
        p.drawEllipse(QPointF(cx, cy), R, R)
        fib = QColor(sky)
        fib.setAlpha(55)
        p.setPen(QPen(fib, max(1.0, R / 90)))
        for i in range(48):
            a = i * math.tau / 48
            p.drawLine(QPointF(cx + math.cos(a) * R * 0.44, cy + math.sin(a) * R * 0.44),
                       QPointF(cx + math.cos(a + 0.08) * R * 0.92, cy + math.sin(a + 0.08) * R * 0.92))

        # 슬릿 빛줄기 — 왼쪽 위에서 비스듬히 들어와 각막 위에 밝은 초승달 단면을 만든다
        beam = QPainterPath()
        bx = cx - R * 0.55
        beam.moveTo(bx - R * 1.9, r.top())
        beam.lineTo(bx - R * 1.9 + R * 0.10, r.top())
        beam.lineTo(bx + R * 0.10, cy - R * 0.9)
        beam.lineTo(bx, cy - R * 0.9)
        beam.closeSubpath()
        bg2 = QLinearGradient(QPointF(bx - R * 1.9, r.top()), QPointF(bx, cy - R * 0.9))
        bg2.setColorAt(0, QColor(255, 255, 255, 0))
        bg2.setColorAt(1, QColor(255, 255, 255, 120))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg2)
        p.drawPath(beam)
        sect = QPainterPath()                       # 각막 단면 (두 호 사이)
        h = R * 0.95
        sect.moveTo(bx, cy - h)
        sect.cubicTo(bx - R * 0.30, cy - h * 0.4, bx - R * 0.30, cy + h * 0.4, bx, cy + h)
        sect.lineTo(bx + R * 0.10, cy + h)
        sect.cubicTo(bx - R * 0.12, cy + h * 0.4, bx - R * 0.12, cy - h * 0.4, bx + R * 0.10, cy - h)
        sect.closeSubpath()
        for width, alpha in ((R * 0.22, 40), (R * 0.12, 70)):
            g = QColor(orange)
            g.setAlpha(alpha)
            p.setPen(QPen(g, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(sect)
        lens = QLinearGradient(QPointF(bx - R * 0.3, cy), QPointF(bx + R * 0.1, cy))
        lens.setColorAt(0, QColor("#ffffff"))
        lens.setColorAt(1, QColor("#ffe2c8"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(lens)
        p.drawPath(sect)
        # 동공 반사점
        p.setBrush(QColor(255, 255, 255, 210))
        p.drawEllipse(QPointF(cx + R * 0.16, cy - R * 0.18), R * 0.06, R * 0.045)

    def _paint_caption(self, p: QPainter, r: QRectF) -> None:
        sky = QColor(self._colors[0])
        pad = max(16.0, r.width() * 0.05)
        y = r.bottom() - pad
        if self._logo:
            from PySide6.QtSvg import QSvgRenderer
            svg = QSvgRenderer(self._logo)
            ds = svg.defaultSize()
            lh = max(20.0, min(40.0, r.height() * 0.11))
            lw = ds.width() * lh / max(1, ds.height())
            svg.render(p, QRectF(r.left() + pad, y - lh - 20, lw, lh))
        f = QFont()
        f.setPixelSize(12)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        p.setFont(f)
        p.setPen(sky)
        p.drawText(QRectF(r.left() + pad, y - 16, r.width() - pad * 2, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._caption)
