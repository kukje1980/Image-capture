"""두 장 3D: the two photos of Simple (OD | OS) — or two picked photos — each on its own 3D eye, side
by side. The 3D icon on the two-photo view opens it; the icon again goes back to the photos.

Each eye is the 3D view of the 3D tab (``eye3d.EyeView``) with the look chosen there (자세히 / 간단히,
유리 공막, 안구 열기 …), so it is turned, zoomed and moved the same way: drag to turn, the wheel or
+ / − to zoom, right drag to zoom, middle / Shift+drag to move, double click or 0 for the start view.
With **함께 움직이기** on (the start) the other eye follows, so both show the same place at the same
size; off, each eye is moved on its own.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .eye3d import EyeView
from .widgets import Switch

# the look of the 3D tab's eye that the two eyes take over
LOOK = ("glass", "relief", "relief_on", "relief_amount", "simple", "cut", "xray", "show_nerve",
        "show_muscles", "show_grid", "align")


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
        self.c_link.setToolTip("켜면 한쪽을 돌리거나 확대할 때 다른 쪽도 같이 움직입니다")
        self.c_link.toggled.connect(self._on_link)
        self.b_home = QPushButton("처음 보기")
        self.b_home.setToolTip("두 안구를 처음 보기로 (더블클릭 · 0)")
        self.b_home.clicked.connect(self.reset_views)
        self.b_front = QPushButton("정면")
        self.b_front.setToolTip("두 안구를 정면에서 보기")
        self.b_front.clicked.connect(lambda: [e.front_view(animate=True) for e in self.eyes])
        hint = QLabel("드래그: 회전 · 휠 · + / −: 확대 · 축소 · 가운데 / Shift+드래그: 이동 · 3D 다시: 사진으로")
        hint.setObjectName("hint3d")
        bar.addWidget(self.c_link)
        bar.addWidget(self.b_home)
        bar.addWidget(self.b_front)
        bar.addStretch(1)
        bar.addWidget(hint)
        lay.addLayout(bar)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.eyes: list[EyeView] = []
        self.labels: list[QLabel] = []
        self.cells: list[QFrame] = []
        for _ in range(2):
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
            cl.addWidget(label)
            cl.addWidget(eye, 1)
            row.addWidget(cell, 1)
            self.eyes.append(eye)
            self.labels.append(label)
            self.cells.append(cell)
        lay.addLayout(row, 1)
        self.image_ids: list[int] = []
        self._lead: EyeView = self.eyes[0]
        self._last: dict | None = None
        # the other eye follows the one last touched (its glides and flings included)
        self._follow = QTimer(self, interval=16, timeout=self._sync)

    # -- what is shown ---------------------------------------------------------------------------
    def copy_look(self, src: EyeView) -> None:
        """Take over how the 3D tab's eye looks (not where it is seen from)."""
        for eye in self.eyes:
            eye.set_detail(src.detail)
            for name in LOOK:
                if hasattr(src, name):
                    setattr(eye, name, getattr(src, name))
            eye.half = 0.0
            eye.update()

    def set_photos(self, photos: list[dict]) -> None:
        """Up to two photos, left to right. Each: ``id``, ``label`` (rich text), ``rgb``, ``alpha``,
        ``circle``, ``mapping`` (keywords of ``EyeView.set_mapping``), ``laterality``, ``disc``,
        ``fovea``, ``mark_circle`` and ``from_cover`` (a montage: its angle is what it covers)."""
        self.image_ids = [p["id"] for p in photos[:2]]
        for k, (eye, label, cell) in enumerate(zip(self.eyes, self.labels, self.cells)):
            p = photos[k] if k < len(photos) else None
            cell.setVisible(p is not None)
            if p is None:
                eye.set_image(None)
                continue
            label.setText(p["label"])
            eye.field_from_cover = bool(p.get("from_cover"))
            eye.set_mapping(**p["mapping"])
            eye.set_landmarks(p["laterality"], p["disc"], p["fovea"], p["mark_circle"])
            eye.set_image(p["rgb"], p["alpha"], p["circle"])
        self.reset_views()

    def clear(self) -> None:
        self.image_ids = []
        for eye in self.eyes:
            eye.set_image(None)

    # -- the two move together -------------------------------------------------------------------
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
        other = self.eyes[1] if lead is self.eyes[0] else self.eyes[0]
        if not other.isVisible():
            return
        pose = lead.pose()
        if pose == self._last:
            return
        self._last = pose
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
