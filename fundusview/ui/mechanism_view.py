"""기전 그림: how a retinal disease comes about, step by step (``diseases.MECHANISMS``) — one picture with a
card per step (a number, a title, a drawing, the words) and arrows between the cards.

The drawings, each in a 360 × 270 box (scaled to the card):

* ``vessel:*`` — a retinal vessel seen close up from the side: its wall, blood cells, the tissue round it
  (sugar and lost pericytes, a microaneurysm leaking, a closed capillary, new vessels, an artery pressing a
  vein, a clot, an embolus at a branch, a thick-walled artery, a burst vessel, a carotid plaque);
* ``eye:*`` — the whole eye cut through from the side (light focused on the macula, the aqueous that cannot
  drain, the vitreous coming away, fluid under the retina, a long myopic eye, pressure from the brain);
* ``nerve:*`` and ``section:*`` — the optic nerve head and the retina cut through (``disease_art.Section``)
  with arrows and labels on them;
* ``cells:*`` — photoreceptors (rods, cones) on the RPE, close up.

All of it is drawn, the same every time.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF

from .. import disease_art as A
from .. import diseases as D
from . import theme
from .disease_view import INK, INK2, M, W, _badge, _font, _wrapped
from .image_view import from_qimage, to_qimage

AW, AH = 360.0, 270.0                 # a drawing's box (design units)
TISSUE = QColor(240, 196, 182)
WALL = QColor(232, 148, 138)
BLOOD = QColor(168, 26, 34)
VBLOOD = QColor(118, 18, 30)
RBC = QColor(214, 56, 56)
EXU = QColor(250, 220, 110)
FLUID = QColor(118, 170, 222)
VEGF = QColor(80, 205, 120)
PRESS = QColor(255, 80, 70)
LIGHT = QColor(255, 226, 92)
WHITE = QColor(250, 248, 244)


def _c(rgb) -> QColor:
    return QColor(*[int(v) for v in rgb])


# -- drawing helpers -------------------------------------------------------------------------------
def _arrow(p: QPainter, a, b, color: QColor = PRESS, width: float = 3.5, head: float = 11) -> None:
    a, b = QPointF(*a), QPointF(*b)
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    tip = b
    base = QPointF(b.x() - head * 0.8 * math.cos(ang), b.y() - head * 0.8 * math.sin(ang))
    p.drawLine(a, base)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    left = QPointF(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45))
    right = QPointF(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))
    p.drawPolygon(QPolygonF([tip, left, right]))


def _tag(p: QPainter, x: float, y: float, text: str, at=None, px: float = 12.5) -> None:
    """A label centred on (x, y); ``at``: a point it points to (a line and a dot)."""
    p.setFont(_font(px, True))
    fm = QFontMetricsF(p.font())
    tw, th = fm.horizontalAdvance(text) + 12, fm.height() + 4
    box = QRectF(x - tw / 2, y - th / 2, tw, th)
    box.moveLeft(min(max(box.left(), 3), AW - tw - 3))
    box.moveTop(min(max(box.top(), 3), AH - th - 3))
    if at is not None:
        q = QPointF(*at)
        near = QPointF(min(max(q.x(), box.left()), box.right()), min(max(q.y(), box.top()), box.bottom()))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.4))
        p.drawLine(near, q)
        p.setPen(QPen(QColor(0, 0, 0, 150), 1))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(q, 3.2, 3.2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(18, 18, 20, 215))
    p.drawRoundedRect(box, 6, 6)
    p.setPen(INK)
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


def _smooth(points) -> QPainterPath:
    pts = [QPointF(*q) for q in points]
    path = QPainterPath(pts[0])
    if len(pts) == 2:
        path.lineTo(pts[1])
        return path
    for i in range(1, len(pts) - 1):
        mid = (pts[i] + pts[i + 1]) / 2
        path.quadTo(pts[i], mid)
    path.lineTo(pts[-1])
    return path


def _tube(p: QPainter, points, r: float, wall: float, blood: QColor = BLOOD, wall_col: QColor = WALL,
          cells: int = 14, seed: int = 1, rbc: QColor = RBC) -> QPainterPath:
    """A vessel along ``points``: the wall, the blood, the red cells in it."""
    path = _smooth(points)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(wall_col.darker(115), 2 * r + 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.setPen(QPen(wall_col, 2 * r, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    if r - wall > 0.5:
        p.setPen(QPen(blood, 2 * (r - wall), Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    rng = np.random.default_rng(seed)
    lum = r - wall
    for k in range(cells):
        t = (k + rng.uniform(0.1, 0.9)) / cells
        pt = path.pointAtPercent(t)
        ang = path.angleAtPercent(t)
        off = rng.uniform(-0.45, 0.45) * lum
        rad = math.radians(ang + 90)
        c = QPointF(pt.x() + off * math.cos(rad), pt.y() - off * math.sin(rad))
        p.save()
        p.translate(c)
        p.rotate(-ang + rng.uniform(-25, 25))
        p.setPen(QPen(rbc.darker(130), 1))
        p.setBrush(rbc)
        p.drawEllipse(QPointF(0, 0), lum * 0.42, lum * 0.26)
        p.setBrush(rbc.darker(118))
        p.drawEllipse(QPointF(0, 0), lum * 0.18, lum * 0.10)
        p.restore()
    return path


def _tissue(p: QPainter, color: QColor = TISSUE, seed: int = 3) -> None:
    p.fillRect(QRectF(0, 0, AW, AH), color)
    rng = np.random.default_rng(seed)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color.darker(108))
    for _ in range(60):                               # cell nuclei, faint
        p.drawEllipse(QPointF(rng.uniform(0, AW), rng.uniform(0, AH)), rng.uniform(2.5, 4.5), rng.uniform(2, 3.5))


def _dots(p: QPainter, cx, cy, n, spread, r, color: QColor, seed=5) -> None:
    rng = np.random.default_rng(seed)
    p.setPen(QPen(color.darker(140), 0.8))
    p.setBrush(color)
    for _ in range(n):
        p.drawEllipse(QPointF(cx + rng.normal(0, spread), cy + rng.normal(0, spread * 0.7)), r * rng.uniform(0.6, 1.2),
                      r * rng.uniform(0.6, 1.2))


def _fluffy(p: QPainter, cx, cy, s, color: QColor = WHITE) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    c = QColor(color)
    for k, (dx, dy, f) in enumerate(((0, 0, 1.0), (-0.6, 0.15, 0.7), (0.6, 0.1, 0.75), (0.1, -0.45, 0.65), (0.2, 0.45, 0.6))):
        c.setAlpha(200 if k == 0 else 170)
        p.setBrush(c)
        p.drawEllipse(QPointF(cx + dx * s, cy + dy * s), s * f * 0.75, s * f * 0.6)


def _hexagon(p: QPainter, cx, cy, r, color: QColor) -> None:
    pts = [QPointF(cx + r * math.cos(math.radians(60 * k + 30)), cy + r * math.sin(math.radians(60 * k + 30))) for k in range(6)]
    p.setPen(QPen(color.darker(160), 1.2))
    p.setBrush(color)
    p.drawPolygon(QPolygonF(pts))


def _cross(p: QPainter, cx, cy, s=9, color: QColor = PRESS) -> None:
    p.setPen(QPen(color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
    p.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))


def _variable_vessel(p: QPainter, x0, x1, y, radius, blood: QColor, wall_col: QColor = WALL, seed: int = 4) -> None:
    """A straight vessel whose radius changes along it (``radius(x)``), with its blood cells."""
    xs = np.linspace(x0, x1, 120)
    for col, inset in ((wall_col.darker(115), -1.0), (wall_col, 0.0), (blood, 6.0)):
        top = [QPointF(x, y - max(0.0, radius(x) - inset)) for x in xs]
        bot = [QPointF(x, y + max(0.0, radius(x) - inset)) for x in xs[::-1]]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPolygon(QPolygonF(top + bot))
    rng = np.random.default_rng(seed)
    rbc = QColor(170, 40, 46)
    for x in np.arange(x0 + 8, x1, 17):
        lum = radius(x) - 6
        if lum < 6:
            continue
        p.save()
        p.translate(QPointF(x + rng.uniform(-4, 4), y + rng.uniform(-0.45, 0.45) * lum))
        p.rotate(rng.uniform(-25, 25))
        p.setPen(QPen(rbc.darker(130), 1))
        p.setBrush(rbc)
        p.drawEllipse(QPointF(0, 0), lum * 0.42, lum * 0.26)
        p.restore()


# -- vessels --------------------------------------------------------------------------------------
def _vessel(p: QPainter, state: str) -> None:
    _tissue(p)
    if state == "sugar":
        _tube(p, [(-10, 140), (180, 128), (370, 140)], 46, 11, cells=12, seed=2)
        rng = np.random.default_rng(4)
        for k in range(11):                           # glucose in the blood
            _hexagon(p, rng.uniform(20, 340), 132 + rng.uniform(-18, 18), 6.5, QColor(255, 255, 255, 230))
        for k, x in enumerate((35, 95, 155, 215, 275, 335)):     # pericytes on the wall; some gone
            for top in (True, False):
                y = (128 + (140 - 128) * abs(x - 180) / 190) + (-50 if top else 50)
                gone = (top and x in (155, 275)) or (not top and x == 215)
                if gone:
                    p.setPen(QPen(QColor(120, 90, 140), 1.5, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    p.setPen(QPen(QColor(110, 70, 130), 1.2))
                    p.setBrush(QColor(176, 130, 196))
                p.drawEllipse(QPointF(x, y), 15, 6.5)
        _tag(p, 95, 22, "혈관주위세포", at=(95, 78))
        _tag(p, 262, 22, "줄어든 혈관주위세포", at=(275, 78))
        _tag(p, 178, 245, "혈당(포도당) ↑ · 약해진 벽", at=(200, 150))
    elif state == "leak":
        _tube(p, [(-10, 165), (180, 160), (370, 168)], 40, 10, cells=12, seed=3)
        p.setPen(QPen(WALL.darker(115), 2))
        p.setBrush(WALL)
        p.drawEllipse(QPointF(175, 106), 32, 30)       # the microaneurysm
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BLOOD)
        p.drawEllipse(QPointF(175, 110), 22, 22)
        p.drawRect(QRectF(160, 112, 30, 30))
        _dots(p, 80, 70, 14, 16, 4.2, EXU, seed=6)
        _dots(p, 300, 82, 10, 14, 4.0, EXU, seed=7)
        _dots(p, 240, 60, 7, 12, 5.0, RBC, seed=8)
        p.setBrush(QColor(FLUID.red(), FLUID.green(), FLUID.blue(), 150))
        for dx, dy in ((-40, 55), (-55, 30), (55, 40), (30, 10)):
            p.drawEllipse(QPointF(175 + dx, 106 + dy - 40), 7, 9)
        for a, b in (((150, 128), (115, 92)), ((205, 125), (235, 92)), ((260, 140), (292, 108))):
            _arrow(p, a, b, QColor(255, 255, 255, 220), 2.5, 9)
        _tag(p, 175, 50, "미세혈관류", at=(175, 85))
        _tag(p, 70, 30, "경성 삼출물", at=(80, 66))
        _tag(p, 292, 30, "새어 나온 피 (출혈)", at=(244, 58))
        _tag(p, 120, 238, "새어 나온 물 → 부종")
    elif state == "blocked":
        p.fillRect(QRectF(205, 0, AW - 205, AH), QColor(196, 196, 210))
        _tissue_overlay = QColor(150, 160, 190, 90)
        p.fillRect(QRectF(205, 0, AW - 205, AH), _tissue_overlay)
        _tube(p, [(-10, 140), (190, 140)], 40, 10, cells=8, seed=4)
        _tube(p, [(205, 140), (370, 140)], 30, 9, blood=QColor(230, 196, 196), wall_col=QColor(222, 190, 186), cells=0)
        p.setPen(QPen(QColor(150, 120, 110), 1.5))
        p.setBrush(QColor(246, 236, 220))
        p.drawRoundedRect(QRectF(186, 104, 26, 72), 10, 10)    # the plug
        _fluffy(p, 290, 62, 34)
        p.setFont(_font(20, True))
        for x, y in ((250, 215), (320, 205)):
            p.setPen(QColor(90, 100, 140))
            p.drawText(QPointF(x - 12, y + 7), "O₂")
            _cross(p, x, y, 13, QColor(220, 60, 60, 200))
        _tag(p, 199, 38, "막힌 곳", at=(199, 104))
        _tag(p, 290, 112, "면화반", at=(290, 82))
        _tag(p, 110, 235, "피가 가지 않음 → 산소 부족 (허혈)", px=12)
    elif state == "vegf":
        p.fillRect(QRectF(0, 0, AW, 120), QColor(205, 205, 222))
        _tube(p, [(-10, 215), (180, 212), (370, 218)], 36, 9, cells=10, seed=5)
        rng = np.random.default_rng(9)
        for k, x0 in enumerate((110, 150, 195, 240, 270)):
            pts = [(x0, 180)]
            for j in range(6):
                pts.append((pts[-1][0] + rng.normal(0, 12), pts[-1][1] - 20))
            path = _smooth(pts)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(150, 20, 28), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor(226, 66, 66), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            if k in (1, 3):
                _dots(p, pts[-1][0], pts[-1][1] - 4, 6, 7, 4, RBC, seed=k)
        rng = np.random.default_rng(10)
        p.setPen(QPen(VEGF.darker(150), 1))
        p.setBrush(VEGF)
        for _ in range(16):
            p.drawEllipse(QPointF(rng.uniform(15, 345), rng.uniform(20, 110)), 4, 4)
        _arrow(p, (60, 60), (100, 150), VEGF.darker(115), 3, 10)
        _arrow(p, (320, 50), (280, 150), VEGF.darker(115), 3, 10)
        _tag(p, 70, 22, "VEGF (자라라는 신호)")
        _tag(p, 255, 22, "산소가 모자란 망막")
        _tag(p, 210, 150, "약한 신생혈관", at=(196, 140))
        _tag(p, 270, 95, "쉽게 터짐", at=(240, 82))
    elif state in ("crossing", "backup"):
        if state == "crossing":
            _variable_vessel(p, -10, 370, 160, lambda x: 32 - 17 * math.exp(-((x - 180) / 34) ** 2), VBLOOD)
            c = (180, 150)
        else:
            _variable_vessel(p, -10, 118, 168, lambda x: 28 - 14 * math.exp(-((x - 92) / 26) ** 2), VBLOOD)
            _tube(p, [(110, 168), (170, 150), (230, 186), (290, 150), (370, 172)], 40, 8, blood=VBLOOD, cells=10, seed=6,
                  rbc=QColor(170, 40, 46))
            c = (92, 158)
        # the artery crossing over the vein (a thick, stiff wall)
        x0 = c[0]
        _tube(p, [(x0 - 110, -10), (x0, c[1] - 8), (x0 + 110, 280)], 26, 10, blood=QColor(204, 42, 42),
              wall_col=QColor(246, 214, 200), cells=6, seed=7)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.6, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(*c), 58, 50)
        if state == "crossing":
            _arrow(p, (180, 84), (180, 128), PRESS, 4, 12)
            _tag(p, 285, 40, "굳고 두꺼운 동맥", at=(225, 70))
            _tag(p, 300, 222, "눌린 정맥", at=(205, 168))
            _tag(p, 75, 232, "같은 막에 싸인 교차 부위", at=(140, 185))
        else:
            p.setPen(QPen(QColor(70, 20, 20), 1))
            p.setBrush(QColor(90, 24, 28))
            p.drawRoundedRect(QRectF(80, 154, 30, 26), 8, 8)  # the clot
            rng = np.random.default_rng(12)
            for _ in range(9):                         # blood out of the swollen vein
                x, y = rng.uniform(140, 350), rng.choice([rng.uniform(70, 105), rng.uniform(205, 250)])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(170, 24, 30, 220))
                p.drawEllipse(QPointF(x, y), rng.uniform(10, 18), rng.uniform(4, 7))
            _arrow(p, (340, 120), (250, 120), QColor(255, 255, 255, 230), 2.5, 9)
            _cross(p, 132, 128, 8, QColor(255, 255, 255))
            _tag(p, 95, 228, "혈전", at=(95, 168))
            _tag(p, 260, 30, "피가 빠지지 못해 부푼 정맥", at=(260, 140))
            _tag(p, 300, 250, "새어 나온 피", at=(300, 230))
    elif state == "embolus":
        _tube(p, [(-10, 140), (150, 140), (240, 70), (370, 30)], 30, 9, cells=6, seed=8)
        _tube(p, [(150, 140), (240, 200), (370, 236)], 30, 9, cells=10, seed=9)
        p.fillRect(QRectF(205, 0, AW - 205, 110), QColor(246, 240, 232, 150))
        _tube(p, [(212, 96), (240, 70), (370, 30)], 21, 1, blood=QColor(238, 214, 210), wall_col=QColor(232, 200, 192), cells=0)
        _tube(p, [(-10, 140), (150, 140)], 30, 9, cells=6, seed=8)
        poly = QPolygonF([QPointF(x, y) for x, y in ((190, 108), (205, 94), (218, 100), (214, 116), (200, 122))])
        p.setPen(QPen(QColor(200, 170, 60), 1.5))
        p.setBrush(QColor(252, 236, 150))
        p.drawPolygon(poly)
        _arrow(p, (70, 112), (140, 112), QColor(255, 255, 255, 230), 2.5, 9)
        _tag(p, 150, 40, "색전 (걸린 조각)", at=(205, 108))
        _tag(p, 300, 110, "피가 가지 않는 가지")
        _tag(p, 290, 250, "막히지 않은 가지", at=(300, 220))
    elif state == "source":
        p.fillRect(QRectF(0, 0, AW, AH), QColor(236, 200, 186))
        _tube(p, [(-10, 190), (370, 190)], 62, 14, cells=16, seed=10)
        path = QPainterPath()
        path.moveTo(60, 141)
        path.cubicTo(110, 158, 190, 160, 250, 141)
        path.closeSubpath()
        p.setPen(QPen(QColor(200, 170, 60), 1.5))
        p.setBrush(QColor(250, 226, 120))
        p.drawPath(path)                               # the plaque on the wall
        p.drawEllipse(QPointF(262, 164), 9, 7)        # a piece breaking off
        _arrow(p, (275, 158), (318, 92), QColor(255, 255, 255, 235), 3, 11)
        p.setPen(QPen(QColor(60, 60, 60), 2))       # the eye it goes to
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(322, 48), 28, 18)
        p.setBrush(QColor(90, 140, 190))
        p.drawEllipse(QPointF(322, 48), 11, 11)
        p.setBrush(QColor(20, 20, 20))
        p.drawEllipse(QPointF(322, 48), 4.5, 4.5)
        _tag(p, 140, 108, "죽상경화 찌꺼기 (플라크)", at=(150, 150))
        _tag(p, 230, 82, "떨어진 조각 → 눈으로")
        _tag(p, 70, 250, "경동맥 (목의 큰 혈관)")
    elif state == "thick":
        _tube(p, [(-10, 64), (370, 64)], 28, 6, cells=8, seed=11)
        _tube(p, [(-10, 190), (370, 190)], 44, 25, wall_col=QColor(244, 206, 192), cells=8, seed=12)
        p.setPen(QPen(QColor(220, 170, 156), 1.2))
        p.drawLine(QPointF(0, 190 - 32), QPointF(AW, 190 - 32))
        p.drawLine(QPointF(0, 190 + 32), QPointF(AW, 190 + 32))
        for x in (70, 180, 290):
            _arrow(p, (x, 190), (x, 168), PRESS, 3, 9)
            _arrow(p, (x, 190), (x, 212), PRESS, 3, 9)
        _tag(p, 72, 18, "정상 동맥")
        _tag(p, 250, 18, "높은 혈압이 오래가면 ↓")
        _tag(p, 120, 125, "두꺼워진 벽", at=(130, 154))
        _tag(p, 270, 252, "좁아진 통로", at=(250, 196))
    elif state == "burst":
        _tube(p, [(-10, 205), (370, 205)], 42, 20, wall_col=QColor(244, 206, 192), cells=8, seed=13)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TISSUE)
        p.drawRect(QRectF(160, 160, 28, 26))           # the break in the wall
        p.setBrush(BLOOD)
        p.drawRect(QRectF(164, 170, 20, 20))
        rng = np.random.default_rng(14)
        for _ in range(16):
            x, y = 174 + rng.normal(0, 22), 140 - abs(rng.normal(0, 40))
            p.setBrush(QColor(176, 26, 32, 220))
            p.drawEllipse(QPointF(x, y), rng.uniform(4, 9), rng.uniform(3, 6))
        _fluffy(p, 300, 70, 32)
        _dots(p, 70, 80, 12, 14, 4, EXU, seed=15)
        p.setBrush(QColor(FLUID.red(), FLUID.green(), FLUID.blue(), 150))
        for x, y in ((240, 135), (110, 135), (255, 110)):
            p.drawEllipse(QPointF(x, y), 7, 9)
        for x in (60, 290):
            _arrow(p, (x, 205), (x, 178), PRESS, 3, 9)
        _tag(p, 174, 30, "터진 혈관 → 출혈", at=(174, 110))
        _tag(p, 300, 120, "면화반", at=(300, 90))
        _tag(p, 62, 42, "경성 삼출물", at=(70, 76))
        _tag(p, 175, 255, "혈압이 갑자기 아주 높을 때")


# -- the eye from the side ----------------------------------------------------------------------------
def _eye_body(p: QPainter, cx: float, cy: float, rx: float, ry: float, nerve=True) -> None:
    """Sclera, choroid, retina, vitreous; the cornea, iris and lens in front (left); the nerve behind."""
    if nerve:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(236, 220, 196))
        p.drawRoundedRect(QRectF(cx + rx - 8, cy - 2, AW - (cx + rx) + 20, 34), 10, 10)
        p.setBrush(QColor(214, 190, 166))
        p.drawRect(QRectF(cx + rx - 8, cy + 10, AW - (cx + rx) + 20, 4))
    p.setPen(QPen(QColor(200, 196, 190), 2))
    p.setBrush(QColor(246, 244, 238))
    p.drawEllipse(QPointF(cx, cy), rx, ry)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(178, 52, 46))
    p.drawEllipse(QPointF(cx, cy), rx - 7, ry - 7)
    p.setBrush(QColor(238, 160, 150))
    p.drawEllipse(QPointF(cx, cy), rx - 11, ry - 11)
    p.setBrush(QColor(206, 222, 236))
    p.drawEllipse(QPointF(cx, cy), rx - 15, ry - 15)
    # the front: cornea, aqueous, iris, lens, ciliary body
    front = cx - rx
    p.setBrush(QColor(206, 222, 236))
    p.setPen(QPen(QColor(150, 190, 220), 2.5))
    p.drawChord(QRectF(front - 22, cy - ry * 0.52, 60, ry * 1.04), 90 * 16, 180 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(206, 222, 236))
    p.drawRect(QRectF(front + 3, cy - ry * 0.5, 22, ry * 1.0))
    p.setBrush(QColor(110, 80, 60))
    p.drawRoundedRect(QRectF(front + 22, cy - ry * 0.55, 6, ry * 0.36), 3, 3)
    p.drawRoundedRect(QRectF(front + 22, cy + ry * 0.19, 6, ry * 0.36), 3, 3)
    p.setBrush(QColor(176, 90, 80))
    p.drawEllipse(QPointF(front + 32, cy - ry * 0.58), 8, 12)
    p.drawEllipse(QPointF(front + 32, cy + ry * 0.58), 8, 12)
    p.setPen(QPen(QColor(200, 190, 150), 1.5))
    p.setBrush(QColor(250, 240, 200, 230))
    p.drawEllipse(QPointF(front + 44, cy), 13, ry * 0.36)


def _eye(p: QPainter, state: str) -> None:
    p.fillRect(QRectF(0, 0, AW, AH), QColor(34, 38, 48))
    cx, cy, R = 170.0, 135.0, 110.0
    if state == "long":
        p.setPen(QPen(QColor(255, 255, 255, 150), 1.6, Qt.PenStyle.DashLine))
        _eye_body(p, cx + 25, cy, R + 25, R - 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 190), 2, Qt.PenStyle.DashLine))
        p.drawEllipse(QPointF(cx, cy), R - 8, R - 8)
        front = cx - R
        for y in (cy - 40, cy, cy + 40):
            p.setPen(QPen(LIGHT, 2))
            p.drawLine(QPointF(0, y), QPointF(front + 44, y))
            p.drawLine(QPointF(front + 44, y), QPointF(cx + R - 20, cy))
            p.drawLine(QPointF(cx + R - 20, cy), QPointF(cx + 2 * R - 12, cy + (y - cy) * 0.55))
        _arrow(p, (cx + 2 * R - 30, cy - 70), (cx + 2 * R - 8, cy - 70), QColor(255, 255, 255), 3, 9)
        _tag(p, cx + R - 20, cy - 108, "정상 길이 (점선)", at=(cx + R - 10, cy - 60))
        _tag(p, 120, 254, "초점이 망막 앞에 맺힘", at=(cx + R - 20, cy))
        _tag(p, 300, 238, "늘어나 얇아진 벽", at=(cx + 2 * R - 20, cy + 50))
        return
    if state == "brain":
        ecx, ecy, er = 70.0, 168.0, 56.0
        p.setPen(QPen(QColor(250, 210, 200), 1.5))
        p.setBrush(QColor(242, 196, 190))
        p.drawRoundedRect(QRectF(214, 16, 150, 200), 70, 70)        # the brain
        p.setPen(QPen(QColor(200, 140, 140), 2))
        for k in range(5):
            p.drawArc(QRectF(230 + 12 * k, 40 + 20 * k, 90, 50), 20 * 16, 140 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FLUID)
        p.drawRect(QRectF(ecx + er - 6, ecy - 14, 230 - (ecx + er), 28))   # the sheath with CSF
        _eye_body(p, ecx, ecy, er, er, nerve=False)
        p.setBrush(QColor(236, 220, 196))
        p.drawRect(QRectF(ecx + er - 6, ecy - 8, 230 - (ecx + er), 16))
        p.setBrush(QColor(246, 176, 160))
        p.drawEllipse(QPointF(ecx + er - 13, ecy), 9, 12)            # the swollen disc
        for (x, y), (dx, dy) in (((290, 110), (0, -36)), ((290, 110), (36, 10)), ((290, 110), (-30, 30)), ((290, 110), (14, 44))):
            _arrow(p, (x, y), (x + dx, y + dy), PRESS, 3.5, 10)
        for x in (205, 165):
            _arrow(p, (x, ecy - 22), (x - 30, ecy - 22), QColor(255, 255, 255, 230), 2.5, 8)
            _arrow(p, (x, ecy + 22), (x - 30, ecy + 22), QColor(255, 255, 255, 230), 2.5, 8)
        _tag(p, 290, 236, "뇌압 ↑")
        _tag(p, 150, 120, "시신경 집의 뇌척수액", at=(170, ecy - 12))
        _tag(p, 60, 252, "부은 유두", at=(ecx + er - 13, ecy + 10))
        return
    _eye_body(p, cx, cy, R, R)
    back = cx + R
    if state == "light":
        for y in (cy - 46, cy, cy + 46):
            p.setPen(QPen(LIGHT, 2.2))
            p.drawLine(QPointF(0, y), QPointF(cx - R + 44, y))
            p.drawLine(QPointF(cx - R + 44, y), QPointF(back - 14, cy))
        p.setBrush(LIGHT)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(back - 14, cy), 5, 5)
        _tag(p, 34, 40, "각막", at=(cx - R - 12, cy - 40))
        _tag(p, 110, 245, "수정체", at=(cx - R + 44, cy + 30))
        _tag(p, 270, 30, "망막 (황반)", at=(back - 14, cy - 4))
        _tag(p, 320, 200, "시신경", at=(back + 30, cy + 16))
    elif state == "iop":
        front = cx - R
        for sgn in (-1, 1):
            path = QPainterPath(QPointF(front + 34, cy + sgn * R * 0.58))
            path.cubicTo(QPointF(front + 30, cy + sgn * 20), QPointF(front + 10, cy + sgn * 10),
                         QPointF(front + 6, cy + sgn * R * 0.42))
            p.setPen(QPen(QColor(120, 200, 255), 2.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            _cross(p, front + 8, cy + sgn * R * 0.47, 6)
        for ang in (-50, -25, 0, 25, 50):
            a = math.radians(ang)
            _arrow(p, (cx + 20 * math.cos(a), cy + 20 * math.sin(a)), (cx + (R - 26) * math.cos(a), cy + (R - 26) * math.sin(a)),
                   PRESS, 3.2, 10)
        _tag(p, 62, 22, "배출구가 막힘", at=(front + 8, cy - R * 0.47))
        _tag(p, 72, 250, "방수 (눈 속 물)", at=(front + 20, cy + 30))
        _tag(p, 168, 82, "안압 ↑")
        _tag(p, 318, 210, "눌리는 시신경", at=(back - 6, cy + 10))
    elif state in ("pvd", "rdfluid"):
        if state == "pvd":
            p.setPen(QPen(QColor(160, 200, 240), 1.5))
            p.setBrush(QColor(150, 190, 232, 150))
            p.drawEllipse(QPointF(cx - 18, cy + 6), R - 40, R - 34)    # the shrunken gel
            p.setPen(QPen(QColor(150, 190, 232), 2))
            for k in range(4):
                p.drawLine(QPointF(cx + 44 + 6 * k, cy - 66 + 4 * k), QPointF(cx + 62 + 6 * k, cy - 92 + 2 * k))
            rng = np.random.default_rng(3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(60, 60, 80, 200))
            for _ in range(7):
                p.drawEllipse(QPointF(cx - 30 + rng.normal(0, 30), cy + rng.normal(0, 30)), 3, 2)
            _arrow(p, (cx + 54, cy - 70), (cx + 30, cy - 40), QColor(255, 255, 255), 2.5, 9)
            _tag(p, 130, 250, "줄어든 유리체", at=(cx - 18, cy + 60))
            _tag(p, 310, 238, "떨어진 틈 (묽은 물)", at=(back - 26, cy + 30))
            _tag(p, 290, 22, "아직 붙어 당기는 곳", at=(cx + 66, cy - 92))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(FLUID)
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), R - 12, R - 12)
            inner = QPainterPath()
            inner.addEllipse(QPointF(cx + 6, cy + 30), R - 14, R - 5)
            p.drawPath(path.subtracted(inner).intersected(_quadrant(cx, cy, R)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(238, 160, 150), 5))
            p.drawArc(QRectF(cx + 6 - (R - 14), cy + 30 - (R - 5), 2 * (R - 14), 2 * (R - 5)), 22 * 16, 82 * 16)
            _arrow(p, (cx + 14, cy - 60), (cx + 40, cy - 92), QColor(255, 255, 255), 2.5, 9)
            _tag(p, 90, 22, "열공", at=(cx + 30, cy - 86))
            _tag(p, 318, 34, "망막 밑으로 들어간 물", at=(cx + 80, cy - 62))
            _tag(p, 150, 252, "들뜬 망막 — 시야가 커튼처럼 가려짐", px=12)


def _quadrant(cx, cy, R) -> QPainterPath:
    q = QPainterPath()
    q.addRect(QRectF(cx - 10, cy - R - 10, R + 20, R * 0.9))
    return q


# -- the optic nerve head, the retina (sections) ------------------------------------------------------
_SEC_W, _SEC_H = 480, 360


def _section_image(state: str) -> tuple[np.ndarray, A.Section]:
    kind, key = state.split(":")
    through = "disc" if kind == "nerve" else "fovea"
    s = A.Section(width=_SEC_W, height=_SEC_H, through=through)
    x = s.x
    g = lambda c, w: np.exp(-((x - c) / w) ** 2).astype(np.float32)   # noqa: E731
    if through == "fovea":                     # close up: a wider, gentler foveal pit
        pit = g(0.5, 0.10)
        shoulder = np.exp(-((np.abs(x - 0.5) - 0.17) / 0.06) ** 2).astype(np.float32)
        s.inner_t = (0.15 * (1 - 0.8 * pit) + 0.025 * shoulder).astype(np.float32)
        s.nfl_t = ((0.028 + 0.04 * np.clip((x - 0.5) / 0.5, 0, 1)) * (1 - 0.9 * pit)).astype(np.float32)
    if kind == "nerve":
        s.disc_cup = {"healthy": 0.3, "pressed": 0.5, "lost": 0.85, "stasis": 0.15, "swollen": 0.0}[key]
        s.nfl_scale = {"healthy": 1.0, "pressed": 0.85, "lost": 0.3, "stasis": 1.2, "swollen": 1.5}[key]
        s.disc_swell = {"stasis": 0.4, "swollen": 1.0}.get(key, 0.0)
    elif key == "drusen":
        s.sub_rpe = 0.035 * g(0.32, 0.03) + 0.05 * g(0.47, 0.035) + 0.04 * g(0.64, 0.03)
    elif key == "ga":
        loss = np.clip((0.17 - np.abs(x - 0.5)) / 0.03, 0, 1).astype(np.float32)
        s.pr_loss, s.rpe_loss = loss, loss
        s.outer_t = s.outer_t * (1 - 0.3 * loss)
        s.sub_rpe = 0.03 * g(0.22, 0.025) + 0.03 * g(0.8, 0.025)
    elif key == "cnv":
        s.sub_rpe = (0.08 * np.clip(1 - ((x - 0.5) / 0.09) ** 2, 0, 1) ** 0.6).astype(np.float32)
        s.sub_rpe_color = (150, 140, 110)
        s.sub_ret = (0.06 * np.clip(1 - ((x - 0.5) / 0.22) ** 2, 0, 1) ** 0.7).astype(np.float32)
    elif key == "edema":
        s.inner_t = s.inner_t + 0.12 * g(0.5, 0.18)
        s.cysts = [(0.42, 0.55, 0.03, 0.05), (0.5, 0.45, 0.025, 0.06), (0.58, 0.6, 0.03, 0.05), (0.65, 0.5, 0.02, 0.04)]
    elif key == "ischemic":
        s.inner_t = s.inner_t * 1.35
    elif key == "tear":
        s.hole = np.abs(x - 0.42) < 0.018
        s.sub_ret = (0.04 * np.clip((0.40 - x) / 0.1, 0, 1)).astype(np.float32)
    elif key == "vmt":
        s.inner_t = s.inner_t + 0.03 * g(0.5, 0.05)
    elif key == "split":
        s.inner_t = s.inner_t + 0.06 * g(0.5, 0.06)
        s.cysts = [(0.5, 0.45, 0.03, 0.08)]
    elif key == "hole":
        hole = np.abs(x - 0.5) < 0.045
        s.hole = hole
        s.inner_t = s.inner_t + 0.07 * (g(0.445, 0.04) + g(0.555, 0.04))
        s.outer_t = np.where(hole, 0, s.outer_t).astype(np.float32)
        s.cysts = [(0.43, 0.5, 0.014, 0.06), (0.57, 0.5, 0.014, 0.06)]
    elif key in ("erm_cells", "erm_pull", "erm_wrinkle"):
        amp = {"erm_cells": 0.0, "erm_pull": 0.008, "erm_wrinkle": 0.018}[key]
        thick = {"erm_cells": 0.0, "erm_pull": 0.04, "erm_wrinkle": 0.11}[key]
        s.inner_t = (s.inner_t + thick * g(0.5, 0.2) + amp * np.sin(x * 70)).astype(np.float32)
    elif key in ("pachy", "leak", "csc"):
        s.choroid_t = np.full_like(s.choroid_t, 0.24)
        if key in ("leak", "csc"):
            s.sub_rpe = 0.03 * g(0.58, 0.015)
            s.sub_rpe_color = (90, 110, 136)
        s.sub_ret = {"pachy": 0 * x, "leak": 0.02 * g(0.55, 0.08), "csc": 0.09 * np.clip(1 - ((x - 0.5) / 0.24) ** 2, 0, 1) ** 0.6}[key].astype(np.float32)
        s.sub_ret_color = (86, 104, 128)
    elif key in ("thin", "crack"):
        s.bow = (0.10 * g(0.5, 0.42) - 0.10 * math.exp(-(0.5 / 0.42) ** 2)).astype(np.float32)
        s.choroid_t = np.full_like(s.choroid_t, 0.055)
        s.inner_t = s.inner_t * 0.8
        if key == "crack":
            gap = np.abs(x - 0.5) < 0.02
            s.rpe_loss = gap.astype(np.float32)
            s.sub_rpe = (0.04 * np.clip(1 - ((x - 0.5) / 0.05) ** 2, 0, 1) ** 0.6).astype(np.float32)
            s.sub_rpe_color = (150, 120, 100)
            s.pr_loss = (np.clip(1 - np.abs(x - 0.25) / 0.06, 0, 1) ** 0.3).astype(np.float32)
    if key == "ischemic":
        def pale(img, sec):
            H = sec.H
            lv = sec.levels
            yy = (np.arange(H, dtype=np.float32) / H)[:, None]
            m = ((yy >= lv["surface"][None, :]) & (yy < lv["outer_top"][None, :])).astype(np.float32)[..., None] * 0.75
            img[:] = img * (1 - m) + np.float32([246, 240, 232]) * m
        s.extras.append(pale)
    img = s.draw()
    return img, s


def _lv(s: A.Section, key: str, x: float) -> float:
    """A level of the section (fraction of its height) at ``x`` — in design units."""
    i = int(np.clip(x, 0, 1) * (len(s.x) - 1))
    v = float(s.y_surface[i]) if key == "surface" else float(s.levels[key][i])
    return v * AH


def _section(p: QPainter, state: str) -> None:
    img, s = _section_image(state)
    p.drawImage(QRectF(0, 0, AW, AH), to_qimage(img))
    kind, key = state.split(":")
    X = lambda f: f * AW                                # noqa: E731
    if kind == "nerve":
        top = _lv(s, "surface", 0.5)
        if key == "healthy":
            _arrow(p, (X(0.5), AH * 0.62), (X(0.5), AH * 0.95), LIGHT, 3, 10)
            _tag(p, X(0.2), _lv(s, "surface", 0.2) - 30, "신경섬유", at=(X(0.22), _lv(s, "surface", 0.22) + 4))
            _tag(p, X(0.72), top - 34, "시신경 유두", at=(X(0.56), top + 6))
            _tag(p, X(0.75), AH * 0.86, "시신경 → 뇌")
        elif key == "pressed":
            for dx in (-0.05, 0.0, 0.05):
                _arrow(p, (X(0.5 + dx), top - 70), (X(0.5 + dx), top - 8), PRESS, 4, 12)
            _tag(p, X(0.2), 30, "안압")
            _tag(p, X(0.8), AH * 0.66, "뒤로 밀리는 사상판", at=(X(0.58), AH * 0.66))
            _tag(p, X(0.22), _lv(s, "surface", 0.2) + 46, "눌린 신경섬유 · 혈관", at=(X(0.4), _lv(s, "surface", 0.38) + 10))
        elif key == "lost":
            _tag(p, X(0.2), _lv(s, "surface", 0.2) - 30, "줄어든 신경섬유", at=(X(0.22), _lv(s, "surface", 0.22) + 3))
            _tag(p, X(0.75), top - 50, "커진 함몰 (컵)", at=(X(0.53), top + 4))
        elif key in ("stasis", "swollen"):
            if key == "stasis":
                for x in (0.37, 0.63):
                    _arrow(p, (X(x), AH * 0.98), (X(x), AH * 0.70), FLUID, 3.5, 11)
                _dots(p, X(0.5), AH * 0.62, 18, 14, 3, QColor(255, 170, 60), seed=4)
                _tag(p, X(0.2), AH * 0.9, "뇌척수액 압력", at=(X(0.36), AH * 0.85))
                _tag(p, X(0.8), AH * 0.55, "막힌 축삭 수송", at=(X(0.53), AH * 0.62))
                _tag(p, X(0.5), top - 36, "붓기 시작한 유두", at=(X(0.5), top + 4))
            else:
                _tag(p, X(0.5), max(16, top - 30), "부풀어 솟은 유두", at=(X(0.5), top + 4))
                _tag(p, X(0.16), _lv(s, "surface", 0.15) - 30, "부은 신경섬유", at=(X(0.2), _lv(s, "surface", 0.2) + 4))
                _tag(p, X(0.82), AH * 0.82, "오래가면 위축")
        return
    surf = lambda f: _lv(s, "surface", f)            # noqa: E731
    if key == "drusen":
        _tag(p, X(0.47), _lv(s, "rpe_top", 0.47) + 52, "드루젠 (쌓인 노폐물)", at=(X(0.47), _lv(s, "rpe_top", 0.47) + 10))
        _tag(p, X(0.85), _lv(s, "rpe_top", 0.85) - 30, "색소상피", at=(X(0.85), _lv(s, "rpe_top", 0.85) + 2))
        _tag(p, X(0.15), _lv(s, "pr_top", 0.15) - 26, "시세포", at=(X(0.15), _lv(s, "pr_top", 0.15) + 6))
        _tag(p, X(0.2), AH * 0.12, "나이 · 흡연 · 유전")
    elif key == "ga":
        _tag(p, X(0.5), _lv(s, "pr_top", 0.5) - 46, "없어진 시세포 · 색소상피", at=(X(0.5), _lv(s, "pr_top", 0.5) + 2))
        _tag(p, X(0.22), _lv(s, "rpe_top", 0.22) + 50, "드루젠", at=(X(0.22), _lv(s, "rpe_top", 0.22) + 6))
    elif key == "cnv":
        _arrow(p, (X(0.5), _lv(s, "choroid_bottom", 0.5) - 6), (X(0.5), _lv(s, "rpe_top", 0.5) + 12), PRESS, 4, 12)
        rng = np.random.default_rng(6)
        p.setPen(QPen(VEGF.darker(150), 1))
        p.setBrush(VEGF)
        for _ in range(10):
            p.drawEllipse(QPointF(X(rng.uniform(0.3, 0.7)), _lv(s, "pr_top", 0.5) + rng.uniform(-30, 0)), 3.5, 3.5)
        _tag(p, X(0.2), _lv(s, "choroid_bottom", 0.2) - 10, "맥락막")
        _tag(p, X(0.78), _lv(s, "rpe_top", 0.62) + 50, "브루크막을 뚫은 신생혈관", at=(X(0.55), _lv(s, "rpe_top", 0.55) + 18))
        _tag(p, X(0.27), surf(0.27) - 34, "새어 나온 액체 · 피", at=(X(0.32), _lv(s, "pr_bot", 0.32) + 4))
        _tag(p, X(0.75), 22, "VEGF (자라라는 신호)")
    elif key == "edema":
        for x in (0.3, 0.7):
            _arrow(p, (X(x), surf(x) + 10), (X(0.5 + (x - 0.5) * 0.4), surf(0.5) + 40), FLUID, 3, 10)
        _tag(p, X(0.5), surf(0.5) - 34, "황반부종 (고인 물)", at=(X(0.5), surf(0.5) + 34))
        _tag(p, X(0.2), 22, "막힌 정맥에서 새어 나온 물")
    elif key == "ischemic":
        _tag(p, X(0.3), surf(0.3) - 36, "피를 못 받은 안쪽 층 (하얗게 부음)", at=(X(0.3), surf(0.3) + 14))
        _tag(p, X(0.7), _lv(s, "choroid_bottom", 0.7) + 22, "바깥층은 맥락막이 먹여 살림", at=(X(0.7), _lv(s, "pr_top", 0.7)))
    elif key == "tear":
        x0 = 0.42
        p.setPen(QPen(QColor(224, 170, 160), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(X(x0 + 0.02), surf(x0 + 0.03)), QPointF(X(x0 + 0.08), surf(x0) - 40))
        p.setPen(QPen(QColor(170, 190, 214), 2))
        for k in range(4):
            p.drawLine(QPointF(X(x0 + 0.08), surf(x0) - 40), QPointF(X(0.6 + 0.1 * k), 16))
        _arrow(p, (X(x0 + 0.08), surf(x0) - 42), (X(x0 + 0.13), surf(x0) - 80), PRESS, 3.5, 11)
        _tag(p, X(0.82), 46, "유리체가 당김")
        _tag(p, X(0.22), _lv(s, "rpe_top", 0.3) + 34, "열공 (찢어진 망막)", at=(X(x0), _lv(s, "rpe_top", x0) - 6))
    elif key in ("vmt", "split", "hole"):
        if key != "hole":
            for side in (-1, 1):
                pts = [(X(0.5 + side * 0.5 * t), surf(0.5) - 6 - 90 * t ** 0.8) for t in np.linspace(0, 1, 24)]
                p.setPen(QPen(QColor(170, 190, 214), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(_smooth(pts))
            _arrow(p, (X(0.5), surf(0.5) - 8), (X(0.5), surf(0.5) - 60), PRESS, 4, 12)
            _tag(p, X(0.18), 30, "줄어드는 유리체")
            if key == "vmt":
                _tag(p, X(0.78), surf(0.5) - 40, "중심와를 당기는 힘", at=(X(0.52), surf(0.5) - 30))
            else:
                _tag(p, X(0.78), surf(0.62) + 70, "갈라진 중심와 (물주머니)", at=(X(0.52), surf(0.5) + 22))
        else:
            p.setPen(QPen(QColor(170, 190, 214), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(_smooth([(0, 40), (X(0.5), 70), (AW, 40)]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(226, 176, 166))
            p.drawEllipse(QPointF(X(0.5), 76), 16, 8)
            _arrow(p, (X(0.44), surf(0.4) + 30), (X(0.38), surf(0.4) + 30), QColor(255, 255, 255), 2.5, 8)
            _arrow(p, (X(0.56), surf(0.6) + 30), (X(0.62), surf(0.6) + 30), QColor(255, 255, 255), 2.5, 8)
            _tag(p, X(0.78), 82, "떨어진 덮개", at=(X(0.53), 76))
            _tag(p, X(0.5), _lv(s, "rpe_top", 0.5) + 36, "전층 원공 (구멍)", at=(X(0.5), _lv(s, "rpe_top", 0.5) - 8))
    elif key.startswith("erm"):
        pts = [(X(f), surf(f) - 5) for f in np.linspace(0.15, 0.85, 50)]
        p.setPen(QPen(QColor(252, 252, 248), 3 if key != "erm_cells" else 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_smooth(pts))
        if key == "erm_cells":
            _dots(p, X(0.5), surf(0.5) - 10, 12, 40, 3.2, QColor(255, 255, 255), seed=2)
            _tag(p, X(0.5), surf(0.5) - 56, "망막 표면에 자란 세포 · 얇은 막", at=(X(0.5), surf(0.5) - 8))
        elif key == "erm_pull":
            for a, b in (((0.18, 0.30)), ((0.82, 0.70))):
                _arrow(p, (X(a), surf(a) - 22), (X(b), surf(b) - 22), PRESS, 4, 12)
            _tag(p, X(0.5), surf(0.5) - 60, "막이 수축하며 당김")
        else:
            _tag(p, X(0.3), surf(0.3) - 44, "주름진 망막", at=(X(0.33), surf(0.33)))
            _tag(p, X(0.72), _lv(s, "pr_top", 0.62) + 60, "두꺼워지고 흐트러진 망막", at=(X(0.58), _lv(s, "outer_top", 0.58)))
    elif key in ("pachy", "leak", "csc"):
        _tag(p, X(0.22), _lv(s, "choroid_bottom", 0.22) - 22, "넓어진 맥락막 혈관" if key == "pachy" else "두꺼운 맥락막")
        if key == "pachy":
            for x in (0.35, 0.65):
                _arrow(p, (X(x), _lv(s, "choroid_bottom", x) - 10), (X(x), _lv(s, "bruch", x) + 10), FLUID, 3, 10)
            _tag(p, X(0.72), 26, "스트레스 · 스테로이드")
        else:
            x0 = 0.58
            _arrow(p, (X(x0), _lv(s, "choroid_bottom", x0) - 12), (X(x0), _lv(s, "pr_bot", x0) - 2), FLUID.lighter(115), 4, 12)
            _tag(p, X(0.82), _lv(s, "rpe_top", x0) + 44, "새는 곳 (색소상피)", at=(X(x0 + 0.02), _lv(s, "rpe_top", x0)))
            if key == "csc":
                _tag(p, X(0.32), surf(0.32) - 40, "망막 밑에 고인 액체", at=(X(0.36), _lv(s, "pr_bot", 0.36) + 6))
    elif key in ("thin", "crack"):
        y = _lv(s, "choroid_bottom", 0.5) + 30
        _arrow(p, (X(0.42), y), (X(0.12), y - 26), QColor(255, 255, 255), 3, 10)
        _arrow(p, (X(0.58), y), (X(0.88), y - 26), QColor(255, 255, 255), 3, 10)
        if key == "thin":
            _tag(p, X(0.5), 26, "늘어난 눈벽")
            _tag(p, X(0.25), _lv(s, "choroid_bottom", 0.25) - 34, "얇아진 맥락막 · 망막", at=(X(0.28), _lv(s, "bruch", 0.28) + 4))
        else:
            _tag(p, X(0.75), _lv(s, "rpe_top", 0.6) - 50, "래커 균열 → 신생혈관", at=(X(0.51), _lv(s, "rpe_top", 0.5) + 4))
            _tag(p, X(0.22), surf(0.25) - 34, "위축", at=(X(0.25), _lv(s, "pr_top", 0.25) + 4))


# -- photoreceptors ----------------------------------------------------------------------------------
def _cells(p: QPainter, state: str) -> None:
    p.fillRect(QRectF(0, 0, AW, AH), QColor(34, 38, 48))
    p.fillRect(QRectF(0, 0, AW, 58), QColor(240, 200, 186))
    p.fillRect(QRectF(0, 58, AW, 52), QColor(222, 170, 164))
    rng = np.random.default_rng(7)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(176, 110, 120))
    for _ in range(40):
        p.drawEllipse(QPointF(rng.uniform(0, AW), rng.uniform(64, 104)), 5, 4)
    p.setBrush(QColor(200, 140, 150))
    for _ in range(9):
        p.drawEllipse(QPointF(rng.uniform(10, AW - 10), rng.uniform(14, 44)), 9, 7)
    # the RPE, Bruch, the choroid
    p.fillRect(QRectF(0, 222, AW, 26), QColor(98, 50, 32))
    p.setPen(QPen(QColor(70, 34, 20), 1.5))
    for x in range(0, int(AW), 30):
        p.drawLine(QPointF(x, 222), QPointF(x, 248))
    p.fillRect(QRectF(0, 248, AW, AH - 248), QColor(170, 46, 40))
    rods_gone = {"healthy": 0.0, "gene": 0.0, "rods": 0.6, "late": 1.0}[state]
    cones_left = {"late": 0.45}.get(state, 1.0)
    rng = np.random.default_rng(11)
    x = 8.0
    k = 0
    while x < AW - 6:
        cone = k % 3 == 2
        if cone:
            if rng.random() < cones_left:
                h = 70 if state != "late" else 46
                poly = QPolygonF([QPointF(x - 7, 222), QPointF(x + 7, 222), QPointF(x + 3, 222 - h), QPointF(x - 3, 222 - h)])
                p.setPen(QPen(QColor(150, 130, 50), 1))
                p.setBrush(QColor(236, 204, 110))
                p.drawPolygon(poly)
                p.drawLine(QPointF(x, 222 - h), QPointF(x, 110))
        else:
            if rng.random() >= rods_gone:
                p.setPen(QPen(QColor(90, 110, 150), 1))
                p.setBrush(QColor(150, 170, 206))
                p.drawRoundedRect(QRectF(x - 4, 130, 8, 92), 3, 3)
                p.setPen(QPen(QColor(110, 130, 170), 0.8))
                for yy in range(134, 220, 6):
                    p.drawLine(QPointF(x - 3, yy), QPointF(x + 3, yy))
                p.setPen(QPen(QColor(150, 170, 206), 1.2))
                p.drawLine(QPointF(x, 130), QPointF(x, 110))
            elif rods_gone < 1.0 and rng.random() < 0.5:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(120, 120, 130))
                p.drawRoundedRect(QRectF(x - 3, 190, 6, 32), 2, 2)        # a stub
        x += 13
        k += 1
    if state == "healthy":
        for x in (60, 180, 300):
            _arrow(p, (x, 6), (x, 120), LIGHT, 3, 10)
        _tag(p, 90, 150, "막대세포 (어두운 곳)", at=(73, 170))
        _tag(p, 262, 150, "원뿔세포 (색 · 글자)", at=(255, 180))
        _tag(p, 280, 236, "색소상피")
        _tag(p, 120, 30, "빛")
        _tag(p, 240, 30, "신호 → 신경섬유 → 뇌")
    else:
        if state == "gene":
            cx, cy = 300, 32
            p.setPen(QPen(QColor(120, 200, 255), 2.4))
            for t0 in (0, math.pi):
                pts = [QPointF(cx - 40 + i * 4, cy + 14 * math.sin(i * 0.5 + t0)) for i in range(21)]
                p.drawPolyline(QPolygonF(pts))
            p.setPen(QPen(QColor(255, 255, 255, 180), 1.4))
            for i in range(0, 21, 3):
                p.drawLine(QPointF(cx - 40 + i * 4, cy + 14 * math.sin(i * 0.5)), QPointF(cx - 40 + i * 4, cy + 14 * math.sin(i * 0.5 + math.pi)))
            p.setPen(QPen(PRESS, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx + 6, cy), 9, 16)
            _tag(p, 110, 32, "유전자 이상 → 시세포 단백질 이상", at=(cx - 6, cy))
            _tag(p, 180, 170, "아직은 시세포가 남아 있음")
        if state in ("rods", "late"):
            _dots(p, 120, 160 if state == "rods" else 120, 6 if state == "rods" else 16, 40 if state == "rods" else 70, 4,
                  QColor(30, 20, 16), seed=3)
            _arrow(p, (240, 220), (240, 150), QColor(255, 255, 255), 2.5, 9)
            _tag(p, 110, 150 if state == "late" else 120, "망막으로 옮겨 가는 색소", at=(120, 150 if state == "rods" else 110))
            if state == "rods":
                _tag(p, 280, 130, "줄어든 막대세포 → 야맹증", at=(230, 200))
                _tag(p, 290, 200, "원뿔세포는 남음")
            else:
                _tag(p, 270, 120, "원뿔세포도 줄어듦 → 터널 시야", at=(256, 190))


def draw_art(p: QPainter, rect: QRectF, art: str) -> None:
    """One drawing (``kind:state``) into ``rect``."""
    kind, state = art.split(":")
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(rect, 10, 10)
    p.setClipPath(clip)
    p.translate(rect.topLeft())
    p.scale(rect.width() / AW, rect.height() / AH)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "vessel":
        _vessel(p, state)
    elif kind == "eye":
        _eye(p, state)
    elif kind in ("nerve", "section"):
        _section(p, art)
    elif kind == "cells":
        _cells(p, state)
    p.restore()


def compose_mechanism(disease: D.Disease, width: int = W) -> np.ndarray:
    """The 기전 picture of ``disease`` (RGB): its steps side by side, with arrows between them."""
    steps = D.MECHANISMS[disease.name]
    n = len(steps)
    k = width / W
    gap = 46
    cw = (W - 2 * M - (n - 1) * gap) / n
    ah = cw * AH / AW
    top = 104
    title_h = 64
    text_h = 150
    H = int(top + title_h + ah + 18 + text_h + M)
    img = QImage(int(W * k), int(H * k), QImage.Format.Format_RGB888)
    img.fill(QColor(theme.BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(k, k)
    head = "눈은 어떻게 보나요" if disease.name == "정상 안저" else "어떻게 생기나요 (기전)"
    p.setFont(_font(34, True))
    p.setPen(INK)
    p.drawText(QPointF(M, 52), disease.name)
    fm = QFontMetricsF(p.font())
    p.setFont(_font(26, True))
    p.setPen(QColor(theme.TEAL))
    p.drawText(QPointF(M + fm.horizontalAdvance(disease.name) + 18, 52), head)
    p.setFont(_font(17))
    p.setPen(INK2)
    p.drawText(QPointF(M, 80), disease.english)
    p.setFont(_font(16, True))
    p.setPen(QColor(theme.ORANGE))
    p.drawText(QRectF(W - M - 620, 30, 620, 30), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
               "설명용 그림 — 이 환자의 소견이 아닙니다")
    for i, st in enumerate(steps):
        x = M + i * (cw + gap)
        _badge(p, QPointF(x + 17, top + 18), i + 1, 16)
        _wrapped(p, QRectF(x + 42, top + 2, cw - 44, title_h), st.title, 21, INK, bold=True)
        art = QRectF(x, top + title_h, cw, ah)
        draw_art(p, art, st.art)
        _wrapped(p, QRectF(x, art.bottom() + 14, cw, text_h), st.text, 17, INK)
        if i < n - 1:                                  # → to the next step
            cy = art.center().y()
            ax = art.right() + 8
            path = QPainterPath(QPointF(ax, cy - 16))
            path.lineTo(ax + gap - 18, cy)
            path.lineTo(ax, cy + 16)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.TEAL))
            p.drawPath(path)
    p.end()
    return from_qimage(img)
