"""녹내장 분석 — disc C/D, wide-field RNFL, stereo viewing and progression (``glaucoma.py``).

Opened with the [녹내장] button beside the photo list. The photo on screen goes to **디스크 C/D**
(cut around its optic disc) and **광각 분석** (its disc and fovea, found at import, are already
marked); with a second photo picked (Ctrl+click, ②) the two go to **스테레오 보기** and
**경과 비교**, cut around their discs to the same retinal field so that different cameras compare.
What a tab shows can be saved into the patient record as a new photo (the originals stay as they
are), written to a file or copied.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from .. import glaucoma as G
from . import theme
from .image_view import from_qimage, to_qimage
from .keys import keys
from .widgets import Segmented, Switch, card, segment

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
    field, whatever the camera) or whole, then registered by a shift."""
    LIMIT_X, LIMIT_Y = 60.0, 60.0

    def __init__(self, pair, parent=None):
        super().__init__(NEED_PAIR, parent)
        self.pair = tuple(pair) if pair else None
        self.a = self.b = self._bs = None
        self.dx = self.dy = 0.0
        self.region = "disc"
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.regions = _Choice(REGIONS)
        self.regions.changed.connect(self.set_region)
        self.b_auto = _button("자동 맞춤", primary=True, tip="두 사진이 겹치도록 좌우·상하로 옮깁니다")
        self.b_zero = _button("맞춤 해제")
        self.b_auto.clicked.connect(self.auto_align)
        self.b_zero.clicked.connect(lambda: self.set_offset(0, 0, "맞춤을 해제했습니다."))
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
        self._bs = G.shifted(self.b, self.dx, self.dy)
        if status is not None:
            self.status.setText(status)
        self._offset_changed()
        self._draw()

    def _offset_changed(self) -> None:
        pass

    def auto_align(self) -> None:
        if self.a is None:
            return
        dx, dy = G.find_shift(self.a, self.b)
        self.set_offset(dx, dy)
        self.status.setText(f"자동 맞춤: 좌우 {_px(self.dx)}, 상하 {_px(self.dy)}")

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
    "wiggle": "두 장을 번갈아 보여 줍니다. 컵 바닥과 림이 서로 다르게 움직이는 만큼이 깊이입니다.",
    "sbs": "평행법: 왼쪽 눈으로 왼쪽, 오른쪽 눈으로 오른쪽 사진을 봅니다. 간이 입체경에 맞는 배치입니다.",
    "cross": "교차법: 눈을 모아 왼쪽 눈으로 오른쪽, 오른쪽 눈으로 왼쪽 사진을 봅니다.",
    "ana": "적청 안경(왼쪽 빨강, 오른쪽 청록)을 쓰고 봅니다.",
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

    def _on_press(self, _x: float, y: float) -> None:
        if self.mode == "depth" and self.a is not None and y < self.a.shape[0]:
            self._prof_y = y
            self._draw()

    def eyes(self) -> tuple:
        """``(left eye's photo, right eye's photo)``."""
        return (self._bs, self.a) if self.swap else (self.a, self._bs)

    def compose(self):
        if self.a is None:
            return None
        a, b = self.eyes()
        if self.mode == "wiggle":
            return b if self._phase else a
        if self.mode == "sbs":
            return G.side_by_side(a, b)
        if self.mode == "cross":
            return G.side_by_side(b, a)
        if self.mode == "ana":
            return G.anaglyph(a, b)
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
class DiscTab(_Tab):
    """The optic disc of the photo with two ellipses to fit: the disc margin and the cup."""

    def __init__(self, photo: Photo | None, parent=None):
        super().__init__(NEED_ONE, parent)
        self.photo = photo
        self.eye_key = "OS" if photo is not None and photo.eye == "OS" else "OD"
        self.img = self.disc = self.cup = None
        self._drag = None
        self.field = "normal"
        self.hint.setText("초록 타원을 디스크 경계에, 노란 타원을 컵 경계에 맞추세요. "
                          "가운데 점은 옮기기, 가장자리 점은 크기입니다.")
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
        self.disc = {"cx": c, "cy": c, "rx": r * 0.95, "ry": r * 1.05}
        self.cup = {"cx": c, "cy": c, "rx": r * 0.45, "ry": r * 0.50}
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
        self.disc, self.cup = dict(disc), dict(cup)
        self._changed()

    def metrics(self) -> dict | None:
        return G.cdr_metrics(self.disc, self.cup, self.eye_key) if self.disc else None

    def _handles(self) -> list:
        out = []
        for key in ("cup", "disc"):
            e = getattr(self, key)
            out += [(key, "c", e["cx"], e["cy"]), (key, "e", e["cx"] + e["rx"], e["cy"]),
                    (key, "w", e["cx"] - e["rx"], e["cy"]), (key, "n", e["cx"], e["cy"] - e["ry"]),
                    (key, "s", e["cx"], e["cy"] + e["ry"])]
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
        elif h in "ew":
            e["rx"] = max(5.0, abs(x - e["cx"]))
        else:
            e["ry"] = max(5.0, abs(y - e["cy"]))
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
            p.drawEllipse(QPointF(e["cx"], e["cy"]), e["rx"], e["ry"])
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
        for text, x, y in (("S", d["cx"], d["cy"] - d["ry"] - 16 * u), ("I", d["cx"], d["cy"] + d["ry"] + 16 * u),
                           (right, d["cx"] + d["rx"] + 16 * u, d["cy"]), (left, d["cx"] - d["rx"] - 16 * u, d["cy"])):
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
                 file_stem: str = "녹내장", save_record=None, parent=None):
        super().__init__(parent)
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
        self.wide = WideTab(current)
        self.stereo = StereoTab(pair)
        self.progress = ProgressTab(pair)
        self.explain = ExplainTab()
        for tab, text in ((self.disc, "디스크 C/D"), (self.wide, "광각 분석"),
                          (self.stereo, "스테레오 보기"), (self.progress, "경과 비교"), (self.explain, "환자 설명")):
            self.tabs.addTab(tab, text)
        if pair is not None:        # two photos of one day: a stereo pair; of two days: a follow-up
            same_day = current.day and current.day == second.day
            self.tabs.setCurrentWidget(self.stereo if same_day else self.progress)
        root.addWidget(self.tabs, 1)
        foot = _note("측정값은 참고용 추정값입니다. 진단은 의사가 사진을 보고 판단하세요. "
                     "깊이 지도는 상대값이며 절대 길이가 아닙니다.")
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
