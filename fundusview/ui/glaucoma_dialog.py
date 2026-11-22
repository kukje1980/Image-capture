"""녹내장 분석 — disc C/D, the disc in 3D, wide-field RNFL, stereo viewing and progression
(``glaucoma.py``, ``disc3d.py``).

Opened with the [Glaucoma] button above the photos (or [녹내장] in the command toolbar). The
photo on screen goes to **디스크 C/D** (cut around its optic disc), **3D 입체** (the disc as a
surface to turn — from one photo, or from the parallax of two) and **광각 분석** (its disc and
fovea, found at import, are already marked); with a second photo picked (Ctrl+click, ②) the two
go to **스테레오 보기** and **경과 비교**, cut around their discs to the same retinal field so
that different cameras compare. **시간별 비교** (``timeline_tab.py``) takes every photo of that eye:
side by side in the order of time, or on top of each other.
What a tab shows can be saved into the patient record as a new photo (the originals stay as they
are), written to a file or copied.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from .. import disc3d
from .. import glaucoma as G
from . import theme
from .image_view import from_qimage, to_qimage
from .keys import keys
from .widgets import RoundCorners, Segmented, Switch, card, segment

DISC_COLOR, CUP_COLOR = QColor(theme.GREEN), QColor(theme.YELLOW)
NEED_PAIR = keys("사진 두 장이 필요합니다.\n\n사진 목록에서 한 장을 클릭하고 두 번째 사진을 Ctrl+클릭(②)한 뒤\n"
                 "[녹내장]을 다시 누르세요.")
NEED_ONE = "분석할 사진이 없습니다."
# what a pair tab shows of each photo: (key, label, width in disc diameters — 0: the whole photo)
REGIONS = (("disc", "유두 주변", 5.0), ("wide", "넓게", 10.0), ("full", "사진 전체", 0.0))
PAIR_PX = 720            # side of a disc-centred crop in the pair tabs
DISC_FIELDS = (("near", "가깝게", 2.5), ("normal", "보통", 3.5), ("wide", "넓게", 5.0))


@dataclass
class Photo:
    """One photo handed to the dialog."""
    image_id: int
    rgb: np.ndarray
    eye: str | None                    # OD / OS / None (unknown)
    disc: tuple[float, float]          # optic disc centre (px) — detected, picked or the expected place
    disc_px: float                     # disc diameter there (px), from the photo's geometry
    fovea: tuple[float, float] | None = None
    disc_found: bool = True            # False: ``disc`` is only where it should be
    when: str = ""                     # "YYYY-MM-DD HH:MM:SS"
    caption: str = ""

    @property
    def day(self) -> str:
        return self.when[:10]


# -- shared widgets ------------------------------------------------------------------------------
class _View(QWidget):
    """The image fitted to the widget; reports the mouse in image pixels. ``overlay(painter)``
    draws on top, in image pixels."""
    pressed = Signal(float, float)
    moved = Signal(float, float)
    released = Signal()

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        RoundCorners(self)    # round corners, as every pane of a photo
        self._img: QImage | None = None
        self._placeholder = placeholder
        self.overlay = None
        self.setMinimumSize(420, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_rgb(self, rgb) -> None:
        self._img = to_qimage(rgb) if rgb is not None else None
        self.update()

    def has_image(self) -> bool:
        return self._img is not None

    def scale(self) -> float:
        return self._geom()[0]

    def _geom(self) -> tuple[float, float, float]:
        if self._img is None:
            return 1.0, 0.0, 0.0
        iw, ih = self._img.width(), self._img.height()
        s = min(self.width() / iw, self.height() / ih) or 1.0
        return s, (self.width() - iw * s) / 2, (self.height() - ih * s) / 2

    def _paint(self, p: QPainter) -> None:
        p.drawImage(0, 0, self._img)
        if self.overlay is not None:
            self.overlay(p)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BLACK))
        if self._img is None:
            p.setPen(QColor(theme.TEXT3))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            return
        s, ox, oy = self._geom()
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(ox, oy)
        p.scale(s, s)
        self._paint(p)

    def render_rgb(self):
        """The image with what is drawn over it, at the image's own size."""
        if self._img is None:
            return None
        out = QImage(self._img.width(), self._img.height(), QImage.Format.Format_RGB888)
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self._paint(p)
        p.end()
        return from_qimage(out)

    def _pos(self, e) -> tuple[float, float]:
        s, ox, oy = self._geom()
        return (e.position().x() - ox) / s, (e.position().y() - oy) / s

    def mousePressEvent(self, e) -> None:
        if self._img is not None and e.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(*self._pos(e))

    def mouseMoveEvent(self, e) -> None:
        if self._img is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.moved.emit(*self._pos(e))

    def mouseReleaseEvent(self, _e) -> None:
        self.released.emit()


def _note(text: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color:{theme.TEXT2}")
    return lb


def _button(text: str, primary: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    if tip:
        b.setToolTip(tip)
    return b


def _pair_row(*widgets: QWidget) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for x in widgets:
        lay.addWidget(x, 1)
    return w


class _Choice(Segmented):
    """One of a few, by key."""
    changed = Signal(str)

    def __init__(self, items, parent=None):
        self._keys = [it[0] for it in items]
        super().__init__([segment(it[1], it[2] if len(it) > 2 and isinstance(it[2], str) else "") for it in items],
                         parent)
        for key, b in zip(self._keys, self.buttons):
            b.clicked.connect(lambda _=False, key=key: self.changed.emit(key))
        self.buttons[0].setChecked(True)

    def set(self, key: str) -> None:
        self.buttons[self._keys.index(key)].setChecked(True)

    def key(self) -> str:
        return self._keys[self.buttons.index(self.group.checkedButton())]


class _Slider(QWidget):
    """A slider with its name and value above it; values come in multiples of ``step``."""
    changed = Signal(float)

    def __init__(self, label: str, lo: float, hi: float, value: float, step: float, fmt, parent=None):
        super().__init__(parent)
        self._step, self._fmt = step, fmt
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(QLabel(label))
        top.addStretch(1)
        self._out = QLabel()
        self._out.setStyleSheet(f"color:{theme.TEXT2}")
        top.addWidget(self._out)
        box.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(lo / step), round(hi / step))
        self.slider.valueChanged.connect(self._on)
        box.addWidget(self.slider)
        self.set(value)

    def value(self) -> float:
        return self.slider.value() * self._step

    def set(self, v: float) -> None:
        blk = self.slider.blockSignals(True)
        self.slider.setValue(round(v / self._step))
        self.slider.blockSignals(blk)
        self._out.setText(self._fmt(self.value()))

    def _on(self, _v) -> None:
        self._out.setText(self._fmt(self.value()))
        self.changed.emit(self.value())


def _px(v: float) -> str:
    return f"{v:+.1f} px".replace(".0 px", " px")


class _Tab(QWidget):
    """The image on the left, a column of cards on the right."""

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)
        left = QVBoxLayout()
        self.view = _View(placeholder)
        self.hint = _note()
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.view, 1)
        left.addWidget(self.hint)
        lay.addLayout(left, 1)
        inner = QWidget()
        self.side = QVBoxLayout(inner)
        self.side.setContentsMargins(0, 0, 6, 0)
        self.side.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        scroll.setFixedWidth(340)
        lay.addWidget(scroll)

    def has_image(self) -> bool:
        return self.view.has_image()

    def render(self):
        return self.view.render_rgb()

    def note(self) -> str:
        return ""

    def image_ids(self) -> list[int]:
        return []

    def eye(self) -> str | None:
        return None


class _PairTab(_Tab):
    """Two photos brought to the same frame: each cut around its disc (to the same retinal
    field, whatever the camera) or whole, then registered — a small turn and size from matched vessel
    points (``G.find_turn``) and a shift (the 좌우 · 상하 sliders); a 기준점 (``set_reference``) lays the
    two exactly on each other at one point."""
    LIMIT_X, LIMIT_Y = 60.0, 60.0

    def __init__(self, pair, parent=None):
        super().__init__(NEED_PAIR, parent)
        self.pair = tuple(pair) if pair else None
        self.a = self.b = self._bs = None
        self.dx = self.dy = 0.0
        self.angle, self.scale = 0.0, 1.0      # the turn and size of b found by 자동 맞춤 (about the centre)
        self.ref: tuple[float, float] | None = None   # 기준점: where the two lie exactly on each other
        self.region = "disc"
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.regions = _Choice(REGIONS)
        self.regions.changed.connect(self.set_region)
        self.b_auto = _button("자동 맞춤", primary=True, tip="두 사진이 겹치도록 좌우·상하로 옮깁니다")
        self.b_zero = _button("맞춤 해제")
        self.b_auto.clicked.connect(self.auto_align)
        self.b_zero.clicked.connect(self.clear_alignment)
        self.s_dx = _Slider("좌우", -self.LIMIT_X, self.LIMIT_X, 0, 0.5, _px)
        self.s_dy = _Slider("상하", -self.LIMIT_Y, self.LIMIT_Y, 0, 0.5, _px)
        self.s_dx.changed.connect(lambda v: self.set_offset(v, self.dy))
        self.s_dy.changed.connect(lambda v: self.set_offset(self.dx, v))
        self.status = _note()

    def align_card(self, title: str = "맞춤") -> QWidget:
        return card(title, self.regions, _pair_row(self.b_auto, self.b_zero), self.s_dx, self.s_dy, self.status)

    # -- the two frames --------------------------------------------------------------------------
    @staticmethod
    def frame(photo: Photo, region: str) -> np.ndarray:
        factor = {k: f for k, _, f in REGIONS}[region]
        if not factor:
            return G.fit(photo.rgb)
        crop, _, _ = G.crop_square(photo.rgb, *photo.disc, factor * photo.disc_px)
        return G.match_size(crop, np.empty((PAIR_PX, PAIR_PX, 3), np.uint8))

    def set_region(self, region: str) -> None:
        self.region = region
        self.regions.set(region)
        self.ref = None                       # (another frame: the point is elsewhere)
        if self.pair is None:
            return
        self.a = self.frame(self.pair[0], region)
        self.b = G.match_size(self.frame(self.pair[1], region), self.a)
        self.auto_align()

    def set_offset(self, dx: float, dy: float, status: str | None = None) -> None:
        if self.a is None:
            return
        self.dx = max(-self.LIMIT_X, min(self.LIMIT_X, dx))
        self.dy = max(-self.LIMIT_Y, min(self.LIMIT_Y, dy))
        self.s_dx.set(self.dx)
        self.s_dy.set(self.dy)
        if abs(self.angle) > 1e-6 or abs(self.scale - 1.0) > 1e-6:
            self._bs = G.turned(self.b, self.angle, self.scale, self.dx, self.dy)
        else:
            self._bs = G.shifted(self.b, self.dx, self.dy)
        if status is not None:
            self.status.setText(status)
        self._offset_changed()
        self._draw()

    def _offset_changed(self) -> None:
        pass

    def auto_align(self) -> None:
        """자동 맞춤: the turn, size and shift that lay the second photo on the first (matched vessel
        points; a shift alone where too few agree) — then the 기준점, if one is set, exactly."""
        if self.a is None:
            return
        found = G.find_turn(self.a, self.b)
        if found is not None and abs(found[2]) <= self.LIMIT_X and abs(found[3]) <= self.LIMIT_Y:
            self.angle, self.scale, dx, dy = found
        else:
            self.angle, self.scale = 0.0, 1.0
            dx, dy = G.find_shift(self.a, self.b)
        self.set_offset(dx, dy)
        turn = (f" · 회전 {self.angle:+.1f}° · 크기 {self.scale * 100:.1f}%"
                if abs(self.angle) >= 0.05 or abs(self.scale - 1) >= 0.0005 else "")
        self.status.setText(f"자동 맞춤: 좌우 {_px(self.dx)}, 상하 {_px(self.dy)}{turn}")
        if self.ref is not None:
            self.set_reference(*self.ref)

    def clear_alignment(self) -> None:
        """맞춤 해제: the photos as they are — no turn, size, shift or 기준점."""
        self.angle, self.scale, self.ref = 0.0, 1.0, None
        self.set_offset(0, 0, "맞춤을 해제했습니다.")

    def set_reference(self, x: float, y: float) -> bool:
        """기준점: the two photos laid exactly on each other at (x, y) of the first — the place looked for
        round it in the second (as it lies now) and the shift corrected by what is left; there the
        picture stands still and everything else moves by its depth."""
        if self.a is None or self._bs is None:
            return False
        found = G.match_point(self.a, self._bs, x, y)
        if found is None:
            self.status.setText("기준점: 그 자리에서 두 사진의 같은 곳을 찾지 못했습니다 — 혈관이 갈라지는 곳이나 "
                                "유두 테두리처럼 무늬가 뚜렷한 곳을 누르세요")
            return False
        self.ref = (float(x), float(y))
        self.set_offset(self.dx + found[0], self.dy + found[1])
        self.status.setText(f"기준점 ({x:.0f}, {y:.0f})에 두 사진을 맞췄습니다 — 이 점을 중심으로 움직입니다 "
                            "(다른 곳을 누르면 그곳으로, 맞춤 해제: 지우기)")
        return True

    # -- alternating the two ---------------------------------------------------------------------
    def _alternating(self) -> bool:
        return False

    def _rate(self) -> float:
        return 2.0

    def _restart(self) -> None:
        if self._alternating() and self.a is not None:
            self._timer.start(max(30, round(500 / self._rate())))
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if self.isVisible():
            self._phase ^= 1
            self._draw()

    def compose(self):
        return None

    def _draw(self) -> None:
        self.view.set_rgb(self.compose())

    def image_ids(self) -> list[int]:
        return [p.image_id for p in self.pair] if self.pair else []

    def eye(self) -> str | None:
        eyes = {p.eye for p in self.pair} if self.pair else set()
        return eyes.pop() if len(eyes) == 1 else None


# -- stereo ----------------------------------------------------------------------------------------
ST_MODES = [("wiggle", "위글", "두 장을 번갈아 보기"), ("sbs", "평행", "나란히 — 평행법 · 입체경"),
            ("cross", "교차", "나란히 — 교차법"), ("ana", "적청", "적청 안경"), ("depth", "깊이", "깊이 지도")]
ST_NAMES = {"wiggle": "위글", "sbs": "나란히(평행)", "cross": "나란히(교차)", "ana": "적청", "depth": "깊이 지도"}
ST_HINT = {
    "wiggle": "두 장을 번갈아 보여 줍니다. 컵 바닥과 림이 서로 다르게 움직이는 만큼이 깊이입니다. "
              "사진을 누르면 그곳이 기준점 — 두 사진을 그 점에 딱 맞춰 그 점을 중심으로 움직입니다.",
    "sbs": "평행법: 왼쪽 눈으로 왼쪽, 오른쪽 눈으로 오른쪽 사진을 봅니다. 간이 입체경에 맞는 배치입니다.",
    "cross": "교차법: 눈을 모아 왼쪽 눈으로 오른쪽, 오른쪽 눈으로 왼쪽 사진을 봅니다.",
    "ana": "적청 안경(왼쪽 빨강, 오른쪽 청록)을 쓰고 봅니다. 사진을 누르면 그곳이 기준점(화면 깊이)입니다.",
    "depth": "파랑은 깊은 곳(컵), 빨강은 솟은 곳입니다. 사진을 누르면 그 높이의 단면이 아래에 그려집니다.",
}


class StereoTab(_PairTab):
    """Two photos of one disc taken from slightly different positions, seen in depth."""
    LIMIT_Y = 40.0

    def __init__(self, pair, parent=None):
        super().__init__(pair, parent)
        self.swap = False
        self.mode = "wiggle"
        self._disp = None
        self._prof_y = None
        self.modes = _Choice(ST_MODES)
        self.modes.changed.connect(self.set_mode)
        self.speed = _Slider("위글 속도", 1, 10, 5, 1, lambda v: f"{v:.0f} Hz")
        self.speed.changed.connect(lambda _v: self._restart())
        self.sw_swap = Switch("좌우 바꾸기")
        self.sw_swap.setToolTip("깊이가 뒤집혀 보이면(컵이 솟아 보이면) 켭니다")
        self.sw_swap.toggled.connect(self.set_swap)
        self.side.addWidget(card("보기 방식", self.modes, self.speed, self.sw_swap, lines=False))
        self.side.addWidget(self.align_card("정렬"))
        self.side.addStretch(1)
        self.view.pressed.connect(self._on_press)
        self.set_region("disc")
        self.set_mode("wiggle")

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.modes.set(mode)
        self.hint.setText(ST_HINT[mode])
        self.speed.setVisible(mode == "wiggle")
        self._restart()
        self._draw()

    def set_swap(self, on: bool) -> None:
        self.swap = on
        if self.sw_swap.isChecked() != on:
            self.sw_swap.setChecked(on)
        self._disp = None
        self._draw()

    def _offset_changed(self) -> None:
        self._disp = None

    def _alternating(self) -> bool:
        return self.mode == "wiggle"

    def _rate(self) -> float:
        return self.speed.value()

    def _on_press(self, x: float, y: float) -> None:
        if self.a is None or not (0 <= x < self.a.shape[1] and 0 <= y < self.a.shape[0]):
            return
        if self.mode == "depth":
            self._prof_y = y
            self._draw()
        elif self.mode in ("wiggle", "ana"):  # 기준점: the two laid exactly on each other there
            self.set_reference(x, y)

    _marking = True                           # the 기준점 is marked on the screen (not in what is saved)

    def render(self):
        self._marking = False
        try:
            self._draw()
            return super().render()
        finally:
            self._marking = True
            self._draw()

    def _mark(self, img: np.ndarray) -> np.ndarray:
        """The 기준점: a small cross in a ring, dark-edged so it shows on any part of the photo."""
        if self.ref is None or not self._marking or img is None:
            return img
        out = img.copy()
        x, y = int(round(self.ref[0])), int(round(self.ref[1]))
        for color, t in (((0, 0, 0), 4), ((80, 220, 255), 2)):
            cv2.circle(out, (x, y), 11, color, t, cv2.LINE_AA)
            cv2.line(out, (x - 18, y), (x - 6, y), color, t, cv2.LINE_AA)
            cv2.line(out, (x + 6, y), (x + 18, y), color, t, cv2.LINE_AA)
            cv2.line(out, (x, y - 18), (x, y - 6), color, t, cv2.LINE_AA)
            cv2.line(out, (x, y + 6), (x, y + 18), color, t, cv2.LINE_AA)
        return out

    def eyes(self) -> tuple:
        """``(left eye's photo, right eye's photo)``."""
        return (self._bs, self.a) if self.swap else (self.a, self._bs)

    def compose(self):
        if self.a is None:
            return None
        a, b = self.eyes()
        if self.mode == "wiggle":
            return self._mark(b if self._phase else a)
        if self.mode == "sbs":
            return G.side_by_side(a, b)
        if self.mode == "cross":
            return G.side_by_side(b, a)
        if self.mode == "ana":
            return self._mark(G.anaglyph(a, b))
        if self._disp is None:
            self._disp = G.disparity(a, b)
        h, w = a.shape[:2]
        y = h / 2 if self._prof_y is None else self._prof_y
        img = G.depth_overlay(a, self._disp)
        img[int(min(h - 1, max(0, y))), ::2] = (255, 255, 255)
        deep, _high = G.disparity_range(self._disp, w)
        self.status.setText(
            f"최대 시차 {deep:.1f} px — 시차가 부족합니다. 두 사진 사이를 더 벌려 다시 찍으세요." if deep < 2
            else f"컵 최대 시차 {deep:.1f} px (상대 깊이, 절대 길이 아님)")
        return np.vstack([img, G.depth_profile(self._disp, y, h, w)])

    def note(self) -> str:
        return "스테레오 " + ST_NAMES[self.mode]


# -- disc: C/D -------------------------------------------------------------------------------------
def _outline_path(e: dict) -> QPainterPath:
    """An outline (``G.outline``) as four quarter ellipses round its centre: up-right, up-left, down-left,
    down-right — the ellipse itself when the opposite reaches are equal."""
    cx, cy, t, r, b, l = (e[k] for k in ("cx", "cy", "top", "right", "bottom", "left"))
    path = QPainterPath(QPointF(cx + r, cy))
    for (rx, ry), start in (((r, t), 0), ((l, t), 90), ((l, b), 180), ((r, b), 270)):
        path.arcTo(QRectF(cx - rx, cy - ry, 2 * rx, 2 * ry), start, 90)
    path.closeSubpath()
    return path


class DiscTab(_Tab):
    """The optic disc of the photo with two outlines to fit: the disc margin and the cup — each point
    (S · N · I · T) moved on its own, the centre moving the whole outline."""

    def __init__(self, photo: Photo | None, parent=None):
        super().__init__(NEED_ONE, parent)
        self.photo = photo
        self.eye_key = "OS" if photo is not None and photo.eye == "OS" else "OD"
        self.img = self.disc = self.cup = None
        self._drag = None
        self.field = "normal"
        self.hint.setText("초록 타원을 디스크 경계에, 노란 타원을 컵 경계에 맞추세요. "
                          "가운데 점은 통째로 옮기기, 가장자리 점(S · N · I · T)은 하나씩 따로 움직입니다.")
        self.eyes = _Choice([("OD", "OD (우안)"), ("OS", "OS (좌안)")])
        self.eyes.set(self.eye_key)
        self.eyes.changed.connect(self.set_eye)
        self.fields = _Choice(DISC_FIELDS)
        self.fields.set("normal")
        self.fields.changed.connect(self.set_field)
        self.fields.setToolTip("화면에 담을 범위 — 유두 지름의 몇 배인지")
        self.warn = _note()
        self.warn.setStyleSheet(f"color:{theme.ORANGE}; font-weight:600")
        self.side.addWidget(card("눈 · 범위", self.eyes, self.fields,
                                 _note("정립상 기준입니다. 우안은 화면 오른쪽이 비측입니다."), self.warn, lines=False))
        self.lbl_v = QLabel("–")
        f = QFont(self.lbl_v.font())
        f.setPixelSize(30)
        f.setBold(True)
        self.lbl_v.setFont(f)
        self.lbl_ratio = QLabel()
        self.lbl_ratio.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_ratio.setWordWrap(True)
        self.side.addWidget(card("수직 C/D", self.lbl_v, self.lbl_ratio))
        self.lbl_rim = QLabel()
        self.lbl_rim.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_rim.setWordWrap(True)
        self.side.addWidget(card("림 두께 (ISNT)", self.lbl_rim,
                                 _note("림 두께는 디스크 수직 지름(DD)에 대한 비율입니다.")))
        self.side.addStretch(1)
        self.view.overlay = self._overlay
        self.view.pressed.connect(self._press)
        self.view.moved.connect(self._move)
        self.view.released.connect(lambda: setattr(self, "_drag", None))
        self.set_field("normal")

    def set_field(self, field: str) -> None:
        """Cut the photo around its disc, ``field`` disc diameters wide, and start the ellipses
        at the size a disc has there."""
        self.field = field
        self.fields.set(field)
        if self.photo is None:
            self.warn.setVisible(False)
            return
        factor = {k: f for k, _, f in DISC_FIELDS}[field]
        crop, _, _ = G.crop_square(self.photo.rgb, *self.photo.disc, factor * self.photo.disc_px)
        self.img = G.fit(crop, 800)
        side = float(self.img.shape[0])
        r = side / factor / 2.0                                  # the disc radius in this picture
        c = side / 2.0
        self.disc = G.outline({"cx": c, "cy": c, "rx": r * 0.95, "ry": r * 1.05})
        self.cup = G.outline({"cx": c, "cy": c, "rx": r * 0.45, "ry": r * 0.50})
        self.warn.setText("" if self.photo.disc_found else
                          "유두를 찾지 못해 예상 위치를 잘랐습니다 — 2D 사진에서 오른쪽 클릭 → 시신경 유두로 지정")
        self.warn.setVisible(not self.photo.disc_found)
        self.view.set_rgb(self.img)
        self._report()

    def set_eye(self, eye: str) -> None:
        self.eye_key = eye
        self.eyes.set(eye)
        self._changed()

    def set_ellipses(self, disc: dict, cup: dict) -> None:
        """The disc and cup outlines (``G.outline``: an ellipse or the reach up · right · down · left)."""
        self.disc, self.cup = G.outline(disc), G.outline(cup)
        self._changed()

    def metrics(self) -> dict | None:
        return G.cdr_metrics(self.disc, self.cup, self.eye_key) if self.disc else None

    def _handles(self) -> list:
        """The points of each outline: its centre (moves it) and S · N · I · T — each moves on its own,
        along its own direction (up / down, left / right), the opposite one staying where it is."""
        out = []
        for key in ("cup", "disc"):
            e = getattr(self, key)
            out += [(key, "c", e["cx"], e["cy"]), (key, "e", e["cx"] + e["right"], e["cy"]),
                    (key, "w", e["cx"] - e["left"], e["cy"]), (key, "n", e["cx"], e["cy"] - e["top"]),
                    (key, "s", e["cx"], e["cy"] + e["bottom"])]
        return out

    def _press(self, x: float, y: float) -> None:
        if self.disc is None:
            return
        best, hit = 14 / self.view.scale(), None
        for h in self._handles():
            d = math.hypot(h[2] - x, h[3] - y)
            if d < best:
                best, hit = d, h
        if hit:
            e = getattr(self, hit[0])
            self._drag = (hit[0], hit[1], x - e["cx"], y - e["cy"])

    def _move(self, x: float, y: float) -> None:
        if not self._drag:
            return
        key, h, ox, oy = self._drag
        e = getattr(self, key)
        if h == "c":
            e["cx"], e["cy"] = x - ox, y - oy
        elif h == "e":                        # each point on its own: the opposite one stays
            e["right"] = max(5.0, x - e["cx"])
        elif h == "w":
            e["left"] = max(5.0, e["cx"] - x)
        elif h == "n":
            e["top"] = max(5.0, e["cy"] - y)
        else:
            e["bottom"] = max(5.0, y - e["cy"])
        self._changed()

    def _changed(self) -> None:
        self._report()
        self.view.update()

    def _overlay(self, p: QPainter) -> None:
        if self.disc is None:
            return
        u = self.img.shape[1] / 600
        for e, col in ((self.disc, DISC_COLOR), (self.cup, CUP_COLOR)):
            p.setPen(QPen(col, 2.5 * u))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(_outline_path(e))
        for key, _h, x, y in self._handles():
            p.setPen(QPen(QColor("#111111"), 1.5 * u))
            p.setBrush(DISC_COLOR if key == "disc" else CUP_COLOR)
            p.drawEllipse(QPointF(x, y), 6 * u, 6 * u)
        d, right = self.disc, ("N" if self.eye_key == "OD" else "T")
        left = "T" if right == "N" else "N"
        f = QFont()
        f.setPixelSize(max(8, round(15 * u)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        for text, x, y in (("S", d["cx"], d["cy"] - d["top"] - 16 * u), ("I", d["cx"], d["cy"] + d["bottom"] + 16 * u),
                           (right, d["cx"] + d["right"] + 16 * u, d["cy"]), (left, d["cx"] - d["left"] - 16 * u, d["cy"])):
            p.drawText(QRectF(x - 20 * u, y - 12 * u, 40 * u, 24 * u), Qt.AlignmentFlag.AlignCenter, text)

    def _report(self) -> None:
        m = self.metrics()
        if not m:
            return
        v = m["vertical"]
        band = "0.7 이상" if v >= 0.7 else "0.5~0.7" if v >= 0.5 else "0.5 미만"
        self.lbl_v.setText(f"{v:.2f}")
        self.lbl_ratio.setText(f"<span style='color:{theme.TEXT2}'>{band}</span><br>"
                               f"수평 C/D <b>{m['horizontal']:.2f}</b> &nbsp;·&nbsp; 면적 C/D <b>{m['area']:.2f}</b>"
                               f" &nbsp;·&nbsp; 림 면적 <b>{(1 - m['area']) * 100:.0f}%</b>")
        rim = m["rim"]
        rows = "".join(f"<tr><td>{k} {ko}&nbsp;&nbsp;&nbsp;</td><td align='right'>"
                       f"{'경계 밖' if rim[k] < 0 else f'{rim[k]:.3f} DD'}</td></tr>"
                       for k, ko in (("I", "하측"), ("S", "상측"), ("N", "비측"), ("T", "이측")))
        verdict = (f"<b style='color:{theme.ORANGE}'>ISNT 어긋남</b> — " + ", ".join(m["isnt"])) if m["isnt"] \
            else f"<b style='color:{theme.GREEN}'>ISNT 순서 유지</b>"
        self.lbl_rim.setText(f"<table>{rows}</table><br>{verdict}")

    def note(self) -> str:
        m = self.metrics()
        return f"녹내장 분석 — 수직 C/D {m['vertical']:.2f}" if m else "녹내장 분석 — C/D"

    def image_ids(self) -> list[int]:
        return [self.photo.image_id] if self.photo is not None else []

    def eye(self) -> str | None:
        return self.eye_key


# -- 3D ----------------------------------------------------------------------------------------------
S3_ONE = "사진 한 장의 밝기로 추정한 모양입니다 (창백한 곳 = 깊은 곳). 실제 깊이를 잰 것이 아닙니다."
S3_HINT = "사진을 끌면 돌아갑니다. 깊이는 과장해서 보여 주는 상대값입니다."
S3_CD = ("입체 표면에서 기준 깊이보다 깊은 곳을 컵(노란 선)으로 본 추정값입니다. 디스크 경계(초록 선)는 "
         "[디스크 C/D] 탭의 초록 선입니다 — 거기서 맞추면 여기도 따라옵니다.")
S3_SPREAD = 0.10         # two photos' vertical C/D further apart than this: say so
S3_NO_CUP = "컵이 뚜렷하지 않아 이 표면에서는 C/D를 추정하지 못했습니다 — [디스크 C/D] 탭에서 직접 맞추세요."


class Surface3DTab(_Tab):
    """The optic disc as a surface to turn (``disc3d.py``): its shape estimated from one photo's
    brightness, or — with two photos of the same disc — from the parallax between them. The two
    photos can also be flickered on the surface."""
    ROCK_YAW, ROCK_PITCH, ROCK_S = 16.0, 6.0, 4.0        # 자동으로 흔들기: degrees each way, seconds a swing
    LIMIT = 65.0                                         # how far the surface turns (degrees)

    def __init__(self, photo: Photo | None, second: Photo | None = None, parent=None, disc_tab=None):
        super().__init__(NEED_ONE, parent)
        self.photos = [p for p in (photo, second) if p is not None]
        self.disc_tab = disc_tab                         # its green outline is the disc margin here
        self._cup: dict = {}
        eyes = {p.eye for p in self.photos if p.eye}
        days = {p.day for p in self.photos if p.day}
        self.follow_up = len(self.photos) == 2 and len(days) == 2     # two days: a follow-up, not a stereo pair
        self.stereo_ok = len(self.photos) == 2 and len(eyes) < 2 and not self.follow_up   # (nor is OD with OS)
        self.source = "stereo" if self.stereo_ok else "a"
        self.field = "normal"
        self.yaw, self.pitch = -22.0, 14.0
        self.info: dict = {}
        self._tex: list = []
        self._heights: dict = {}
        self._phase = 0
        self._t0 = time.monotonic()
        self._drag = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self.hint.setText(S3_HINT)

        self.sources = None
        self.sw_flip = Switch("깊이 뒤집기")
        self.sw_flip.setToolTip("컵이 솟아 보이면 켭니다 (어느 사진이 왼쪽에서 찍혔는지는 알 수 없습니다)")
        self.sw_flip.toggled.connect(lambda _on: self._shape_changed())
        self.sw_flick = Switch("두 사진 깜빡임")
        self.sw_flick.setToolTip("같은 표면 위에서 사진 ①과 ②를 번갈아 보여 줍니다")
        self.sw_flick.toggled.connect(lambda _on: self._restart())
        self.speed = _Slider("깜빡임 속도", 1, 6, 2, 1, lambda v: f"{v:.0f} Hz")
        self.fields = _Choice(DISC_FIELDS)
        self.fields.set("normal")
        self.fields.changed.connect(self.set_field)
        self.fields.setToolTip("화면에 담을 범위 — 유두 지름의 몇 배인지")
        self.status = _note()
        rows = [self.fields, self.status]
        if len(self.photos) == 2:
            self.sources = _Choice([("a", "사진 ①", "사진 ① 한 장으로 추정"), ("b", "사진 ②", "사진 ② 한 장으로 추정"),
                                    ("stereo", "2장 스테레오", "두 사진의 시차로 깊이 계산")])
            self.sources.set(self.source)
            self.sources.changed.connect(self.set_source)
            rows = [self.sources, self.fields, self.sw_flip, self.sw_flick, self.speed, self.status]
        self.side.addWidget(card("모양 (깊이)", *rows, lines=False))

        self.s_depth = _Slider("깊이 과장", 0, 200, 100, 5, lambda v: f"{v:.0f}%")
        self.s_depth.changed.connect(lambda _v: self._draw())
        self.sw_auto = Switch("자동으로 흔들기")
        self.sw_auto.setChecked(True)
        self.sw_auto.toggled.connect(lambda _on: self._restart())
        self.sw_light = Switch("입체 조명")
        self.sw_light.setChecked(True)
        self.sw_contour = Switch("등고선")
        self.sw_contour.setToolTip("같은 깊이를 잇는 선 — 파랑은 들어간 곳, 주황은 솟은 곳")
        self.sw_ana = Switch("적청 안경")
        self.sw_ana.setToolTip("적청 안경(왼쪽 빨강, 오른쪽 청록)으로 보는 입체 화면")
        for sw in (self.sw_light, self.sw_contour, self.sw_ana):
            sw.toggled.connect(lambda _on: self._draw())
        self.b_front = _button("정면", tip="돌리기 전의 사진 그대로")
        self.b_tilt = _button("비스듬히")
        self.b_front.clicked.connect(lambda: self.set_view(0.0, 0.0))
        self.b_tilt.clicked.connect(lambda: self.set_view(-22.0, 14.0))
        self.side.addWidget(card("보기", self.s_depth, self.sw_auto, self.sw_light, self.sw_contour, self.sw_ana,
                                 _pair_row(self.b_front, self.b_tilt)))
        self.lbl_cd = QLabel("–")
        f = QFont(self.lbl_cd.font())
        f.setPixelSize(30)
        f.setBold(True)
        self.lbl_cd.setFont(f)
        self.lbl_cd2 = QLabel()
        self.lbl_cd2.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_cd2.setWordWrap(True)
        self.s_level = _Slider("컵 기준 깊이", 10, 80, disc3d.CUP_LEVEL * 100, 5, lambda v: f"{v:.0f}%")
        self.s_level.setToolTip("가장 깊은 곳까지의 깊이 중 이만큼보다 깊은 곳을 컵으로 봅니다 — 올리면 컵이 작아집니다")
        self.s_level.changed.connect(lambda _v: self._draw())
        self.sw_lines = Switch("디스크 · 컵 선")
        self.sw_lines.setChecked(True)
        self.sw_lines.toggled.connect(lambda _on: self._draw())
        self.b_apply = _button("디스크 C/D 탭에 적용", tip="이 컵 경계를 [디스크 C/D] 탭의 노란 선으로 옮깁니다 — "
                                                       "거기서 다듬고 림 두께 · ISNT를 봅니다")
        self.b_apply.clicked.connect(self.apply_to_disc_tab)
        self.b_apply.setVisible(disc_tab is not None)
        self.side.addWidget(card("수직 C/D (추정)", self.lbl_cd, self.lbl_cd2, self.s_level, self.sw_lines,
                                 self.b_apply, _note(S3_CD)))
        self.side.addStretch(1)
        self.view.pressed.connect(self._press)
        self.view.moved.connect(self._move)
        self.view.released.connect(lambda: setattr(self, "_drag", None))
        self.set_field("normal")
        if self.source == "stereo" and not self.info.get("reliable", True):
            self.set_source("a")                         # not a stereo pair after all: one photo's estimate

    # -- the photos and the shape ----------------------------------------------------------------
    def _factor(self) -> float:
        return {k: f for k, _, f in DISC_FIELDS}[self.field]

    def set_field(self, field: str) -> None:
        """Cut each photo around its disc, ``field`` disc diameters wide; the second is moved
        onto the first."""
        self.field = field
        self.fields.set(field)
        self._tex, self._heights = [], {}
        size = np.empty((disc3d.TEX_PX, disc3d.TEX_PX, 3), np.uint8)
        for ph in self.photos:
            crop, _, _ = G.crop_square(ph.rgb, *ph.disc, self._factor() * ph.disc_px)
            self._tex.append(np.ascontiguousarray(G.match_size(crop, size)))
        if len(self._tex) == 2:
            self._tex[1] = G.shifted(self._tex[1], *G.find_shift(self._tex[0], self._tex[1]))
        self._shape_changed()

    def set_source(self, source: str) -> None:
        if source == "stereo" and len(self.photos) < 2:
            return
        self.source = source
        if self.sources is not None:
            self.sources.set(source)
        self._shape_changed()

    def _surface(self, source: str) -> tuple[np.ndarray, dict] | None:
        """The surface of ``source`` (a · b · stereo) and what is known of it."""
        if not self._tex or (source != "a" and len(self._tex) < 2):
            return None
        key = (source, self.sw_flip.isChecked())
        if key not in self._heights:
            frac = 1.0 / self._factor()
            if source == "stereo":
                self._heights[key] = disc3d.height_from_stereo(self._tex[0], self._tex[1], frac,
                                                               flip=self.sw_flip.isChecked())
            else:
                info: dict = {}
                self._heights[key] = (disc3d.height_from_photo(self._tex[source == "b"], frac, info=info), info)
        return self._heights[key]

    def heights(self) -> np.ndarray | None:
        found = self._surface(self.source)
        if found is None:
            return None
        H, self.info = found
        return H

    def _shape_changed(self) -> None:
        stereo = self.source == "stereo"
        self.sw_flip.setVisible(stereo)
        self.heights()
        if not self._tex:
            self.status.setText("")
        elif not stereo:
            self.status.setText(S3_ONE)
        else:
            px = self.info.get("parallax", 0.0)
            text = f"두 사진의 시차로 계산한 깊이입니다 (최대 시차 {px:.1f} px · 상대값, 길이 아님)."
            if not self.info.get("enough", True):
                text = (f"최대 시차 {px:.1f} px — 시차가 부족해 깊이가 믿을 만하지 않습니다. 두 사진 사이를 더 벌려 "
                        "다시 찍거나 [사진 ①] 한 장 추정으로 보세요.")
            elif self.follow_up:
                text = ("두 사진이 서로 다른 날짜입니다 — 그 사이의 변화가 시차로 잡혀 스테레오 깊이는 맞지 않습니다. "
                        "[사진 ①] · [사진 ②]로 보고, 날짜별 C/D는 아래 경과에 나옵니다.")
            elif not self.stereo_ok:
                text = "두 사진이 서로 다른 눈(OD · OS)입니다 — 스테레오 깊이는 같은 눈의 두 장에서만 맞습니다."
            elif not self.info.get("reliable", True):
                text = ("두 사진이 스테레오 쌍으로 맞지 않아 깊이가 믿을 만하지 않습니다 (유두 둘레가 고르게 나오지 않음). "
                        "같은 곳을 보게 하고 카메라만 옆으로 조금 옮겨 찍은 두 장이 필요합니다 — [사진 ①] 한 장 추정으로 보세요.")
            self.status.setText(text)
        self._restart()
        self._draw()

    # -- the view --------------------------------------------------------------------------------
    def set_view(self, yaw: float, pitch: float) -> None:
        self.sw_auto.setChecked(False)
        self.yaw = max(-self.LIMIT, min(self.LIMIT, yaw))
        self.pitch = max(-self.LIMIT, min(self.LIMIT, pitch))
        self._draw()

    def _press(self, x: float, y: float) -> None:
        angles = self._angles()
        self.sw_auto.setChecked(False)
        self.yaw, self.pitch = angles
        self._drag = (x, y, self.yaw, self.pitch)

    def _move(self, x: float, y: float) -> None:
        if self._drag is not None:
            x0, y0, yaw, pitch = self._drag
            self.set_view(yaw + (x - x0) * 0.3, pitch - (y - y0) * 0.3)

    def _angles(self) -> tuple[float, float]:
        if not self.sw_auto.isChecked():
            return self.yaw, self.pitch
        a = 2 * math.pi * (time.monotonic() - self._t0) / self.ROCK_S
        return self.ROCK_YAW * math.sin(a), self.pitch * 0.5 + self.ROCK_PITCH * math.cos(a)

    def _flickering(self) -> bool:
        return len(self._tex) == 2 and self.sw_flick.isChecked()

    def _restart(self) -> None:
        self.speed.setVisible(self._flickering())
        if self._tex and self.isVisible() and (self.sw_auto.isChecked() or self._flickering()):
            self._timer.start()
        else:
            self._timer.stop()
        self._draw()

    def _tick(self) -> None:
        if not self.isVisible():
            self._timer.stop()
            return
        if self._flickering():
            self._phase = int((time.monotonic() - self._t0) * self.speed.value() * 2) & 1
        self._draw()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._restart()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def shown_photo(self) -> int:
        """Index of the photo drawn on the surface now."""
        if self._flickering():
            return self._phase
        return 1 if self.source == "b" else 0

    def depth_px(self) -> float:
        return self.s_depth.value() / 100.0 * disc3d.DEPTH_DD * disc3d.TEX_PX / self._factor()

    # -- C/D from the surface --------------------------------------------------------------------
    def disc_outline(self) -> dict:
        """The disc margin in texture pixels: the green outline of the 디스크 C/D tab (of the same
        photo, whatever field that tab shows), or a disc of the expected size in the middle."""
        c, r = (disc3d.TEX_PX - 1) / 2.0, disc3d.TEX_PX / self._factor() / 2.0
        t = self.disc_tab
        if t is not None and t.disc is not None and t.img is not None:
            side = float(t.img.shape[0])
            k = r / (side / {k: f for k, _, f in DISC_FIELDS}[t.field] / 2.0)
            d = t.disc
            return {"cx": c + (d["cx"] - side / 2.0) * k, "cy": c + (d["cy"] - side / 2.0) * k,
                    **{key: d[key] * k for key in ("top", "right", "bottom", "left")}}
        return G.outline({"cx": c, "cy": c, "rx": r * 0.95, "ry": r * 1.05})

    def cup(self, source: str | None = None) -> tuple[dict, dict, np.ndarray] | None:
        """(disc outline, cup outline, the cup's margin) in texture pixels — the cup as the surface
        of ``source`` (the one shown, if None) has it (``disc3d.cup_from_surface``) — or None: no
        surface, no cup seen in the photo, or a stereo depth that is not to be trusted."""
        source = source or self.source
        surface = self._surface(source)
        if surface is None or not surface[1].get("cup", True) or not surface[1].get("reliable", True):
            return None
        if source == "stereo" and not self.stereo_ok:
            return None
        H = surface[0]
        disc = self.disc_outline()
        key = (source, self.sw_flip.isChecked(), self.field, self.s_level.value(), tuple(disc.values()))
        if key not in self._cup:
            k = H.shape[0] / disc3d.TEX_PX                # (the surface is coarser than the texture)
            small = {**{a: disc[a] * k for a in ("top", "right", "bottom", "left")},
                     "cx": (disc["cx"] + 0.5) * k - 0.5, "cy": (disc["cy"] + 0.5) * k - 0.5}
            found = disc3d.cup_from_surface(H, small, self.s_level.value() / 100.0)
            if found is not None:
                cup, edge = found
                cup = {**{a: cup[a] / k for a in ("top", "right", "bottom", "left")},
                       "cx": (cup["cx"] + 0.5) / k - 0.5, "cy": (cup["cy"] + 0.5) / k - 0.5}
                found = (disc, cup, (edge + 0.5) / k - 0.5)
            if len(self._cup) > 12:                      # (a slider dragged: only the last ones are asked again)
                self._cup.clear()
            self._cup[key] = found
        return self._cup[key]

    def metrics(self, source: str | None = None) -> dict | None:
        """C/D of the cup read off the surface (``G.cdr_metrics``) — of the one shown, or of
        ``source`` (a · b · stereo) — or None."""
        found = self.cup(source)
        return G.cdr_metrics(found[0], found[1], self.eye() or "OD") if found else None

    def both(self) -> dict | None:
        """With two photos: vertical C/D of each one's own estimate, of the stereo depth, the mean
        of the two photos and how far they are apart — ``{"a", "b", "stereo", "mean", "spread"}``
        (None where there is none)."""
        if len(self.photos) < 2:
            return None
        v = {k: (m["vertical"] if (m := self.metrics(k)) else None) for k in ("a", "b", "stereo")}
        ab = [x for x in (v["a"], v["b"]) if x is not None]
        v["mean"] = sum(ab) / 2 if len(ab) == 2 else None
        v["spread"] = abs(ab[0] - ab[1]) if len(ab) == 2 else None
        # two days: a follow-up — the older photo first, and the change to the newer one
        days = [p.day for p in self.photos]
        v["days"] = None
        if days[0] and days[1] and days[0] != days[1]:
            old, new = ("a", "b") if days[0] < days[1] else ("b", "a")
            v["days"] = {"old": old, "new": new, "old_day": min(days), "new_day": max(days),
                         "change": v[new] - v[old] if len(ab) == 2 else None}
        return v

    def apply_to_disc_tab(self) -> None:
        """The cup found here becomes the yellow outline of the 디스크 C/D tab."""
        found, t = self.cup(), self.disc_tab
        if not found or t is None or t.disc is None:
            return
        c, r = (disc3d.TEX_PX - 1) / 2.0, disc3d.TEX_PX / self._factor() / 2.0
        side = float(t.img.shape[0])
        k = (side / {k: f for k, _, f in DISC_FIELDS}[t.field] / 2.0) / r
        cup = found[1]
        t.set_ellipses(t.disc, {"cx": side / 2.0 + (cup["cx"] - c) * k, "cy": side / 2.0 + (cup["cy"] - c) * k,
                                **{key: cup[key] * k for key in ("top", "right", "bottom", "left")}})

    def _report(self) -> None:
        m = self.metrics()
        self.b_apply.setEnabled(m is not None)
        if m is None:
            self.lbl_cd.setText("–")
            self.lbl_cd2.setText(f"<span style='color:{theme.TEXT2}'>{S3_NO_CUP if self._tex else ''}</span>"
                                 + self._both_text())
            return
        v = m["vertical"]
        band = "0.7 이상" if v >= 0.7 else "0.5~0.7" if v >= 0.5 else "0.5 미만"
        self.lbl_cd.setText(f"{v:.2f}")
        self.lbl_cd2.setText(f"<span style='color:{theme.TEXT2}'>{band}</span><br>"
                             f"수평 C/D <b>{m['horizontal']:.2f}</b> &nbsp;·&nbsp; 면적 C/D <b>{m['area']:.2f}</b>"
                             + self._both_text())

    def _both_text(self) -> str:
        """Two photos: each one's vertical C/D side by side (the one shown in bold)."""
        v = self.both()
        if not v:
            return ""
        def cell(key, name):
            text = f"{name} {v[key]:.2f}" if v[key] is not None else f"{name} –"
            return f"<b>{text}</b>" if key == self.source else text
        if v["days"]:                                     # a follow-up: then → now
            d = v["days"]
            out = (f"<br><br>경과 (수직 C/D)<br>{cell(d['old'], d['old_day'])} &nbsp;→&nbsp; "
                   f"{cell(d['new'], d['new_day'])}")
            if d["change"] is not None:
                big = abs(d["change"]) > S3_SPREAD
                out += (f"<br>변화 <b style='color:{theme.ORANGE if big else theme.TEXT}'>{d['change']:+.2f}</b>"
                        + ("" if big else f" <span style='color:{theme.TEXT2}'>(추정 오차 범위 안)</span>"))
                out += (f"<br><span style='color:{theme.TEXT2}'>같은 디스크 경계 · 같은 기준 깊이로 두 날짜를 잰 "
                        "값입니다. 밝기 · 초점이 다르면 달라질 수 있어 [경과 비교] 탭의 깜빡임과 함께 보세요.</span>")
            return out
        out = "<br><br>수직 C/D — " + " &nbsp;·&nbsp; ".join(
            cell(k, n) for k, n in (("a", "사진 ①"), ("b", "사진 ②"), ("stereo", "스테레오")))
        if v["mean"] is not None:
            out += f"<br>두 사진 평균 <b>{v['mean']:.2f}</b> (차이 {v['spread']:.2f})"
            if v["spread"] > S3_SPREAD:
                out += (f"<br><span style='color:{theme.ORANGE}'>두 사진의 값이 많이 다릅니다 — 초점 · 밝기가 "
                        "다르거나 경계가 뚜렷하지 않습니다.</span>")
        return out

    def _texture(self) -> np.ndarray:
        """The photo to lay on the surface, with the disc (green) and cup (yellow) lines on it."""
        tex = self._tex[self.shown_photo()]
        found = self.cup() if self.sw_lines.isChecked() else None
        if not found:
            return tex
        tex = tex.copy()
        for pts, col in ((disc3d.outline_points(found[0]), DISC_COLOR), (found[2], CUP_COLOR)):
            line = [np.round(pts * 8).astype(np.int32)]
            cv2.polylines(tex, line, True, (20, 20, 20), 5, cv2.LINE_AA, shift=3)      # (seen on a pale cup too)
            cv2.polylines(tex, line, True, (col.red(), col.green(), col.blue()), 2, cv2.LINE_AA, shift=3)
        return tex

    def compose(self):
        H = self.heights()
        if H is None:
            return None
        yaw, pitch = self._angles()
        kw = dict(light=1.0 if self.sw_light.isChecked() else 0.0, contours=self.sw_contour.isChecked())
        draw = disc3d.anaglyph if self.sw_ana.isChecked() else disc3d.render
        return draw(self._texture(), H, self.depth_px(), yaw, pitch, **kw)

    def _draw(self) -> None:
        self._report()
        self.view.set_rgb(self.compose())

    def note(self) -> str:
        m = self.metrics()
        return ("녹내장 분석 — 유두 3D " + ("(2장 스테레오)" if self.source == "stereo" else "(1장 추정)")
                + (f" · 추정 수직 C/D {m['vertical']:.2f}" if m else "")
                + self._both_note())

    def _both_note(self) -> str:
        v = self.both()
        if not v or v["mean"] is None:
            return ""
        if v["days"]:
            d = v["days"]
            return f" ({d['old_day']} {v[d['old']]:.2f} → {d['new_day']} {v[d['new']]:.2f})"
        return f" (두 사진 평균 {v['mean']:.2f})"

    def image_ids(self) -> list[int]:
        if self.source == "stereo" or self._flickering():
            return [p.image_id for p in self.photos]
        return [self.photos[self.source == "b"].image_id] if self.photos else []

    def eye(self) -> str | None:
        if not self.photos:
            return None
        if self.source == "stereo":
            eyes = {p.eye for p in self.photos}
            return eyes.pop() if len(eyes) == 1 else None
        return self.photos[self.source == "b"].eye


# -- wide field ------------------------------------------------------------------------------------
WD_KINDS = ["RNFL 결손", "디스크 출혈", "기타"]


class WideTab(_Tab):
    """The whole photo, red-free with the nerve fibre layer brought out; findings are marked
    and named by clock hour, Garway-Heath sector and the visual field they match."""

    def __init__(self, photo: Photo | None, parent=None):
        super().__init__(NEED_ONE, parent)
        self.photo = photo
        self.src = G.fit(photo.rgb) if photo is not None else None
        self.disc = self.fovea = None
        if photo is not None:
            k = G.fit_scale(photo.rgb.shape)
            if photo.disc_found:
                self.disc = (photo.disc[0] * k, photo.disc[1] * k)
            if photo.fovea is not None:
                self.fovea = (photo.fovea[0] * k, photo.fovea[1] * k)
        self.marks: list = []
        self.tool = "disc"
        self.sw_rf = Switch("레드프리 (녹색 채널)")
        self.sw_rf.setChecked(True)
        self.sw_rf.toggled.connect(lambda _on: self._enhance())
        self.s_k = _Slider("RNFL 대비 강화", 0, 3, 1.5, 0.1, lambda v: f"{v:.1f}")
        self.s_k.changed.connect(lambda _v: self._enhance())
        self.side.addWidget(card("강조", self.sw_rf, self.s_k))
        self.tools = _Choice([("mark", "소견 표시"), ("disc", "유두 지정"), ("fovea", "황반 지정")])
        self.tools.changed.connect(self.set_tool)
        self.c_kind = QComboBox()
        self.c_kind.addItems(WD_KINDS)
        self.b_clear = _button("표시 지우기")
        self.b_clear.clicked.connect(self.clear_marks)
        self.side.addWidget(card("사진을 눌러서", self.tools, _pair_row(self.c_kind, self.b_clear)))
        self.sw_sec = Switch("디스크 구역 (Garway-Heath)")
        self.sw_vf = Switch("시야검사 24-2 격자")
        for sw in (self.sw_sec, self.sw_vf):
            sw.setChecked(True)
            sw.toggled.connect(lambda _on: self._changed())
        self.lbl_geo = _note()
        self.side.addWidget(card("겹쳐 보기", self.sw_sec, self.sw_vf, self.lbl_geo))
        self.lbl_list = QLabel()
        self.lbl_list.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_list.setWordWrap(True)
        self.side.addWidget(card("소견 목록", self.lbl_list))
        self.side.addStretch(1)
        self.view.overlay = self._overlay
        self.view.pressed.connect(self.click)
        self.set_tool("disc" if self.disc is None else "fovea" if self.fovea is None else "mark")
        self._enhance()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.tools.set(tool)

    def clear_marks(self) -> None:
        self.marks = []
        self._changed()

    def click(self, x: float, y: float) -> None:
        if self.tool == "disc":
            self.disc = (x, y)
            self.set_tool("mark" if self.fovea else "fovea")
        elif self.tool == "fovea":
            self.fovea = (x, y)
            self.set_tool("mark" if self.disc else "disc")
        elif self.disc and self.fovea:
            self.marks.append((x, y, self.c_kind.currentText()))
        self._changed()

    def findings(self) -> list:
        if not (self.disc and self.fovea):
            return []
        return [dict(G.sector_info(self.disc, self.fovea, (x, y)), kind=kind) for x, y, kind in self.marks]

    def _enhance(self) -> None:
        if self.src is None:
            return
        self.view.set_rgb(G.enhance_wide(self.src, self.sw_rf.isChecked(), self.s_k.value()))
        self._changed()

    def _changed(self) -> None:
        ready = bool(self.disc and self.fovea)
        self.hint.setText("사진을 누르면 소견이 표시되고, 시계 방향 · 구역 · 대응 시야가 목록에 나옵니다." if ready
                          else "먼저 시신경 유두 중심을, 이어서 황반을 눌러 지정하세요.")
        if ready:
            ax = G.axes(self.disc, self.fovea)
            ang = G.disc_fovea_angle(self.disc, self.fovea)
            self.lbl_geo.setText(f"{'OD (우안)' if ax['od'] else 'OS (좌안)'}  ·  유두–황반 각 "
                                 f"{abs(ang):.1f}° {'아래' if ang >= 0 else '위'}")
            items = [f"<b>{k}. {f['kind']} · {f['hour']}시 방향</b><br>{f['sector']} 구역, 유두에서 {f['dd']:.1f} DD"
                     f"<br>대응 시야: {f['field']}" for k, f in enumerate(self.findings(), 1)]
            self.lbl_list.setText("<br><br>".join(items) or "아직 표시한 소견이 없습니다.")
        else:
            self.lbl_geo.setText("")
            self.lbl_list.setText("유두와 황반을 지정하면 계산됩니다.")
        self.view.update()

    def _overlay(self, p: QPainter) -> None:
        if self.src is None:
            return
        u = self.src.shape[1] / 900
        if self.disc and self.fovea:
            if self.sw_sec.isChecked():
                for _name, rgb, pts in G.sector_polygons(self.disc, self.fovea):
                    p.setPen(QPen(QColor(0, 0, 0, 150), 1))
                    p.setBrush(QColor(*rgb, 150))
                    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
            if self.sw_vf.isChecked():
                p.setPen(QPen(QColor(0, 0, 0, 190), 1))
                for x, y, upper in G.vf_points(self.disc, self.fovea):
                    p.setBrush(QColor("#58d6ff") if upper else QColor("#ffc14a"))
                    p.drawEllipse(QPointF(x, y), 3.2 * u, 3.2 * u)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.2 * u, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(*self.disc), QPointF(*self.fovea))
        f = QFont()
        f.setPixelSize(max(8, round(12 * u)))
        f.setBold(True)
        p.setFont(f)
        for pt, col, text in ((self.disc, DISC_COLOR, "유두"), (self.fovea, CUP_COLOR, "황반")):
            if pt:
                p.setPen(QPen(QColor("#000000"), 1.5 * u))
                p.setBrush(col)
                p.drawEllipse(QPointF(*pt), 5 * u, 5 * u)
                p.setPen(QColor("#ffffff"))
                p.drawText(QPointF(pt[0] + 8 * u, pt[1] - 8 * u), text)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k, (x, y, _kind) in enumerate(self.marks, 1):
            p.setPen(QPen(QColor("#ffffff"), 2.5 * u))
            p.drawEllipse(QPointF(x, y), 11 * u, 11 * u)
            p.setPen(QPen(QColor(theme.RED), 1.5 * u))
            p.drawEllipse(QPointF(x, y), 11 * u, 11 * u)
            p.setPen(QColor("#ffffff"))
            p.drawText(QPointF(x + 14 * u, y + 4 * u), str(k))

    def note(self) -> str:
        n = len(self.findings())
        return f"녹내장 분석 — 광각 RNFL (소견 {n}곳)" if n else "녹내장 분석 — 광각 RNFL"

    def image_ids(self) -> list[int]:
        return [self.photo.image_id] if self.photo is not None else []

    def eye(self) -> str | None:
        if self.disc and self.fovea:
            return "OD" if G.axes(self.disc, self.fovea)["od"] else "OS"
        return self.photo.eye if self.photo is not None else None


# -- progression -------------------------------------------------------------------------------------
PG_MODES = [("flick", "깜빡임"), ("blend", "겹치기"), ("diff", "변화 지도")]
PG_HINT = {
    "flick": "맞춘 두 사진을 번갈아 보여 줍니다. 움직이거나 나타나는 부분이 변화입니다.",
    "blend": "슬라이더로 기준 사진과 추적 사진을 섞어 봅니다.",
    "diff": "밝기 차이가 큰 곳을 분홍색으로 표시합니다. 조명 차이도 함께 잡히므로 깜빡임으로 확인하세요.",
}


class ProgressTab(_PairTab):
    """An earlier and a later photo of the same eye, registered: what changed between them."""

    def __init__(self, pair, parent=None):
        if pair:
            pair = sorted(pair, key=lambda ph: (ph.when or "", ph.image_id))     # the earlier photo is the baseline
        super().__init__(pair, parent)
        self.mode = "flick"
        self.modes = _Choice(PG_MODES)
        self.modes.changed.connect(self.set_mode)
        self.speed = _Slider("깜빡임 속도", 1, 6, 2, 1, lambda v: f"{v:.0f} Hz")
        self.speed.changed.connect(lambda _v: self._restart())
        self.mix = _Slider("기준 ↔ 추적", 0, 100, 50, 1, lambda v: f"{v:.0f}%")
        self.mix.changed.connect(lambda _v: self._draw())
        self.lbl_dates = _note()
        if self.pair:
            self.lbl_dates.setText(f"기준: {self.pair[0].day or '날짜 미상'}  →  추적: {self.pair[1].day or '날짜 미상'}")
        self.side.addWidget(card("비교 방식", self.modes, self.speed, self.mix, self.lbl_dates, lines=False))
        self.side.addWidget(self.align_card())
        self.side.addStretch(1)
        self.set_region("disc")
        self.set_mode("flick")

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.modes.set(mode)
        self.hint.setText(PG_HINT[mode])
        self.speed.setVisible(mode == "flick")
        self.mix.setVisible(mode == "blend")
        self._restart()
        self._draw()

    def _alternating(self) -> bool:
        return self.mode == "flick"

    def _rate(self) -> float:
        return self.speed.value()

    def compose(self):
        if self.a is None:
            return None
        if self.mode == "flick":
            return self._bs if self._phase else self.a
        if self.mode == "blend":
            return G.blend(self.a, self._bs, self.mix.value() / 100)
        return G.diff_map(self.a, self._bs)

    def note(self) -> str:
        days = " → ".join(p.day for p in self.pair if p.day) if self.pair else ""
        return "녹내장 분석 — 경과 비교" + (f" ({days})" if days else "")


# -- the window --------------------------------------------------------------------------------------
class ExplainTab(_Tab):
    """환자 설명: what glaucoma does at each stage — a schematic disc (the cup grows) beside what the
    patient sees (the field narrows), with a sentence to say. A model, not this patient's stage."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.stage = 0
        self._scene = G.sample_scene(600)
        self.hint.setText("왼쪽: 시신경 유두 모식도 (가운데 밝은 곳이 함몰) · 오른쪽: 환자가 보는 시야 (예시)")
        self.stages = _Choice([(str(i), name) for i, name in enumerate(G.STAGES)])
        self.stages.changed.connect(lambda key: self.set_stage(int(key)))
        self.side.addWidget(card("진행 단계", self.stages, lines=False))
        self.lbl_text = QLabel()
        self.lbl_text.setWordWrap(True)
        self.lbl_cd = _note()
        self.side.addWidget(card("설명", self.lbl_text, self.lbl_cd))
        self.lbl_model = _note(G.NOTE_MODEL)
        self.lbl_model.setStyleSheet(f"color:{theme.ORANGE}; font-weight:600")
        self.side.addWidget(card("", self.lbl_model, _note(
            "이 환자의 사진과 측정은 디스크 C/D · 광각 분석 · 경과 비교 탭에 있습니다."), lines=False))
        self.side.addStretch(1)
        self.set_stage(0)

    def set_stage(self, stage: int) -> None:
        self.stage = max(0, min(len(G.STAGES) - 1, int(stage)))
        if self.stages.key() != str(self.stage):
            self.stages.set(str(self.stage))
        self.view.set_rgb(G.explain_picture(self.stage, 600, self._scene))
        self.lbl_text.setText(G.STAGE_TEXT[self.stage])
        self.lbl_cd.setText(f"모식도의 C/D 약 {G.STAGE_CUP[self.stage]:.1f} · 남은 시야(예시) 약 "
                            f"{round(G.STAGE_FIELD[self.stage] * 100)}%")

    def note(self) -> str:
        return f"녹내장 환자 설명 — {G.STAGES[self.stage]} (설명용 모형)"


class GlaucomaDialog(QDialog):
    """``current`` = the photo on screen (disc, wide field); ``second`` = the ② photo, which with
    ``current`` makes the pair (stereo, progression). ``save_record(rgb, note, eye, image_ids)``
    stores the shown picture in the patient record and returns its id."""

    def __init__(self, current: Photo | None, second: Photo | None = None, *, title_line: str = "",
                 file_stem: str = "녹내장", save_record=None, parent=None, series=None, prefer=(),
                 start: str | None = None):
        """``series``: the photos of this eye over time (``timeline.Shot`` — 시간별 비교), ``prefer``:
        those of them the user picked; ``start="timeline"`` opens on that tab."""
        super().__init__(parent)
        from .timeline_tab import TimelineTab        # (it builds on the widgets of this module)

        self.setWindowTitle("녹내장 분석")
        self._save_record, self.file_stem = save_record, file_stem
        self.saved_id: int | None = None
        pair = (current, second) if current is not None and second is not None else None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.lbl_src = QLabel(title_line)
        self.lbl_src.setStyleSheet("font-weight:600")
        root.addWidget(self.lbl_src)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("views")
        self.tabs.setDocumentMode(True)
        self.disc = DiscTab(current)
        self.surface = Surface3DTab(current, second, disc_tab=self.disc)
        self.surface.b_apply.clicked.connect(lambda: self.tabs.setCurrentWidget(self.disc))
        self.wide = WideTab(current)
        self.stereo = StereoTab(pair)
        self.progress = ProgressTab(pair)
        self.timeline = TimelineTab(series, current.image_id if current is not None else None, prefer)
        self.explain = ExplainTab()
        for tab, text in ((self.disc, "디스크 C/D"), (self.surface, "3D 입체"), (self.wide, "광각 분석"),
                          (self.stereo, "스테레오 보기"), (self.progress, "경과 비교"), (self.timeline, "시간별 비교"),
                          (self.explain, "환자 설명")):
            self.tabs.addTab(tab, text)
        if pair is not None:        # two photos of one day: a stereo pair; of two days: a follow-up
            same_day = current.day and current.day == second.day
            self.tabs.setCurrentWidget(self.stereo if same_day else self.progress)
        if start == "timeline":
            self.tabs.setCurrentWidget(self.timeline)
        root.addWidget(self.tabs, 1)
        foot = _note("측정값은 참고용 추정값입니다. 진단은 의사가 사진을 보고 판단하세요. "
                     "깊이 지도와 3D 입체는 상대값이며 절대 길이가 아닙니다.")
        foot.setStyleSheet(f"color:{theme.TEXT3}")
        root.addWidget(foot)
        btns = QHBoxLayout()
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.GREEN}")
        btns.addWidget(self.status, 1)
        self.b_record = _button("환자 기록에 저장", primary=True,
                                tip="지금 보이는 분석 화면을 이 환자의 새 사진으로 추가 (원본 사진은 그대로)")
        self.b_record.setEnabled(save_record is not None)
        self.b_record.clicked.connect(self.save_to_record)
        self.b_file = _button("파일로 저장…")
        self.b_file.clicked.connect(self.save_file)
        self.b_copy = _button("복사")
        self.b_copy.clicked.connect(self.copy)
        self.b_close = _button("닫기")
        self.b_close.clicked.connect(self.accept)
        for b in (self.b_record, self.b_file, self.b_copy, self.b_close):
            btns.addWidget(b)
        root.addLayout(btns)
        self.resize(1280, 880)

    def shown(self):
        """The current tab's picture (RGB) or None."""
        tab = self.tabs.currentWidget()
        return tab.render() if tab.has_image() else None

    def save_to_record(self) -> int | None:
        tab, rgb = self.tabs.currentWidget(), self.shown()
        if tab is self.explain:        # a model, not a finding of this patient: never into the record
            self.status.setText("환자 설명 그림은 설명용 모형이라 환자 기록에 넣지 않습니다 (파일로 저장 · 복사는 됩니다)")
            return None
        if rgb is None or self._save_record is None:
            self.status.setText("저장할 분석 화면이 없습니다")
            return None
        self.saved_id = self._save_record(rgb, tab.note(), tab.eye(), tab.image_ids())
        self.status.setText(f"환자 기록에 새 사진으로 저장했습니다 — {tab.note()}")
        return self.saved_id

    def save_file(self) -> None:
        rgb = self.shown()
        if rgb is None:
            self.status.setText("저장할 분석 화면이 없습니다")
            return
        path, _ = QFileDialog.getSaveFileName(self, "녹내장 분석 저장", f"{self.file_stem}.jpg",
                                              "JPEG (*.jpg *.jpeg);;PNG (*.png)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".jpg"
        ok = to_qimage(rgb).save(path, quality=95)
        self.status.setText(f"저장했습니다: {path}" if ok else f"저장하지 못했습니다: {path}")

    def copy(self) -> None:
        rgb = self.shown()
        if rgb is None:
            self.status.setText("복사할 분석 화면이 없습니다")
            return
        QApplication.clipboard().setImage(to_qimage(rgb))
        self.status.setText("클립보드에 복사했습니다")
