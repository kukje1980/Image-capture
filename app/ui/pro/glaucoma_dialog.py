"""녹내장 분석 창 — 스테레오 보기 · 디스크 C/D · 광각 RNFL · 경과 비교.

Pro 검토의 '녹내장' 버튼으로 연다. MULTI 에서 고른 2장은 스테레오·경과 비교에,
현재 영상은 디스크·광각 분석에 쓴다. '이 화면 저장' 은 보이는 분석 화면을
환자의 새 영상으로 저장한다 (원본 보존).
"""
from __future__ import annotations

import logging
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.capture import glaucoma as G
from app.capture.frame_utils import bgr_to_qimage
from app.ui.pro.image_canvas import qimage_to_bgr

log = logging.getLogger(__name__)

_DISC, _CUP = QColor("#4be08a"), QColor("#ffe14a")
_NEED_PAIR = "MULTI 화면에서 영상 2장을 고른 뒤 '녹내장'을 누르세요."
_NEED_ONE = "분석할 영상이 없습니다."


# ================= 공통 위젯 =================
class _View(QWidget):
    """영상을 창 크기에 맞춰 그리고, 마우스 위치를 영상 좌표로 알려준다."""
    pressed = Signal(float, float)
    moved = Signal(float, float)
    released = Signal()

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self._img: QImage | None = None
        self._placeholder = placeholder
        self.overlay = None                      # callable(painter) — 영상 좌표계에서 그린다
        self.setMinimumSize(360, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_bgr(self, img) -> None:
        self._img = bgr_to_qimage(img) if img is not None else None
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

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        if self._img is None:
            p.setPen(QColor("#8a94a3"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            return
        s, ox, oy = self._geom()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(ox, oy)
        p.scale(s, s)
        self._paint(p)

    def render_bgr(self):
        """영상 + 겹쳐 그린 내용을 영상 해상도로 합성."""
        if self._img is None:
            return None
        out = QImage(self._img.width(), self._img.height(), QImage.Format.Format_RGB888)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint(p)
        p.end()
        return qimage_to_bgr(out)

    def _pos(self, e) -> tuple[float, float]:
        s, ox, oy = self._geom()
        return (e.position().x() - ox) / s, (e.position().y() - oy) / s

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self._img is not None and e.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(*self._pos(e))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._img is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.moved.emit(*self._pos(e))

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self.released.emit()


def _head(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("PanelHeader")
    return lb


def _note(text: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("Muted")
    return lb


def _button(text: str, primary: bool = False, checkable: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("ProPrimary" if primary else "ProSegBtn" if checkable else "ProBtn")
    b.setCheckable(checkable)
    b.setMinimumHeight(30)
    return b


class _Choice(QWidget):
    """하나만 고르는 버튼 줄."""
    changed = Signal(str)

    def __init__(self, items: list, per_row: int = 3, parent=None):
        super().__init__(parent)
        self._buttons: dict = {}
        self._group = QButtonGroup(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        row = None
        for k, (key, text) in enumerate(items):
            if k % per_row == 0:
                row = QHBoxLayout()
                row.setSpacing(4)
                box.addLayout(row)
            b = _button(text, checkable=True)
            self._group.addButton(b)
            b.clicked.connect(lambda _=False, key=key: self.changed.emit(key))
            self._buttons[key] = b
            row.addWidget(b)
        self.set(items[0][0])

    def set(self, key: str) -> None:
        self._buttons[key].setChecked(True)


class _Slider(QWidget):
    """이름 · 값 표시가 붙은 슬라이더. step 단위의 실수 값을 다룬다."""
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
    """왼쪽 영상 + 오른쪽 조작 패널."""

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
        side = QWidget()
        side.setFixedWidth(300)
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(8)
        lay.addWidget(side)

    def has_image(self) -> bool:
        return self.view.has_image()

    def render(self):
        return self.view.render_bgr()

    def note(self) -> str:
        return ""


# ================= 스테레오 =================
_ST_MODES = [("wiggle", "위글"), ("sbs", "나란히(평행)"), ("cross", "나란히(교차)"),
             ("ana", "적청 안경"), ("depth", "깊이 지도")]
_ST_HINT = {
    "wiggle": "두 장을 번갈아 보여줍니다. 컵 바닥과 림이 서로 다르게 움직이는 정도가 깊이입니다.",
    "sbs": "평행법: 왼쪽 눈으로 왼쪽, 오른쪽 눈으로 오른쪽 영상을 봅니다. 간이 입체경에 맞는 배치입니다.",
    "cross": "교차법: 눈을 모아 왼쪽 눈으로 오른쪽, 오른쪽 눈으로 왼쪽 영상을 봅니다.",
    "ana": "적청 안경(왼쪽 빨강, 오른쪽 청록)을 쓰고 봅니다.",
    "depth": "파랑은 깊은 곳(컵), 빨강은 솟은 곳입니다. 영상을 누르면 그 높이의 단면이 아래에 그려집니다.",
}


class StereoTab(_Tab):
    def __init__(self, pair, parent=None):
        super().__init__(_NEED_PAIR, parent)
        self.left = self.right = self._rs = self._disp = None
        self.dx = self.dy = 0.0
        self.swap = False
        self.mode = "wiggle"
        self._phase = 0
        self._prof_y = None

        self.side.addWidget(_head("보기 방식"))
        self.modes = _Choice(_ST_MODES, per_row=2)
        self.modes.changed.connect(self.set_mode)
        self.side.addWidget(self.modes)
        self.speed = _Slider("위글 속도", 1, 10, 5, 1, lambda v: f"{v:.0f} Hz")
        self.speed.changed.connect(lambda _v: self._restart())
        self.side.addWidget(self.speed)
        self.chk_swap = QCheckBox("좌우 바꾸기 (깊이가 뒤집혀 보일 때)")
        self.chk_swap.toggled.connect(self.set_swap)
        self.side.addWidget(self.chk_swap)

        self.side.addWidget(_head("정렬"))
        row = QHBoxLayout()
        self.b_auto = _button("자동 정렬", primary=True)
        self.b_zero = _button("보정 해제")
        self.b_auto.clicked.connect(self.auto_align)
        self.b_zero.clicked.connect(lambda: self.set_offset(0, 0, "보정을 해제했습니다."))
        row.addWidget(self.b_auto)
        row.addWidget(self.b_zero)
        self.side.addLayout(row)
        self.s_dx = _Slider("좌우 (수렴 위치)", -60, 60, 0, 0.5, _px)
        self.s_dy = _Slider("상하 어긋남", -40, 40, 0, 0.5, _px)
        self.s_dx.changed.connect(lambda v: self.set_offset(v, self.dy))
        self.s_dy.changed.connect(lambda v: self.set_offset(self.dx, v))
        self.side.addWidget(self.s_dx)
        self.side.addWidget(self.s_dy)
        self.status = _note()
        self.side.addWidget(self.status)
        self.side.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.view.pressed.connect(self._on_press)
        if pair:
            self.left = G.fit(pair[0])
            self.right = G.match_size(G.fit(pair[1]), self.left)
            self.auto_align()
        self.set_mode("wiggle")

    # --- 상태 ---
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.modes.set(mode)
        self.hint.setText(_ST_HINT[mode])
        self.speed.setVisible(mode == "wiggle")
        self._restart()
        self._draw()

    def set_swap(self, on: bool) -> None:
        self.swap = on
        self._disp = None
        self._draw()

    def set_offset(self, dx: float, dy: float, status: str | None = None) -> None:
        if self.left is None:
            return
        self.dx, self.dy = max(-60.0, min(60.0, dx)), max(-40.0, min(40.0, dy))
        self.s_dx.set(self.dx)
        self.s_dy.set(self.dy)
        self._rs = G.shifted(self.right, self.dx, self.dy)
        self._disp = None
        if status is not None:
            self.status.setText(status)
        self._draw()

    def auto_align(self) -> None:
        if self.left is None:
            return
        dx, dy = G.find_shift(self.left, self.right)
        self.set_offset(dx, dy)
        self.status.setText(f"자동 정렬: 좌우 {_px(self.dx)}, 상하 {_px(self.dy)} 보정")

    def _restart(self) -> None:
        if self.mode == "wiggle" and self.left is not None:
            self._timer.start(max(30, round(500 / self.speed.value())))
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if self.isVisible():
            self._phase ^= 1
            self._draw()

    def _on_press(self, _x: float, y: float) -> None:
        if self.mode == "depth" and self.left is not None and y < self.left.shape[0]:
            self._prof_y = y
            self._draw()

    # --- 그리기 ---
    def eyes(self) -> tuple:
        """(왼쪽 눈 영상, 오른쪽 눈 영상)."""
        return (self._rs, self.left) if self.swap else (self.left, self._rs)

    def compose(self):
        if self.left is None:
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
            f"최대 시차 {deep:.1f} px — 시차가 부족합니다. 두 컷 사이를 더 벌려 다시 찍으세요." if deep < 2
            else f"컵 최대 시차 {deep:.1f} px (상대 깊이, 절대 길이 아님)")
        return np.vstack([img, G.depth_profile(self._disp, y, h, w)])

    def _draw(self) -> None:
        self.view.set_bgr(self.compose())

    def note(self) -> str:
        return "스테레오 " + dict(_ST_MODES)[self.mode].split("(")[0]


# ================= 디스크 C/D =================
class DiscTab(_Tab):
    def __init__(self, img, eye: str = "OD", parent=None):
        super().__init__(_NEED_ONE, parent)
        self.eye = "OS" if eye == "OS" else "OD"
        self.disc = self.cup = None
        self._drag = None
        self.hint.setText("초록 타원을 디스크 경계에, 노란 타원을 컵 경계에 맞추세요. "
                          "가운데 점은 이동, 가장자리 점은 크기 조절입니다.")

        self.side.addWidget(_head("눈"))
        self.eyes = _Choice([("OD", "OD (우안)"), ("OS", "OS (좌안)")], per_row=2)
        self.eyes.set(self.eye)
        self.eyes.changed.connect(self.set_eye)
        self.side.addWidget(self.eyes)
        self.side.addWidget(_note("정립상 기준입니다. 우안은 화면 오른쪽이 비측입니다."))
        self.side.addWidget(_head("수직 C/D"))
        self.lbl_v = QLabel("–")
        f = QFont(self.lbl_v.font())
        f.setPointSize(20)
        f.setBold(True)
        self.lbl_v.setFont(f)
        self.side.addWidget(self.lbl_v)
        self.lbl_ratio = QLabel()
        self.lbl_ratio.setTextFormat(Qt.TextFormat.RichText)
        self.side.addWidget(self.lbl_ratio)
        self.side.addWidget(_head("림 두께 (ISNT)"))
        self.lbl_rim = QLabel()
        self.lbl_rim.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_rim.setWordWrap(True)
        self.side.addWidget(self.lbl_rim)
        self.side.addWidget(_note("림 두께는 디스크 수직 지름(DD)에 대한 비율입니다."))
        self.side.addStretch(1)

        self.view.overlay = self._overlay
        self.view.pressed.connect(self._press)
        self.view.moved.connect(self._move)
        self.view.released.connect(lambda: setattr(self, "_drag", None))
        if img is not None:
            self.img = G.fit(img)
            h, w = self.img.shape[:2]
            m = min(w, h)
            self.disc = {"cx": w / 2, "cy": h / 2, "rx": m * 0.27, "ry": m * 0.30}
            self.cup = {"cx": w / 2, "cy": h / 2, "rx": m * 0.13, "ry": m * 0.15}
            self.view.set_bgr(self.img)
            self._report()

    def set_eye(self, eye: str) -> None:
        self.eye = eye
        self.eyes.set(eye)
        self._changed()

    def set_ellipses(self, disc: dict, cup: dict) -> None:
        self.disc, self.cup = dict(disc), dict(cup)
        self._changed()

    def metrics(self) -> dict | None:
        return G.cdr_metrics(self.disc, self.cup, self.eye) if self.disc else None

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
        for e, col in ((self.disc, _DISC), (self.cup, _CUP)):
            p.setPen(QPen(col, 2.5 * u))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(e["cx"], e["cy"]), e["rx"], e["ry"])
        for key, _h, x, y in self._handles():
            p.setPen(QPen(QColor("#111111"), 1.5 * u))
            p.setBrush(_DISC if key == "disc" else _CUP)
            p.drawEllipse(QPointF(x, y), 6 * u, 6 * u)
        d, right = self.disc, ("N" if self.eye == "OD" else "T")
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
        self.lbl_v.setText(f"{v:.2f}   ({band})")
        self.lbl_ratio.setText(f"수평 C/D <b>{m['horizontal']:.2f}</b> &nbsp;·&nbsp; 면적 C/D <b>{m['area']:.2f}</b>"
                               f" &nbsp;·&nbsp; 림 면적 <b>{(1 - m['area']) * 100:.0f}%</b>")
        rim = m["rim"]
        rows = "".join(f"<tr><td>{k} {ko}&nbsp;&nbsp;</td><td align='right'>"
                       f"{'경계 밖' if rim[k] < 0 else f'{rim[k]:.3f} DD'}</td></tr>"
                       for k, ko in (("I", "하측"), ("S", "상측"), ("N", "비측"), ("T", "이측")))
        verdict = ("<b>ISNT 어긋남</b> — " + ", ".join(m["isnt"])) if m["isnt"] else "<b>ISNT 순서 유지</b>"
        self.lbl_rim.setText(f"<table>{rows}</table><br>{verdict}")

    def note(self) -> str:
        m = self.metrics()
        return f"CDR {m['vertical']:.2f}" if m else "CDR"


# ================= 광각 =================
_WD_KINDS = ["RNFL 결손", "디스크 출혈", "기타"]


class WideTab(_Tab):
    def __init__(self, img, parent=None):
        super().__init__(_NEED_ONE, parent)
        self.src = G.fit(img) if img is not None else None
        self.disc = self.fovea = None
        self.marks: list = []
        self.tool = "disc"

        self.side.addWidget(_head("강조"))
        self.chk_rf = QCheckBox("레드프리 (녹색 채널)")
        self.chk_rf.setChecked(True)
        self.chk_rf.toggled.connect(lambda _on: self._enhance())
        self.side.addWidget(self.chk_rf)
        self.s_k = _Slider("RNFL 대비 강화", 0, 3, 1.5, 0.1, lambda v: f"{v:.1f}")
        self.s_k.changed.connect(lambda _v: self._enhance())
        self.side.addWidget(self.s_k)

        self.side.addWidget(_head("영상을 눌러서"))
        self.tools = _Choice([("mark", "소견 표시"), ("disc", "디스크 지정"), ("fovea", "황반 지정")], per_row=3)
        self.tools.changed.connect(self.set_tool)
        self.side.addWidget(self.tools)
        row = QHBoxLayout()
        self.c_kind = QComboBox()
        self.c_kind.addItems(_WD_KINDS)
        self.b_clear = _button("표시 모두 지우기")
        self.b_clear.clicked.connect(self.clear_marks)
        row.addWidget(self.c_kind)
        row.addWidget(self.b_clear)
        self.side.addLayout(row)

        self.side.addWidget(_head("겹쳐 보기"))
        self.chk_sec = QCheckBox("디스크 구역 (Garway-Heath)")
        self.chk_vf = QCheckBox("시야검사 24-2 격자")
        for c in (self.chk_sec, self.chk_vf):
            c.setChecked(True)
            c.toggled.connect(lambda _on: self._changed())
            self.side.addWidget(c)
        self.lbl_geo = QLabel()
        self.lbl_geo.setWordWrap(True)
        self.side.addWidget(self.lbl_geo)
        self.side.addWidget(_head("소견 목록"))
        self.lbl_list = QLabel()
        self.lbl_list.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_list.setWordWrap(True)
        self.side.addWidget(self.lbl_list)
        self.side.addStretch(1)

        self.view.overlay = self._overlay
        self.view.pressed.connect(self.click)
        self.set_tool("disc")
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
        self.view.set_bgr(G.enhance_wide(self.src, self.chk_rf.isChecked(), self.s_k.value()))
        self._changed()

    def _changed(self) -> None:
        ready = bool(self.disc and self.fovea)
        self.hint.setText("영상을 누르면 소견이 표시되고, 시계 방향·구역·대응 시야가 목록에 계산됩니다." if ready
                          else "먼저 디스크 중심을, 이어서 황반을 눌러 지정하세요.")
        if ready:
            ax = G.axes(self.disc, self.fovea)
            ang = G.disc_fovea_angle(self.disc, self.fovea)
            self.lbl_geo.setText(f"{'OD (우안)' if ax['od'] else 'OS (좌안)'}  ·  디스크–황반 각 "
                                 f"{abs(ang):.1f}° {'아래' if ang >= 0 else '위'}  ·  {ax['dist'] / 15.5:.1f} px/°")
            items = [f"<b>{k}. {f['kind']} · {f['hour']}시 방향</b><br>{f['sector']} 구역, 디스크에서 {f['dd']:.1f} DD"
                     f"<br>대응 시야: {f['field']}" for k, f in enumerate(self.findings(), 1)]
            self.lbl_list.setText("<br><br>".join(items) or "아직 표시한 소견이 없습니다.")
        else:
            self.lbl_geo.setText("")
            self.lbl_list.setText("디스크와 황반을 지정하면 계산됩니다.")
        self.view.update()

    def _overlay(self, p: QPainter) -> None:
        if self.src is None:
            return
        u = self.src.shape[1] / 900
        if self.disc and self.fovea:
            if self.chk_sec.isChecked():
                for _name, rgb, pts in G.sector_polygons(self.disc, self.fovea):
                    p.setPen(QPen(QColor(0, 0, 0, 150), 1))
                    p.setBrush(QColor(*rgb, 150))
                    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
            if self.chk_vf.isChecked():
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
        for pt, col, text in ((self.disc, _DISC, "디스크"), (self.fovea, _CUP, "황반")):
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
            p.setPen(QPen(QColor("#ff4d6a"), 1.5 * u))
            p.drawEllipse(QPointF(x, y), 11 * u, 11 * u)
            p.setPen(QColor("#ffffff"))
            p.drawText(QPointF(x + 14 * u, y + 4 * u), str(k))

    def note(self) -> str:
        return "광각 RNFL 분석"


# ================= 경과 =================
_PG_MODES = [("flick", "깜빡임"), ("blend", "겹치기"), ("diff", "변화 지도")]
_PG_HINT = {
    "flick": "정합한 두 사진을 번갈아 보여줍니다. 움직이거나 나타나는 부분이 변화입니다.",
    "blend": "슬라이더로 기준과 추적 사진을 섞어 봅니다.",
    "diff": "밝기 차이가 큰 곳을 분홍색으로 표시합니다. 조명 차이도 함께 잡히므로 깜빡임으로 확인하세요.",
}


class ProgressTab(_Tab):
    def __init__(self, pair, parent=None):
        super().__init__(_NEED_PAIR, parent)
        self.base = self.follow = self._fs = None
        self.dx = self.dy = 0.0
        self.mode = "flick"
        self._phase = 0

        self.side.addWidget(_head("비교 방식"))
        self.modes = _Choice(_PG_MODES, per_row=3)
        self.modes.changed.connect(self.set_mode)
        self.side.addWidget(self.modes)
        self.speed = _Slider("깜빡임 속도", 1, 6, 2, 1, lambda v: f"{v:.0f} Hz")
        self.speed.changed.connect(lambda _v: self._restart())
        self.side.addWidget(self.speed)
        self.mix = _Slider("기준 ↔ 추적", 0, 100, 50, 1, lambda v: f"{v:.0f}%")
        self.mix.changed.connect(lambda _v: self._draw())
        self.side.addWidget(self.mix)

        self.side.addWidget(_head("정합"))
        row = QHBoxLayout()
        self.b_auto = _button("자동 정합", primary=True)
        self.b_zero = _button("보정 해제")
        self.b_auto.clicked.connect(self.auto_align)
        self.b_zero.clicked.connect(lambda: self.set_offset(0, 0, "보정을 해제했습니다."))
        row.addWidget(self.b_auto)
        row.addWidget(self.b_zero)
        self.side.addLayout(row)
        self.s_dx = _Slider("좌우", -60, 60, 0, 0.5, _px)
        self.s_dy = _Slider("상하", -60, 60, 0, 0.5, _px)
        self.s_dx.changed.connect(lambda v: self.set_offset(v, self.dy))
        self.s_dy.changed.connect(lambda v: self.set_offset(self.dx, v))
        self.side.addWidget(self.s_dx)
        self.side.addWidget(self.s_dy)
        self.status = _note()
        self.side.addWidget(self.status)
        self.side.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if pair:
            self.base = G.fit(pair[0])
            self.follow = G.match_size(G.fit(pair[1]), self.base)
            self.auto_align()
        self.set_mode("flick")

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.modes.set(mode)
        self.hint.setText(_PG_HINT[mode])
        self.speed.setVisible(mode == "flick")
        self.mix.setVisible(mode == "blend")
        self._restart()
        self._draw()

    def set_offset(self, dx: float, dy: float, status: str | None = None) -> None:
        if self.base is None:
            return
        self.dx, self.dy = max(-60.0, min(60.0, dx)), max(-60.0, min(60.0, dy))
        self.s_dx.set(self.dx)
        self.s_dy.set(self.dy)
        self._fs = G.shifted(self.follow, self.dx, self.dy)
        if status is not None:
            self.status.setText(status)
        self._draw()

    def auto_align(self) -> None:
        if self.base is None:
            return
        dx, dy = G.find_shift(self.base, self.follow)
        self.set_offset(dx, dy)
        self.status.setText(f"자동 정합: 좌우 {_px(self.dx)}, 상하 {_px(self.dy)} 보정")

    def _restart(self) -> None:
        if self.mode == "flick" and self.base is not None:
            self._timer.start(max(30, round(500 / self.speed.value())))
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if self.isVisible():
            self._phase ^= 1
            self._draw()

    def compose(self):
        if self.base is None:
            return None
        if self.mode == "flick":
            return self._fs if self._phase else self.base
        if self.mode == "blend":
            return G.blend(self.base, self._fs, self.mix.value() / 100)
        return G.diff_map(self.base, self._fs)

    def _draw(self) -> None:
        self.view.set_bgr(self.compose())

    def note(self) -> str:
        return "경과 비교"


# ================= 창 =================
class GlaucomaDialog(QDialog):
    saved = Signal(object)

    def __init__(self, patient, service, pair=None, current=None, eye: str = "NA", source: str = "", parent=None):
        """pair = (기준/왼쪽 BGR, 추적/오른쪽 BGR) 또는 None, current = 디스크·광각용 BGR 또는 None."""
        super().__init__(parent)
        self.setWindowTitle("녹내장 분석")
        self.resize(1280, 860)
        self.patient, self.service, self.eye = patient, service, eye or "NA"

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        top = QHBoxLayout()
        self.lbl_src = _note(source)
        self.lbl_msg = QLabel()
        self.b_save = _button("이 화면 저장", primary=True)
        self.b_save.setToolTip("지금 보이는 분석 화면을 환자의 새 영상으로 저장 (원본 보존)")
        self.b_close = _button("닫기")
        top.addWidget(self.lbl_src, 1)
        top.addWidget(self.lbl_msg)
        top.addWidget(self.b_save)
        top.addWidget(self.b_close)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.stereo = StereoTab(pair)
        self.disc = DiscTab(current, eye)
        self.wide = WideTab(current)
        self.progress = ProgressTab(pair)
        for tab, text in ((self.stereo, "스테레오 보기"), (self.disc, "디스크 C/D"),
                          (self.wide, "광각 분석"), (self.progress, "경과 비교")):
            self.tabs.addTab(tab, text)
        root.addWidget(self.tabs, 1)
        root.addWidget(_note("측정값은 참고용 추정값입니다. 진단은 의사가 영상을 보고 판단하세요. "
                             "깊이 지도는 상대값이며 절대 길이가 아닙니다."))
        self.b_save.clicked.connect(self.save)
        self.b_close.clicked.connect(self.close)

    def save(self):
        tab = self.tabs.currentWidget()
        if self.patient is None:
            self.lbl_msg.setText("환자를 먼저 선택하세요.")
            return None
        frame = tab.render() if tab.has_image() else None
        if frame is None:
            self.lbl_msg.setText("저장할 분석 화면이 없습니다.")
            return None
        eye = self.disc.eye if tab is self.disc else self.eye
        try:
            cap = self.service.save_photo(frame, self.patient, eye=eye, note=tab.note())
        except Exception as e:  # noqa: BLE001
            log.exception("glaucoma save failed")
            self.lbl_msg.setText(f"저장하지 못했습니다: {e}")
            return None
        self.lbl_msg.setText(f"저장했습니다 — {tab.note()}")
        self.saved.emit(cap)
        return cap
