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

from .. import disc3d, discpair
from .. import glaucoma as G
from ..timeline import common_eye
from . import theme
from .image_view import from_qimage, to_qimage
from .widgets import RoundCorners, Segmented, Switch, card, segment

DISC_COLOR, CUP_COLOR = QColor(theme.GREEN), QColor(theme.YELLOW)
NEED_PAIR = ("사진 두 장이 필요합니다.\n\n사진 목록에서 같은 눈의 사진 두 장을 차례로 클릭해 고른 뒤 (몽타주처럼)\n"
             "[Glaucoma]를 다시 누르세요.")
NEED_ONE = "분석할 사진이 없습니다."
NEED_SAME_EYE = "같은 눈(OD 또는 OS)이 확인된 사진 두 장이 필요합니다.\n다른 눈이나 눈 미상 사진은 한 장씩 분석하세요."
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
    scale_known: bool = False          # ``disc_px`` stands on the camera's field of view (not a guess)

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
        valid = pair is not None and len(pair) == 2 and common_eye(pair) is not None
        super().__init__(NEED_PAIR if not pair else NEED_SAME_EYE, parent)
        self.pair = tuple(pair) if valid else None
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
        # 청구용 한 장: the two discs on a white sheet with the patient's name and the dates (disc_pair.py)
        # — the dialog connects it; it also takes an OD · OS pair, which is no stereo pair
        self.b_sheet = _button("청구용 한 장 (흰 종이)…",
                               tip="두 사진의 시신경 유두만 확대해 환자 이름 · 검사일과 함께 한 장으로 — 보험 청구용\n"
                                   "환자 기록에 저장 · 파일로 저장 · 인쇄 · 복사")
        self.b_sheet.setEnabled(False)
        self.side.addWidget(card("보험 청구용", self.b_sheet,
                                 _note("두 사진의 유두만 확대해 환자 이름 · 검사일과 함께 흰 종이 한 장으로 만듭니다."),
                                 lines=False))
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
# How the ratio is measured, and why (docs/cd_ratio.md has the sources):
# * the disc's margin is the inner edge of the scleral ring, the cup's is where the surface falls away —
#   the contour, shown by the small vessels bending, not the colour (the pale part lags behind the cup
#   in glaucoma, so a cup drawn on pallor alone comes out small);
# * the vertical C/D is the cup's height over the disc's (planimetry); what is normal depends on the
#   disc's size, and the rim tells more than the ratio (ISNT, the narrowest rim: DDLS);
# * from one photo the cup is an estimate — experts reading the same photo differ by up to 0.2 — so the
#   outlines start where the photo puts them and every point is then the examiner's to move.
DT_HINT = ("초록 선은 디스크 경계(공막 고리 안쪽)에, 노란 선은 컵 경계(혈관이 꺾이는 곳)에 맞춥니다. 점은 끄는 대로 "
           "움직이고, 가운데 표시(바깥 고리 = 디스크 · 안쪽 점 = 컵)나 선을 끌면 통째로 옮겨집니다.")
DT_GRAB = 14.0           # a point is taken from this near (screen px)
DT_CUP_DOT = 6.0         # … the cup's centre dot, inside the disc's centre ring, from this near
DT_LINE = 7.0            # … and an outline's line from this near: the whole outline moves
DT_TURN = 6.0            # a point keeps this many degrees from its neighbours (the line does not cross itself)
DT_EST_FIELD = 3.5       # the photo's shape is estimated on this field (disc diameters), whatever the tab
#                          shows — the 3D 입체 tab's 보통, so that both tabs read the same surface
DT_SPREAD = 0.10         # the ways of estimating further apart than this (vertical C/D): say so
DT_NOTE = ("자동 맞춤과 등고선은 사진 한 장의 밝기 · 혈관 꺾임으로 추정한 출발점입니다 (실제 깊이를 잰 것이 아님). "
           "컵은 색이 아니라 윤곽 — 작은 혈관이 꺾이는 곳 — 으로 정합니다: 창백한 곳만 따르면 녹내장에서 컵을 작게 "
           "보기 쉽습니다. 점을 끌어 다듬은 것이 측정값입니다.")
DT_STATE = {
    "disc": {"auto": "디스크 경계: 사진에서 찾음 (밝기가 꺾이는 곳)", "hand": "디스크 경계: 직접 맞춤",
             "given": "디스크 경계: 3D 입체 탭에서 가져옴",
             "none": "디스크 경계: 뚜렷하지 않아 찾지 못함 — 초록 점을 직접 맞추세요",
             "default": "디스크 경계: 기본 크기 — 초록 점을 맞추세요"},
    "cup": {"hand": "컵: 직접 맞춤", "given": "컵: 3D 입체 탭의 컵 경계(등고선)를 가져옴",
            "none": "컵: 등고선에서 찾지 못함 — 노란 점을 직접 맞추세요",
            "default": "컵: 기본 크기 — 노란 점을 맞추세요"},
}


def _poly_path(pts) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(float(x), float(y)) for x, y in pts]))
    path.closeSubpath()
    return path


class DiscTab(_Tab):
    """The optic disc of the photo with two outlines to fit: the disc margin and the cup — each a smooth
    line through ``G.RING`` points that move on their own (wherever they are dragged); the mark in an
    outline's middle (it follows the outline) or its line moves the whole outline. They start where the
    photo puts them: the disc's margin where the brightness falls to the retina (``G.find_disc_margin``),
    the cup on a line of equal depth (등고선) of the shape estimated from the photo (``disc3d``) — drawn
    over the photo with the places where the vessels bend, which is what the cup is judged by."""

    def __init__(self, photo: Photo | None, parent=None, method: str = "hybrid"):
        """``method``: how the photo's shape is estimated at first (``disc3d.METHODS``; 설정 → 일반)."""
        super().__init__(NEED_ONE, parent)
        self.photo = photo
        self.eye_key = photo.eye if photo is not None and photo.eye in ("OD", "OS") else None
        self.img = self.disc = self.cup = None
        self._drag = None
        self._saving = False
        self.field = "normal"
        self.method = method if method in disc3d.METHODS else "hybrid"
        self.state = {"disc": "default", "cup": "default"}       # default · auto · hand · given · none (not found)
        self._tex = None                  # the photo round its disc, as the shape is estimated on
        self._surfaces: dict = {}         # method → (heights, what is known of them)
        self._lines = None                # (key, the lines of equal depth drawn)
        self._spread = None               # (key, each method's vertical C/D)
        self.hint.setText(DT_HINT)
        self.eyes = _Choice([("", "눈 미상"), ("OD", "OD (우안)"), ("OS", "OS (좌안)")])
        self.eyes.set(self.eye_key or "")
        self.eyes.changed.connect(self.set_eye)
        self.fields = _Choice(DISC_FIELDS)
        self.fields.set("normal")
        self.fields.changed.connect(self.set_field)
        self.fields.setToolTip("화면에 담을 범위 — 유두 지름의 몇 배인지 (맞춘 선은 그대로 따라옵니다)")
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

        self.b_auto = _button("자동 맞춤", primary=True,
                              tip="디스크 경계는 밝기가 망막 쪽으로 꺾이는 곳, 컵은 아래 기준 깊이의 등고선 — 그 뒤 점을 끌어 다듬습니다")
        self.b_cup = _button("컵 → 등고선", tip="노란 선만 기준 깊이의 등고선으로 옮깁니다 (초록 선은 그대로)")
        self.b_auto.clicked.connect(lambda: self.auto_fit())
        self.b_cup.clicked.connect(lambda: self.fit_cup())
        self.methods = _Choice(S3_METHODS)
        self.methods.set(self.method)
        self.methods.changed.connect(self.set_method)
        self.methods.setToolTip("등고선을 그리는 모양(깊이)을 사진 한 장에서 추정하는 방법 — 3D 입체 탭과 같습니다")
        self.s_level = _Slider("컵 기준 깊이", 10, 80, disc3d.CUP_LEVEL * 100, 5, lambda v: f"{v:.0f}%")
        self.s_level.setToolTip("가장 깊은 곳까지의 깊이 중 이 등고선보다 깊은 곳을 컵으로 봅니다 — 올리면 컵이 작아집니다.\n"
                                "움직이면 노란 선이 그 등고선으로 옮겨집니다")
        self.s_level.changed.connect(lambda _v: self.fit_cup())
        self.sw_contour = Switch("등고선")
        self.sw_contour.setChecked(True)
        self.sw_contour.setToolTip("추정한 모양에서 같은 깊이를 잇는 선 (10%마다) — 점선이 컵 기준 깊이")
        self.sw_bends = Switch("혈관 꺾임 점")
        self.sw_bends.setChecked(True)
        self.sw_bends.setToolTip("혈관이 꺾인 곳 = 컵 경계의 단서 — 하늘색: 혈관마다 가장 바깥 꺾임 (컵 경계), "
                                 "분홍: 같은 혈관의 안쪽 꺾임")
        for sw in (self.sw_contour, self.sw_bends):
            sw.toggled.connect(lambda _on: self.view.update())
        self.lbl_auto = QLabel()
        self.lbl_auto.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_auto.setWordWrap(True)
        self.side.addWidget(card("자동 맞춤 · 등고선", _pair_row(self.b_auto, self.b_cup), self.methods, self.s_level,
                                 self.sw_contour, self.sw_bends, self.lbl_auto, _note(DT_NOTE)))
        self.lbl_rim = QLabel()
        self.lbl_rim.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_rim.setWordWrap(True)
        self.side.addWidget(card("림 두께 (ISNT · DDLS)", self.lbl_rim,
                                 _note("림 두께는 디스크 수직 지름(DD)에 대한 비율, 림/디스크는 그 방향 디스크 지름에 대한 "
                                       "비율입니다.")))
        self.side.addStretch(1)
        self.view.overlay = self._overlay
        self.view.pressed.connect(self._press)
        self.view.moved.connect(self._move)
        self.view.released.connect(self._release)
        self.set_field("normal")

    # -- the picture and the outlines ----------------------------------------------------------------
    def _factor(self, field: str | None = None) -> float:
        return {k: f for k, _, f in DISC_FIELDS}[field or self.field]

    def set_field(self, field: str) -> None:
        """Cut the photo around its disc, ``field`` disc diameters wide. The outlines stay where they are
        on the photo; the first time they are put where the photo shows the disc and the cup
        (``auto_fit``), or — a photo whose disc was not found — at the size a disc has there."""
        old = (self._factor(), float(self.img.shape[0])) if self.img is not None else None
        self.field = field
        self.fields.set(field)
        if self.photo is None:
            self.warn.setVisible(False)
            return
        factor = self._factor()
        crop, _, _ = G.crop_square(self.photo.rgb, *self.photo.disc, factor * self.photo.disc_px)
        self.img = G.fit(crop, 800)
        side = float(self.img.shape[0])
        self._lines = self._spread = None
        if old is not None and self.disc is not None:            # the same places in the new picture
            k = (old[0] / old[1]) * (side / factor)
            sh = side / 2.0 - old[1] / 2.0 * k
            self.disc, self.cup = G.moved(self.disc, k, sh, sh), G.moved(self.cup, k, sh, sh)
        else:
            self.reset_outlines()
            if self.photo.disc_found:
                self.auto_fit(report=False)
        self.warn.setText("" if self.photo.disc_found else
                          "유두를 찾지 못해 예상 위치를 잘랐습니다 — 2D 사진에서 오른쪽 클릭 → 시신경 유두로 지정")
        self.warn.setVisible(not self.photo.disc_found)
        self.view.set_rgb(self.img)
        self._changed()

    def reset_outlines(self) -> None:
        """Both outlines at the size a disc has in this picture (an upright oval, the cup half of it)."""
        side = float(self.img.shape[0])
        r, c = side / self._factor() / 2.0, side / 2.0
        self.disc = {"pts": G.ring({"cx": c, "cy": c, "rx": r * 0.95, "ry": r * 1.05})}
        self.cup = {"pts": G.ring({"cx": c, "cy": c, "rx": r * 0.45, "ry": r * 0.50})}
        self.state = {"disc": "default", "cup": "default"}

    def set_eye(self, eye: str) -> None:
        self.eye_key = eye if eye in ("OD", "OS") else None
        self.eyes.set(self.eye_key or "")
        self._changed()

    def set_outlines(self, disc: dict, cup: dict, given: bool = False) -> None:
        """The disc and cup outlines (any ``glaucoma`` outline: points, a traced line, an ellipse), each
        taken as its ``G.RING`` points. One handed back as it is keeps what it stands on; ``given``: the
        other comes from the 3D 입체 tab's surface (not set by hand)."""
        new = "given" if given else "hand"
        self.state = {"disc": self.state["disc"] if disc is self.disc else new,
                      "cup": self.state["cup"] if cup is self.cup else new}
        self.disc, self.cup = {"pts": G.ring(disc)}, {"pts": G.ring(cup)}
        self._changed()

    def disc_mm(self) -> float | None:
        """The vertical disc diameter in mm by the photo's scale (the camera's field, a 24 mm eye) — an
        estimate; None where the photo has no scale."""
        if self.photo is None or self.disc is None or not self.photo.scale_known:
            return None
        tall = float(np.ptp(G.curve(self.disc)[:, 1]))
        return discpair.DISC_DIAMETER_MM * tall / (float(self.img.shape[0]) / self._factor())

    def metrics(self) -> dict | None:
        return G.cdr_metrics(self.disc, self.cup, self.eye_key or "OD", self.disc_mm()) if self.disc else None

    # -- the shape estimated from the photo: where the outlines start ------------------------------------
    def _texture(self) -> np.ndarray:
        if self._tex is None:
            crop, _, _ = G.crop_square(self.photo.rgb, *self.photo.disc, DT_EST_FIELD * self.photo.disc_px)
            self._tex = np.ascontiguousarray(
                G.match_size(crop, np.empty((disc3d.TEX_PX, disc3d.TEX_PX, 3), np.uint8)))
        return self._tex

    def _to_tex(self) -> tuple[float, float]:
        """``(k, shift)``: a point p of the picture shown lies at ``p · k + shift`` in that texture."""
        side = float(self.img.shape[0])
        k = (self._factor() / side) * (disc3d.TEX_PX / DT_EST_FIELD)
        return k, (disc3d.TEX_PX - 1) / 2.0 - side / 2.0 * k

    def _on_surface(self, e: dict, n: int) -> dict:
        k, sh = self._to_tex()
        kh = n / disc3d.TEX_PX
        return G.moved(e, k * kh, (sh + 0.5) * kh - 0.5, (sh + 0.5) * kh - 0.5)

    def _off_surface(self, pts, n: int) -> np.ndarray:
        k, sh = self._to_tex()
        kh = n / disc3d.TEX_PX
        return ((np.asarray(pts, np.float64) + 0.5) / kh - 0.5 - sh) / k

    def _surface(self, method: str | None = None) -> tuple[np.ndarray, dict]:
        method = method or self.method
        if method not in self._surfaces:
            info: dict = {}
            self._surfaces[method] = (disc3d.height_one_photo(self._texture(), 1.0 / DT_EST_FIELD, method,
                                                              info=info), info)
        return self._surfaces[method]

    def cup_line(self, method: str | None = None, level: float | None = None) -> np.ndarray | None:
        """The line of equal depth the cup is read on (등고선), (k, 2) in the picture's pixels: the hollow
        of the shape estimated by ``method`` (the one chosen) inside the green outline, ``level`` (컵 기준
        깊이) of the way down (``disc3d.cup_from_surface``) — or None where the photo shows no cup."""
        if self.img is None or self.disc is None:
            return None
        H, info = self._surface(method)
        if not info.get("cup", True):
            return None
        level = self.s_level.value() / 100.0 if level is None else level
        found = disc3d.cup_from_surface(H, self._on_surface(self.disc, H.shape[0]), level)
        return self._off_surface(found[1], H.shape[0]) if found else None

    def auto_fit(self, report: bool = True) -> None:
        """자동 맞춤: the green outline on the disc's margin as the photo shows it, then the yellow one on
        the line of equal depth inside it. What is not found stays as it is."""
        if self.img is None:
            return
        found = G.find_disc_margin(self._texture(), 1.0 / DT_EST_FIELD)
        if found is not None:
            k, sh = self._to_tex()
            self.disc = {"pts": (found["pts"] - sh) / k}
        self.state["disc"] = "auto" if found is not None else "none"
        self.fit_cup(report=False)
        if report:
            self._changed()

    def fit_cup(self, report: bool = True) -> bool:
        """컵 → 등고선: the yellow outline on the line of equal depth at 컵 기준 깊이 (``cup_line``)."""
        line = self.cup_line()
        if line is not None:
            self.cup = {"pts": G.ring({"poly": line})}
        self.state["cup"] = "auto" if line is not None else "none"
        if report:
            self._changed()
        return line is not None

    def set_method(self, method: str) -> None:
        """How the shape is estimated (``disc3d.METHODS``): the lines of equal depth are that shape's, and
        the cup goes onto its line."""
        self.method = method if method in disc3d.METHODS else "hybrid"
        self.methods.set(self.method)
        self._lines = None
        if self.img is not None:
            self.fit_cup()

    def _outline_key(self) -> tuple:
        return self.field, round(self.s_level.value() / 100.0, 3), np.round(self.disc["pts"], 1).tobytes()

    def contours(self) -> list:
        """The lines of equal depth to draw: ``[(level, (k, 2) picture pixels), …]`` — every tenth of the
        way down and the 컵 기준 깊이 — inside the green outline (kept while that is being dragged)."""
        if self.img is None or self.disc is None:
            return []
        key = (self.method,) + self._outline_key()
        if self._lines is None or (self._lines[0] != key and self._drag is None):
            H, info = self._surface()
            lines = []
            if info.get("cup", True):
                levels = sorted(set(disc3d.CONTOUR_LEVELS) | {key[2]})
                lines = [(lv, self._off_surface(edge, H.shape[0])) for lv, edge in
                         disc3d.depth_contours(H, self._on_surface(self.disc, H.shape[0]), levels)]
            self._lines = (key, lines)
        return self._lines[1]

    def by_method(self) -> dict:
        """The vertical C/D each way of estimating the shape gives on its own line of equal depth, for the
        green outline as it is: ``{method: value or None}``. How far they lie apart says how sure the
        photo is about its cup."""
        if self.img is None or self.disc is None:
            return {}
        key = self._outline_key()
        if self._spread is None or (self._spread[0] != key and self._drag is None):
            out = {}
            for m in disc3d.METHODS:
                line = self.cup_line(m)
                out[m] = G.cdr_metrics(self.disc, {"poly": line})["vertical"] if line is not None else None
            self._spread = (key, out)
        return self._spread[1]

    def bends(self) -> tuple[np.ndarray, np.ndarray]:
        """Where the vessels on the disc bend, (k, 2) in the picture's pixels, and whether each is its
        vessel's outermost bend (k,) — the top of the cup's wall, the sign the cup's margin is judged by."""
        none = np.zeros((0, 2)), np.zeros(0, bool)
        if self.img is None:
            return none
        b = self._surface("hybrid")[1].get("bends")
        if b is None or not len(b["weight"]):
            return none
        k, sh = self._to_tex()
        return (b["xy"] * disc3d.TEX_PX - sh) / k, b["weight"] >= 0.4 * float(b["weight"].max())

    # -- moving the points -------------------------------------------------------------------------------
    def _press(self, x: float, y: float) -> None:
        """What lies under the cursor: the nearest point; the mark in an outline's middle (the cup's dot
        first where it lies inside the disc's ring); else an outline's line (the whole outline)."""
        if self.disc is None:
            return
        u = 1.0 / self.view.scale()
        best, hit = DT_GRAB * u, None
        for key in ("cup", "disc"):                              # (the disc's are drawn on top)
            pts = getattr(self, key)["pts"]
            d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
            i = int(np.argmin(d))
            if d[i] <= best:
                best, hit = float(d[i]), (key, i)
        (dx, dy), (cx, cy) = G.centre(self.disc), G.centre(self.cup)
        dd, dc = math.hypot(dx - x, dy - y), math.hypot(cx - x, cy - y)
        mid = (("cup", dc) if dc <= DT_CUP_DOT * u else ("disc", dd) if dd <= DT_GRAB * u and dd <= dc
               else ("cup", dc) if dc <= DT_GRAB * u else ("disc", dd) if dd <= DT_GRAB * u else None)
        if mid is not None and (hit is None or mid[1] < best):
            hit = (mid[0], "c")
        if hit is None:
            near = DT_LINE * u
            for key in ("cup", "disc"):
                c = G.curve(getattr(self, key))
                d = float(np.hypot(c[:, 0] - x, c[:, 1] - y).min())
                if d <= near:
                    near, hit = d, (key, "c")
        if hit is None:
            return
        e = getattr(self, hit[0])
        self._drag = {"key": hit[0], "what": hit[1], "at": (x, y), "pts": e["pts"].copy(), "mid": G.centre(e)}
        self.view.setCursor(Qt.CursorShape.CrossCursor)
        self.view.update()

    @staticmethod
    def _in_turn(pts: np.ndarray, i: int, p, mid) -> np.ndarray:
        """Where point ``i`` goes when dragged to ``p``: there, but kept between its two neighbours as seen
        from the outline's middle (the line does not cross itself) and off the middle itself."""
        def ang(q):
            return math.atan2(q[1] - mid[1], q[0] - mid[0])
        k = len(pts)
        r = max(3.0, math.hypot(p[0] - mid[0], p[1] - mid[1]))
        lo = ang(pts[(i - 1) % k])
        span = (ang(pts[(i + 1) % k]) - lo) % (2.0 * math.pi)
        rel = (ang(p) - lo) % (2.0 * math.pi)
        gap = min(math.radians(DT_TURN), span / 4.0)
        if rel < gap:
            rel = gap
        elif rel > span - gap:                                   # (past the next one, or back past the last)
            rel = span - gap if rel - (span - gap) <= (2.0 * math.pi - rel) + gap else gap
        return np.array([mid[0] + r * math.cos(lo + rel), mid[1] + r * math.sin(lo + rel)])

    def _move(self, x: float, y: float) -> None:
        if not self._drag:
            return
        g = self._drag
        side = float(self.img.shape[0])
        dx, dy = x - g["at"][0], y - g["at"][1]
        pts = g["pts"].copy()
        if g["what"] == "c":                                     # the whole outline (its middle stays inside)
            mx, my = g["mid"]
            pts += (min(max(dx, -mx), side - 1.0 - mx), min(max(dy, -my), side - 1.0 - my))
        else:
            p = np.clip(pts[g["what"]] + (dx, dy), 0.0, side - 1.0)
            pts[g["what"]] = self._in_turn(pts, g["what"], p, g["mid"])
        getattr(self, g["key"])["pts"] = pts
        self.state[g["key"]] = "hand"
        self._changed()

    def _release(self) -> None:
        if self._drag is None:
            return
        self._drag = None
        self.view.unsetCursor()
        self._changed()

    def _changed(self) -> None:
        self._report()
        self.view.update()

    # -- drawing -----------------------------------------------------------------------------------------
    def render(self):
        self._saving = True                                      # (sizes in the picture's own pixels)
        try:
            return super().render()
        finally:
            self._saving = False

    def _overlay(self, p: QPainter) -> None:
        if self.disc is None:
            return
        u = self.img.shape[1] / 600 if self._saving else 1.0 / self.view.scale()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.sw_contour.isChecked():                          # the lines of equal depth, the cup's dashed
            level = self.s_level.value() / 100.0
            for lv, pts in self.contours():
                chosen = abs(lv - level) < 1e-6
                pen = QPen(QColor(100, 210, 255, 240 if chosen else 120), (1.8 if chosen else 1.0) * u)
                if chosen:
                    pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawPath(_poly_path(pts))
        if self.sw_bends.isChecked():
            for (x, y), main in zip(*self.bends()):
                for col, w in ((QColor(20, 20, 20), 3.4), (QColor(*(BEND_USED if main else BEND_INNER)), 1.7)):
                    p.setPen(QPen(col, w * u))
                    p.drawEllipse(QPointF(float(x), float(y)), 6.5 * u, 6.5 * u)
        for key, col in (("cup", CUP_COLOR), ("disc", DISC_COLOR)):
            path = _poly_path(G.curve(getattr(self, key)))
            p.setPen(QPen(QColor(0, 0, 0, 130), 4.2 * u))        # (seen on a pale cup too)
            p.drawPath(path)
            p.setPen(QPen(col, 2.2 * u))
            p.drawPath(path)
        g = self._drag or {}
        for key, col in (("cup", CUP_COLOR), ("disc", DISC_COLOR)):
            for i, (x, y) in enumerate(getattr(self, key)["pts"]):
                if g.get("key") == key and g.get("what") == i:   # the one held: a ring, the photo seen in it
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    for c, w in ((QColor("#111111"), 3.6), (col, 1.8)):
                        p.setPen(QPen(c, w * u))
                        p.drawEllipse(QPointF(float(x), float(y)), 6.5 * u, 6.5 * u)
                    continue
                p.setPen(QPen(QColor("#111111"), 1.5 * u))
                p.setBrush(col)
                p.drawEllipse(QPointF(float(x), float(y)), 5.5 * u, 5.5 * u)
        # the middles: the disc's a ring, the cup's a dot (inside it where the two lie on each other)
        mid = QPointF(*G.centre(self.disc))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for c, w in ((QColor("#111111"), 4.4), (DISC_COLOR, 2.4)):
            p.setPen(QPen(c, w * u))
            p.drawEllipse(mid, 9.5 * u, 9.5 * u)
        p.setPen(QPen(QColor("#111111"), 1.5 * u))
        p.setBrush(CUP_COLOR)
        p.drawEllipse(QPointF(*G.centre(self.cup)), 4.5 * u, 4.5 * u)
        names = G.ring_names(self.eye_key) if self.eye_key else ("S", "", "?", "", "I", "", "?", "")
        f = QFont()
        f.setPixelSize(max(8, round(15 * u)))
        f.setBold(True)
        p.setFont(f)
        for i in (0, 2, 4, 6):
            x, y = self.disc["pts"][i]
            d = math.hypot(x - mid.x(), y - mid.y()) or 1.0
            x, y = x + (x - mid.x()) / d * 17 * u, y + (y - mid.y()) / d * 17 * u
            rect = QRectF(x - 20 * u, y - 12 * u, 40 * u, 24 * u)
            p.setPen(QColor(0, 0, 0, 200))
            p.drawText(rect.translated(1.2 * u, 1.2 * u), Qt.AlignmentFlag.AlignCenter, names[i])
            p.setPen(QColor("#ffffff"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, names[i])

    # -- the numbers -------------------------------------------------------------------------------------
    def _report(self) -> None:
        m = self.metrics()
        if not m:
            return
        v = m["vertical"]
        band = "0.7 이상" if v >= 0.7 else "0.5~0.7" if v >= 0.5 else "0.5 미만"
        self.lbl_v.setText(f"{v:.2f}")
        text = (f"<span style='color:{theme.TEXT2}'>{band}</span><br>"
                f"수평 C/D <b>{m['horizontal']:.2f}</b> &nbsp;·&nbsp; 면적 C/D <b>{m['area']:.2f}</b>"
                f" &nbsp;·&nbsp; 림 면적 <b>{(1 - m['area']) * 100:.0f}%</b>")
        mm = self.disc_mm()
        if mm is not None:                                       # what is normal depends on the disc's size
            size = "작은" if mm < G.DISC_SMALL_MM else "큰" if mm > G.DISC_LARGE_MM else "평균 크기"
            text += (f"<br><span style='color:{theme.TEXT2}'>디스크 수직 지름 약 <b>{mm:.1f} mm</b> ({size} 디스크 · "
                     f"24 mm 안구 가정) — 이 크기의 정상 평균 C/D 약 {G.expected_cdr(mm):.2f}</span>")
        self.lbl_ratio.setText(text)
        self._report_auto()
        narrow = m["narrow"]
        where = f"{narrow['hour']}시 방향" + (f" ({G.RIM_NAMES[narrow['name']]})" if self.eye_key else "")
        gone = f" · 림 없음 {narrow['absent']:.0f}°" if narrow["absent"] else ""
        tail = (f"가장 얇은 림: <b>{where}</b> · 림/디스크 <b>{narrow['ratio']:.2f}</b>{gone}<br>"
                f"DDLS <b>{m['ddls']}단계</b> <span style='color:{theme.TEXT2}'>"
                f"({'디스크 크기 반영' if mm is not None else '평균 크기 디스크로 가정'} · 1~10, 클수록 손상)</span>")
        if self.eye_key is None:
            self.lbl_rim.setText("눈(OD/OS)을 확인해야 비측·이측 림과 ISNT 순서를 표시할 수 있습니다.<br><br>" + tail)
            return
        rim = m["rim"]

        def cell(k):
            return (f"<td>{k} {G.RIM_NAMES[k]}&nbsp;&nbsp;</td><td align='right'>"
                    f"{'경계 밖' if rim[k] < 0 else f'{rim[k]:.3f}'}</td>")
        rows = "".join(f"<tr>{cell(a)}<td>&nbsp;&nbsp;&nbsp;&nbsp;</td>{cell(b)}</tr>"
                       for a, b in (("I", "IT"), ("S", "ST"), ("N", "IN"), ("T", "SN")))
        verdict = (f"<b style='color:{theme.ORANGE}'>ISNT 어긋남</b> — " + ", ".join(m["isnt"])) if m["isnt"] \
            else f"<b style='color:{theme.GREEN}'>ISNT 순서 유지</b>"
        self.lbl_rim.setText(f"<table>{rows}</table><br>{verdict}<br><br>{tail}")

    def _report_auto(self) -> None:
        """What the outlines stand on, and each way's vertical C/D on its line of equal depth."""
        level = f"{self.s_level.value():.0f}%"
        cup = DT_STATE["cup"].get(self.state["cup"]) or f"컵: {S3_METHOD_NAMES[self.method]} 등고선 {level}"
        text = f"{DT_STATE['disc'][self.state['disc']]}<br>{cup}"
        v = self.by_method()
        if v:
            cells = [(f"{name} {v[k]:.2f}" if v.get(k) is not None else f"{name} –") for k, name, _ in S3_METHODS]
            cells = [f"<b>{c}</b>" if k == self.method else c for c, (k, _, _) in zip(cells, S3_METHODS)]
            text += f"<br><br>추정 방식별 수직 C/D (등고선 {level})<br>" + " &nbsp;·&nbsp; ".join(cells)
            got = [x for x in v.values() if x is not None]
            if len(got) >= 2 and max(got) - min(got) > DT_SPREAD:
                text += (f"<br><span style='color:{theme.ORANGE}'>방식에 따라 {max(got) - min(got):.2f} 차이 — 사진만으로는 "
                         "컵 경계가 뚜렷하지 않습니다. 혈관 꺾임을 보고 직접 맞추세요.</span>")
        self.lbl_auto.setText(f"<span style='color:{theme.TEXT2}'>{text}</span>")

    def note(self) -> str:
        m = self.metrics()
        return f"녹내장 분석 — 수직 C/D {m['vertical']:.2f}" if m else "녹내장 분석 — C/D"

    def image_ids(self) -> list[int]:
        return [self.photo.image_id] if self.photo is not None else []

    def eye(self) -> str | None:
        return self.eye_key


# -- 3D ----------------------------------------------------------------------------------------------
S3_ONE = "사진 한 장의 밝기로 추정한 모양입니다 (창백한 곳 = 깊은 곳). 실제 깊이를 잰 것이 아닙니다."
S3_HINT = ("사진을 끌면 돌아갑니다. 사진의 색과 밝기는 찍힌 그대로이고(정면 = 원래 사진), 깊이는 추정한 상대값입니다 — "
           "100%가 깊은 컵 정도입니다.")
S3_CD = ("입체 표면에서 기준 깊이보다 깊은 곳을 컵(노란 선)으로 본 추정값입니다. 디스크 경계(초록 선)는 "
         "[디스크 C/D] 탭의 초록 선입니다 — 거기서 맞추면 여기도 따라옵니다.")
S3_NERVE = ("망막 위의 신경섬유가 유두로 모여 림을 넘어 뒤쪽 다발로 나가는 모습을 그린 설명용 그림입니다. 림이 얇은 "
            "방향은 가닥이 줄어듭니다. 초록빛 구간은 사진의 결에서 방향을 읽은 곳이고, 나머지는 일반적인 주행 모양입니다 — "
            "섬유 수나 두께를 잰 것이 아닙니다.")
S3_SPREAD = 0.10         # two photos' vertical C/D further apart than this: say so
S3_NO_CUP = "컵이 뚜렷하지 않아 이 표면에서는 C/D를 추정하지 못했습니다 — [디스크 C/D] 탭에서 직접 맞추세요."
# one photo: three ways to the shape (disc3d.METHODS)
S3_METHODS = (("pallor", "밝기", "창백한 곳 = 깊은 곳"),
              ("vessels", "혈관 꺾임", "혈관이 꺾이는 곳 = 컵 경계 (색은 쓰지 않음)"),
              ("hybrid", "하이브리드", "혈관이 꺾이는 쪽은 그 경계, 혈관이 없는 쪽과 바닥 모양은 밝기"))
S3_METHOD_NAMES = {k: name for k, name, _ in S3_METHODS}
# two photos of one day: the stereo depth alone, or its cup's margin where the vessels bend
# (disc3d.STEREO_METHODS)
S3_STEREO_METHODS = (("parallax", "시차", "두 사진의 시차로 계산한 깊이 그대로"),
                     ("parallax_vessels", "시차 + 혈관 꺾임",
                      "깊이는 시차, 컵 경계는 혈관이 꺾이는 곳 (꺾임이 없는 쪽은 시차 그대로)"))
S3_STEREO_NAMES = {k: name for k, name, _ in S3_STEREO_METHODS}
S3_COMPARE_PX = 420      # 셋 나란히 비교: each of the three views (px)
S3_GAP = 8               # … and the gap between them
BEND_USED = (63, 224, 255)       # a bend the margin goes through (the outermost of its vessel)
BEND_INNER = (255, 92, 200)      # a vessel's other bends (down the wall: onto the floor)


def s3_status(method: str, info: dict) -> str:
    """What the one-photo shape of ``method`` stands on (the 3D tab's status line)."""
    if method == "pallor":
        return S3_ONE
    b = info.get("bends") or {}
    k, v = len(b.get("r", ())), b.get("vessels", 0)
    found = f"꺾임 {k}곳 · 혈관 {v}개"
    share = f"경계의 {info.get('support', 0.0):.0%}"
    if method == "vessels":
        if not info.get("cup"):
            return (f"혈관 꺾임을 충분히 찾지 못했습니다 ({found}) — 디스크가 작게 찍혔거나 경계를 지나는 혈관이 "
                    "적습니다. 그림의 오목한 곳은 자리만 채운 것입니다. [밝기]나 [하이브리드]로 보세요.")
        return (f"혈관이 꺾이는 곳을 컵 경계로 본 모양입니다 ({found} · {share}가 꺾임에 가까움, 나머지는 이어 그림). "
                "색은 쓰지 않으며 깊이는 정해 둔 모양입니다 — 실제 깊이를 잰 것이 아닙니다.")
    if not info.get("support"):
        return f"혈관 꺾임을 찾지 못해 ({found}) [밝기]와 같은 모양입니다. " + S3_ONE
    return (f"경계는 혈관이 꺾이는 곳 ({found} · {share}), 혈관이 없는 쪽과 바닥 모양은 밝기로 추정한 모양입니다. "
            "실제 깊이를 잰 것이 아닙니다.")


class Surface3DTab(_Tab):
    """The optic disc as a surface to turn (``disc3d.py``): its shape estimated from one photo's
    brightness, or — with two photos of the same disc — from the parallax between them. The two
    photos can also be flickered on the surface."""
    ROCK_YAW, ROCK_PITCH, ROCK_S = 16.0, 6.0, 4.0        # 자동으로 흔들기: degrees each way, seconds a swing
    LIMIT = 65.0                                         # how far the surface turns (degrees)

    def __init__(self, photo: Photo | None, second: Photo | None = None, parent=None, disc_tab=None,
                 method: str = "hybrid", stereo_method: str = "parallax_vessels"):
        """``method``: how one photo's shape is estimated at first (``disc3d.METHODS``, 설정 → 일반);
        ``stereo_method``: how the stereo depth is drawn at first (``disc3d.STEREO_METHODS``, 설정 → 일반)."""
        super().__init__(NEED_ONE, parent)
        self.photos = [p for p in (photo, second) if p is not None]
        self.disc_tab = disc_tab                         # its green outline is the disc margin here
        self._cup: dict = {}
        self.same_eye = len(self.photos) == 2 and common_eye(self.photos) is not None
        days = {p.day for p in self.photos if p.day}
        self.follow_up = self.same_eye and len(days) == 2
        self.stereo_ok = self.same_eye and not self.follow_up
        self.source = "stereo" if self.stereo_ok else "a"
        # one photo's estimate: 밝기 · 혈관 꺾임 · 하이브리드 (the last the one a new window opens on)
        self.method = method if method in disc3d.METHODS else "hybrid"
        # two photos: 시차 · 시차 + 혈관 꺾임 (the last the one a new window opens on)
        self.stereo_method = stereo_method if stereo_method in disc3d.STEREO_METHODS else "parallax_vessels"
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
        self.stereo_methods = None
        self.sw_flip = Switch("깊이 뒤집기")
        self.sw_flip.setToolTip("컵이 솟아 보이면 켭니다 (어느 사진이 왼쪽에서 찍혔는지는 알 수 없습니다)")
        self.sw_flip.toggled.connect(lambda _on: self._shape_changed())
        self.sw_flick = Switch("두 사진 깜빡임")
        self.sw_flick.setEnabled(self.same_eye)
        self.sw_flick.setToolTip("같은 표면 위에서 사진 ①과 ②를 번갈아 보여 줍니다")
        self.sw_flick.toggled.connect(lambda _on: self._restart())
        self.speed = _Slider("깜빡임 속도", 1, 6, 2, 1, lambda v: f"{v:.0f} Hz")
        self.fields = _Choice(DISC_FIELDS)
        self.fields.set("normal")
        self.fields.changed.connect(self.set_field)
        self.fields.setToolTip("화면에 담을 범위 — 유두 지름의 몇 배인지")
        self.status = _note()
        self.methods = _Choice(S3_METHODS)
        self.methods.set(self.method)
        self.methods.changed.connect(self.set_method)
        self.methods.setToolTip("사진 한 장으로 모양을 추정하는 방법")
        self.sw_bends = Switch("꺾임 점")
        self.sw_bends.setChecked(True)
        self.sw_bends.setToolTip("혈관이 꺾인 곳 — 하늘색: 컵 경계로 쓴 곳 (혈관마다 가장 바깥), "
                                 "분홍: 같은 혈관의 안쪽 꺾임 (벽을 내려가 바닥에 닿는 곳)")
        self.sw_bends.toggled.connect(lambda _on: self._draw())
        self.sw_compare = Switch("셋 나란히 비교")
        self.sw_compare.setToolTip("밝기 · 혈관 꺾임 · 하이브리드를 나란히 — 함께 돌아갑니다")
        self.sw_compare.toggled.connect(lambda _on: self._shape_changed())
        rows = [self.methods, self.fields, self.sw_bends, self.sw_compare, self.status]
        if len(self.photos) == 2:
            self.sources = _Choice([("a", "사진 ①", "사진 ① 한 장으로 추정"), ("b", "사진 ②", "사진 ② 한 장으로 추정"),
                                    ("stereo", "2장 스테레오", "두 사진의 시차로 깊이 계산")])
            self.sources.set(self.source)
            self.sources.changed.connect(self.set_source)
            self.sources.buttons[2].setEnabled(self.stereo_ok)
            self.stereo_methods = _Choice(S3_STEREO_METHODS)
            self.stereo_methods.set(self.stereo_method)
            self.stereo_methods.changed.connect(self.set_stereo_method)
            self.stereo_methods.setToolTip("두 장 스테레오의 깊이 — 시차만, 또는 컵 경계를 혈관 꺾임으로")
            rows = [self.sources, self.methods, self.stereo_methods, self.fields, self.sw_bends, self.sw_compare,
                    self.sw_flip, self.sw_flick, self.speed, self.status]
        self.side.addWidget(card("모양 (깊이)", *rows, lines=False))

        self.s_depth = _Slider("깊이 과장", 0, 200, 100, 5, lambda v: f"{v:.0f}%")
        self.s_depth.setToolTip("100%: 가장 깊은 곳이 유두 지름의 0.4배 (깊은 컵 정도, 약 0.7 mm) — 올리면 더 깊게 과장합니다")
        self.s_depth.changed.connect(lambda _v: self._draw())
        self.sw_auto = Switch("자동으로 흔들기")
        self.sw_auto.setChecked(True)
        self.sw_auto.toggled.connect(lambda _on: self._restart())
        self.sw_light = Switch("입체 조명")
        self.sw_light.setChecked(True)
        self.sw_light.setToolTip("돌려 볼 때 보는 쪽으로 향한 경사면은 조금 밝게, 등진 경사면은 조금 어둡게 — 사진의 색은 그대로.\n"
                                 "끄면 사진만 입힙니다 (정면에서는 켜도 원래 사진 그대로)")
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
        # the nerve behind the disc: a picture to explain with (off until asked for)
        self._fields: dict = {}
        self._fibres: tuple = (None, [], None)             # (what they were made for, the strands, the photo with them)
        self.sw_nerve = Switch("시신경 다발 보기")
        self.sw_nerve.setToolTip("망막 위 신경섬유가 유두로 모여 뒤로 나가는 모습을 그려 넣습니다 (설명용 그림)")
        self.sw_rnfl = Switch("망막 위 신경섬유")
        self.sw_rnfl.setChecked(True)
        self.sw_read = Switch("사진에서 읽은 방향 따르기")
        self.sw_read.setChecked(True)
        self.sw_read.setToolTip("사진에 신경섬유층의 결이 보이는 곳에서는 가닥이 그 방향을 따릅니다 (초록빛 구간)")
        self.sw_xray = Switch("망막 비쳐 보기")
        self.sw_xray.setChecked(True)
        self.sw_xray.setToolTip("망막을 반투명하게 해서 뒤쪽 다발이 비쳐 보이게 합니다")
        self.sw_pulse = Switch("신호 흐름")
        self.sw_pulse.setChecked(True)
        self.s_strands = _Slider("가닥 수", 20, disc3d.FIBRE_MAX, 150, 10, lambda v: f"{v:.0f}")
        self.lbl_nerve = _note()
        self.lbl_nerve.setTextFormat(Qt.TextFormat.RichText)
        self.nerve_note = _note(S3_NERVE)
        self.nerve_rows = QWidget()                        # (shown with the option)
        rows = QVBoxLayout(self.nerve_rows)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        for w in (self.sw_rnfl, self.sw_read, self.sw_xray, self.sw_pulse, self.s_strands, self.lbl_nerve,
                  self.nerve_note):
            rows.addWidget(w)
        for sw in (self.sw_nerve, self.sw_rnfl, self.sw_read, self.sw_xray, self.sw_pulse):
            sw.toggled.connect(lambda _on: self._restart())
        self.s_strands.changed.connect(lambda _v: self._draw())
        self.side.addWidget(card("시신경 다발 (그림)", self.sw_nerve, self.nerve_rows, lines=False))
        self.side.addStretch(1)
        self.view.pressed.connect(self._press)
        self.view.moved.connect(self._move)
        self.view.released.connect(lambda: setattr(self, "_drag", None))
        self.view.overlay = self._labels
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
        self._tex, self._heights, self._fields, self._fibres = [], {}, {}, (None, [], None)
        size = np.empty((disc3d.TEX_PX, disc3d.TEX_PX, 3), np.uint8)
        for ph in self.photos:
            crop, _, _ = G.crop_square(ph.rgb, *ph.disc, self._factor() * ph.disc_px)
            self._tex.append(np.ascontiguousarray(G.match_size(crop, size)))
        if len(self._tex) == 2:
            self._tex[1] = G.shifted(self._tex[1], *G.find_shift(self._tex[0], self._tex[1]))
        self._shape_changed()

    def set_source(self, source: str) -> None:
        if source == "stereo" and not self.stereo_ok:
            self.status.setText(NEED_SAME_EYE if not self.same_eye else
                                "서로 다른 날짜의 사진은 경과 비교에서 확인하세요.")
            if self.sources is not None:
                self.sources.set(self.source)
            return
        self.source = source
        if self.sources is not None:
            self.sources.set(source)
        self._shape_changed()

    def set_method(self, method: str) -> None:
        """How one photo's shape is estimated: ``disc3d.METHODS`` (밝기 · 혈관 꺾임 · 하이브리드)."""
        self.method = method
        self.methods.set(method)
        self._shape_changed()

    def set_stereo_method(self, method: str) -> None:
        """How the stereo depth is drawn: ``disc3d.STEREO_METHODS`` (시차 · 시차 + 혈관 꺾임)."""
        self.stereo_method = method
        if self.stereo_methods is not None:
            self.stereo_methods.set(method)
        self._shape_changed()

    def current_method(self, source: str | None = None) -> str:
        """The way to the shape of ``source`` (the one shown, if None): the stereo one or one photo's."""
        return self.stereo_method if (source or self.source) == "stereo" else self.method

    def family(self) -> tuple:
        """The ways to the shape the source shown has: (key, name, tip) — 시차 · 시차 + 혈관 꺾임 for
        the stereo depth, 밝기 · 혈관 꺾임 · 하이브리드 for one photo."""
        return S3_STEREO_METHODS if self.source == "stereo" else S3_METHODS

    def comparing(self) -> bool:
        """나란히 비교: the ways to the shape of the source shown side by side — the three one-photo
        estimates, or the stereo depth with and without the vessels' bends."""
        return self.sw_compare.isChecked() and bool(self._tex) and (self.source != "stereo" or self.stereo_ok)

    def _surface(self, source: str, method: str | None = None) -> tuple[np.ndarray, dict] | None:
        """The surface of ``source`` (a · b · stereo) by ``method`` (``disc3d.STEREO_METHODS`` for the
        stereo depth, ``disc3d.METHODS`` for one photo; the one chosen, if None) — and what is known
        of it."""
        if source == "stereo" and not self.stereo_ok:
            return None
        if not self._tex or (source != "a" and len(self._tex) < 2):
            return None
        method = method or self.current_method(source)
        key = (source, method, self.sw_flip.isChecked()) if source == "stereo" else (source, method)
        if key not in self._heights:
            frac = 1.0 / self._factor()
            if source == "stereo":
                draw = disc3d.height_stereo_vessels if method == "parallax_vessels" else disc3d.height_from_stereo
                self._heights[key] = draw(self._tex[0], self._tex[1], frac, flip=self.sw_flip.isChecked())
            else:
                info: dict = {}
                self._heights[key] = (disc3d.height_one_photo(self._tex[source == "b"], frac, method, info=info),
                                      info)
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
        self.methods.setVisible(not stereo)
        if self.stereo_methods is not None:
            self.stereo_methods.setVisible(stereo)
        self.sw_compare.setText("둘 나란히 비교" if stereo else "셋 나란히 비교")
        self.sw_compare.setToolTip("시차 · 시차 + 혈관 꺾임을 나란히 — 함께 돌아갑니다" if stereo
                                   else "밝기 · 혈관 꺾임 · 하이브리드를 나란히 — 함께 돌아갑니다")
        self.sw_bends.setVisible(self.sw_compare.isChecked()
                                 or self.current_method() not in ("pallor", "parallax"))
        self.heights()
        if not self._tex:
            self.status.setText("")
        elif not stereo:
            self.status.setText(s3_status(self.method, self.info))
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
            elif self.stereo_method == "parallax_vessels":
                b = self.info.get("bends") or {}
                found = f"꺾임 {len(b.get('r', ()))}곳 · 혈관 {b.get('vessels', 0)}개"
                if self.info.get("support"):
                    text += (f" 컵 경계는 혈관이 꺾이는 곳입니다 ({found} · 경계의 {self.info['support']:.0%}, "
                             "두 사진 모두에서 찾은 꺾임일수록 무겁게) — 꺾임이 없는 쪽은 시차 그대로.")
                elif self.info.get("no_hollow"):
                    text += (f" 혈관 꺾임({found})은 찾았지만 시차에서 그 안쪽이 오목하지 않아 쓰지 않았습니다 "
                             "([시차]와 같은 모양).")
                else:
                    text += f" 혈관 꺾임을 찾지 못해 ({found}) [시차]와 같은 모양입니다."
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
        return self.same_eye and len(self._tex) == 2 and self.sw_flick.isChecked()

    def _pulsing(self) -> bool:
        return self.sw_nerve.isChecked() and self.sw_pulse.isChecked()

    def _restart(self) -> None:
        self.speed.setVisible(self._flickering())
        self.nerve_rows.setVisible(self.sw_nerve.isChecked())
        if self._tex and self.isVisible() and (self.sw_auto.isChecked() or self._flickering() or self._pulsing()):
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
            return G.moved(t.disc, k, c - side / 2.0 * k, c - side / 2.0 * k)
        return {"pts": G.ring({"cx": c, "cy": c, "rx": r * 0.95, "ry": r * 1.05})}

    def cup(self, source: str | None = None, method: str | None = None) -> tuple[dict, dict, np.ndarray] | None:
        """(disc outline, cup outline, the cup's margin) in texture pixels — the cup as the surface
        of ``source`` (the one shown, if None; one photo's by ``method``, the one chosen if None) has
        it (``disc3d.cup_from_surface``) — or None: no surface, no cup seen in the photo, or a stereo
        depth that is not to be trusted."""
        source = source or self.source
        method = method or self.current_method(source)
        surface = self._surface(source, method)
        if surface is None or not surface[1].get("cup", True) or not surface[1].get("reliable", True):
            return None
        if source == "stereo" and not self.stereo_ok:
            return None
        H = surface[0]
        disc = self.disc_outline()
        key = (source, method, self.sw_flip.isChecked(), self.field,
               self.s_level.value(), np.round(G.ring(disc), 2).tobytes())
        if key not in self._cup:
            k = H.shape[0] / disc3d.TEX_PX                # (the surface is coarser than the texture)
            small = G.moved(disc, k, 0.5 * k - 0.5, 0.5 * k - 0.5)
            found = disc3d.cup_from_surface(H, small, self.s_level.value() / 100.0)
            if found is not None:
                cup, edge = found
                found = (disc, G.moved(cup, 1.0 / k, 0.5 / k - 0.5, 0.5 / k - 0.5), (edge + 0.5) / k - 0.5)
            if len(self._cup) > 12:                      # (a slider dragged: only the last ones are asked again)
                self._cup.clear()
            self._cup[key] = found
        return self._cup[key]

    def metrics(self, source: str | None = None, method: str | None = None) -> dict | None:
        """C/D of the cup read off the surface (``G.cdr_metrics``) — of the one shown, or of
        ``source`` (a · b · stereo) and one photo's ``method`` — or None."""
        found = self.cup(source, method)
        return G.cdr_metrics(found[0], found[1], self.eye() or "OD") if found else None

    def by_method(self) -> dict:
        """The vertical C/D of each way to the shape of the source shown (``family``), ``{method: value
        or None}`` — the three one-photo estimates, or the stereo depth with and without the bends."""
        return {k: (m["vertical"] if (m := self.metrics(self.source, k)) else None) for k, _, _ in self.family()}

    def both(self) -> dict | None:
        """With two photos: vertical C/D of each one's own estimate, of the stereo depth, the mean
        of the two photos and how far they are apart — ``{"a", "b", "stereo", "mean", "spread"}``
        (None where there is none)."""
        if not self.same_eye:
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
        """The cup found here — its line of equal depth — becomes the yellow outline of the 디스크 C/D tab
        (its ``G.RING`` points on that line)."""
        found, t = self.cup(), self.disc_tab
        if self.source == "b" and not self.same_eye:
            return
        if not found or t is None or t.disc is None:
            return
        c, r = (disc3d.TEX_PX - 1) / 2.0, disc3d.TEX_PX / self._factor() / 2.0
        side = float(t.img.shape[0])
        k = (side / {k: f for k, _, f in DISC_FIELDS}[t.field] / 2.0) / r
        t.set_outlines(t.disc, G.moved(found[1], k, side / 2.0 - c * k, side / 2.0 - c * k), given=True)

    def _report(self) -> None:
        m = self.metrics()
        self.b_apply.setEnabled(m is not None and (self.source != "b" or self.same_eye))
        if m is None:
            self.lbl_cd.setText("–")
            self.lbl_cd2.setText(f"<span style='color:{theme.TEXT2}'>{S3_NO_CUP if self._tex else ''}</span>"
                                 + self._methods_text() + self._both_text())
            return
        v = m["vertical"]
        band = "0.7 이상" if v >= 0.7 else "0.5~0.7" if v >= 0.5 else "0.5 미만"
        self.lbl_cd.setText(f"{v:.2f}")
        self.lbl_cd2.setText(f"<span style='color:{theme.TEXT2}'>{band}</span><br>"
                             f"수평 C/D <b>{m['horizontal']:.2f}</b> &nbsp;·&nbsp; 면적 C/D <b>{m['area']:.2f}</b>"
                             + self._methods_text() + self._both_text())

    def _methods_text(self) -> str:
        """The vertical C/D of each way to the shape side by side (the one shown in bold)."""
        if not self._tex or (self.source == "stereo" and not self.stereo_ok):
            return ""
        v = self.by_method()
        cells = []
        for key, name, _ in self.family():
            text = f"{name} {v[key]:.2f}" if v[key] is not None else f"{name} –"
            cells.append(f"<b>{text}</b>" if key == self.current_method() else text)
        title = "깊이 방식별 수직 C/D" if self.source == "stereo" else "추정 방식별 수직 C/D"
        return f"<br><br>{title}<br>" + " &nbsp;·&nbsp; ".join(cells)

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

    def bends(self, method: str | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Where the vessels bend on the photo shown (texture pixels, (k, 2)) and whether each is
        one the margin goes through (k,) — for 혈관 꺾임 · 하이브리드 · 시차 + 혈관 꺾임, else none
        (the stereo depth's: found in either photo, the two laid on each other)."""
        method = method or self.current_method()
        none = np.zeros((0, 2), np.float32), np.zeros(0, bool)
        if method in ("pallor", "parallax") or self._flickering():
            return none
        surface = self._surface(self.source, method)
        b = surface[1].get("bends") if surface is not None else None
        if b is None or not len(b["weight"]):
            return none
        return b["xy"] * disc3d.TEX_PX, b["weight"] >= 0.4 * float(b["weight"].max())

    # -- the nerve behind the disc ---------------------------------------------------------------
    def temporal(self) -> float:
        """The direction from the disc to the macula in the picture (radians, y down): to the
        marked fovea, or by the eye — the macula of a right eye lies to the left of its disc."""
        ph = self.photos[self.shown_photo()]
        if ph.fovea is not None and ph.disc is not None:
            dx, dy = ph.fovea[0] - ph.disc[0], ph.fovea[1] - ph.disc[1]
            if math.hypot(dx, dy) > ph.disc_px:
                return math.atan2(dy, dx)
        return 0.0 if ph.eye == "OS" else math.pi

    def fibres(self) -> tuple[list, np.ndarray, dict] | None:
        """(the strands, the photo with those over the retina drawn on it, the disc outline) for
        what is shown now — ``disc3d.fibre_paths`` — or None: the option is off or nothing is shown."""
        H = self.heights()
        if H is None or not self.sw_nerve.isChecked() or self.comparing():       # (나란히 비교: the shapes only)
            return None
        i = self.shown_photo()
        found = self.cup()
        disc = found[0] if found else self.disc_outline()
        if found:
            cup = found[1]
        else:                                             # (no cup to see: every strand)
            mid = np.asarray(G.centre(disc))
            cup = {"poly": mid + (G.curve(disc) - mid) * 0.3}
        read = self.sw_read.isChecked()
        key = (i, self.source, self.current_method(), self.sw_flip.isChecked(), self.field, G.curve(disc).round(2).tobytes(), G.curve(cup).round(2).tobytes(),
               self.s_strands.value(), self.depth_px(), read, self.sw_rnfl.isChecked())
        if self._fibres[0] != key:
            tex = self._tex[i]
            if read and i not in self._fields:
                self._fields[i] = disc3d.fibre_field(tex, 1.0 / self._factor())
            paths = disc3d.fibre_paths(disc, cup, H, self.depth_px(), disc3d.TEX_PX, int(self.s_strands.value()),
                                       self.temporal(), self._fields[i] if read else None, tex.sum(axis=2) > 60)
            drawn = disc3d.fibres_on_texture(tex, paths) if self.sw_rnfl.isChecked() else tex
            self._fibres = (key, paths, drawn)
        return self._fibres[1], self._fibres[2], disc

    def _texture(self, method: str | None = None) -> np.ndarray:
        """The photo to lay on the surface, with the disc (green) and cup (yellow) lines on it, and
        where the vessels bend (혈관 꺾임 · 하이브리드) — and the nerve's strands over the retina, when
        they are shown."""
        tex = self._tex[self.shown_photo()]
        nerve = self.fibres()
        if nerve:
            tex = nerve[1]
            if self.sw_pulse.isChecked() and self.sw_rnfl.isChecked():
                tex = tex.copy()
                for x, y in disc3d.pulses(nerve[0], time.monotonic() - self._t0)[0]:
                    cv2.circle(tex, (int(round(x * 8)), int(round(y * 8))), 20, (255, 250, 215), -1, cv2.LINE_AA, shift=3)
        found = self.cup(method=method) if self.sw_lines.isChecked() else None
        pts, used = self.bends(method) if self.sw_bends.isChecked() else (np.zeros((0, 2)), np.zeros(0, bool))
        if not found and not len(pts):
            return tex
        tex = tex.copy()
        lines = ((G.curve(found[0]), DISC_COLOR), (found[2], CUP_COLOR)) if found else ()
        for line_pts, col in lines:
            line = [np.round(line_pts * 8).astype(np.int32)]
            cv2.polylines(tex, line, True, (20, 20, 20), 4, cv2.LINE_AA, shift=3)      # (seen on a pale cup too)
            cv2.polylines(tex, line, True, (col.red(), col.green(), col.blue()), 2, cv2.LINE_AA, shift=3)
        for (x, y), main in zip(pts, used):
            c = (int(round(x * 8)), int(round(y * 8)))
            cv2.circle(tex, c, 7 * 8, (20, 20, 20), 3, cv2.LINE_AA, shift=3)
            cv2.circle(tex, c, 7 * 8, BEND_USED if main else BEND_INNER, 2, cv2.LINE_AA, shift=3)
        return tex

    def compose(self):
        H = self.heights()
        if H is None:
            return None
        yaw, pitch = self._angles()
        kw = dict(light=1.0 if self.sw_light.isChecked() else 0.0, contours=self.sw_contour.isChecked(),
                  perspective=disc3d.VIEW_DIST)
        nerve = self.fibres()
        if nerve:
            dots = (disc3d.pulses(nerve[0], time.monotonic() - self._t0, self.sw_rnfl.isChecked())[1]
                    if self.sw_pulse.isChecked() else None)
            kw.update(behind=disc3d.fibres_behind(nerve[0], nerve[2], self.depth_px(), disc3d.TEX_PX, dots),
                      sheet_alpha=0.62 if self.sw_xray.isChecked() else 1.0)
        draw = disc3d.anaglyph if self.sw_ana.isChecked() else disc3d.render
        if self.comparing():                             # 나란히: each way to the shape, turned alike
            views = [draw(self._texture(key), self._surface(self.source, key)[0], self.depth_px(), yaw, pitch,
                          out_px=S3_COMPARE_PX, **kw) for key, _, _ in self.family()]
            gap = np.zeros((S3_COMPARE_PX, S3_GAP, 3), np.uint8)
            row = [views[0]]
            for v in views[1:]:
                row += [gap, v]
            return np.hstack(row)
        return draw(self._texture(), H, self.depth_px(), yaw, pitch, **kw)

    def _labels(self, p: QPainter) -> None:
        """셋 나란히: each view's name and vertical C/D over it (the one chosen in orange)."""
        if not self.comparing():
            return
        v = self.by_method()
        f = QFont()
        f.setPixelSize(17)
        f.setBold(True)
        p.setFont(f)
        for i, (key, name, _) in enumerate(self.family()):
            text = f"{name}   C/D {v[key]:.2f}" if v[key] is not None else f"{name}   C/D –"
            rect = QRectF(i * (S3_COMPARE_PX + S3_GAP) + 12, 8, S3_COMPARE_PX - 24, 28)
            p.setPen(QColor(0, 0, 0, 200))
            p.drawText(rect.translated(1.5, 1.5), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            p.setPen(QColor(theme.ORANGE) if key == self.current_method() else QColor("#ffffff"))
            p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _draw(self) -> None:
        self._report()
        self.view.set_rgb(self.compose())
        nerve = self.fibres()
        if nerve:
            text = f"그려진 가닥 <b>{len(nerve[0])}</b> / {self.s_strands.value():.0f}"
            if self.sw_read.isChecked() and self.sw_rnfl.isChecked():
                text += (f"<br>사진에서 방향을 읽은 구간 <b style='color:{theme.GREEN}'>"
                         f"{disc3d.read_share(nerve[0]) * 100:.0f}%</b>")
            self.lbl_nerve.setText(text)

    def note(self) -> str:
        stereo = self.source == "stereo"
        if self.comparing():
            v = self.by_method()
            return ("녹내장 분석 — 유두 3D " + ("(2장 스테레오 · 둘 나란히)" if stereo else "(1장 추정 · 셋 나란히)")
                    + " · 수직 C/D " + " · ".join(f"{name} {v[k]:.2f}" if v[k] is not None else f"{name} –"
                                                 for k, name, _ in self.family()))
        m = self.metrics()
        if stereo:
            kind = "(2장 스테레오)" if self.stereo_method == "parallax" else "(2장 스테레오 · 혈관 꺾임)"
        else:
            kind = ("(1장 추정)" if self.method == "pallor" else f"(1장 추정 · {S3_METHOD_NAMES[self.method]})")
        return ("녹내장 분석 — 유두 3D " + kind
                + (f" · 추정 수직 C/D {m['vertical']:.2f}" if m else "")
                + self._both_note() + (" · 시신경 다발 그림 표시" if self.sw_nerve.isChecked() else ""))

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
                 start: str | None = None, method: str = "hybrid", stereo_method: str = "parallax_vessels",
                 sheet=None):
        """``series``: the photos of this eye over time (``timeline.Shot`` — 시간별 비교), ``prefer``:
        those of them the user picked; ``start="timeline"`` · ``"stereo"`` opens on that tab.
        ``sheet(parent)``: opens the 청구용 한 장 of the two photos (스테레오 보기 → 보험 청구용). ``method``: how the 3D
        입체 tab estimates one photo's shape at first (``disc3d.METHODS``; 설정 → 일반), ``stereo_method``:
        how it draws the stereo depth at first (``disc3d.STEREO_METHODS``; 설정 → 일반)."""
        super().__init__(parent)
        from .timeline_tab import TimelineTab        # (it builds on the widgets of this module)

        self.setWindowTitle("녹내장 분석")
        self._save_record, self.file_stem = save_record, file_stem
        self.saved_id: int | None = None
        candidates = (current, second) if current is not None and second is not None else None
        pair = candidates if candidates and common_eye(candidates) is not None else None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.lbl_src = QLabel(title_line)
        self.lbl_src.setStyleSheet("font-weight:600")
        root.addWidget(self.lbl_src)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("views")
        self.tabs.setDocumentMode(True)
        self.disc = DiscTab(current, method=method)
        self.surface = Surface3DTab(current, second, disc_tab=self.disc, method=method, stereo_method=stereo_method)
        self.surface.b_apply.clicked.connect(lambda: self.tabs.setCurrentWidget(self.disc))
        self.wide = WideTab(current)
        self.stereo = StereoTab(candidates)
        self.progress = ProgressTab(candidates)
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
        elif start == "stereo":
            self.tabs.setCurrentWidget(self.stereo)
        if sheet is not None and candidates is not None:
            self.stereo.b_sheet.setEnabled(True)
            self.stereo.b_sheet.clicked.connect(lambda: sheet(self))
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
        ids, eye = tab.image_ids(), tab.eye()
        if len(ids) > 1 and eye not in ("OD", "OS"):
            self.status.setText(NEED_SAME_EYE)
            return None
        try:
            self.saved_id = self._save_record(rgb, tab.note(), eye, ids)
        except (ValueError, LookupError) as exc:
            self.status.setText(f"저장하지 못했습니다 — {exc}")
            return None
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
