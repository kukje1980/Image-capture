"""여러 장 3D: the photos on screen — Simple's two (OD | OS), or the photos picked on Simple or Multi
(up to ``MAX_EYES``) — each on its own 3D eye, side by side (2) or in a grid (3 · 4 · 6 · 9). [3D] on
those views opens it (with more than two photos it asks first: the one photo or all of them); [3D]
again goes back to the photos.

Each eye is the 3D view of the 3D tab (``eye3d.EyeView``) with the look chosen there (자세히 / 간단히,
유리 공막, 안구 열기 …), so it is turned, zoomed and moved the same way: drag to turn, the wheel or
+ / − to zoom, right drag to zoom, middle / Shift+drag to move, double click or 0 for the start view.
Each eye has the 3D tab's 깊이 막대 at its right edge (depth_bar.py): how deep the eye is cut open,
starting from the 3D tab's depth. With **함께 움직이기** on (the start) the other eyes follow the one
moved or cut, so all show the same place at the same size and depth; off, each eye is moved and cut on
its own.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from .depth_bar import DepthBar
from .eye3d import EyeView
from .widgets import Switch

# the look of the 3D tab's eye that the eyes take over
LOOK = ("glass", "relief", "relief_on", "relief_amount", "simple", "cut", "xray", "show_nerve",
        "show_muscles", "show_grid", "align")
MAX_EYES = 9            # photos on 3D eyes at once (3 × 3)
DEPTH_RANGE = (-30, 100)   # the 깊이 막대's slider, as the 3D tab's (100 = the closed eye)


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
        hint = QLabel("드래그: 회전 · 휠 · + / −: 확대 · 축소 · 가운데 / Shift+드래그: 이동 · 오른쪽 막대: 깊이 · "
                      "3D 다시: 사진으로")
        hint.setObjectName("hint3d")
        bar.addWidget(self.c_link)
        bar.addWidget(self.b_home)
        bar.addWidget(self.b_front)
        bar.addStretch(1)
        bar.addWidget(hint)
        lay.addLayout(bar)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        lay.addLayout(self._grid, 1)
        self.eyes: list[EyeView] = []
        self.labels: list[QLabel] = []
        self.cells: list[QFrame] = []
        self.depths: list[QSlider] = []      # each eye's 깊이 (the value its 깊이 막대 shows and sets)
        self.depth_bars: list[DepthBar] = []
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
        self.depth_bars.append(DepthBar(depth, eye))
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
            eye.update()

    # -- 깊이 막대 ---------------------------------------------------------------------------------
    def _show_depth(self, depth: QSlider, v: int) -> None:
        """The slider (and its bar) at ``v`` without cutting again."""
        if depth.value() != v:
            depth.blockSignals(True)
            depth.setValue(v)
            depth.blockSignals(False)
        self.depth_bars[self.depths.index(depth)].update()

    def _on_depth(self, eye: EyeView, v: int) -> None:
        """An eye's 깊이 막대 moved: that eye cut so deep — all the eyes shown with 함께 움직이기 on."""
        cut = v / 100.0 if v < DEPTH_RANGE[1] else 1.0
        together = self.linked() and eye in self._shown()
        for other, depth in zip(self.eyes, self.depths):
            if other is eye or (together and other in self._shown()):
                other.cut = cut
                self._show_depth(depth, v)
                other.update()
        self._set_lead(eye)

    def set_depth(self, v: int) -> None:
        """깊이 for every eye (as the 깊이 막대 says: 100 closed … −30 the deepest)."""
        for eye, depth in zip(self.eyes, self.depths):
            eye.cut = v / 100.0 if v < DEPTH_RANGE[1] else 1.0
            self._show_depth(depth, v)
            eye.update()

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
            other.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.linked():
            self._follow.start()

    def hideEvent(self, e):
        self._follow.stop()
        super().hideEvent(e)
