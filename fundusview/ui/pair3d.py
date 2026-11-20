"""여러 장 3D: the photos on screen — Simple's two (OD | OS), or the photos picked on Simple or Multi
(up to ``MAX_EYES``) — each on its own 3D eye, side by side (2) or in a grid (3 · 4 · 6 · 9). [3D] on
those views opens it (with more than two photos it asks first: the one photo or all of them); [3D]
again goes back to the photos.

Each eye is the 3D view of the 3D tab (``eye3d.EyeView``) with the look chosen there (자세히 / 간단히,
유리 공막, 안구 열기 …), so it is turned, zoomed and moved the same way: drag to turn, the wheel or
+ / − to zoom, right drag to zoom, middle / Shift+drag to move, double click or 0 for the start view.
Up to ``BARS_MAX`` eyes (four), each has the 3D tab's two bars floating over it (depth_bar.py): the 깊이
막대 at its right edge — how deep the eye is cut open, starting from the 3D tab's depth — and the 배율 막대
at its top left. The bar whose ☑ 휠 is checked is what the wheel over the eyes does (배율 at first). With
**함께 움직이기** on (the start) the other eyes follow the one moved or cut, so all show the same place at
the same size and depth; off, each eye is moved and cut on its own.

With more eyes than that the bars would cover them: the wheel magnifies, and one 깊이 막대 in a strip above
the eyes cuts all of them at once.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from .depth_bar import LYING_H, DepthBar, TopDepthBar, ZoomBar
from .eye3d import EyeView
from .widgets import Switch

# the look of the 3D tab's eye that the eyes take over
LOOK = ("glass", "relief", "relief_on", "relief_amount", "simple", "cut", "xray", "show_nerve",
        "show_muscles", "show_grid", "align")
MAX_EYES = 9            # photos on 3D eyes at once (3 × 3)
BARS_MAX = 4            # up to so many eyes each has its own 깊이 막대 · 배율 막대; more: one 깊이 막대 above
DEPTH_RANGE = (-30, 100)   # the 깊이 막대's slider, as the 3D tab's (100 = the closed eye)
ZOOM_RANGE = (0.3, 16.0)   # the 배율 막대's ends, as the 3D tab's (MainWindow.ZOOM3D)
DEPTH_WHEEL = 4.0          # 깊이 slider units per wheel notch over an eye (as the 3D tab's)


def depth_value(cut: float) -> int:
    """An eye's ``cut`` as the 깊이 slider's value (the 3D tab's ``_on_cut`` the other way)."""
    lo, hi = DEPTH_RANGE
    return hi if cut >= 1.0 else max(lo, min(hi - 1, round(cut * 100)))


def grid_shape(n: int) -> tuple[int, int]:
    """Rows and columns for ``n`` eyes: 1 · 1 × 2 · 2 × 2 · 2 × 3 · 3 × 3."""
    for rows, cols in ((1, 1), (1, 2), (2, 2), (2, 3), (3, 3)):
        if n <= rows * cols:
            return rows, cols
    return 3, 3


class Pair3D(QWidget):
    glError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pair3d")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 2, 8, 0)
        bar.setSpacing(10)
        self.c_link = Switch("함께 움직이기", trailing=False)
        self.c_link.setChecked(True)
        self.c_link.setToolTip("켜면 한 안구를 돌리거나 확대할 때 다른 안구도 같이 움직입니다")
        self.c_link.toggled.connect(self._on_link)
        self.b_home = QPushButton("처음 보기")
        self.b_home.setToolTip("모든 안구를 처음 보기로 (더블클릭 · 0)")
        self.b_home.clicked.connect(self.reset_views)
        self.b_front = QPushButton("정면")
        self.b_front.setToolTip("모든 안구를 정면에서 보기")
        self.b_front.clicked.connect(lambda: [e.front_view(animate=True) for e in self._shown()])
        self.hint = QLabel("")
        self.hint.setObjectName("hint3d")
        bar.addWidget(self.c_link)
        bar.addWidget(self.b_home)
        bar.addWidget(self.b_front)
        bar.addStretch(1)
        bar.addWidget(self.hint)
        lay.addLayout(bar)
        # more than BARS_MAX eyes: one 깊이 막대 for all of them, lying in a strip above the eyes
        self.wheel_mode = "zoom"            # what the wheel over the eyes does: "zoom" or "depth" (☑ 휠)
        self._bars_on = True                # each eye has its own two bars (up to BARS_MAX eyes)
        self.top_strip = QWidget()
        self.top_strip.setObjectName("depthStrip3d")
        self.top_strip.setFixedHeight(LYING_H + 8)
        self.depth_all = QSlider(Qt.Orientation.Horizontal, self)
        self.depth_all.hide()
        self.depth_all.setRange(*DEPTH_RANGE)
        self.depth_all.setEnabled(False)
        self.depth_all.valueChanged.connect(self._on_depth_all)
        self.top_depth_bar = TopDepthBar(self.depth_all, self.top_strip)
        self.top_strip.hide()
        lay.addWidget(self.top_strip)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        lay.addLayout(self._grid, 1)
        self.eyes: list[EyeView] = []
        self.labels: list[QLabel] = []
        self.cells: list[QFrame] = []
        self.depths: list[QSlider] = []      # each eye's 깊이 (the value its 깊이 막대 shows and sets)
        self.depth_bars: list[DepthBar] = []
        self.zooms: list[QSlider] = []       # each eye's 배율 (100 · log2 of its magnification)
        self.zoom_bars: list[ZoomBar] = []
        self._depth_wheel = 0.0              # (the part of a slider step a fine wheel has not made up yet)
        for _ in range(2):                  # (more are made when more photos come)
            self._add_eye()
        self._place(2)
        self.image_ids: list[int] = []
        self._lead: EyeView = self.eyes[0]
        self._last: dict | None = None
        # the other eyes follow the one last touched (its glides and flings included)
        self._follow = QTimer(self, interval=16, timeout=self._sync)

    def _add_eye(self) -> None:
        cell = QFrame()
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        label = QLabel("")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setContentsMargins(8, 2, 8, 2)
        eye = EyeView()
        eye.wheel_mode = "zoom"            # the wheel zooms here, whatever it does in the 3D tab
        eye.pick_walk = False
        eye.glError.connect(self.glError)
        eye.interacted.connect(lambda eye=eye: self._set_lead(eye))
        if self.eyes:                      # the look the first ones have
            first = self.eyes[0]
            eye.set_detail(first.detail)
            for name in LOOK:
                if hasattr(first, name):
                    setattr(eye, name, getattr(first, name))
        cl.addWidget(label)
        cl.addWidget(eye, 1)
        # 깊이 막대 at the eye's right edge, on a slider of its own (not on screen) as in the 3D tab
        depth = QSlider(Qt.Orientation.Horizontal, self)
        depth.hide()
        depth.setRange(*DEPTH_RANGE)
        depth.setValue(depth_value(eye.cut))
        depth.valueChanged.connect(lambda v, eye=eye: self._on_depth(eye, v))
        self.depths.append(depth)
        depth_bar = DepthBar(depth, eye, checkable=True)
        self.depth_bars.append(depth_bar)
        # 배율 막대 at its top left, the same way: the slider is 100 · log2 of the eye's magnification
        zoom = QSlider(Qt.Orientation.Horizontal, self)
        zoom.hide()
        zoom.setRange(round(100 * math.log2(ZOOM_RANGE[0])), round(100 * math.log2(ZOOM_RANGE[1])))
        zoom.setValue(0)
        zoom.valueChanged.connect(lambda v, eye=eye: eye.set_magnification(2.0 ** (v / 100.0)))
        eye.zoomChanged.connect(lambda _m, eye=eye: self._show_zoom(eye))
        eye.depthWheel.connect(lambda steps, eye=eye: self._on_depth_wheel(eye, steps))
        self.zooms.append(zoom)
        zoom_bar = ZoomBar(zoom, eye, checkable=True)
        self.zoom_bars.append(zoom_bar)
        depth_bar.checkToggled.connect(lambda on: self.set_wheel("depth" if on else "zoom"))
        zoom_bar.checkToggled.connect(lambda on: self.set_wheel("zoom"))
        depth.setEnabled(self._bars_on)     # (a bar is shown while its slider is enabled)
        zoom.setEnabled(self._bars_on)
        depth_bar.set_checked(self.wheel_mode == "depth")
        zoom_bar.set_checked(self.wheel_mode == "zoom")
        eye.wheel_mode = self.wheel_mode if self._bars_on else "zoom"
        self.eyes.append(eye)
        self.labels.append(label)
        self.cells.append(cell)

    def _place(self, n: int) -> None:
        """The first ``n`` cells in rows and columns (2: side by side), the others hidden."""
        rows, cols = grid_shape(max(1, n))
        for k, cell in enumerate(self.cells):
            self._grid.removeWidget(cell)
            if k < n:
                self._grid.addWidget(cell, k // cols, k % cols)
            cell.setVisible(k < n)
        for r in range(3):
            self._grid.setRowStretch(r, 1 if r < rows else 0)
        for c in range(3):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        self._set_bars(n <= BARS_MAX)

    # -- the bars ---------------------------------------------------------------------------------
    def _set_bars(self, each: bool) -> None:
        """Each eye with its own 깊이 막대 · 배율 막대 (``each``: up to BARS_MAX eyes), or none over the eyes
        and one 깊이 막대 for all of them above (the wheel magnifies)."""
        self._bars_on = each
        for w in self.depths + self.zooms:
            w.setEnabled(each)
        self.depth_all.setEnabled(not each)
        self.top_strip.setVisible(not each)
        if not each and self.depths:
            self._show_depth(self.depth_all, self.depths[0].value())
        for eye in self.eyes:
            eye.wheel_mode = self.wheel_mode if each else "zoom"
        self.hint.setText(
            "드래그: 회전 · 휠: ☑ 휠을 체크한 막대 (배율 · 깊이) · 가운데 / Shift+드래그: 이동 · 3D 다시: 사진으로"
            if each else
            "드래그: 회전 · 휠 · + / −: 확대 · 축소 · 가운데 / Shift+드래그: 이동 · 위쪽 막대: 모든 안구의 깊이 · "
            "3D 다시: 사진으로")

    def set_wheel(self, mode: str) -> None:
        """☑ 휠: what the wheel over the eyes does — "zoom" (배율) or "depth" (깊이). One of the two."""
        self.wheel_mode = "depth" if mode == "depth" else "zoom"
        for eye, depth_bar, zoom_bar in zip(self.eyes, self.depth_bars, self.zoom_bars):
            eye.wheel_mode = self.wheel_mode if self._bars_on else "zoom"
            depth_bar.set_checked(self.wheel_mode == "depth")
            zoom_bar.set_checked(self.wheel_mode == "zoom")

    def _show_zoom(self, eye: EyeView) -> None:
        """An eye's 배율 막대 where the eye's magnification is (without zooming again)."""
        k = self.eyes.index(eye)
        zoom = self.zooms[k]
        v = round(100 * math.log2(max(eye.magnification, 1e-3)))
        if zoom.value() != v:
            zoom.blockSignals(True)
            zoom.setValue(v)
            zoom.blockSignals(False)
        self.zoom_bars[k].update()

    def _on_depth_wheel(self, eye: EyeView, steps: float) -> None:
        """The wheel over an eye with ☑ 휠 on 깊이: forward cuts deeper, back closes (as the 3D tab's)."""
        self._depth_wheel -= steps * DEPTH_WHEEL
        n = int(self._depth_wheel)
        if n == 0:
            return
        self._depth_wheel -= n
        depth = self.depths[self.eyes.index(eye)]
        v = max(depth.minimum(), min(depth.maximum(), depth.value() + n))
        if v == depth.value():
            self._depth_wheel = 0.0
        depth.setValue(v)

    def _on_depth_all(self, v: int) -> None:
        """The 깊이 막대 above the eyes moved: every eye shown is cut so deep."""
        cut = v / 100.0 if v < DEPTH_RANGE[1] else 1.0
        for eye, depth in zip(self.eyes, self.depths):
            eye.cut = cut
            eye.cut_changed()
            self._show_depth(depth, v)
            eye.update()

    def _shown(self) -> list[EyeView]:
        return self.eyes[:len(self.image_ids)] if self.image_ids else []

    # -- what is shown ---------------------------------------------------------------------------
    def copy_look(self, src: EyeView) -> None:
        """Take over how the 3D tab's eye looks (not where it is seen from), its depth too."""
        for eye, depth in zip(self.eyes, self.depths):
            eye.set_detail(src.detail)
            for name in LOOK:
                if hasattr(src, name):
                    setattr(eye, name, getattr(src, name))
            eye.half = 0.0
            self._show_depth(depth, depth_value(eye.cut))
            eye.wheel_mode = self.wheel_mode if self._bars_on else "zoom"   # (not the 3D tab's wheel)
            eye.update()
        self._show_depth(self.depth_all, depth_value(src.cut))

    # -- 깊이 막대 ---------------------------------------------------------------------------------
    def _show_depth(self, depth: QSlider, v: int) -> None:
        """The slider (and its bar) at ``v`` without cutting again."""
        if depth.value() != v:
            depth.blockSignals(True)
            depth.setValue(v)
            depth.blockSignals(False)
        (self.top_depth_bar if depth is self.depth_all else self.depth_bars[self.depths.index(depth)]).update()

    def _on_depth(self, eye: EyeView, v: int) -> None:
        """An eye's 깊이 막대 moved: that eye cut so deep — all the eyes shown with 함께 움직이기 on."""
        cut = v / 100.0 if v < DEPTH_RANGE[1] else 1.0
        together = self.linked() and eye in self._shown()
        for other, depth in zip(self.eyes, self.depths):
            if other is eye or (together and other in self._shown()):
                other.cut = cut
                other.cut_changed()
                self._show_depth(depth, v)
                other.update()
        self._show_depth(self.depth_all, v)
        self._set_lead(eye)

    def set_depth(self, v: int) -> None:
        """깊이 for every eye (as the 깊이 막대 says: 100 closed … −30 the deepest)."""
        for eye, depth in zip(self.eyes, self.depths):
            eye.cut = v / 100.0 if v < DEPTH_RANGE[1] else 1.0
            self._show_depth(depth, v)
            eye.update()
        self._show_depth(self.depth_all, v)

    def set_photos(self, photos: list[dict]) -> None:
        """Up to ``MAX_EYES`` photos, left to right, row by row. Each: ``id``, ``label`` (rich text),
        ``rgb``, ``alpha``, ``circle``, ``mapping`` (keywords of ``EyeView.set_mapping``),
        ``laterality``, ``disc``, ``fovea``, ``mark_circle`` and ``from_cover`` (a montage: its
        angle is what it covers)."""
        photos = photos[:MAX_EYES]
        while len(self.eyes) < len(photos):
            self._add_eye()
        self.image_ids = [p["id"] for p in photos]
        self._place(len(photos))
        for k, (eye, label) in enumerate(zip(self.eyes, self.labels)):
            p = photos[k] if k < len(photos) else None
            if p is None:
                eye.set_image(None)
                continue
            label.setText(p["label"])
            eye.field_from_cover = bool(p.get("from_cover"))
            eye.set_mapping(**p["mapping"])
            eye.set_landmarks(p["laterality"], p["disc"], p["fovea"], p["mark_circle"])
            eye.set_image(p["rgb"], p["alpha"], p["circle"])
        if self._lead not in self._shown():
            self._lead = self.eyes[0]
        self.reset_views()

    def clear(self) -> None:
        self.image_ids = []
        for eye in self.eyes:
            eye.set_image(None)

    # -- they move together ----------------------------------------------------------------------
    def reset_views(self) -> None:
        for eye in self.eyes:
            eye.reset_view()
            self._show_zoom(eye)
        self._last = None

    def linked(self) -> bool:
        return self.c_link.isChecked()

    def _on_link(self, on: bool) -> None:
        self._last = None
        if on and self.isVisible():
            self._follow.start()
        else:
            self._follow.stop()

    def _set_lead(self, eye: EyeView) -> None:
        if eye is not self._lead:
            self._lead, self._last = eye, None

    def _sync(self) -> None:
        lead = self._lead
        pose = lead.pose()
        if pose == self._last:
            return
        self._last = pose
        for other in self.eyes:
            if other is lead or not other.isVisible():
                continue
            other.yaw, other.pitch, other.dist = lead.yaw, lead.pitch, lead.dist
            other.target = lead.target.copy()
            self._show_zoom(other)
            other.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.linked():
            self._follow.start()

    def hideEvent(self, e):
        self._follow.stop()
        super().hideEvent(e)
