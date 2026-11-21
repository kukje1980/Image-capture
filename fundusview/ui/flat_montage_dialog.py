"""수동 합치기 — the photos as they are, laid over each other by hand (``flat_montage.py``).

* 맞추기 tab: the photo at the back (맨 뒤 사진) opaque, the photos over it semi-transparent (투명도),
  so the vessels of the one below show through. Drag a photo to move it, Ctrl+drag or right-drag
  to turn it, wheel to zoom, drag the empty background to pan; arrow keys nudge the selected photo
  by one screen pixel (Shift: ten), [ ] turn it. Nothing is reprojected: every photo keeps its shape.
* 완성 tab: the photos blended as they lie — brightness matched, no seams (the blend of the montage).
* 파일로 저장 writes that picture (cut to what the photos cover); 환자 기록에 저장 stores it as a new
  photo of the patient (modality 몽타주; its arrangement is kept, so it opens here again).
"""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from .. import flat_montage as fm
from .. import montage as mt
from .widgets import RoundCorners
from . import theme
from .image_view import ImageView, to_qimage

FULL_SIZE = 4000               # the saved picture, at most this many pixels across
PREVIEW_SIZE = 1400            # 완성 preview (from the working copies)
SEL, OTHER = QColor(255, 214, 64), QColor(235, 240, 245)
NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯"


def number(k: int) -> str:
    return NUMBERS[k] if k < len(NUMBERS) else f"({k + 1})"


def _layer(shot: mt.Shot) -> QImage:
    """The working copy of a photo with what is not retina transparent."""
    rgba = np.dstack([shot.rgb, fm.mask(shot)])
    h, w = rgba.shape[:2]
    img = QImage(np.ascontiguousarray(rgba).data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)     # (a copy of its own)


class FlatCanvas(QWidget):
    """The plane with the photos over each other; drag to place them."""
    selectedChanged = Signal(int)
    editStarted = Signal()           # before a photo moves (for 되돌리기)
    edited = Signal()                # a photo was moved or turned

    def __init__(self, parent=None):
        super().__init__(parent)
        RoundCorners(self)    # round corners, as every pane of a photo
        self.setMinimumSize(480, 380)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.shots: list[mt.Shot] = []
        self.rhos: list[float] = []
        self.places: list[fm.Placement] = []
        self.layers: list[QImage] = []
        self.hidden: set[int] = set()
        self.base = 0                           # the photo at the back (opaque)
        self.selected = 0
        self.opacity = 0.55                     # of the photos over it
        self.cx = self.cy = 0.0                 # the middle of the window on the plane
        self.scale = 300.0                      # screen pixels per plane unit
        self._drag = None

    # -- state ----------------------------------------------------------------------
    def set_photos(self, shots, rhos, places, hidden=()) -> None:
        self.shots, self.rhos, self.places = shots, rhos, places
        self.layers = [_layer(s) for s in shots]
        self.hidden = set(hidden)
        self.selected = min(self.selected, max(0, len(shots) - 1))
        self.update()

    def order(self) -> list[int]:
        """The photos shown, from the back to the front."""
        vis = [k for k in range(len(self.shots)) if k not in self.hidden]
        return ([self.base] if self.base in vis else []) + [k for k in vis if k != self.base]

    def select(self, k: int) -> None:
        if k != self.selected and 0 <= k < len(self.shots):
            self.selected = k
            self.selectedChanged.emit(k)
            self.update()

    def fit(self) -> None:
        """Show every photo."""
        vis = self.order() or list(range(len(self.shots)))
        if not vis:
            return
        x0, y0, x1, y1 = fm.bounds([self.rhos[k] for k in vis], [self.places[k] for k in vis])
        self.cx, self.cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = max(1.0, self.width() - 24.0), max(1.0, self.height() - 24.0)
        self.scale = min(w / max(1e-3, x1 - x0), h / max(1e-3, y1 - y0))
        self.update()

    # -- coordinates ----------------------------------------------------------------
    def to_plane(self, p: QPointF) -> tuple[float, float]:
        return (self.cx + (p.x() - self.width() / 2) / self.scale,
                self.cy + (p.y() - self.height() / 2) / self.scale)

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (self.width() / 2 + (x - self.cx) * self.scale, self.height() / 2 + (y - self.cy) * self.scale)

    def photo_at(self, p: QPointF) -> int | None:
        """The photo under that point: the selected one if it is there, else the one on top."""
        x, y = self.to_plane(p)
        on = [k for k in self.order() if fm.hit(self.shots[k], self.rhos[k], self.places[k], x, y)]
        if not on:
            return None
        return self.selected if self.selected in on else on[-1]

    # -- drawing --------------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(17, 19, 22))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        order = self.order()
        for n, k in enumerate(order):
            s, pl = self.shots[k], self.places[k]
            cx, cy, r = s.circle
            x, y = self.to_screen(pl.x, pl.y)
            p.save()
            p.translate(x, y)
            p.rotate(-pl.angle)
            f = self.rhos[k] / r * self.scale
            p.scale(f, f)
            p.translate(-cx, -cy)
            p.setOpacity(1.0 if n == 0 else self.opacity)       # the one at the back: opaque
            p.drawImage(0, 0, self.layers[k])
            p.restore()
        font = QFont()
        font.setPixelSize(15)
        font.setBold(True)
        p.setFont(font)
        for k in [k for k in range(len(self.shots)) if k != self.selected] + [self.selected]:
            if not (0 <= k < len(self.shots)):
                continue
            pl = self.places[k]
            x, y = self.to_screen(pl.x, pl.y)
            rad = self.rhos[k] * self.scale
            sel = k == self.selected
            col = QColor(SEL if sel else OTHER)
            col.setAlpha(255 if sel else 90)
            pen = QPen(col, 2.0 if sel else 1.0)
            if k in self.hidden:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(x, y), rad, rad)
            if sel:                                             # which way the photo's top points
                a = math.radians(pl.angle + 90.0)
                p.drawLine(QPointF(x + 0.94 * rad * math.cos(a), y - 0.94 * rad * math.sin(a)),
                           QPointF(x + rad * math.cos(a), y - rad * math.sin(a)))
            box = QRectF(x - 13, y - 13, 26, 26)
            p.setBrush(QBrush(QColor(0, 0, 0, 150)))
            p.setPen(QPen(col, 1.5))
            p.drawEllipse(box)
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), str(k + 1))
        if not self.shots:
            p.setPen(QColor(200, 205, 210))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "사진이 없습니다")
        p.end()

    # -- mouse ----------------------------------------------------------------------
    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        k = self.photo_at(pos)
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
        pl = self.places[k]
        self.editStarted.emit()
        x, y = self.to_plane(pos)
        if roll:
            self._drag = ("roll", math.atan2(-(y - pl.y), x - pl.x), pl.angle)
        else:
            self._drag = ("move", (x, y), (pl.x, pl.y))
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        pos = e.position()
        kind = self._drag[0]
        if kind == "pan":
            _, start, (cx, cy) = self._drag
            self.cx = cx - (pos.x() - start.x()) / self.scale
            self.cy = cy - (pos.y() - start.y()) / self.scale
            self.update()
            return
        pl = self.places[self.selected]
        x, y = self.to_plane(pos)
        if kind == "move":
            _, (sx, sy), (px, py) = self._drag
            pl.x, pl.y = px + x - sx, py + y - sy
        else:
            _, a0, angle0 = self._drag
            pl.angle = angle0 + math.degrees(math.atan2(-(y - pl.y), x - pl.x) - a0)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            kind = self._drag[0]
            self._drag = None
            self.unsetCursor()
            if kind != "pan":
                self.edited.emit()
            self.update()

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if not steps:
            return
        pos = e.position()
        x, y = self.to_plane(pos)
        self.scale = min(max(self.scale * 1.18 ** steps, 20.0), 20000.0)
        nx, ny = self.to_plane(pos)                         # keep the point under the cursor
        self.cx += x - nx
        self.cy += y - ny
        self.update()

    def keyPressEvent(self, e):
        if not self.shots:
            return super().keyPressEvent(e)
        big = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = (10.0 if big else 1.0) / self.scale          # one screen pixel (Shift: ten)
        moves = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                 Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
        pl = self.places[self.selected]
        if e.key() in moves:
            self.editStarted.emit()
            pl.x += moves[e.key()][0]
            pl.y += moves[e.key()][1]
        elif e.key() in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            self.editStarted.emit()
            pl.angle += (1.0 if big else 0.2) * (1 if e.key() == Qt.Key.Key_BracketLeft else -1)
        elif e.key() == Qt.Key.Key_Tab:
            vis = sorted(self.order())
            if vis:
                self.select(vis[(vis.index(self.selected) + 1) % len(vis)] if self.selected in vis else vis[0])
            return
        else:
            return super().keyPressEvent(e)
        self.update()
        self.edited.emit()

    def focusNextPrevChild(self, nxt):                      # Tab picks the next photo
        return False



class FlatMontageDialog(QDialog):
    """``sources``: the photos (``montage_dialog.MontageSource``); ``places``: where they lie to begin
    with (``flat_montage.Placement`` each — e.g. as 자동 합치기 left them); ``definition``: a saved
    arrangement; ``save_record(result)`` stores a ``MontageResult`` in the patient record."""

    def __init__(self, sources, *, places=None, definition: dict | None = None, file_stem: str = "몽타주",
                 save_record=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("수동 합치기 — 원본 사진을 겹쳐서 한 장으로")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.sources = list(sources)
        self.file_stem = file_stem
        self._save_record = save_record
        self.saved_id: int | None = None
        self.shots = [mt.Shot.from_photo(s.rgb, s.alpha, s.circle, fov_deg=s.fov_deg, fov_type=s.fov_type,
                                         projection=s.projection, viewpoint=s.viewpoint, radial_c=s.radial_c,
                                         image_id=s.image_id, label=s.label) for s in self.sources]
        self.rhos = fm.unit_radii(self.shots)
        self.places = [p.copy() for p in places] if places else fm.spread(self.rhos, 0)
        self._undo: list = []
        self._preview_key = None

        self.list = QListWidget()
        self.list.setIconSize(QSize(56, 56))
        self.list.setMinimumHeight(150)
        for k, s in enumerate(self.shots):
            it = QListWidgetItem(self._thumb(s), f"{number(k)} {s.label}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setToolTip("체크를 끄면 합치는 사진에서 뺍니다")
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._on_check)

        self.c_base = QComboBox()
        self.c_base.setToolTip("맨 뒤에 놓이는 사진 — 이 사진은 불투명하게, 그 위의 사진들은 반투명하게 보입니다")
        for k, s in enumerate(self.shots):
            self.c_base.addItem(f"{number(k)} {s.label}", k)
        self.c_base.currentIndexChanged.connect(self._on_base)

        g_view = QGroupBox("겹쳐 보기")
        self.s_opacity = QSlider(Qt.Orientation.Horizontal)
        self.s_opacity.setRange(10, 100)
        self.s_opacity.setValue(55)
        self.s_opacity.setToolTip("위에 놓인 사진들의 불투명도 — 낮추면 아래 사진이 더 비쳐 보입니다 (맨 뒤 사진은 늘 불투명)")
        self.s_opacity.valueChanged.connect(self._on_view)
        vl = QVBoxLayout(g_view)
        row = QHBoxLayout()
        row.addWidget(QLabel("맨 뒤 사진"))
        row.addWidget(self.c_base, 1)
        vl.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("위 사진 투명도"))
        row.addWidget(self.s_opacity, 1)
        vl.addLayout(row)

        g_photo = QGroupBox("고른 사진")
        pl = QVBoxLayout(g_photo)
        rot = QHBoxLayout()
        for text, deg, tip in (("⟲ 1°", 1.0, "시계 반대 방향으로 1° 돌리기 ( Shift+[ )"),
                               ("⟳ 1°", -1.0, "시계 방향으로 1° 돌리기 ( Shift+] )"),
                               ("⟲ 0.2°", 0.2, "시계 반대 방향으로 0.2° ( [ )"), ("⟳ 0.2°", -0.2, "시계 방향으로 0.2° ( ] )")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, d=deg: self._roll(d))
            rot.addWidget(b)
        pl.addLayout(rot)
        self.lbl_place = QLabel("")
        self.lbl_place.setStyleSheet(f"color:{theme.TEXT2}")
        pl.addWidget(self.lbl_place)

        self.b_undo = QPushButton("되돌리기")
        self.b_undo.setToolTip("마지막 이동·회전을 취소 (Ctrl+Z)")
        self.b_undo.clicked.connect(self.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(self.undo)
        b_fit = QPushButton("전체 보기")
        b_fit.clicked.connect(lambda: self.canvas.fit())

        g_out = QGroupBox("완성")
        self.c_gain = QCheckBox("밝기 맞추기")
        self.c_gain.setChecked(True)
        self.c_gain.setToolTip("겹친 부분의 밝기를 비교해 사진마다 밝기·색을 맞춥니다 (이음매가 덜 보입니다)")
        self.c_gain.toggled.connect(self._changed)
        ol = QVBoxLayout(g_out)
        ol.addWidget(self.c_gain)
        note = QLabel("저장하면 사진 가장자리가 부드럽게 이어지고(이음매 없음), 혈관은 그 자리를 가장 가운데로 "
                      "찍은 사진의 것만 써서 두 겹으로 보이지 않습니다.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.TEXT3}")
        ol.addWidget(note)

        side = QVBoxLayout()
        side.addWidget(QLabel("사진 (체크 = 포함)"))
        side.addWidget(self.list, 1)
        side.addWidget(g_view)
        side.addWidget(g_photo)
        row = QHBoxLayout()
        row.addWidget(self.b_undo)
        row.addWidget(b_fit)
        side.addLayout(row)
        side.addWidget(g_out)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(318)

        self.canvas = FlatCanvas()
        self.canvas.selectedChanged.connect(self._on_canvas_select)
        self.canvas.editStarted.connect(self._push_undo)
        self.canvas.edited.connect(self._changed)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas, 1)
        hint = QLabel("드래그: 사진 옮기기 · Ctrl/오른쪽 드래그: 돌리기 · 빈 곳 드래그: 화면 이동 · 휠: 확대 · "
                      "방향키: 1픽셀 (Shift 10픽셀) · [ ]: 0.2° 돌리기 (Shift 1°) · Tab: 다음 사진")
        hint.setStyleSheet(f"color:{theme.TEXT3}; padding:3px 6px")
        lay.addWidget(hint)
        self.done_view = ImageView()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("views")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(page, "맞추기 (원본 사진 겹치기)")
        self.tabs.addTab(self.done_view, "완성 (저장될 모습)")
        self.tabs.currentChanged.connect(self._on_tab)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.b_record = QPushButton("환자 기록에 저장")
        self.b_record.setToolTip("이 환자의 사진 목록에 합친 사진을 새 사진으로 추가 (원본 사진은 그대로)")
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
        top = QVBoxLayout(self)
        top.addLayout(split, 1)
        top.addLayout(btns)
        self.resize(1360, 880)

        base = 0
        if definition:
            for pl_, d in zip(self.places, definition.get("shots", [])):
                pl_.x, pl_.y = float(d.get("x", 0.0)), float(d.get("y", 0.0))
                pl_.angle = float(d.get("angle", 0.0))
            base = max(0, min(int(definition.get("ref") or 0), len(self.shots) - 1))
            inc = definition.get("included")
            self.list.blockSignals(True)
            for k in range(len(self.shots)):
                if inc is not None and k not in inc:
                    self.list.item(k).setCheckState(Qt.CheckState.Unchecked)
            self.list.blockSignals(False)
            self.c_gain.setChecked(bool(definition.get("brightness", True)))
        self.canvas.base = base
        self.c_base.blockSignals(True)
        self.c_base.setCurrentIndex(base)
        self.c_base.blockSignals(False)
        self.canvas.opacity = self.s_opacity.value() / 100.0
        self.canvas.set_photos(self.shots, self.rhos, self.places,
                               hidden=set(range(len(self.shots))) - set(self.included()))
        self.list.setCurrentRow(1 if len(self.shots) > 1 and base == 0 else 0)
        self._show_place()
        self._set_status("위 사진을 끌어서 아래 사진의 혈관에 맞추세요 — Ctrl/오른쪽 드래그로 돌립니다")
        self._fitted = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self._fitted:
            self._fitted = True
            self.canvas.fit()

    # -- helpers ------------------------------------------------------------------------------
    def _thumb(self, s: mt.Shot) -> QIcon:
        import cv2

        h, w = s.rgb.shape[:2]
        k = 56.0 / max(h, w)
        small = cv2.resize(s.rgb, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
        return QIcon(QPixmap.fromImage(to_qimage(small)))

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setStyleSheet(f"color:{theme.ORANGE}; font-weight:600" if error else f"color:{theme.GREEN}")
        self.status.setText(text)

    def included(self) -> list[int]:
        return [k for k in range(len(self.shots))
                if self.list.item(k).checkState() == Qt.CheckState.Checked]

    def base(self) -> int:
        """The photo at the back: the one chosen, or the first one included when that is left out."""
        inc = self.included()
        return self.canvas.base if self.canvas.base in inc or not inc else inc[0]

    def _show_place(self) -> None:
        k = self.canvas.selected
        if 0 <= k < len(self.places):
            a = (self.places[k].angle + 180.0) % 360.0 - 180.0
            where = "맨 뒤 (불투명)" if k == self.canvas.base else "위 (반투명)"
            self.lbl_place.setText(f"{number(k)} · {where} · 회전 {a:+.1f}°")

    # -- undo -------------------------------------------------------------------------------------
    def _push_undo(self) -> None:
        self._undo.append([p.copy() for p in self.places])
        del self._undo[:-50]

    def undo(self) -> None:
        if not self._undo:
            self._set_status("되돌릴 것이 없습니다")
            return
        for p, old in zip(self.places, self._undo.pop()):
            p.x, p.y, p.angle = old.x, old.y, old.angle
        self._changed()
        self._set_status("되돌렸습니다")

    # -- selection / view ---------------------------------------------------------------------
    def _on_row(self, k: int) -> None:
        if k >= 0:
            self.canvas.select(k)
            self._show_place()

    def _on_canvas_select(self, k: int) -> None:
        self.list.blockSignals(True)
        self.list.setCurrentRow(k)
        self.list.blockSignals(False)
        self._show_place()

    def _on_check(self, item: QListWidgetItem) -> None:
        self.canvas.hidden = set(range(len(self.shots))) - set(self.included())
        self._changed()

    def _on_base(self, *_):
        self.canvas.base = int(self.c_base.currentData() or 0)
        self.canvas.update()
        self._show_place()

    def _on_view(self, *_):
        self.canvas.opacity = self.s_opacity.value() / 100.0
        self.canvas.update()

    def _roll(self, deg: float) -> None:
        self._push_undo()
        self.places[self.canvas.selected].angle += deg
        self._changed()

    def _changed(self, *_):
        self._preview_key = None
        self._show_place()
        self.canvas.update()
        if self.tabs.currentIndex() == 1:
            self._draw_preview()

    # -- 완성 ---------------------------------------------------------------------------------
    def _on_tab(self, i: int) -> None:
        if i == 1:
            self._draw_preview()

    def _gains(self, idx: list[int]) -> None:
        """Brightness matched over the photos included (``shot.gain``), or left as it is."""
        for s in self.shots:
            s.gain = np.ones(3)
        if self.c_gain.isChecked() and len(idx) > 1:
            fm.match_gains([self.shots[k] for k in idx], [self.rhos[k] for k in idx], [self.places[k] for k in idx])

    def _draw_preview(self) -> None:
        idx = self.included()
        key = (tuple(idx), self.c_gain.isChecked(), tuple((p.x, p.y, p.angle) for p in self.places))
        if key == self._preview_key or not idx:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            self._gains(idx)
            rgb, cover, _ = fm.render([self.shots[k] for k in idx], [self.rhos[k] for k in idx],
                                      [self.places[k] for k in idx], max_side=PREVIEW_SIZE)
            rgb = fm.crop(rgb, cover)[0]
        finally:
            QApplication.restoreOverrideCursor()
        self._preview_key = key
        self.done_view.set_rgb(rgb)
        self.done_view.fit()
        self._set_status(f"완성 미리보기 · {len(idx)}장 — 저장하면 이 모습 그대로 (원본 해상도로) 저장됩니다")

    # -- output -------------------------------------------------------------------------------
    def _full(self, idx: list[int]) -> list[mt.Shot]:
        """The photos at their own size, placed and gain-matched as the working copies."""
        self._gains(idx)
        out = []
        for k in idx:
            s, src = self.shots[k], self.sources[k]
            a = src.alpha if src.alpha is not None else np.full(src.rgb.shape[:2], 255, np.uint8)
            out.append(dataclasses.replace(s, rgb=src.rgb, alpha=a, circle=tuple(src.circle), scale=1.0,
                                           gain=s.gain.copy()))
        return out

    def render_final(self, square: bool = False):
        """The finished picture from the original photos. ``square``: on the square map of a montage
        (the photo at the back in its middle) — for the patient record; else cut to what is covered.
        Returns (rgb, cover, (x0, y0, k), included indices)."""
        idx = self.included()
        rhos, places = [self.rhos[k] for k in idx], [self.places[k] for k in idx]
        rect = fm.square_around(rhos, places, idx.index(self.base())) if square else None

        def say(f):
            self._set_status(f"합친 사진을 그리는 중 {int(f * 100)}%")
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        self.setEnabled(False)
        try:
            rgb, cover, (x0, y0, k) = fm.render(self._full(idx), rhos, places, max_side=FULL_SIZE, rect=rect,
                                                progress=say)
        finally:
            self.setEnabled(True)
            QApplication.restoreOverrideCursor()
        if not square:
            rgb, cover, (le, to) = fm.crop(rgb, cover)
            x0, y0 = x0 + le / k, y0 + to / k
        return rgb, cover, (x0, y0, k), idx

    def definition(self, idx: list[int]) -> dict:
        return {"version": 1, "flat": True, "ref": self.base(), "included": idx,
                "brightness": self.c_gain.isChecked(),
                "shots": [{"image_id": s.image_id, "x": p.x, "y": p.y, "angle": p.angle}
                          for s, p in zip(self.shots, self.places)]}

    def result(self):
        """The montage for the patient record (``montage_dialog.MontageResult``): the picture on a square
        map around the photo at the back, with the angle that map spans (roughly: the photos are flat)."""
        from .montage_dialog import MontageResult

        rgb, cover, (x0, y0, k), idx = self.render_final(square=True)
        n = min(rgb.shape[:2])
        rgb, cover = np.ascontiguousarray(rgb[:n, :n]), cover[:n, :n]
        angle = min(math.radians(170.0), n / 2.0 / k * self.shots[0].tmax)
        geom = mt.MapGeometry(n, angle)
        span = tuple(round(v, 1) for v in mt.coverage_span(cover, angle))
        b = self.base()
        disc = self.sources[b].disc
        if disc is not None:
            m = fm.matrix(self.sources[b].circle, self.rhos[b], self.places[b], k, x0, y0)
            disc = tuple(float(v) for v in m @ np.array([disc[0], disc[1], 1.0]))
        eyes = {self.sources[i].laterality for i in idx} - {None, ""}
        d = self.definition(idx) | {"span": list(span), "fov_deg": round(2 * math.degrees(angle), 1)}
        return MontageResult(rgb=rgb, geom=geom, fov_deg=round(2 * math.degrees(angle), 1), span=span, disc=disc,
                             definition=d, image_ids=[self.shots[i].image_id for i in idx],
                             laterality=eyes.pop() if len(eyes) == 1 else None)

    def save_to_record(self) -> None:
        if self._save_record is None or not self.included():
            return
        try:
            res = self.result()
            self.saved_id = self._save_record(res)
        except Exception as exc:  # pragma: no cover - reported to the user
            self._set_status(f"저장하지 못했습니다 — {type(exc).__name__}: {exc}", error=True)
            return
        self._set_status(f"환자 기록에 합친 사진을 저장했습니다 ({res.geom.size}×{res.geom.size})")

    def save_file(self, path: str | None = None) -> None:
        if not self.included():
            return
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "합친 사진 저장", f"{self.file_stem}.png",
                                                  "PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".png"
        try:
            rgb = self.render_final()[0]
        except Exception as exc:  # pragma: no cover - reported to the user
            self._set_status(f"합친 사진을 만들지 못했습니다 — {type(exc).__name__}: {exc}", error=True)
            return
        ok = to_qimage(rgb).save(path, quality=95)
        self._set_status(f"저장했습니다: {path} ({rgb.shape[1]}×{rgb.shape[0]})" if ok
                         else f"저장하지 못했습니다: {path}", error=not ok)
