"""녹내장 분석 → 시간별 비교: the optic disc of one eye over the years (``timeline.py``).

The photos of the eye of the photo on screen — one of each exam day at first, any of them by the
check marks of the list — are cut around their discs to the same retinal field, laid onto the
oldest one and shown

* **나란히**: all of them on one screen in the order of time, each with its date and how long after
  the first it was taken;
* **겹치기**: on top of each other — the 시간 slider fades from each photo into the next (▶ runs it);
* **넘겨 보기**: one after the other in place (a flicker over all of them, or of the first and the
  chosen one);
* **변화 지도**: where the chosen photo differs from the first.

Photos are read when the tab is first shown, and only the checked ones.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem

from .. import glaucoma as G
from .. import timeline as T
from . import theme
from .glaucoma_dialog import _Choice, _Slider, _Tab, _button, _note, _pair_row, _px
from .widgets import Switch, card

NEED = ("시간별로 비교할 사진이 없습니다.\n\n같은 환자 · 같은 눈의 사진이 두 장 이상 있어야 합니다\n"
        "(시신경 유두가 찍힌 사진 — 가져올 때 유두를 찾은 사진).")
MODES = [("grid", "나란히", "모든 사진을 시간순으로 한 화면에"),
         ("overlay", "겹치기", "겹쳐 놓고 시간 슬라이더로 넘기기"),
         ("flick", "넘겨 보기", "제자리에서 차례로 바꿔 보기 (깜빡임)"),
         ("diff", "변화 지도", "처음 사진과 달라진 곳")]
HINT = {
    "grid": "왼쪽 위가 가장 오래된 사진입니다. 사진을 누르면 그 사진이 선택됩니다 (파란 테두리).",
    "overlay": "시간 슬라이더를 움직이면 한 사진에서 다음 사진으로 서서히 바뀝니다. 달라지는 곳이 변화입니다.",
    "flick": "맞춘 사진을 제자리에서 차례로 보여 줍니다. 움직이거나 나타나는 부분이 변화입니다.",
    "diff": "처음 사진과 선택한 사진의 밝기 차이가 큰 곳을 분홍색으로 표시합니다. 조명 차이도 함께 잡히므로 "
            "넘겨 보기로 확인하세요.",
}
ROLE = Qt.ItemDataRole.UserRole


class TimelineTab(_Tab):
    """``shots``: every photo that may go on the timeline (``timeline.Shot``); ``current_id``: the
    photo on screen; ``prefer``: photos the user picked (shown at first when two or more are here)."""

    def __init__(self, shots=None, current_id: int | None = None, prefer=(), parent=None):
        super().__init__(NEED, parent)
        self.shots = T.in_order(shots or [])
        self._by_id = {s.image_id: s for s in self.shots}
        self.current_id, self._prefer = current_id, tuple(prefer)
        self.checked: list[int] = self._default() if len(self.shots) >= 2 else []
        self._frames: dict[int, dict] = {}                # image id -> {region: frame}
        self._failed: set[int] = set()                    # photos that could not be read
        self._fits: dict[tuple, T.Fit] = {}               # (image id, region, reference id) -> how it is laid
        self._nudge: dict[tuple, tuple] = {}              # (image id, region) -> the hand's correction
        self._laid: dict[int, np.ndarray] = {}            # the frames as shown now (by image id)
        self._cells: list = []
        self._loaded = False
        self.region, self.mode, self.aligned = "near", "grid", True
        self.selected: int | None = None
        self.pos = 0.0                                    # 겹치기: 0 = the first photo, 1 = the second …
        self._phase, self._dir = 0, 1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.view.overlay = self._overlay
        self.view.pressed.connect(self._press)

        self.modes = _Choice(MODES)
        self.modes.changed.connect(self.set_mode)
        self.s_time = _Slider("시간", 0, 1, 0, 0.05, lambda _v: self._pos_text())
        self.s_time.changed.connect(self.set_pos)
        self.b_play = _button("▶ 자동으로 넘기기", tip="시간 슬라이더를 처음에서 끝까지 저절로 오가게 합니다")
        self.b_play.setCheckable(True)
        self.b_play.toggled.connect(lambda _on: self._restart())
        self.speed = _Slider("속도", 1, 6, 2, 1, lambda v: f"{v:.0f} Hz")
        self.speed.changed.connect(lambda _v: self._restart())
        self.sw_two = Switch("처음 ↔ 선택한 사진 두 장만")
        self.sw_two.toggled.connect(lambda _on: self._draw())
        self.lbl_span = _note()
        self.side.addWidget(card("보는 방식", self.modes, self.s_time, self.b_play, self.speed, self.sw_two,
                                 self.lbl_span, lines=False))

        self.list = QListWidget()
        self.list.setFixedHeight(190)
        self.list.setToolTip("표시(✓)한 사진을 봅니다. 줄을 누르면 그 사진이 선택됩니다.")
        self.list.itemChanged.connect(self._on_checked)
        self.list.currentRowChanged.connect(self._on_row)
        self.b_default = _button("날짜마다 한 장", tip="검사일마다 한 장씩 (많으면 고르게 줄여서) 다시 고릅니다")
        self.b_default.clicked.connect(self.reset_checked)
        self.b_ends = _button("처음과 최근", tip="가장 오래된 사진과 가장 최근 사진 두 장만")
        self.b_ends.clicked.connect(lambda: self.set_checked([s.image_id for s in (self.shots[:1] + self.shots[-1:])]))
        self.lbl_count = _note()
        self.side.addWidget(card("사진 (오래된 것부터)", self.list, _pair_row(self.b_default, self.b_ends),
                                 self.lbl_count, lines=False))

        self.regions = _Choice(T.REGIONS)
        self.regions.changed.connect(self.set_region)
        self.sw_align = Switch("혈관에 맞춰 겹치기")
        self.sw_align.setChecked(True)
        self.sw_align.toggled.connect(self.set_aligned)
        self.b_auto = _button("선택한 사진 다시 맞춤", tip="선택한 사진을 처음 사진에 다시 자동으로 맞춥니다 (손으로 옮긴 것은 지움)")
        self.b_auto.clicked.connect(self.realign)
        self.s_dx = _Slider("좌우", -T.LIMIT, T.LIMIT, 0, 0.5, _px)
        self.s_dy = _Slider("상하", -T.LIMIT, T.LIMIT, 0, 0.5, _px)
        self.s_dx.changed.connect(lambda v: self.set_nudge(v, self.s_dy.value()))
        self.s_dy.changed.connect(lambda v: self.set_nudge(self.s_dx.value(), v))
        self.status = _note()
        self.side.addWidget(card("범위 · 맞춤", self.regions, self.sw_align, self.b_auto, self.s_dx, self.s_dy,
                                 self.status))
        self.side.addStretch(1)
        self._fill_list()
        self.set_mode("grid")

    # -- which photos ----------------------------------------------------------------------------
    def _default(self) -> list[int]:
        return T.pick_default(self.shots, self.current_id, T.MAX_PHOTOS, self._prefer)

    def shown(self) -> list:
        """The checked photos that could be read, oldest first."""
        return [s for s in self.shots if s.image_id in self.checked and s.image_id in self._frames]

    def reference(self):
        """The photo the others are laid onto: the oldest one shown."""
        shown = self.shown()
        return shown[0] if shown else None

    def _fill_list(self) -> None:
        blk = self.list.blockSignals(True)
        self.list.clear()
        for s in self.shots:
            it = QListWidgetItem()
            it.setData(ROLE, s.image_id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.list.addItem(it)
        self.list.blockSignals(blk)
        self._label_list()

    def _label_list(self) -> None:
        first = next((s.day for s in self.shots if s.image_id in self.checked), "")
        blk = self.list.blockSignals(True)
        for i, s in enumerate(self.shots):
            it = self.list.item(i)
            gap = T.interval_text(first, s.day) if s.image_id in self.checked else ""
            bits = [s.day or "날짜 미상", gap, s.caption, "읽지 못함" if s.image_id in self._failed else ""]
            it.setText("  ·  ".join(b for b in bits if b))
            it.setCheckState(Qt.CheckState.Checked if s.image_id in self.checked else Qt.CheckState.Unchecked)
        if self.selected is not None:
            self.list.setCurrentRow(next((i for i, s in enumerate(self.shots) if s.image_id == self.selected), -1))
        self.list.blockSignals(blk)
        n = len(self.checked)
        more = len(self.shots) - n
        self.lbl_count.setText(f"{n}장 보는 중" + (f" · 표시하지 않은 사진 {more}장" if more > 0 else "")
                               + f" (한 번에 {T.MAX_PHOTOS}장까지)")

    def _on_checked(self, item: QListWidgetItem) -> None:
        iid, on = item.data(ROLE), item.checkState() == Qt.CheckState.Checked
        if on == (iid in self.checked):
            return
        if on and len(self.checked) >= T.MAX_PHOTOS:
            self.status.setText(f"한 번에 {T.MAX_PHOTOS}장까지 볼 수 있습니다 — 다른 사진의 표시를 먼저 지우세요.")
            self._label_list()
            return
        ids = set(self.checked) ^ {iid}
        self.set_checked([s.image_id for s in self.shots if s.image_id in ids])

    def _on_row(self, row: int) -> None:
        if 0 <= row < len(self.shots) and self.shots[row].image_id in self._frames \
                and self.shots[row].image_id in self.checked:
            self.select(self.shots[row].image_id)

    def set_checked(self, ids) -> None:
        """Show these photos (image ids; at most ``MAX_PHOTOS``, in the order of time)."""
        want = set(ids)
        self.checked = [s.image_id for s in self.shots if s.image_id in want][:T.MAX_PHOTOS]
        if self._loaded:
            self.ensure_loaded()
        else:
            self._label_list()

    def reset_checked(self) -> None:
        self.set_checked(self._default())

    # -- reading and laying ------------------------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Read the checked photos that are not read yet and cut them around their discs."""
        self._loaded = True
        todo = [s for s in self.shots if s.image_id in self.checked and s.image_id not in self._frames
                and s.image_id not in self._failed]
        if todo:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for s in todo:
                    photo = s.load() if s.load is not None else None
                    if photo is None or photo.rgb is None:
                        self._failed.add(s.image_id)
                        continue
                    self._frames[s.image_id] = T.frames_of(photo.rgb, photo.disc, photo.disc_px)
                    if s.eye is None:
                        s.eye = photo.eye
            finally:
                QApplication.restoreOverrideCursor()
        shown = [s.image_id for s in self.shown()]
        if self.selected not in shown:
            self.selected = shown[-1] if shown else None
        self._sync()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._loaded:
            self.ensure_loaded()
        self._restart()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._timer.stop()

    def fit_of(self, image_id: int) -> T.Fit:
        """How the photo is laid onto the reference in this region (found once, then kept)."""
        ref = self.reference()
        if ref is None or ref.image_id == image_id or not self.aligned:
            return T.Fit()
        key = (image_id, self.region, ref.image_id)
        if key not in self._fits:
            self._fits[key] = T.register(self._frames[ref.image_id][self.region], self._frames[image_id][self.region])
        return self._fits[key]

    def _lay(self) -> None:
        self._laid = {}
        ref = self.reference()
        for s in self.shown():
            raw = self._frames[s.image_id][self.region]
            if s is ref:
                self._laid[s.image_id] = raw
            else:
                self._laid[s.image_id] = T.applied(raw, self.fit_of(s.image_id),
                                                   self._nudge.get((s.image_id, self.region), (0.0, 0.0)))

    def frames(self) -> list[np.ndarray]:
        return [self._laid[s.image_id] for s in self.shown()]

    def _sync(self) -> None:
        """After the photos, the region or the alignment changed: lay them again, set the controls."""
        if self.checked and self._loaded:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._lay()
            finally:
                QApplication.restoreOverrideCursor()
        n = len(self.shown())
        self.pos = min(self.pos, max(0, n - 1))
        blk = self.s_time.slider.blockSignals(True)
        self.s_time.slider.setRange(0, max(1, round((n - 1) / 0.05)))
        self.s_time.slider.blockSignals(blk)
        self.s_time.set(self.pos)
        self._label_list()
        self._selection_changed()
        self._restart()
        self._draw()

    def set_region(self, region: str) -> None:
        self.region = region
        self.regions.set(region)
        self._sync()

    def set_aligned(self, on: bool) -> None:
        self.aligned = bool(on)
        if self.sw_align.isChecked() != self.aligned:
            self.sw_align.setChecked(self.aligned)
        self._sync()

    def realign(self) -> None:
        ref = self.reference()
        if ref is None or self.selected is None or self.selected == ref.image_id:
            return
        self._nudge.pop((self.selected, self.region), None)
        self._fits.pop((self.selected, self.region, ref.image_id), None)
        self._sync()

    def set_nudge(self, dx: float, dy: float) -> None:
        """Move the selected photo by hand, on top of where the automatic alignment put it."""
        ref = self.reference()
        if ref is None or self.selected is None or self.selected == ref.image_id:
            return
        self._nudge[(self.selected, self.region)] = (float(dx), float(dy))
        raw = self._frames[self.selected][self.region]
        self._laid[self.selected] = T.applied(raw, self.fit_of(self.selected), (dx, dy))
        self._selection_changed()
        self._draw()

    # -- the selected photo ------------------------------------------------------------------------
    def select(self, image_id: int) -> None:
        ids = [s.image_id for s in self.shown()]
        if image_id not in ids:
            return
        self.selected = image_id
        if self.mode == "overlay":
            self.pos = float(ids.index(image_id))
            self.s_time.set(self.pos)
        self._label_list()
        self._selection_changed()
        self._draw()

    def _selection_changed(self) -> None:
        ref = self.reference()
        movable = ref is not None and self.selected is not None and self.selected != ref.image_id
        for w in (self.s_dx, self.s_dy, self.b_auto):
            w.setEnabled(movable)
        dx, dy = self._nudge.get((self.selected, self.region), (0.0, 0.0)) if movable else (0.0, 0.0)
        self.s_dx.set(dx)
        self.s_dy.set(dy)
        shown = self.shown()
        if not shown:
            self.status.setText("")
            self.lbl_span.setText("")
            return
        days = [s.day for s in shown if s.day]
        span = T.interval_text(days[0], days[-1]).lstrip("+") if len(days) >= 2 else ""
        self.lbl_span.setText(f"{len(shown)}장" + (f" · {days[0]} → {days[-1]}" if len(days) >= 2 else "")
                              + (f" ({span})" if span and span != "기준일" else ""))
        sel = self._by_id.get(self.selected)
        if sel is None:
            return
        if not movable:
            self.status.setText(f"선택: {sel.day or '날짜 미상'} — 기준 사진입니다 (다른 사진을 이 사진에 맞춥니다).")
        else:
            fit = self.fit_of(sel.image_id)
            how = {"turn": "자동 맞춤", "shift": "자동 맞춤 (좌우 · 상하만 — 혈관 점이 모자람)", "none": "맞추지 않음"}[fit.how]
            hand = f" · 손으로 좌우 {_px(dx)}, 상하 {_px(dy)}" if (dx or dy) else ""
            self.status.setText(f"선택: {sel.day or '날짜 미상'} — {how}"
                                + (f": {fit.text()}" if fit.how != "none" else "") + hand)

    def _press(self, x: float, y: float) -> None:
        if self.mode != "grid":
            return
        i = T.cell_at(self._cells, x, y)
        shown = self.shown()
        if i is not None and i < len(shown):
            self.select(shown[i].image_id)

    # -- what is shown -----------------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.modes.set(mode)
        self.hint.setText(HINT[mode])
        self.s_time.setVisible(mode == "overlay")
        self.b_play.setVisible(mode == "overlay")
        self.speed.setVisible(mode in ("overlay", "flick"))
        self.sw_two.setVisible(mode == "flick")
        if mode == "overlay" and self.selected is not None:
            ids = [s.image_id for s in self.shown()]
            if self.selected in ids:
                self.pos = float(ids.index(self.selected))
                self.s_time.set(self.pos)
        self._restart()
        self._draw()

    def set_pos(self, pos: float) -> None:
        """겹치기: the place on the time slider (0 = the first photo, 1 = the second …)."""
        shown = self.shown()
        self.pos = float(np.clip(pos, 0, max(0, len(shown) - 1)))
        self.s_time.set(self.pos)
        if shown:
            near = shown[int(round(self.pos))].image_id
            if near != self.selected:
                self.selected = near
                self._label_list()
                self._selection_changed()
        self._draw()

    def _pos_text(self) -> str:
        shown = self.shown() if hasattr(self, "_frames") else []
        if not shown:
            return ""
        i = min(int(self.pos), len(shown) - 1)
        t = self.pos - i
        if t < 1e-3 or i + 1 >= len(shown):
            return shown[i].day or f"{i + 1}번째"
        return f"{shown[i].day or i + 1} → {shown[i + 1].day or i + 2}  {t * 100:.0f}%"

    def _pair(self) -> list:
        """The first photo and the selected one (the last, while the first itself is selected)."""
        shown = self.shown()
        if len(shown) < 2:
            return shown
        other = next((s for s in shown[1:] if s.image_id == self.selected), shown[-1])
        return [shown[0], other]

    def _sequence(self) -> list:
        """넘겨 보기: the photos that take turns."""
        return self._pair() if self.sw_two.isChecked() else self.shown()

    def _alternating(self) -> bool:
        return self.mode == "flick" or (self.mode == "overlay" and self.b_play.isChecked())

    def _restart(self) -> None:
        if self._alternating() and len(self.shown()) >= 2 and self.isVisible():
            self._timer.start(40 if self.mode == "overlay" else max(30, round(1000 / self.speed.value())))
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if not self.isVisible():
            return
        if self.mode == "overlay":                       # there and back, ``speed`` / 2 photos a second
            last = max(1, len(self.shown()) - 1)
            pos = self.pos + self._dir * self.speed.value() * 0.02
            if pos >= last or pos <= 0:
                self._dir = -self._dir
            self.set_pos(pos)
        else:
            self._phase += 1
            self._draw()

    def compose(self):
        shown = self.shown()
        if not shown:
            return None
        if self.mode == "grid":
            img, self._cells = T.sheet(self.frames())
            return img
        self._cells = []
        if self.mode == "overlay":
            return T.crossfade(self.frames(), self.pos)
        if self.mode == "flick":
            seq = self._sequence()
            return self._laid[seq[self._phase % len(seq)].image_id]
        pair = self._pair()
        if len(pair) < 2:
            return self._laid[pair[0].image_id]
        return G.diff_map(self._laid[pair[0].image_id], self._laid[pair[1].image_id])

    def _draw(self) -> None:
        self.view.set_rgb(self.compose())

    # -- dates on the picture ----------------------------------------------------------------------
    def _label(self, shot, first_day: str) -> str:
        gap = T.interval_text(first_day, shot.day)
        return (shot.day or "날짜 미상") + (f"   {gap}" if gap else "")

    @staticmethod
    def _pill(p: QPainter, x: float, y: float, text: str, size: float, color=None) -> None:
        font = QFont(p.font())
        font.setPixelSize(max(9, round(size)))
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        pad = size * 0.45
        box = QRectF(x, y, fm.horizontalAdvance(text) + 2 * pad, fm.height() + pad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 165))
        p.drawRoundedRect(box, size * 0.4, size * 0.4)
        p.setPen(QColor(color or theme.TEXT))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _overlay(self, p: QPainter) -> None:
        shown = self.shown()
        if not shown:
            return
        first = shown[0].day
        if self.mode == "grid":
            for s, (x, y, w, h) in zip(shown, self._cells):
                size = w / 24
                self._pill(p, x + size * 0.5, y + size * 0.5, self._label(s, first), size)
                if s.caption:
                    self._pill(p, x + size * 0.5, y + h - size * 2.3, s.caption, size * 0.8, theme.TEXT2)
                if s.image_id == self.selected and len(shown) > 1:
                    p.setPen(QPen(QColor(theme.ACCENT), max(2.0, w / 160)))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(QRectF(x + 1, y + 1, w - 2, h - 2))
            return
        w = self.view._img.width() if self.view._img is not None else T.FRAME_PX
        h = self.view._img.height() if self.view._img is not None else T.FRAME_PX
        size = w / 26
        at = None                                        # where on the time line the picture is (0 … n-1)
        if self.mode == "overlay":
            text, at = self._pos_text(), self.pos
            i = min(int(self.pos), len(shown) - 1)
            if self.pos - i < 1e-3:
                text = self._label(shown[i], first)
        elif self.mode == "flick":
            seq = self._sequence()
            s = seq[self._phase % len(seq)]
            text, at = self._label(s, first), float(shown.index(s))
        else:
            pair = self._pair()
            text = "변화 지도   " + " ↔ ".join(s.day or "날짜 미상" for s in pair)
        self._pill(p, size * 0.5, size * 0.5, text, size)
        if at is None or len(shown) < 2:
            return
        marks = T.time_marks([s.day for s in shown])     # the time line along the bottom
        x0, x1, y = w * 0.06, w * 0.94, h - size * 1.1
        p.setPen(QPen(QColor(255, 255, 255, 120), max(1.0, size * 0.08)))
        p.drawLine(int(x0), int(y), int(x1), int(y))
        p.setPen(Qt.PenStyle.NoPen)
        for m in marks:
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawEllipse(QRectF(x0 + (x1 - x0) * m - size * 0.16, y - size * 0.16, size * 0.32, size * 0.32))
        i = min(int(at), len(shown) - 2)
        m = marks[i] + (marks[i + 1] - marks[i]) * (at - i)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(QRectF(x0 + (x1 - x0) * m - size * 0.3, y - size * 0.3, size * 0.6, size * 0.6))

    # -- for saving --------------------------------------------------------------------------------
    def note(self) -> str:
        shown = self.shown()
        days = [s.day for s in shown if s.day]
        span = f"{days[0]} → {days[-1]}, " if len(days) >= 2 else ""
        name = {m[0]: m[1] for m in MODES}[self.mode]
        return f"녹내장 분석 — 시간별 비교 {name} ({span}{len(shown)}장)"

    def image_ids(self) -> list[int]:
        return [s.image_id for s in self.shown()]

    def eye(self) -> str | None:
        eyes = {s.eye for s in self.shown()}
        return eyes.pop() if len(eyes) == 1 else None
