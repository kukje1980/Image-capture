"""몽타주 편집기 — several photos of one eye put together (``montage.py``).

* 맞추기 tab: the photos laid over each other on the map of the eye, the selected one on
  top and semi-transparent (투명도), or green over magenta (색으로 구분: matching vessels
  turn grey). Drag a photo to move it, Ctrl+drag or right-drag to turn it, wheel to zoom,
  drag the empty background to pan; arrow keys nudge the selected photo, [ ] turn it.
* 자동 합치기 finds the vessels the photos share and places them (and corrects a wrong
  field of view); 기준점 맞추기 places the selected photo from points clicked on it and on
  a neighbour.
* 완성 tab: the blended montage (brightness matched, two-band blend: no seams, no doubled
  vessels); 3D tab: it on the eyeball, with the field of view worked out from the
  photos (몽타주 화각 자동) or set by hand.
* 환자 기록에 저장 stores it as a new photo of the patient (modality 몽타주, its eye
  geometry and the arrangement for 다시 편집); 파일로 저장 writes the picture.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, \
    QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSlider, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import imaging
from .. import montage as mt
from .. import projection as proj
from . import theme
from .image_view import ImageView, to_qimage

NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯"
FULL_SIZE = 4000               # the saved montage, at most this many pixels across
FAST_SIZE = 2400               # … with 빠르게 저장
PREVIEW_SIZE = 1400            # 완성 / 3D preview (the saved montage is drawn at full detail)
SEL, OTHER = QColor(255, 214, 64), QColor(235, 240, 245)


def number(k: int) -> str:
    return NUMBERS[k] if k < len(NUMBERS) else f"({k + 1})"


@dataclass
class MontageSource:
    """One photo for the montage, as the main window has it (original pixels)."""
    image_id: int | None
    rgb: np.ndarray
    alpha: np.ndarray | None
    circle: tuple[float, float, float]
    fov_deg: float
    fov_type: str = "external"
    projection: str = "perspective"
    viewpoint: float = proj.DEFAULT_VIEWPOINT
    radial_c: float = proj.DEFAULT_RADIAL_C
    label: str = ""
    disc: tuple[float, float] | None = None
    laterality: str | None = None


@dataclass
class MontageResult:
    """What 환자 기록에 저장 hands the main window."""
    rgb: np.ndarray
    geom: mt.MapGeometry
    fov_deg: float                       # internal, equidistant: the 3D view's field of view
    disc: tuple[float, float] | None     # on the montage
    definition: dict
    image_ids: list
    laterality: str | None


def _qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _clone(shots: list[mt.Shot]) -> list[mt.Shot]:
    """Copies a worker thread may change (the pictures are shared, read-only)."""
    return [dataclasses.replace(s, R=s.R.copy(), gain=s.gain.copy()) for s in shots]


class _Job(QThread):
    """``fn(say)`` off the GUI thread; ``say(text)`` reports progress."""
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.finished.connect(self.deleteLater)          # no thread object outlives its work

    def run(self):
        try:
            res = self._fn(self.progress.emit)
        except Exception as exc:  # pragma: no cover - reported to the user
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(res)


# ---------------------------------------------------------------------------
# 맞추기: the photos over each other
# ---------------------------------------------------------------------------
class MontageCanvas(QWidget):
    """The map of the eye with the photos laid over each other; drag to place them."""
    selectedChanged = Signal(int)
    editStarted = Signal()           # before a photo moves (for 되돌리기)
    edited = Signal()                # a photo was moved or turned
    hovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 380)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.shots: list[mt.Shot] = []
        self.hidden: set[int] = set()
        self.selected = 0
        self.opacity = 0.55
        self.tint = False
        self.cx = self.cy = 0.0                 # the middle of the window on the map plane (radians)
        self.scale = 400.0                      # screen pixels per radian
        self.overlay = mt.Overlay()
        self._img: QImage | None = None
        self._img_view = None                   # (cx, cy, scale, w, h) the image was drawn for
        self._drag = None
        self._full = QTimer(self)
        self._full.setSingleShot(True)
        self._full.timeout.connect(lambda: self.redraw(fast=False))

    # -- state ----------------------------------------------------------------------
    def set_shots(self, shots: list[mt.Shot], hidden=()) -> None:
        self.shots = shots
        self.hidden = set(hidden)
        self.selected = min(self.selected, max(0, len(shots) - 1))
        self.redraw()

    def select(self, k: int) -> None:
        if k != self.selected and 0 <= k < len(self.shots):
            self.selected = k
            self.selectedChanged.emit(k)
            self.redraw()

    def visible(self) -> list[int]:
        return [k for k in range(len(self.shots)) if k not in self.hidden]

    def fit(self) -> None:
        """Show every photo."""
        xs, ys = [], []
        for k in self.visible() or range(len(self.shots)):
            x, y = mt.plane_xy(self.shots[k].outline(60))
            xs.append(x)
            ys.append(y)
        if not xs:
            return
        x, y = np.concatenate(xs), np.concatenate(ys)
        self.cx, self.cy = float(x.min() + x.max()) / 2, float(y.min() + y.max()) / 2
        w, h = max(1.0, self.width() - 24.0), max(1.0, self.height() - 24.0)
        self.scale = min(w / max(1e-3, float(np.ptp(x))), h / max(1e-3, float(np.ptp(y))))
        self.redraw()

    # -- coordinates ----------------------------------------------------------------
    def to_plane(self, p: QPointF) -> tuple[float, float]:
        return (self.cx + (p.x() - self.width() / 2) / self.scale,
                self.cy - (p.y() - self.height() / 2) / self.scale)

    def to_screen(self, x, y):
        return (self.width() / 2 + (np.asarray(x) - self.cx) * self.scale,
                self.height() / 2 - (np.asarray(y) - self.cy) * self.scale)

    def dir_at(self, p: QPointF) -> np.ndarray:
        return mt.plane_dirs(*self.to_plane(p))

    # -- drawing --------------------------------------------------------------------
    def redraw(self, fast: bool = False) -> None:
        """Draw the photos again (``fast``: at half resolution while dragging; full shortly after)."""
        w, h = self.width(), self.height()
        if w < 2 or h < 2 or not self.shots:
            self._img = None
            self.update()
            return
        f = 2 if fast else 1
        x0, y0 = self.to_plane(QPointF(0, 0))
        self.overlay.set_view(x0, y0, f / self.scale, max(1, w // f), max(1, h // f))
        sel = self.selected if self.selected not in self.hidden else None
        rgb = self.overlay.compose(self.shots, sel, self.opacity, self.tint, hidden=self.hidden)
        self._img = _qimage(rgb)
        self._img_view = (self.cx, self.cy, self.scale, w, h)
        if fast:
            self._full.start(140)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._full.start(60)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(17, 19, 22))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._img is not None and self._img_view is not None:
            cx, cy, sc, w, h = self._img_view
            # the last picture, moved / scaled to the current view until the new one is drawn
            k = self.scale / sc
            sx, sy = self.to_screen(cx - w / 2 / sc, cy + h / 2 / sc)
            p.drawImage(QRectF(float(sx), float(sy), w * k, h * k), self._img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPixelSize(15)
        font.setBold(True)
        p.setFont(font)
        order = [k for k in range(len(self.shots)) if k != self.selected] + [self.selected]
        for k in order:
            if not (0 <= k < len(self.shots)):
                continue
            s = self.shots[k]
            xs, ys = self.to_screen(*mt.plane_xy(s.outline(160)))
            path = QPainterPath(QPointF(float(xs[0]), float(ys[0])))
            for x, y in zip(xs[1:], ys[1:]):
                path.lineTo(float(x), float(y))
            sel = k == self.selected
            col = QColor(SEL if sel else OTHER)
            col.setAlpha(255 if sel else 110)
            pen = QPen(col, 2.0 if sel else 1.0)
            if k in self.hidden:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            cx, cy = self.to_screen(*mt.plane_xy(s.centre()))
            r = QRectF(float(cx) - 13, float(cy) - 13, 26, 26)
            p.setBrush(QBrush(QColor(0, 0, 0, 150)))
            p.setPen(QPen(col, 1.5))
            p.drawEllipse(r)
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), str(k + 1))
        if not self.shots:
            p.setPen(QColor(200, 205, 210))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "사진이 없습니다")
        p.end()

    # -- mouse ----------------------------------------------------------------------
    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        d = self.dir_at(pos)
        shown = [s for k, s in enumerate(self.shots) if k not in self.hidden]
        idx = [k for k in range(len(self.shots)) if k not in self.hidden]
        hit = mt.shot_at(shown, d, prefer=idx.index(self.selected) if self.selected in idx else None)
        k = idx[hit] if hit is not None else None
        roll = (e.button() == Qt.MouseButton.RightButton
                or (e.button() == Qt.MouseButton.LeftButton
                    and e.modifiers() & Qt.KeyboardModifier.ControlModifier))
        if e.button() == Qt.MouseButton.MiddleButton or (k is None and e.button() == Qt.MouseButton.LeftButton):
            self._drag = ("pan", pos, (self.cx, self.cy))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if k is None:
            return
        self.select(k)
        s = self.shots[k]
        self.editStarted.emit()
        if roll:
            c = mt.plane_xy(s.centre())
            x, y = self.to_plane(pos)
            self._drag = ("roll", math.atan2(y - float(c[1]), x - float(c[0])), s.R.copy(), (float(c[0]), float(c[1])))
        else:
            self._drag = ("move", d, s.R.copy())
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        x, y = self.to_plane(pos)
        self.hovered.emit(f"후극에서 {math.degrees(math.hypot(x, y)):.0f}°")
        if self._drag is None:
            return
        kind = self._drag[0]
        if kind == "pan":
            _, start, (cx, cy) = self._drag
            self.cx = cx - (pos.x() - start.x()) / self.scale
            self.cy = cy + (pos.y() - start.y()) / self.scale
            self.update()
            self._full.start(120)
            return
        s = self.shots[self.selected]
        if kind == "move":
            _, d0, r0 = self._drag
            s.R = mt.rotation_between(d0, self.dir_at(pos)) @ r0
        else:
            _, a0, r0, (cx, cy) = self._drag
            s.R = r0.copy()
            mt.roll_about(s, math.degrees(math.atan2(y - cy, x - cx) - a0))
        self.redraw(fast=True)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            kind = self._drag[0]
            self._drag = None
            self.unsetCursor()
            if kind != "pan":
                self.edited.emit()
            self.redraw()

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if not steps:
            return
        pos = e.position()
        x, y = self.to_plane(pos)
        self.scale = min(max(self.scale * 1.18 ** steps, 40.0), 40000.0)
        nx, ny = self.to_plane(pos)                         # keep the point under the cursor
        self.cx += x - nx
        self.cy += y - ny
        self.update()
        self._full.start(90)

    def keyPressEvent(self, e):
        if not self.shots:
            return super().keyPressEvent(e)
        big = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = math.radians(1.0 if big else 0.1)
        moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                 Qt.Key.Key_Up: (0, step), Qt.Key.Key_Down: (0, -step)}
        s = self.shots[self.selected]
        if e.key() in moves:
            self.editStarted.emit()
            mt.move_on_plane(s, *moves[e.key()])
        elif e.key() in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            self.editStarted.emit()
            mt.roll_about(s, (1.0 if big else 0.2) * (1 if e.key() == Qt.Key.Key_BracketLeft else -1))
        elif e.key() == Qt.Key.Key_Tab:
            vis = self.visible()
            if vis:
                self.select(vis[(vis.index(self.selected) + 1) % len(vis)] if self.selected in vis else vis[0])
            return
        else:
            return super().keyPressEvent(e)
        self.redraw()
        self.edited.emit()

    def focusNextPrevChild(self, nxt):                      # Tab picks the next photo
        return False


# ---------------------------------------------------------------------------
# 기준점: the same spots on two photos
# ---------------------------------------------------------------------------
class PointView(QWidget):
    """A photo to click points on: wheel zooms at the cursor, right/middle-drag pans."""
    clicked = Signal(float, float)

    COLORS = [QColor(255, 214, 64), QColor(110, 215, 255), QColor(255, 120, 160), QColor(140, 235, 120),
              QColor(255, 160, 60), QColor(200, 150, 255)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 320)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._img: QImage | None = None
        self.points: list[tuple[float, float]] = []
        self.guess: tuple[float, float] | None = None
        self.zoom, self.ox, self.oy = 1.0, 0.0, 0.0
        self._pan = None

    def set_image(self, rgb: np.ndarray | None) -> None:
        self._img = _qimage(rgb) if rgb is not None else None
        self.fit()

    def fit(self) -> None:
        if self._img is None:
            return
        self.zoom = min(self.width() / self._img.width(), self.height() / self._img.height())
        self.ox = (self.width() - self._img.width() * self.zoom) / 2
        self.oy = (self.height() - self._img.height() * self.zoom) / 2
        self.update()

    def to_image(self, p: QPointF) -> tuple[float, float]:
        return (p.x() - self.ox) / self.zoom, (p.y() - self.oy) / self.zoom

    def to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(self.ox + x * self.zoom, self.oy + y * self.zoom)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(17, 19, 22))
        if self._img is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(QRectF(self.ox, self.oy, self._img.width() * self.zoom, self._img.height() * self.zoom),
                        self._img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPixelSize(14)
        font.setBold(True)
        p.setFont(font)
        if self.guess is not None:
            c = self.to_widget(*self.guess)
            p.setPen(QPen(QColor(255, 255, 255, 170), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 16, 16)
        for i, (x, y) in enumerate(self.points):
            c = self.to_widget(x, y)
            col = self.COLORS[i % len(self.COLORS)]
            p.setPen(QPen(QColor(0, 0, 0, 200), 4))
            p.drawLine(c + QPointF(-9, 0), c + QPointF(9, 0))
            p.drawLine(c + QPointF(0, -9), c + QPointF(0, 9))
            p.setPen(QPen(col, 2))
            p.drawLine(c + QPointF(-9, 0), c + QPointF(9, 0))
            p.drawLine(c + QPointF(0, -9), c + QPointF(0, 9))
            p.drawText(c + QPointF(8, -8), str(i + 1))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._img is not None:
            x, y = self.to_image(e.position())
            if 0 <= x < self._img.width() and 0 <= y < self._img.height():
                self.clicked.emit(x, y)
        elif e.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._pan = (e.position(), self.ox, self.oy)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            start, ox, oy = self._pan
            self.ox, self.oy = ox + e.position().x() - start.x(), oy + e.position().y() - start.y()
            self.update()

    def mouseReleaseEvent(self, e):
        self._pan = None

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            self.fit()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if not steps or self._img is None:
            return
        x, y = self.to_image(e.position())
        self.zoom = min(max(self.zoom * 1.2 ** steps, 0.05), 40.0)
        self.ox = e.position().x() - x * self.zoom
        self.oy = e.position().y() - y * self.zoom
        self.update()


class PointPairDialog(QDialog):
    """기준점 맞추기: click the same vessel crossing on the photo to place (left) and on a placed
    neighbour (right), as many pairs as wanted (2 or more; 4 or more also correct its field of view)."""

    def __init__(self, shots: list[mt.Shot], moving: int, anchors: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("기준점으로 맞추기")
        self.shots, self.moving = shots, moving
        self.left, self.right = PointView(), PointView()
        self.left.set_image(shots[moving].rgb)
        self.left.clicked.connect(self._on_left)
        self.right.clicked.connect(self._on_right)
        self.anchor = QComboBox()
        for k in anchors:
            self.anchor.addItem(f"{number(k)} {shots[k].label}", k)
        self.anchor.currentIndexChanged.connect(self._anchor_changed)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{theme.ACCENT_HI}; font-weight:600")
        b_undo = QPushButton("마지막 점 지우기")
        b_undo.clicked.connect(self.undo)
        b_clear = QPushButton("모두 지우기")
        b_clear.clicked.connect(self.clear)
        self.b_ok = QPushButton("이 점들로 맞추기")
        self.b_ok.setDefault(True)
        self.b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("취소")
        b_cancel.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(QLabel(f"맞출 사진: <b>{number(moving)} {shots[moving].label}</b>"))
        top.addStretch()
        top.addWidget(QLabel("기준이 될 사진"))
        top.addWidget(self.anchor)
        views = QSplitter(Qt.Orientation.Horizontal)
        views.addWidget(self.left)
        views.addWidget(self.right)
        btns = QHBoxLayout()
        btns.addWidget(b_undo)
        btns.addWidget(b_clear)
        btns.addStretch()
        btns.addWidget(self.b_ok)
        btns.addWidget(b_cancel)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(views, 1)
        lay.addWidget(self.hint)
        lay.addWidget(QLabel("휠: 확대·축소 · 오른쪽 드래그: 이동 · 오른쪽 더블클릭: 전체 보기"))
        lay.addLayout(btns)
        self.resize(1180, 680)
        self._anchor_changed()

    @property
    def anchor_index(self) -> int:
        return int(self.anchor.currentData())

    def _anchor_changed(self, *_):
        self.right.set_image(self.shots[self.anchor_index].rgb)
        self.clear()

    def pairs(self) -> tuple[np.ndarray, np.ndarray]:
        n = min(len(self.left.points), len(self.right.points))
        return np.asarray(self.left.points[:n], np.float64), np.asarray(self.right.points[:n], np.float64)

    def _sync(self) -> None:
        n = min(len(self.left.points), len(self.right.points))
        waiting_right = len(self.left.points) > len(self.right.points)
        if waiting_right:
            self.hint.setText(f"{len(self.left.points)}번 점: 오른쪽 사진에서 같은 곳을 클릭하세요 "
                              "(점선 원 = 지금 배치로 예상한 곳)")
        elif n < 2:
            self.hint.setText("왼쪽 사진에서 혈관이 갈라지거나 교차하는 곳을 클릭한 뒤, 오른쪽 사진에서 같은 곳을 "
                              f"클릭하세요 — {n}/2쌍 (4쌍 이상이면 화각도 함께 맞춥니다)")
        else:
            more = " · 화각도 함께 맞춥니다" if n >= 4 else " · 4쌍 이상이면 화각도 함께 맞춥니다"
            self.hint.setText(f"{n}쌍 — [이 점들로 맞추기]를 누르거나 점을 더 찍으세요{more}")
        self.b_ok.setEnabled(n >= 2 and not waiting_right)
        self.left.update()
        self.right.update()

    def _on_left(self, x: float, y: float) -> None:
        if len(self.left.points) > len(self.right.points):
            self.left.points[-1] = (x, y)                 # clicked again: move the waiting point
        else:
            self.left.points.append((x, y))
        # where the current arrangement puts that spot on the other photo
        m, a = self.shots[self.moving], self.shots[self.anchor_index]
        d = m.dirs(np.array([[x, y]])) @ m.R.T
        u, v, rho = a.pixels(d @ a.R)
        self.right.guess = (float(u[0]), float(v[0])) if np.isfinite(rho[0]) and rho[0] <= 1.05 else None
        self._sync()

    def _on_right(self, x: float, y: float) -> None:
        if len(self.right.points) >= len(self.left.points):
            if self.right.points:
                self.right.points[-1] = (x, y)            # move the last pair's point
            else:
                return
        else:
            self.right.points.append((x, y))
        self.right.guess = None
        self._sync()

    def undo(self) -> None:
        if len(self.left.points) > len(self.right.points):
            self.left.points.pop()
        elif self.left.points:
            self.left.points.pop()
            self.right.points.pop()
        self.right.guess = None
        self._sync()

    def clear(self) -> None:
        self.left.points.clear()
        self.right.points.clear()
        self.right.guess = None
        self._sync()


# ---------------------------------------------------------------------------
# the editor
# ---------------------------------------------------------------------------
class MontageDialog(QDialog):
    """``sources``: the photos (``MontageSource``); ``save_record(result)`` stores the montage in the
    patient record and returns its id; ``definition``: a saved arrangement to edit again."""

    def __init__(self, sources: list[MontageSource], *, file_stem: str = "몽타주", save_record=None,
                 definition: dict | None = None, auto: bool = True, fast: bool = False, on_fast=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("몽타주 — 여러 장을 한 장으로")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.sources = list(sources)
        self.file_stem = file_stem
        self._save_record = save_record
        self.saved_id: int | None = None
        self.definition_loaded = bool(definition)
        self.shots = [mt.Shot.from_photo(s.rgb, s.alpha, s.circle, fov_deg=s.fov_deg, fov_type=s.fov_type,
                                         projection=s.projection, viewpoint=s.viewpoint, radial_c=s.radial_c,
                                         image_id=s.image_id, label=s.label) for s in self.sources]
        self.ref = 0
        self._ref_chosen = False
        self._undo: list = []
        self._gen = 0                           # bumps on every change: stale previews are dropped
        self._preview = None                    # (gen, rgb, alpha, geom)
        self._job: _Job | None = None
        self._render_job: _Job | None = None
        self._busy_on = False
        self.eye = None                         # the 3D view, made when its tab is first opened

        # -- photos ------------------------------------------------------------------------
        self.list = QListWidget()
        self.list.setIconSize(QSize(56, 56))
        self.list.setMinimumHeight(150)
        for k, s in enumerate(self.shots):
            it = QListWidgetItem(self._thumb(s), self._item_text(k))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setToolTip("체크를 끄면 몽타주에서 뺍니다")
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._on_check)

        g_photo = QGroupBox("고른 사진")
        self.sp_fov = QDoubleSpinBox()
        self.sp_fov.setRange(10.0, 240.0)
        self.sp_fov.setDecimals(1)
        self.sp_fov.setSuffix("°")
        self.sp_fov.setToolTip("이 사진의 화각 (기기 설정과 다르면 고치세요 — 자동 합치기가 ±15%까지 스스로 고칩니다)")
        self.c_type = QComboBox()
        self.c_type.addItem("외부각(동공)", "external")
        self.c_type.addItem("안구 중심각", "internal")
        self.c_proj = QComboBox()
        for k in proj.PROJECTIONS:
            self.c_proj.addItem(proj.PROJECTION_LABELS[k], k)
        for w in (self.sp_fov, self.c_type, self.c_proj):
            sig = w.valueChanged if isinstance(w, QDoubleSpinBox) else w.currentIndexChanged
            sig.connect(self._on_geometry)
        self.lbl_fix = QLabel("")
        self.lbl_fix.setStyleSheet(f"color:{theme.GREEN}")
        rot = QHBoxLayout()
        for text, deg, tip in (("⟲ 1°", 1.0, "시계 반대 방향으로 1° 돌리기 ( [ )"),
                               ("⟳ 1°", -1.0, "시계 방향으로 1° 돌리기 ( ] )")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, d=deg: self._roll(d))
            rot.addWidget(b)
        form = QFormLayout(g_photo)
        form.addRow("화각", self.sp_fov)
        form.addRow("화각 기준", self.c_type)
        form.addRow("투영", self.c_proj)
        form.addRow("", self.lbl_fix)
        form.addRow("회전", rot)

        self.c_ref = QComboBox()
        self.c_ref.setToolTip("몽타주의 가운데(후극)가 될 사진 — 3D 안구에서 각막 반대편 중심에 놓입니다")
        for k, s in enumerate(self.shots):
            self.c_ref.addItem(f"{number(k)} {s.label}", k)
        self.c_ref.currentIndexChanged.connect(self._on_ref)

        self.b_auto = QPushButton("자동 합치기")
        self.b_auto.setObjectName("primaryButton")
        self.b_auto.setToolTip("사진들이 함께 보이는 혈관을 찾아 자동으로 맞춥니다 (화각이 조금 틀려도 고쳐 맞춤)")
        self.b_auto.clicked.connect(self.auto_align)
        self.b_points = QPushButton("기준점으로 맞추기…")
        self.b_points.setToolTip("고른 사진과 옆 사진에서 같은 곳(혈관 갈림길)을 찍어 맞춥니다")
        self.b_points.clicked.connect(self.align_by_points)
        self.b_undo = QPushButton("되돌리기")
        self.b_undo.setToolTip("마지막 이동·회전·맞추기를 취소 (Ctrl+Z)")
        self.b_undo.clicked.connect(self.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(self.undo)
        b_fit = QPushButton("전체 보기")
        b_fit.clicked.connect(lambda: self.canvas.fit())

        g_view = QGroupBox("겹쳐 보기")
        self.s_opacity = QSlider(Qt.Orientation.Horizontal)
        self.s_opacity.setRange(0, 100)
        self.s_opacity.setValue(55)
        self.s_opacity.setToolTip("고른 사진의 불투명도 — 낮추면 아래 사진이 비쳐 보입니다")
        self.s_opacity.valueChanged.connect(self._on_view)
        self.c_tint = QCheckBox("색으로 구분 (고른 사진 초록 · 나머지 자홍)")
        self.c_tint.setToolTip("혈관이 정확히 겹치면 회색, 어긋나면 초록·자홍 테두리가 보입니다")
        self.c_tint.toggled.connect(self._on_view)
        vl = QVBoxLayout(g_view)
        row = QHBoxLayout()
        row.addWidget(QLabel("투명도"))
        row.addWidget(self.s_opacity, 1)
        vl.addLayout(row)
        vl.addWidget(self.c_tint)

        g_out = QGroupBox("완성")
        self.c_gain = QCheckBox("밝기 맞추기")
        self.c_gain.setChecked(True)
        self.c_gain.setToolTip("겹친 부분의 밝기를 비교해 사진마다 밝기·색을 맞춥니다")
        self.c_gain.toggled.connect(self._changed)
        self.c_auto_fov = QCheckBox("몽타주 화각 자동")
        self.c_auto_fov.setChecked(True)
        self.c_auto_fov.setToolTip("사진들이 덮은 범위에서 안구 중심각을 계산합니다 — 끄면 직접 정합니다")
        self.c_auto_fov.toggled.connect(self._on_fov_mode)
        self.sp_mfov = QDoubleSpinBox()
        self.sp_mfov.setRange(20.0, 340.0)
        self.sp_mfov.setDecimals(1)
        self.sp_mfov.setSuffix("°")
        self.sp_mfov.setEnabled(False)
        self.sp_mfov.setToolTip("3D 안구에 입힐 때의 안구 중심각 (후극에서 가장자리까지 각도의 2배)")
        self.sp_mfov.valueChanged.connect(self._on_mfov)
        self.lbl_range = QLabel("")
        self.lbl_range.setWordWrap(True)
        self.c_fast = QCheckBox("빠르게 저장")
        self.c_fast.setChecked(bool(fast))
        self.c_fast.setToolTip(f"저장하는 몽타주를 최대 {FAST_SIZE}픽셀로 그립니다 (기본 {FULL_SIZE}픽셀) —\n"
                               "그리는 시간이 절반 아래로 줄고, 아주 크게 확대했을 때만 덜 선명합니다")
        if on_fast is not None:
            self.c_fast.toggled.connect(on_fast)
        ol = QVBoxLayout(g_out)
        ol.addWidget(self.c_gain)
        ol.addWidget(self.c_fast)
        row = QHBoxLayout()
        row.addWidget(self.c_auto_fov)
        row.addWidget(self.sp_mfov)
        ol.addLayout(row)
        ol.addWidget(self.lbl_range)

        side = QVBoxLayout()
        side.addWidget(QLabel("사진 (체크 = 포함)"))
        side.addWidget(self.list, 1)
        side.addWidget(g_photo)
        row = QHBoxLayout()
        row.addWidget(QLabel("가운데 사진"))
        row.addWidget(self.c_ref, 1)
        side.addLayout(row)
        side.addWidget(self.b_auto)
        row = QHBoxLayout()
        row.addWidget(self.b_points)
        row.addWidget(self.b_undo)
        side.addLayout(row)
        side.addWidget(g_view)
        side.addWidget(g_out)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(318)

        # -- views -------------------------------------------------------------------------
        self.canvas = MontageCanvas()
        self.canvas.selectedChanged.connect(self._on_canvas_select)
        self.canvas.editStarted.connect(self._push_undo)
        self.canvas.edited.connect(self._changed)
        self.canvas.hovered.connect(lambda t: self.lbl_hover.setText(t))
        page_edit = QWidget()
        pl = QVBoxLayout(page_edit)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.canvas, 1)
        bar = QHBoxLayout()
        hint = QLabel("드래그: 사진 옮기기 · Ctrl/오른쪽 드래그: 돌리기 · 빈 곳 드래그: 화면 이동 · 휠: 확대 · "
                      "방향키: 0.1° (Shift 1°) · [ ]: 돌리기 · Tab: 다음 사진")
        hint.setStyleSheet(f"color:{theme.TEXT3}; padding:3px 6px")
        self.lbl_hover = QLabel("")
        self.lbl_hover.setMinimumWidth(130)
        self.lbl_hover.setStyleSheet(f"color:{theme.TEXT2}; padding:3px 6px")
        bar.addWidget(hint, 1)
        bar.addWidget(self.lbl_hover)
        bar.addWidget(b_fit)
        pl.addLayout(bar)
        self.done_view = ImageView()
        self.page3d = QWidget()
        self._lay3d = QVBoxLayout(self.page3d)
        self._lay3d.setContentsMargins(0, 0, 0, 0)
        self._lbl3d = QLabel("3D 안구를 준비하는 중…")
        self._lbl3d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl3d.setStyleSheet(f"color:{theme.TEXT3}")
        self._lay3d.addWidget(self._lbl3d)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("views")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(page_edit, "맞추기 (반투명 겹치기)")
        self.tabs.addTab(self.done_view, "완성")
        self.tabs.addTab(self.page3d, "3D 안구")
        self.tabs.currentChanged.connect(self._on_tab)

        # -- bottom --------------------------------------------------------------------------
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.b_record = QPushButton("환자 기록에 저장")
        self.b_record.setToolTip("이 환자의 사진 목록에 몽타주를 새 사진으로 추가 (원본 사진은 그대로)")
        self.b_record.setEnabled(save_record is not None)
        self.b_record.clicked.connect(self.save_to_record)
        self.b_file = QPushButton("파일로 저장…")
        self.b_file.clicked.connect(self.save_file)
        b_close = QPushButton("닫기")
        b_close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addWidget(self.status, 1)
        for b in (self.b_record, self.b_file, b_close):
            btns.addWidget(b)

        split = QHBoxLayout()
        split.addWidget(side_w)
        split.addWidget(self.tabs, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(split, 1)
        lay.addLayout(btns)
        self.resize(1360, 880)

        # -- start ----------------------------------------------------------------------------
        if definition:
            for s, d in zip(self.shots, definition.get("shots", [])):
                s.apply_json(d)
            self.ref = max(0, min(int(definition.get("ref") or 0), len(self.shots) - 1))
            self._ref_chosen = True
            self.c_ref.blockSignals(True)
            self.c_ref.setCurrentIndex(self.ref)
            self.c_ref.blockSignals(False)
            inc = definition.get("included")
            self.list.blockSignals(True)
            for k in range(len(self.shots)):
                if inc is not None and k not in inc:
                    self.list.item(k).setCheckState(Qt.CheckState.Unchecked)
            self.list.blockSignals(False)
            self.c_gain.setChecked(bool(definition.get("brightness", True)))
            if definition.get("auto_fov") is False and definition.get("fov_deg"):
                self.c_auto_fov.setChecked(False)
                self.sp_mfov.setValue(float(definition["fov_deg"]))
        else:
            mt.spread(self.shots, 0)
        self.canvas.set_shots(self.shots, hidden=set(range(len(self.shots))) - set(self.included()))
        self.list.setCurrentRow(0)
        self._load_photo_controls()
        self._update_range()
        self._set_status("사진을 끌어 맞추거나 [자동 합치기]를 누르세요" if definition is None
                         else "저장된 몽타주 배치를 불러왔습니다")
        if auto and definition is None and len(self.shots) >= 2:
            QTimer.singleShot(0, self.auto_align)
        QTimer.singleShot(0, self.canvas.fit)

    # -- helpers ------------------------------------------------------------------------------
    def _thumb(self, s: mt.Shot) -> QIcon:
        h, w = s.rgb.shape[:2]
        k = 56.0 / max(h, w)
        import cv2
        small = cv2.resize(s.rgb, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
        return QIcon(QPixmap.fromImage(_qimage(small)))

    def _item_text(self, k: int) -> str:
        s = self.shots[k]
        fix = f" · 보정 ×{s.fov_scale:.2f}" if abs(s.fov_scale - 1.0) > 1e-3 else ""
        return f"{number(k)} {s.label}\n{s.fov_deg:g}°{fix}"

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setStyleSheet(f"color:{theme.ORANGE}; font-weight:600" if error else f"color:{theme.GREEN}")
        self.status.setText(text)

    def included(self) -> list[int]:
        return [k for k in range(len(self.shots))
                if self.list.item(k).checkState() == Qt.CheckState.Checked]

    def _busy(self, on: bool) -> None:
        for w in (self.b_auto, self.b_points, self.b_undo, self.b_record, self.b_file, self.list, self.c_ref,
                  self.sp_fov, self.c_type, self.c_proj):
            w.setEnabled(not on and (w is not self.b_record or self._save_record is not None))
        self.canvas.setEnabled(not on)
        if on != self._busy_on:
            self._busy_on = on
            if on:
                QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
            else:
                QApplication.restoreOverrideCursor()

    # -- undo -------------------------------------------------------------------------------------
    def _snapshot(self):
        return [(s.R.copy(), s.fov_scale, s.fov_deg, s.fov_type, s.projection, s.gain.copy(), s.radial_c, s.alpha, s.cut)
                for s in self.shots]

    def _push_undo(self) -> None:
        self._undo.append(self._snapshot())
        del self._undo[:-50]

    def undo(self) -> None:
        if not self._undo:
            self._set_status("되돌릴 것이 없습니다")
            return
        for s, (r, fs, fov, ft, pj, g, rc, al, cut) in zip(self.shots, self._undo.pop()):
            s.R, s.fov_scale, s.fov_deg, s.fov_type, s.projection, s.gain = r, fs, fov, ft, pj, g
            if al is not s.alpha:
                s._edge = None
            s.radial_c, s.alpha, s.cut = rc, al, cut
        self._load_photo_controls()
        self._changed()
        self._set_status("되돌렸습니다")

    # -- photo list / controls ---------------------------------------------------------------
    @property
    def current(self) -> int:
        return max(0, self.list.currentRow())

    def _on_row(self, k: int) -> None:
        if k < 0:
            return
        self.canvas.select(k)
        self._load_photo_controls()

    def _on_canvas_select(self, k: int) -> None:
        self.list.blockSignals(True)
        self.list.setCurrentRow(k)
        self.list.blockSignals(False)
        self._load_photo_controls()

    def _on_check(self, item: QListWidgetItem) -> None:
        self.canvas.set_shots(self.shots, hidden=set(range(len(self.shots))) - set(self.included()))
        self._changed()

    def _load_photo_controls(self) -> None:
        s = self.shots[self.current]
        for w in (self.sp_fov, self.c_type, self.c_proj):
            w.blockSignals(True)
        self.sp_fov.setValue(s.fov_deg)
        self.c_type.setCurrentIndex(max(0, self.c_type.findData(s.fov_type)))
        self.c_proj.setCurrentIndex(max(0, self.c_proj.findData(s.projection)))
        for w in (self.sp_fov, self.c_type, self.c_proj):
            w.blockSignals(False)
        tmax = math.degrees(s.tmax)
        fix = f"자동 보정 ×{s.fov_scale:.2f} → " if abs(s.fov_scale - 1.0) > 1e-3 else ""
        self.lbl_fix.setText(f"{fix}안구 중심각 {2 * tmax:.0f}°")

    def _on_geometry(self, *_):
        s = self.shots[self.current]
        self._push_undo()
        s.fov_deg = self.sp_fov.value()
        s.fov_type = self.c_type.currentData()
        s.projection = self.c_proj.currentData()
        s.fov_scale = 1.0
        self._load_photo_controls()
        self._changed()

    def _roll(self, deg: float) -> None:
        self._push_undo()
        mt.roll_about(self.shots[self.current], deg)
        self._changed()

    def _on_ref(self, *_):
        k = int(self.c_ref.currentData())
        self._ref_chosen = True
        if k != self.ref:
            self._push_undo()
            self.ref = k
            mt.recentre(self.shots, k)
            self._changed()
            self.canvas.fit()

    def _on_view(self, *_):
        self.canvas.opacity = self.s_opacity.value() / 100.0
        self.canvas.tint = self.c_tint.isChecked()
        self.canvas.redraw()

    # -- changes -------------------------------------------------------------------------------
    def _changed(self, *_):
        """Something moved: the overlay redraws now, 완성 / 3D when they are looked at."""
        self._gen += 1
        self.list.blockSignals(True)
        for k in range(len(self.shots)):
            self.list.item(k).setText(self._item_text(k))
        self.list.blockSignals(False)
        self.canvas.redraw()
        self._update_range()
        if self.tabs.currentIndex() != 0:
            self._schedule_preview()

    def _active(self) -> list[mt.Shot]:
        return [self.shots[k] for k in self.included()]

    def auto_fov_deg(self) -> float:
        """The montage's field of view (internal) from the photos it covers."""
        act = self._active()
        return 2.0 * math.degrees(mt.coverage_angle(act)) if act else 0.0

    def montage_fov(self) -> float:
        return self.auto_fov_deg() if self.c_auto_fov.isChecked() else self.sp_mfov.value()

    def _update_range(self) -> None:
        a = self.auto_fov_deg()
        if self.c_auto_fov.isChecked():
            self.sp_mfov.blockSignals(True)
            self.sp_mfov.setValue(a)
            self.sp_mfov.blockSignals(False)
        f = self.montage_fov()
        self.lbl_range.setText(f"덮은 범위: 후극에서 {a / 2:.0f}° (안구 중심각 {a:.0f}°)"
                               + ("" if self.c_auto_fov.isChecked() else f"\n3D에는 {f:.0f}°로 입힙니다"))

    def _on_fov_mode(self, on: bool) -> None:
        self.sp_mfov.setEnabled(not on)
        self._update_range()
        self._push_3d()

    def _on_mfov(self, *_):
        self._update_range()
        self._push_3d()

    # -- 자동 / 기준점 -----------------------------------------------------------------------
    def auto_align(self) -> None:
        idx = self.included()
        if len(idx) < 2:
            self._set_status("사진을 두 장 이상 포함하세요", error=True)
            return
        if self._job is not None:
            return
        ref = self.ref if self.ref in idx else idx[0]
        work = _clone([self.shots[k] for k in idx])
        r = idx.index(ref)
        gains = self.c_gain.isChecked()

        def run(say):
            rep = mt.auto_align(work, r, progress=say)
            if gains and len(rep.placed) >= 2:
                say("밝기 맞추는 중")
                mt.match_gains([work[k] for k in rep.placed])
            return rep

        self._push_undo()
        self._busy(True)
        self._set_status("자동 합치기를 시작합니다…")
        job = _Job(run, self)
        job.progress.connect(lambda t: self._set_status(t + "…"))
        job.done.connect(lambda rep: self._auto_done(rep, idx, work))
        job.failed.connect(lambda msg: self._auto_failed(msg))
        job.finished.connect(lambda: setattr(self, "_job", None))
        self._job = job
        job.start()

    def _auto_done(self, rep: mt.AlignReport, idx: list[int], work: list[mt.Shot]) -> None:
        self._busy(False)
        for k, w in zip(idx, work):
            s = self.shots[k]
            s.R, s.fov_scale, s.gain = w.R, w.fov_scale, w.gain
            # the lens found from the photos and what was left out of them (glare, flare)
            s.projection, s.fov_deg, s.radial_c = w.projection, w.fov_deg, w.radial_c
            if w.alpha is not s.alpha:
                s.alpha, s.cut, s._edge = w.alpha, w.cut, None
        placed = [idx[k] for k in rep.placed]
        if not self._ref_chosen and len(placed) >= 3:      # the middle photo becomes the centre
            mid = mt.most_central(self.shots, placed)
            if mid != self.ref:
                self.ref = mid
                mt.recentre(self.shots, mid)
                self.c_ref.blockSignals(True)
                self.c_ref.setCurrentIndex(mid)
                self.c_ref.blockSignals(False)
        self._load_photo_controls()
        self._changed()
        self.canvas.fit()
        self._set_status("자동 합치기: " + rep.text(), error=bool(rep.unplaced))

    def _auto_failed(self, msg: str) -> None:
        self._busy(False)
        if self._undo:
            self._undo.pop()
        self._set_status(f"자동 합치기를 하지 못했습니다 — {msg}", error=True)

    def align_by_points(self) -> None:
        k = self.current
        others = [j for j in self.included() if j != k]
        if not others:
            self._set_status("기준이 될 다른 사진을 포함하세요", error=True)
            return
        c = self.shots[k].centre()
        others.sort(key=lambda j: -float(self.shots[j].centre() @ c))   # the nearest photo first
        dlg = PointPairDialog(self.shots, k, others, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mu, au = dlg.pairs()
        self._push_undo()
        try:
            err = mt.align_points(self.shots[k], mu, self.shots[dlg.anchor_index], au)
        except ValueError as exc:
            self._undo.pop()
            self._set_status(str(exc), error=True)
            return
        self._load_photo_controls()
        self._changed()
        warn = err > 1.0
        self._set_status(f"기준점 {len(mu)}쌍으로 맞췄습니다 · 가장 큰 어긋남 {err:.2f}°"
                         + (" — 잘못 찍은 점이 있는지 확인하세요" if warn else ""), error=warn)

    # -- 완성 / 3D -------------------------------------------------------------------------
    def _on_tab(self, i: int) -> None:
        if i == 2 and self.eye is None:
            self._make_eye()
        if i != 0:
            self._schedule_preview()

    def _schedule_preview(self) -> None:
        if self._preview is not None and self._preview[0] == self._gen:
            return
        if self._render_job is not None:                     # one at a time; the newest wins after it
            return
        act = _clone(self._active())
        if not act:
            return
        gen = self._gen
        smooth_gain = self.c_gain.isChecked()

        def run(say):
            if not smooth_gain:
                for s in act:
                    s.gain = np.ones(3)
            geom = mt.map_for(act, max_size=PREVIEW_SIZE)
            rgb, alpha, geom = mt.render(act, geom)
            return gen, rgb, alpha, geom

        self._set_status("완성 미리보기를 그리는 중…")
        job = _Job(run, self)
        job.done.connect(self._preview_done)
        job.failed.connect(lambda m: self._set_status(f"미리보기를 그리지 못했습니다 — {m}", error=True))
        job.finished.connect(self._preview_finished)
        self._render_job = job
        job.start()

    def _preview_done(self, res) -> None:
        self._preview = res
        gen, rgb, alpha, geom = res
        self.done_view.set_rgb(rgb)
        self._push_3d()
        if gen == self._gen:
            self._set_status(f"완성 미리보기 · {len(self._active())}장 · 덮은 범위 안구 중심각 "
                             f"{2 * math.degrees(geom.angle):.0f}°")

    def _preview_finished(self) -> None:
        self._render_job = None
        if self.tabs.currentIndex() != 0 and (self._preview is None or self._preview[0] != self._gen):
            self._schedule_preview()

    def _make_eye(self) -> None:
        try:
            from .eye3d import EyeView
            self.eye = EyeView()
        except Exception as exc:  # pragma: no cover - no OpenGL
            self._lbl3d.setText(f"3D 안구를 열 수 없습니다: {exc}")
            return
        self.eye.set_detail("detailed")
        self.eye.relief = 0.6                 # 입체 조명 and 유리 공막, as in the main window
        self.eye.glass = 0.8
        self._lay3d.removeWidget(self._lbl3d)
        self._lbl3d.hide()
        self._lay3d.addWidget(self.eye, 1)
        self._push_3d()

    def _disc_on(self, geom: mt.MapGeometry, shots=None, idx=None) -> tuple[float, float] | None:
        """The optic disc on the montage, from the photos that know where theirs is (the centre photo first)."""
        idx = self.included() if idx is None else idx
        shots = [self.shots[k] for k in idx] if shots is None else shots
        order = sorted(range(len(idx)), key=lambda i: idx[i] != self.ref)
        for i in order:
            disc = self.sources[idx[i]].disc
            if disc is not None:
                return mt.disc_on_map(shots[i], disc, geom)
        return None

    def laterality(self) -> str | None:
        eyes = {self.sources[k].laterality for k in self.included()} - {None, ""}
        return eyes.pop() if len(eyes) == 1 else None

    def _push_3d(self) -> None:
        if self.eye is None or self._preview is None:
            return
        _, rgb, alpha, geom = self._preview
        circle = geom.circle()
        self.eye.set_mapping(fov_deg=self.montage_fov(), fov_type="internal", projection="equidistant", roll_deg=0.0)
        self.eye.set_image(rgb, alpha, circle)
        # on the eye as in the main window: the montage's fovea at the posterior pole, its disc nasal
        lat, disc = self.laterality(), self._disc_on(geom)
        fovea = imaging.detect_fovea(rgb, self.eye.photo_camera(circle), disc, lat) if disc is not None else None
        self.eye.set_landmarks(lat, disc, fovea[:2] if fovea else None, circle)

    # -- output ----------------------------------------------------------------------------
    def _final_job(self):
        """The montage at full detail from the original photos — a function for the worker thread,
        with everything it needs taken from the dialog now."""
        idx = self.included()
        gains = self.c_gain.isChecked()
        full = []
        for k in idx:
            s, src = self.shots[k], self.sources[k]
            a = src.alpha if src.alpha is not None else np.full(src.rgb.shape[:2], 255, np.uint8)
            a = mt.full_alpha(s, a)                 # glare and flare stay out of the saved montage too
            full.append(dataclasses.replace(s, rgb=src.rgb, alpha=a, circle=tuple(src.circle), scale=1.0,
                                            R=s.R.copy(), gain=s.gain.copy() if gains else np.ones(3)))
        fov, lat = round(self.montage_fov(), 1), self.laterality()
        definition = mt.definition(self.shots, self.ref) | {
            "included": idx, "auto_fov": self.c_auto_fov.isChecked(), "brightness": gains, "fov_deg": fov}
        ids = [self.shots[k].image_id for k in idx]

        size = FAST_SIZE if self.c_fast.isChecked() else FULL_SIZE

        def run(say):
            geom = mt.map_for(full, max_size=size)
            rgb, _, geom = mt.render(full, geom, progress=lambda f: say(f"몽타주를 그리는 중 {int(f * 100)}%"))
            return MontageResult(rgb=rgb, geom=geom, fov_deg=fov, disc=self._disc_on(geom, full, idx),
                                 definition=definition, image_ids=ids, laterality=lat)
        return run

    def _run_final(self, then) -> None:
        if not self.included() or self._job is not None:
            return
        self._busy(True)
        job = _Job(self._final_job(), self)
        job.progress.connect(self._set_status)
        job.done.connect(lambda res: (self._busy(False), then(res)))
        job.failed.connect(lambda m: (self._busy(False), self._set_status(f"몽타주를 만들지 못했습니다 — {m}",
                                                                          error=True)))
        job.finished.connect(lambda: setattr(self, "_job", None))
        self._job = job
        job.start()

    def save_to_record(self) -> None:
        if self._save_record is None:
            return

        def store(res: MontageResult):
            self.saved_id = self._save_record(res)
            self._set_status(f"환자 기록에 몽타주를 저장했습니다 ({res.geom.size}×{res.geom.size}, "
                             f"안구 중심각 {res.fov_deg:g}°) — 3D 안구에서도 볼 수 있습니다")

        self._run_final(store)

    def save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "몽타주 저장", f"{self.file_stem}.png",
                                              "PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".png"

        def write(res: MontageResult):
            ok = to_qimage(res.rgb).save(path, quality=95)
            self._set_status(f"저장했습니다: {path}" if ok else f"저장하지 못했습니다: {path}", error=not ok)

        self._run_final(write)

    def closeEvent(self, e):
        self._wait_jobs()
        super().closeEvent(e)

    def done(self, r):
        self._wait_jobs()
        super().done(r)

    def _wait_jobs(self) -> None:
        for j in (self._job, self._render_job):
            if j is not None:
                j.wait(120000)
        QApplication.processEvents()                     # deliver their results before the dialog goes
        self._busy(False)


def confirm_sources(parent, sources: list[MontageSource]) -> bool:
    """Photos of different eyes cannot make one montage."""
    eyes = {s.laterality for s in sources} - {None, ""}
    if len(eyes) > 1:
        QMessageBox.information(parent, "몽타주", "오른쪽 눈과 왼쪽 눈 사진이 섞여 있습니다.\n같은 눈의 사진만 고르세요.")
        return False
    return True
