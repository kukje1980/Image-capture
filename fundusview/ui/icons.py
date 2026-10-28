"""Toolbar icons, drawn with QPainter (no image assets in the repo).

``icon(name)`` returns a QIcon for the toolbar keys used in the main window.
Glyphs are light line drawings for the dark toolbars (menus show no icons).
"""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

S = 64  # drawing canvas; Qt scales the pixmap to the button size
INK = QColor(228, 234, 238)
ACCENT = QColor(96, 200, 232)
BG = QColor(42, 49, 56)  # toolbar background, for filled shapes


def _pen(color=INK, w=4.5) -> QPen:
    p = QPen(color, w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def _arrow(p: QPainter, a: QPointF, b: QPointF, color=INK, head=10.0) -> None:
    p.setPen(_pen(color))
    p.drawLine(a, b)
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    pts = [b, QPointF(b.x() - head * math.cos(ang - 0.5), b.y() - head * math.sin(ang - 0.5)),
           QPointF(b.x() - head * math.cos(ang + 0.5), b.y() - head * math.sin(ang + 0.5))]
    p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _text(p: QPainter, rect: QRectF, txt: str, size: int, color=INK, bold=True) -> None:
    f = QFont()
    f.setPixelSize(size)
    f.setBold(bold)
    p.setFont(f)
    p.setPen(color)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, txt)


def _magnifier(p: QPainter, plus: str | None = None) -> None:
    p.setPen(_pen())
    p.drawEllipse(QRectF(10, 8, 30, 30))
    p.setPen(_pen(INK, 7))
    p.drawLine(QPointF(36, 34), QPointF(54, 52))
    if plus:
        p.setPen(_pen(ACCENT, 4))
        p.drawLine(QPointF(17, 23), QPointF(33, 23))
        if plus == "+":
            p.drawLine(QPointF(25, 15), QPointF(25, 31))


def _draw(name: str, p: QPainter) -> None:
    r = QRectF(6, 6, 52, 52)
    if name in ("red", "green", "blue", "redfree", "color"):
        cols = {"red": QColor(220, 60, 50), "green": QColor(60, 170, 80), "blue": QColor(60, 110, 220),
                "redfree": QColor(90, 160, 90)}
        if name == "color":
            for i, c in enumerate((QColor(220, 60, 50), QColor(60, 170, 80), QColor(60, 110, 220))):
                p.setBrush(QBrush(c))
                p.setPen(Qt.PenStyle.NoPen)
                ang = math.radians(90 + i * 120)
                p.drawEllipse(QPointF(32 + 9 * math.cos(ang), 32 - 9 * math.sin(ang)), 13, 13)
            return
        p.setBrush(QBrush(cols[name]))
        p.setPen(_pen(INK, 2.5))
        p.drawEllipse(QRectF(12, 12, 40, 40))
        _text(p, QRectF(12, 12, 40, 40), {"red": "R", "green": "G", "blue": "B", "redfree": "RF"}[name],
              18 if name != "redfree" else 15, QColor(255, 255, 255))
        return
    if name == "sharpen":
        p.setPen(_pen())
        p.drawPolygon(QPolygonF([QPointF(32, 8), QPointF(56, 54), QPointF(8, 54)]))
        p.setPen(_pen(ACCENT, 3))
        p.drawLine(QPointF(32, 20), QPointF(32, 46))
    elif name == "gamma":
        p.setPen(_pen(INK, 2.5))
        p.drawRect(r)
        path = QPainterPath(QPointF(8, 56))
        path.cubicTo(QPointF(14, 18), QPointF(30, 10), QPointF(56, 8))
        p.setPen(_pen(ACCENT))
        p.drawPath(path)
    elif name == "enhance":
        p.setPen(_pen())
        for i in range(8):
            a = math.radians(i * 45)
            rr = 24 if i % 2 == 0 else 13
            p.drawLine(QPointF(32, 32), QPointF(32 + rr * math.cos(a), 32 + rr * math.sin(a)))
        p.setBrush(QBrush(ACCENT))
        p.drawEllipse(QPointF(32, 32), 6, 6)
    elif name == "contrast":
        p.setPen(_pen())
        p.drawEllipse(r)
        path = QPainterPath()
        path.moveTo(32, 6)
        path.arcTo(r, 90, 180)
        path.closeSubpath()
        p.fillPath(path, QBrush(INK))
    elif name == "bright":
        p.setPen(_pen())
        p.drawEllipse(QPointF(32, 32), 11, 11)
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(QPointF(32 + 17 * math.cos(a), 32 + 17 * math.sin(a)),
                       QPointF(32 + 26 * math.cos(a), 32 + 26 * math.sin(a)))
    elif name == "negative":
        p.setPen(_pen(INK, 3))
        p.drawRect(r)
        p.fillRect(QRectF(32, 6, 26, 52), QBrush(INK))
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(32, 32), 12, 12)
        p.setBrush(QBrush(INK))
        p.drawPie(QRectF(20, 20, 24, 24), 90 * 16, 180 * 16)
    elif name == "flip_v":
        _arrow(p, QPointF(32, 30), QPointF(32, 6))
        _arrow(p, QPointF(32, 34), QPointF(32, 58))
        p.setPen(_pen(ACCENT, 3))
        p.drawLine(QPointF(10, 32), QPointF(54, 32))
    elif name == "flip_h":
        _arrow(p, QPointF(30, 32), QPointF(6, 32))
        _arrow(p, QPointF(34, 32), QPointF(58, 32))
        p.setPen(_pen(ACCENT, 3))
        p.drawLine(QPointF(32, 10), QPointF(32, 54))
    elif name in ("rot_cw", "rot_ccw", "loop", "undo"):
        p.setPen(_pen())
        rect = QRectF(12, 12, 40, 40)
        if name == "undo":
            path = QPainterPath(QPointF(16, 26))
            path.cubicTo(QPointF(26, 12), QPointF(52, 14), QPointF(50, 36))
            path.cubicTo(QPointF(48, 50), QPointF(30, 54), QPointF(22, 46))
            p.drawPath(path)
            _arrow(p, QPointF(24, 30), QPointF(12, 22))
            return
        span = 300 if name == "loop" else 270
        start = 60 if name == "rot_cw" else 120
        p.drawArc(rect, start * 16, (span if name != "rot_cw" else -span) * 16)
        end_ang = math.radians(start + (span if name != "rot_cw" else -span))
        tip = QPointF(32 + 20 * math.cos(end_ang), 32 - 20 * math.sin(end_ang))
        tangent = end_ang + (math.pi / 2 if name != "rot_cw" else -math.pi / 2)
        _arrow(p, QPointF(tip.x() - 6 * math.cos(tangent), tip.y() + 6 * math.sin(tangent)), tip)
        if name == "loop":
            p.setBrush(QBrush(ACCENT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([QPointF(26, 22), QPointF(42, 32), QPointF(26, 42)]))
    elif name == "zoom":
        _magnifier(p, "+")
    elif name == "loupe":
        _magnifier(p)
        p.setBrush(QBrush(QColor(110, 190, 230, 120)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(13, 11, 24, 24))
    elif name == "search":
        _magnifier(p)
    elif name == "pan":
        for a, b in (((32, 32), (32, 6)), ((32, 32), (32, 58)), ((32, 32), (6, 32)), ((32, 32), (58, 32))):
            _arrow(p, QPointF(*a), QPointF(*b), head=9)
    elif name == "length":
        p.setPen(_pen())
        p.drawLine(QPointF(8, 44), QPointF(56, 20))
        for i in range(6):
            t = i / 5
            x, y = 8 + 48 * t, 44 - 24 * t
            p.drawLine(QPointF(x, y), QPointF(x + 4, y + 8))
    elif name == "angle":
        p.setPen(_pen())
        p.drawLine(QPointF(10, 54), QPointF(56, 54))
        p.drawLine(QPointF(10, 54), QPointF(46, 12))
        p.setPen(_pen(ACCENT, 3.5))
        p.drawArc(QRectF(-10, 34, 40, 40), 0, 50 * 16)
    elif name == "cd":
        p.setPen(_pen())
        p.drawEllipse(r.adjusted(2, 2, -2, -2))
        p.setPen(_pen(ACCENT))
        p.drawEllipse(QRectF(22, 22, 20, 20))
    elif name == "text":
        _text(p, r, "T", 46, INK)
    elif name == "arrow":
        _arrow(p, QPointF(52, 52), QPointF(14, 14), head=14)
    elif name == "profile":
        p.setPen(_pen(INK, 2.5))
        p.drawLine(QPointF(6, 50), QPointF(58, 50))
        path = QPainterPath(QPointF(6, 42))
        for x, y in ((14, 30), (20, 36), (28, 14), (34, 40), (42, 26), (50, 32), (58, 20)):
            path.lineTo(QPointF(x, y))
        p.setPen(_pen(ACCENT, 3.5))
        p.drawPath(path)
    elif name == "histogram":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(INK))
        for i, h in enumerate((14, 26, 40, 48, 34, 20, 10)):
            p.drawRect(QRectF(8 + i * 7, 56 - h, 6, h))
    elif name == "equalize":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(INK))
        for i in range(7):
            p.drawRect(QRectF(8 + i * 7, 26, 6, 30))
        p.setPen(_pen(ACCENT, 3))
        p.drawLine(QPointF(6, 22), QPointF(58, 22))
    elif name == "denoise":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(INK))
        for i, (x, y) in enumerate(((14, 16), (40, 12), (24, 30), (50, 34), (12, 46), (34, 50), (46, 22))):
            p.drawEllipse(QPointF(x, y), 3 if i % 2 else 2, 3 if i % 2 else 2)
        p.setPen(_pen(ACCENT, 3.5))
        path = QPainterPath(QPointF(6, 40))
        path.cubicTo(QPointF(22, 28), QPointF(40, 50), QPointF(58, 36))
        p.drawPath(path)
    elif name == "auto":
        p.setPen(_pen())
        p.drawEllipse(r)
        path = QPainterPath()
        path.moveTo(32, 6)
        path.arcTo(r, 90, 180)
        path.closeSubpath()
        p.fillPath(path, QBrush(INK))
        _text(p, QRectF(30, 28, 30, 30), "A", 20, ACCENT)
    elif name == "original":
        p.setPen(_pen(INK, 3.5))
        p.drawRect(QRectF(8, 12, 48, 40))
        p.setBrush(QBrush(QColor(210, 120, 70)))
        p.drawEllipse(QPointF(32, 32), 13, 13)
    elif name == "fit":
        p.setPen(_pen())
        for (x, y), (dx, dy) in (((8, 8), (1, 1)), ((56, 8), (-1, 1)), ((8, 56), (1, -1)), ((56, 56), (-1, -1))):
            p.drawLine(QPointF(x, y), QPointF(x + 14 * dx, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + 14 * dy))
    elif name == "actual":
        _text(p, r, "1:1", 26)
    elif name in ("prev", "next"):
        p.setBrush(QBrush(ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        pts = [QPointF(44, 10), QPointF(44, 54), QPointF(12, 32)] if name == "prev" else \
              [QPointF(20, 10), QPointF(20, 54), QPointF(52, 32)]
        p.drawPolygon(QPolygonF(pts))
    elif name.startswith("multi"):
        n = {"multi": 2, "multi1": 1, "multi2": 2, "multi4": 2, "multi9": 3, "multi16": 4}.get(name, 2)
        p.setPen(_pen(INK, 3))
        cell = 48 / n
        for i in range(n):
            for j in range(n):
                p.drawRect(QRectF(8 + i * cell + 2, 8 + j * cell + 2, cell - 4, cell - 4))
    elif name == "copy":
        p.setPen(_pen(INK, 3.5))
        p.drawRect(QRectF(8, 8, 32, 36))
        p.setBrush(QBrush(BG))
        p.drawRect(QRectF(22, 20, 32, 36))
    elif name == "save":
        p.setPen(_pen(INK, 3.5))
        p.drawRect(QRectF(8, 8, 48, 48))
        p.fillRect(QRectF(18, 8, 26, 16), QBrush(INK))
        p.drawRect(QRectF(16, 34, 32, 22))
    elif name == "record":
        p.setPen(_pen(INK, 3.5))
        p.drawRect(QRectF(6, 12, 40, 36))
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(QPointF(48, 38), QPointF(48, 60))
        p.drawLine(QPointF(37, 49), QPointF(59, 49))
    elif name == "print":
        p.setPen(_pen(INK, 3.5))
        p.drawRect(QRectF(18, 6, 28, 16))
        p.drawRoundedRect(QRectF(6, 22, 52, 24), 4, 4)
        p.setBrush(QBrush(BG))
        p.drawRect(QRectF(18, 38, 28, 20))
    elif name == "edit":
        p.setPen(_pen())
        p.drawEllipse(QPointF(26, 20), 10, 10)
        path = QPainterPath(QPointF(6, 56))
        path.cubicTo(QPointF(8, 36), QPointF(44, 36), QPointF(46, 56))
        p.drawPath(path)
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(QPointF(40, 50), QPointF(58, 32))
    elif name == "folder":
        p.setPen(_pen(INK, 3.5))
        path = QPainterPath(QPointF(6, 16))
        path.lineTo(24, 16)
        path.lineTo(30, 22)
        path.lineTo(58, 22)
        path.lineTo(58, 52)
        path.lineTo(6, 52)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "import":
        _arrow(p, QPointF(32, 6), QPointF(32, 40), head=12)
        p.setPen(_pen(INK, 4))
        p.drawLine(QPointF(8, 44), QPointF(8, 56))
        p.drawLine(QPointF(8, 56), QPointF(56, 56))
        p.drawLine(QPointF(56, 56), QPointF(56, 44))
    elif name in ("watch_on", "watch_off"):
        p.setPen(_pen())
        path = QPainterPath(QPointF(4, 32))
        path.cubicTo(QPointF(18, 12), QPointF(46, 12), QPointF(60, 32))
        path.cubicTo(QPointF(46, 52), QPointF(18, 52), QPointF(4, 32))
        p.drawPath(path)
        p.setBrush(QBrush(QColor(40, 150, 90) if name == "watch_on" else QColor(200, 70, 60)))
        p.drawEllipse(QPointF(32, 32), 9, 9)
    elif name == "settings":
        p.setPen(_pen())
        p.drawEllipse(QPointF(32, 32), 10, 10)
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(QPointF(32 + 16 * math.cos(a), 32 + 16 * math.sin(a)),
                       QPointF(32 + 25 * math.cos(a), 32 + 25 * math.sin(a)))
    elif name == "log":
        p.setPen(_pen(INK, 3.5))
        p.drawRect(QRectF(10, 6, 44, 52))
        for y in (18, 28, 38, 48):
            p.drawLine(QPointF(18, y), QPointF(46, y))
    elif name == "tools":   # VK-2 TOOLS: crossed screwdriver and wrench
        p.setPen(_pen(INK, 5))
        p.drawLine(QPointF(14, 50), QPointF(40, 24))
        p.setBrush(QBrush(ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(34, 20), QPointF(48, 6), QPointF(58, 16), QPointF(44, 30)]))
        p.setPen(_pen(INK, 6))
        p.drawLine(QPointF(20, 20), QPointF(48, 48))
        p.setPen(_pen(INK, 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(6, 6, 20, 20), 300 * 16, 270 * 16)
    elif name == "annot_clear":   # eraser over a measurement line
        p.setPen(_pen(ACCENT, 3))
        p.drawLine(QPointF(6, 56), QPointF(58, 56))
        p.setPen(_pen(INK, 3.5))
        p.setBrush(QBrush(BG))
        body = QPolygonF([QPointF(10, 40), QPointF(34, 12), QPointF(54, 28), QPointF(30, 54), QPointF(20, 54)])
        p.drawPolygon(body)
        p.setBrush(QBrush(INK))
        p.drawPolygon(QPolygonF([QPointF(10, 40), QPointF(22, 26), QPointF(40, 44), QPointF(30, 54),
                                 QPointF(20, 54)]))
    elif name == "exit":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(196, 52, 44)))
        p.drawRoundedRect(QRectF(4, 16, 56, 32), 5, 5)
        _text(p, QRectF(4, 16, 56, 32), "EXIT", 18, QColor(255, 236, 230))
    elif name == "eye3d":
        p.setPen(_pen())
        p.drawEllipse(r.adjusted(2, 2, -2, -2))
        p.setBrush(QBrush(QColor(120, 80, 40)))
        p.drawEllipse(QPointF(42, 30), 9, 9)
        p.setPen(_pen(ACCENT, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(10, 20, 44, 24), 180 * 16, 180 * 16)
    else:
        _text(p, r, name[:2].upper(), 22)


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    pm = QPixmap(S, S)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(name, p)
    p.end()
    return QIcon(pm)
