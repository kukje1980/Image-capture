"""Toolbar icons, drawn with QPainter (no image assets in the repo).

``icon(name)`` returns a QIcon for the toolbar keys used in the main window: a rounded square
("squircle") tile in one of a dozen fresh colours with a soft top-to-bottom gradient, and the
glyph on it in white with round, chunky strokes — the look of the icons in macOS's System
Settings and Dock. ``icon(name, plain=True)`` is the glyph alone, as a light line drawing, for
places that bring their own background (the ◀ ▶ over a photo, a badge).
"""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

S = 64                     # the drawing canvas, in units; Qt scales the pixmap to the button size
PX = 2                     # pixels per unit: the pixmap is 128 px, sharp on a Retina screen too
INK = QColor(228, 234, 238)        # plain glyphs: light lines …
ACCENT = QColor(96, 200, 232)      # … with a second colour
BG = QColor(42, 49, 56)            # … on a dark bar (for shapes that cover what is behind them)

TILE = QRectF(3, 3, 58, 58)
TILE_RADIUS = 15.0
GLYPH_SCALE = 0.62         # the glyph (drawn on the whole canvas) is this large on its tile
# the tile colours — light at the top, deeper at the bottom
TILES = {
    "blue": ("#56b4ff", "#0a72f5"),
    "sky": ("#6fd3ff", "#1d9bf0"),
    "teal": ("#5fdde6", "#10a6ba"),
    "mint": ("#6be6c8", "#10b894"),
    "green": ("#6fe07f", "#27b548"),
    "amber": ("#ffcc4d", "#f5a300"),
    "orange": ("#ffb057", "#f77f0a"),
    "red": ("#ff7a70", "#e8382d"),
    "pink": ("#ff86b0", "#f23d77"),
    "purple": ("#cf95ff", "#9545e6"),
    "indigo": ("#9496ff", "#5557e0"),
    "slate": ("#8fa3bd", "#55698a"),
    "gray": ("#b3b7c2", "#727685"),
}
# which tile a glyph sits on (the rest: blue)
TILE_OF = {
    "log": "blue", "search": "blue", "prev": "slate", "next": "slate",
    "simple": "indigo", "detail": "teal", "fit": "sky", "actual": "sky", "tools": "orange",
    "eye3d": "pink", "montage": "amber", "glaucoma": "green", "discpair": "green",
    "print": "slate", "settings": "gray", "exit": "red",
    "flip_v": "teal", "flip_h": "teal", "rot_cw": "mint", "rot_ccw": "mint",
    "zoom": "blue", "loupe": "sky", "pan": "indigo",
    "length": "amber", "angle": "orange", "cd": "green", "text": "indigo", "arrow": "indigo",
    "profile": "purple", "histogram": "purple", "equalize": "purple", "denoise": "teal",
    "loop": "pink", "undo": "gray", "annot_clear": "red",
    "red": "red", "green": "green", "blue": "blue", "redfree": "mint", "color": "gray",
    "sharpen": "sky", "gamma": "amber", "enhance": "amber", "contrast": "slate", "bright": "orange",
    "negative": "slate", "auto": "slate", "original": "orange",
    "copy": "sky", "save": "blue", "record": "green", "edit": "orange", "folder": "sky", "import": "green",
    "watch_on": "green", "watch_off": "red",
}


class _Glyph:
    """What a glyph is drawn with: the painter and its three colours.

    ``ink`` — the lines; ``soft`` — the second, quieter colour; ``hole`` — the colour behind the
    glyph, for shapes that cover a part of it. ``k`` scales every line width (a glyph on a tile
    is drawn smaller, so its lines are made thicker to stay as strong).
    """

    def __init__(self, p: QPainter, ink: QColor, soft: QColor, hole: QColor, k: float, tiled: bool):
        self.p, self.ink, self.soft, self.hole, self.k, self.tiled = p, ink, soft, hole, k, tiled

    def pen(self, color: QColor | None = None, w: float = 4.5) -> QPen:
        pen = QPen(color or self.ink, w * self.k)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def stroke(self, color: QColor | None = None, w: float = 4.5) -> None:
        self.p.setPen(self.pen(color, w))
        self.p.setBrush(Qt.BrushStyle.NoBrush)

    def fill(self, color: QColor | None = None) -> None:
        self.p.setPen(Qt.PenStyle.NoPen)
        self.p.setBrush(QBrush(color or self.ink))

    def line(self, x1: float, y1: float, x2: float, y2: float, color: QColor | None = None, w: float = 4.5) -> None:
        self.p.setPen(self.pen(color, w))
        self.p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def arrow(self, a: QPointF, b: QPointF, color: QColor | None = None, head: float = 10.0,
              w: float = 4.5) -> None:
        color = color or self.ink
        p = self.p
        p.setPen(self.pen(color, w))
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        pts = [b, QPointF(b.x() - head * math.cos(ang - 0.5), b.y() - head * math.sin(ang - 0.5)),
               QPointF(b.x() - head * math.cos(ang + 0.5), b.y() - head * math.sin(ang + 0.5))]
        p.setBrush(QBrush(color))
        p.drawPolygon(QPolygonF(pts))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def text(self, rect: QRectF, txt: str, size: int, color: QColor | None = None) -> None:
        f = QFont()
        f.setPixelSize(size)
        f.setBold(True)
        self.p.setFont(f)
        self.p.setPen(color or self.ink)
        self.p.drawText(rect, Qt.AlignmentFlag.AlignCenter, txt)

    def magnifier(self, lens: QColor | None = None) -> None:
        p = self.p
        self.line(37, 35, 54, 52, w=7)
        self.p.setPen(self.pen())
        p.setBrush(QBrush(lens) if lens is not None else Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(9, 7, 32, 32))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def disc(self, cx: float, cy: float, r: float, cup: float) -> None:
        """An optic disc: the rim as a ring, the cup filled."""
        self.stroke(w=3.5)
        self.p.drawEllipse(QPointF(cx, cy), r, r)
        self.fill()
        self.p.drawEllipse(QPointF(cx, cy), cup, cup * 1.1)


def _with_alpha(c: QColor, a: int) -> QColor:
    c = QColor(c)
    c.setAlpha(a)
    return c


def _draw(name: str, g: _Glyph) -> None:
    p, ink, soft, hole = g.p, g.ink, g.soft, g.hole
    r = QRectF(6, 6, 52, 52)
    if name in ("red", "green", "blue", "redfree"):
        g.text(QRectF(0, 0, 64, 64), {"red": "R", "green": "G", "blue": "B", "redfree": "RF"}[name],
               46 if name != "redfree" else 34)
    elif name == "color":
        for i, c in enumerate((QColor(255, 99, 88), QColor(72, 214, 110), QColor(74, 150, 255))):
            g.fill(c)
            ang = math.radians(90 + i * 120)
            p.drawEllipse(QPointF(32 + 10 * math.cos(ang), 33 - 10 * math.sin(ang)), 14, 14)
    elif name == "sharpen":
        g.stroke()
        p.drawPolygon(QPolygonF([QPointF(32, 8), QPointF(56, 54), QPointF(8, 54)]))
        g.line(32, 24, 32, 44, soft, 3.5)
    elif name == "gamma":
        g.stroke(soft, 3)
        p.drawRoundedRect(r, 6, 6)
        path = QPainterPath(QPointF(10, 54))
        path.cubicTo(QPointF(14, 20), QPointF(30, 12), QPointF(54, 10))
        g.stroke()
        p.drawPath(path)
    elif name == "enhance":    # a sparkle: a large four-pointed star and a small one
        g.fill()
        for cx, cy, a, b in ((27.0, 36.0, 22.0, 6.0), (49.0, 15.0, 11.0, 3.0)):
            path = QPainterPath(QPointF(cx, cy - a))
            for i in range(1, 8):
                rr = a if i % 2 == 0 else b
                ang = math.radians(-90 + i * 45)
                path.lineTo(QPointF(cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
            path.closeSubpath()
            p.drawPath(path)
    elif name in ("contrast", "auto"):
        g.stroke()
        p.drawEllipse(r)
        path = QPainterPath()
        path.moveTo(32, 6)
        path.arcTo(r, 90, 180)
        path.closeSubpath()
        p.fillPath(path, QBrush(ink))
        if name == "auto":
            g.text(QRectF(30, 28, 30, 30), "A", 22, soft if not g.tiled else ink)
    elif name == "bright":
        g.fill()
        p.drawEllipse(QPointF(32, 32), 11, 11)
        for i in range(8):
            a = math.radians(i * 45)
            g.line(32 + 19 * math.cos(a), 32 + 19 * math.sin(a), 32 + 26 * math.cos(a), 32 + 26 * math.sin(a))
    elif name == "negative":
        g.stroke(w=3.5)
        p.drawRoundedRect(r, 7, 7)
        half = QPainterPath()
        half.addRect(QRectF(32, 0, 32, 64))
        frame = QPainterPath()
        frame.addRoundedRect(r, 7, 7)
        p.fillPath(half & frame, QBrush(ink))
        g.fill(ink)
        p.drawPie(QRectF(20, 20, 24, 24), 90 * 16, 180 * 16)
        g.fill(hole)
        p.drawPie(QRectF(20, 20, 24, 24), 270 * 16, 180 * 16)
    elif name in ("flip_v", "flip_h"):    # a shape and its mirror image, either side of the axis
        if name == "flip_h":
            p.translate(32, 32)
            p.rotate(-90)
            p.translate(-32, -32)
        g.line(6, 32, 58, 32, soft, 3)
        g.fill()
        p.setPen(g.pen(w=3.5))
        p.drawPolygon(QPolygonF([QPointF(14, 24), QPointF(50, 24), QPointF(32, 6)]))
        g.stroke(w=3.5)
        p.drawPolygon(QPolygonF([QPointF(14, 40), QPointF(50, 40), QPointF(32, 58)]))
    elif name == "undo":
        g.stroke()
        path = QPainterPath(QPointF(16, 26))
        path.cubicTo(QPointF(26, 12), QPointF(52, 14), QPointF(50, 36))
        path.cubicTo(QPointF(48, 50), QPointF(30, 54), QPointF(22, 46))
        p.drawPath(path)
        g.arrow(QPointF(24, 30), QPointF(12, 22))
    elif name in ("rot_cw", "rot_ccw", "loop"):
        g.stroke()
        span = 300 if name == "loop" else 270
        start = 60 if name == "rot_cw" else 120
        sweep = -span if name == "rot_cw" else span
        p.drawArc(QRectF(12, 12, 40, 40), start * 16, sweep * 16)
        end_ang = math.radians(start + sweep)
        tip = QPointF(32 + 20 * math.cos(end_ang), 32 - 20 * math.sin(end_ang))
        tangent = end_ang + (math.pi / 2 if name != "rot_cw" else -math.pi / 2)
        g.arrow(QPointF(tip.x() - 6 * math.cos(tangent), tip.y() + 6 * math.sin(tangent)), tip)
        if name == "loop":
            g.fill(soft if not g.tiled else ink)
            p.drawPolygon(QPolygonF([QPointF(27, 23), QPointF(42, 32), QPointF(27, 41)]))
    elif name == "zoom":
        g.magnifier()
        g.line(17, 23, 33, 23, soft if not g.tiled else ink, 4)
        g.line(25, 15, 25, 31, soft if not g.tiled else ink, 4)
    elif name == "loupe":
        g.magnifier(_with_alpha(soft, 130) if not g.tiled else _with_alpha(ink, 110))
    elif name == "search":
        g.magnifier()
    elif name == "pan":
        for b in ((32, 5), (32, 59), (5, 32), (59, 32)):
            g.arrow(QPointF(32, 32), QPointF(*b), head=10)
    elif name == "length":    # a ruler
        p.translate(32, 32)
        p.rotate(-30)
        g.stroke(w=3.5)
        p.drawRoundedRect(QRectF(-28, -10, 56, 20), 4, 4)
        for i, x in enumerate((-18, -9, 0, 9, 18)):
            g.line(x, -10, x, -1 if i % 2 == 0 else -4, w=3)
    elif name == "angle":
        g.line(10, 54, 56, 54)
        g.line(10, 54, 46, 12)
        g.stroke(soft, 4)
        p.drawArc(QRectF(-12, 32, 44, 44), 0, 50 * 16)
    elif name == "cd":        # the disc and the cup in it
        g.stroke()
        p.drawEllipse(QPointF(32, 32), 24, 24)
        g.fill(soft if not g.tiled else ink)
        p.drawEllipse(QPointF(32, 32), 11, 12)
    elif name == "text":
        g.line(14, 14, 50, 14, w=6.5)
        g.line(32, 14, 32, 52, w=6.5)
    elif name == "arrow":
        g.arrow(QPointF(52, 52), QPointF(14, 14), head=15)
    elif name == "profile":
        g.line(6, 54, 58, 54, soft, 3)
        path = QPainterPath(QPointF(6, 44))
        for x, y in ((14, 32), (20, 38), (28, 12), (34, 42), (42, 26), (50, 32), (58, 20)):
            path.lineTo(QPointF(x, y))
        g.stroke(w=4)
        p.drawPath(path)
    elif name == "histogram":
        g.fill()
        for i, h in enumerate((16, 30, 46, 36, 22, 12)):
            p.drawRoundedRect(QRectF(7 + i * 8.6, 56 - h, 6.6, h), 2.5, 2.5)
    elif name == "equalize":
        g.fill()
        for i in range(6):
            p.drawRoundedRect(QRectF(7 + i * 8.6, 26, 6.6, 30), 2.5, 2.5)
        g.line(6, 16, 58, 16, soft, 3.5)
    elif name == "denoise":
        g.fill()
        for i, (x, y) in enumerate(((14, 16), (40, 12), (24, 30), (50, 34), (12, 46), (34, 50), (46, 22))):
            p.drawEllipse(QPointF(x, y), 3.5 if i % 2 else 2.5, 3.5 if i % 2 else 2.5)
        g.stroke(soft, 4)
        path = QPainterPath(QPointF(6, 40))
        path.cubicTo(QPointF(22, 28), QPointF(40, 50), QPointF(58, 36))
        p.drawPath(path)
    elif name == "original":  # the photo as it was taken: a frame with the fundus in it
        g.stroke(w=3.5)
        p.drawRoundedRect(QRectF(6, 10, 52, 44), 7, 7)
        g.fill()
        p.drawEllipse(QPointF(32, 32), 13, 13)
    elif name == "fit":       # the corners of the screen, and the photo filling it
        g.stroke()
        for (x, y), (dx, dy) in (((8, 8), (1, 1)), ((56, 8), (-1, 1)), ((8, 56), (1, -1)), ((56, 56), (-1, -1))):
            path = QPainterPath(QPointF(x + 15 * dx, y))
            path.lineTo(x + 5 * dx, y)
            path.quadTo(x, y, x, y + 5 * dy)
            path.lineTo(x, y + 15 * dy)
            p.drawPath(path)
        g.fill(soft if not g.tiled else _with_alpha(ink, 235))
        p.drawRoundedRect(QRectF(20, 20, 24, 24), 5, 5)
    elif name == "actual":
        g.text(r, "1:1", 28)
    elif name in ("prev", "next"):   # a chevron
        g.stroke(w=7.5)
        x0, x1 = (41, 21) if name == "prev" else (23, 43)
        path = QPainterPath(QPointF(x0, 11))
        path.lineTo(x1, 32)
        path.lineTo(x0, 53)
        p.drawPath(path)
    elif name == "simple":    # two photos side by side: OD | OS
        for x, c in ((5.0, QColor(64, 150, 255)), (34.0, QColor(255, 159, 28))):
            g.fill()
            p.drawRoundedRect(QRectF(x, 9, 25, 46), 6, 6)
            g.fill(c)
            p.drawEllipse(QPointF(x + 12.5, 32), 7, 7)
    elif name == "detail":    # one photo, large, looked at closely
        g.stroke(soft if not g.tiled else _with_alpha(ink, 190), 3.5)
        p.drawRoundedRect(QRectF(5, 7, 54, 48), 8, 8)
        g.stroke(w=4.5)
        p.setBrush(QBrush(_with_alpha(ink, 70)))
        p.drawEllipse(QPointF(28, 28), 11, 11)
        g.line(36.5, 36.5, 47, 47, w=6)
    elif name.startswith("multi"):   # a grid of photos (16 as 3 × 3: the cells stay readable)
        n = {"multi1": 1, "multi2": 2, "multi4": 2, "multi9": 3, "multi16": 3}.get(name, 2)
        g.fill()
        gap = 5.0
        cell = (50 - gap * (n - 1)) / n
        for i in range(n):
            for j in range(n):
                p.drawRoundedRect(QRectF(7 + i * (cell + gap), 7 + j * (cell + gap), cell, cell),
                                  cell * 0.24, cell * 0.24)
    elif name == "copy":
        g.stroke(w=3.5)
        p.drawRoundedRect(QRectF(8, 8, 32, 36), 5, 5)
        p.setBrush(QBrush(hole))
        p.drawRoundedRect(QRectF(22, 20, 32, 36), 5, 5)
    elif name == "save":      # a tray and an arrow down into it
        g.arrow(QPointF(32, 6), QPointF(32, 38), head=12)
        g.stroke()
        path = QPainterPath(QPointF(8, 40))
        path.lineTo(8, 50)
        path.quadTo(8, 56, 14, 56)
        path.lineTo(50, 56)
        path.quadTo(56, 56, 56, 50)
        path.lineTo(56, 40)
        p.drawPath(path)
    elif name == "record":
        g.stroke(w=3.5)
        p.drawRoundedRect(QRectF(6, 10, 40, 38), 6, 6)
        g.line(48, 38, 48, 60, soft, 5)
        g.line(37, 49, 59, 49, soft, 5)
    elif name == "print":
        g.stroke(w=3.5)
        p.drawRoundedRect(QRectF(18, 6, 28, 18), 3, 3)
        g.fill()
        p.drawRoundedRect(QRectF(5, 20, 54, 28), 7, 7)
        p.setPen(g.pen(w=3.5))
        p.setBrush(QBrush(hole))
        p.drawRoundedRect(QRectF(17, 36, 30, 22), 3, 3)
        g.fill(hole)
        p.drawEllipse(QPointF(49, 28), 2.6, 2.6)
    elif name == "edit":      # a pencil
        p.translate(32, 32)
        p.rotate(45)
        g.stroke(w=3.5)
        p.setBrush(QBrush(_with_alpha(ink, 70)))
        p.drawRoundedRect(QRectF(-8, -30, 16, 40), 3, 3)
        g.line(-8, -20, 8, -20, w=3)
        g.fill()
        p.setPen(g.pen(w=3.5))
        p.drawPolygon(QPolygonF([QPointF(-8, 12), QPointF(8, 12), QPointF(0, 30)]))
    elif name == "folder":
        g.stroke(w=4)
        path = QPainterPath(QPointF(6, 18))
        path.lineTo(24, 18)
        path.lineTo(30, 24)
        path.lineTo(58, 24)
        path.lineTo(58, 52)
        path.lineTo(6, 52)
        path.closeSubpath()
        p.setBrush(QBrush(_with_alpha(ink, 70)))
        p.drawPath(path)
    elif name == "import":
        g.arrow(QPointF(32, 6), QPointF(32, 40), head=12)
        g.line(8, 44, 8, 56, w=4)
        g.line(8, 56, 56, 56, w=4)
        g.line(56, 56, 56, 44, w=4)
    elif name in ("watch_on", "watch_off"):
        g.stroke()
        path = QPainterPath(QPointF(4, 32))
        path.cubicTo(QPointF(18, 12), QPointF(46, 12), QPointF(60, 32))
        path.cubicTo(QPointF(46, 52), QPointF(18, 52), QPointF(4, 32))
        p.drawPath(path)
        if g.tiled:
            g.fill()
        else:
            p.setBrush(QBrush(QColor(40, 150, 90) if name == "watch_on" else QColor(200, 70, 60)))
        p.drawEllipse(QPointF(32, 32), 9, 9)
    elif name == "settings":  # a gear
        g.stroke(w=6)
        p.drawEllipse(QPointF(32, 32), 13, 13)
        for i in range(8):
            a = math.radians(i * 45 + 22.5)
            g.line(32 + 19 * math.cos(a), 32 + 19 * math.sin(a), 32 + 25 * math.cos(a), 32 + 25 * math.sin(a), w=7)
    elif name == "log":       # a list: a dot and a line, three times
        for y in (16, 32, 48):
            g.fill()
            p.drawEllipse(QPointF(11, y), 4.2, 4.2)
            g.line(23, y, 55, y, w=5.5)
    elif name == "tools":     # sliders: the image processing controls
        for y, x in ((14, 40), (32, 20), (50, 44)):
            g.line(6, y, 58, y, soft if not g.tiled else _with_alpha(ink, 170), 4)
            p.setPen(g.pen(w=3.5))
            p.setBrush(QBrush(ink if g.tiled else hole))
            p.drawEllipse(QPointF(x, y), 7, 7)
    elif name == "annot_clear":   # an eraser over a line
        g.line(6, 57, 58, 57, soft, 3.5)
        g.stroke(w=3.5)
        p.setBrush(QBrush(_with_alpha(ink, 70)))
        p.drawPolygon(QPolygonF([QPointF(9, 39), QPointF(34, 10), QPointF(55, 28), QPointF(30, 54),
                                 QPointF(20, 54)]))
        p.setBrush(QBrush(ink))
        p.drawPolygon(QPolygonF([QPointF(9, 39), QPointF(22, 25), QPointF(41, 43), QPointF(30, 54),
                                 QPointF(20, 54)]))
    elif name == "exit":      # the power symbol
        g.stroke(w=6.5)
        p.drawArc(QRectF(10, 12, 44, 44), 125 * 16, 290 * 16)
        g.line(32, 6, 32, 30, w=6.5)
    elif name == "discpair":  # two optic discs side by side
        for cx in (17.0, 47.0):
            g.disc(cx, 32, 13, 5.5)
    elif name == "glaucoma":  # one disc with a large cup
        g.stroke()
        p.drawEllipse(QPointF(32, 32), 24, 25)
        g.fill(_with_alpha(ink, 90))
        p.drawEllipse(QPointF(32, 32), 24, 25)
        g.fill()
        p.drawEllipse(QPointF(32, 33), 13, 15)
    elif name == "montage":   # three overlapping photos of one eye, put together into one
        for cx, cy in ((20.0, 41.0), (44.0, 41.0), (32.0, 21.0)):
            g.stroke(w=3.5)
            p.setBrush(QBrush(_with_alpha(ink, 95)))
            p.drawEllipse(QPointF(cx, cy), 15, 15)
    elif name == "eye3d":     # the eyeball: a globe with its meridians, looking to the side
        g.stroke()
        p.drawEllipse(QPointF(32, 32), 25, 25)
        g.stroke(soft if not g.tiled else _with_alpha(ink, 190), 3)
        p.drawArc(QRectF(7, 21, 50, 22), 180 * 16, 180 * 16)
        p.drawArc(QRectF(20, 7, 24, 50), 90 * 16, 180 * 16)
        g.fill()
        p.drawEllipse(QPointF(43, 27), 8, 8)
    else:
        g.text(r, name[:2].upper(), 26)


def _tile(p: QPainter, top: QColor, bottom: QColor) -> None:
    """The rounded square under a glyph: a gradient, a light edge along the top, a soft sheen."""
    shape = QPainterPath()
    shape.addRoundedRect(TILE, TILE_RADIUS, TILE_RADIUS)
    grad = QLinearGradient(0, TILE.top(), 0, TILE.bottom())
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bottom)
    p.fillPath(shape, QBrush(grad))
    sheen = QLinearGradient(0, TILE.top(), 0, TILE.center().y())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 46))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(shape, QBrush(sheen))
    edge = QLinearGradient(0, TILE.top(), 0, TILE.bottom())
    edge.setColorAt(0.0, QColor(255, 255, 255, 120))
    edge.setColorAt(0.35, QColor(255, 255, 255, 0))
    edge.setColorAt(1.0, QColor(0, 0, 0, 40))
    p.setPen(QPen(QBrush(edge), 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(TILE.adjusted(0.6, 0.6, -0.6, -0.6), TILE_RADIUS - 0.6, TILE_RADIUS - 0.6)


def tile_colors(name: str) -> tuple[QColor, QColor]:
    """The gradient (top, bottom) of the tile under glyph ``name``."""
    key = "purple" if name.startswith("multi") else TILE_OF.get(name, "blue")
    top, bottom = TILES[key]
    return QColor(top), QColor(bottom)


@lru_cache(maxsize=None)
def icon(name: str, plain: bool = False) -> QIcon:
    pm = QPixmap(S * PX, S * PX)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(PX, PX)
    if plain:
        _draw(name, _Glyph(p, INK, ACCENT, BG, 1.0, tiled=False))
    else:
        top, bottom = tile_colors(name)
        _tile(p, top, bottom)
        mid = QColor((top.red() + bottom.red()) // 2, (top.green() + bottom.green()) // 2,
                     (top.blue() + bottom.blue()) // 2)
        # the glyph a little below the middle of the tile is where the eye puts the middle
        p.translate(32, 32.5)
        p.scale(GLYPH_SCALE, GLYPH_SCALE)
        p.translate(-32, -32)
        white = QColor(255, 255, 255)
        _draw(name, _Glyph(p, white, _with_alpha(white, 175), mid, 1.3, tiled=True))
    p.end()
    return QIcon(pm)
