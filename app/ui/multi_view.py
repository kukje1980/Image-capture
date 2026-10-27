"""촬영 화면의 멀티 보기 — 오른쪽 목록에서 고른 사진들을 한 화면에 격자로 모아 보고, Pro 검토처럼 편집한다.

1장=전체, 2장=좌우, 3~4장=2×2, 5~6장=3×2, 7~9장=3×3 … (선택 순서대로).
칸마다 Pro 검토와 같은 편집 캔버스(ImageCanvas)이고, 위 편집 도구줄은 누른 칸(노란 테두리)에 적용된다.
- 기본 도구는 돋보기: 사진을 누르고 있는 동안 확대 렌즈. 휠 = 확대 · 축소.
- 이동 · 텍스트 · 화살표 · 원 · 길이 · 각도, 회전 · 반전, 보정(밝기 · 대비 · 감마 · 채도 · 채널 · 선명하게 · 자동 대비),
  실행 취소 · 다시 실행 · 원본으로 · 주석 지우기, 편집본 저장(saveEditedRequested).
칸을 두 번 누르면(돋보기 · 이동 도구일 때) 그 사진을 큰 화면으로 본다.
composite() 는 편집 · 주석까지 반영해 한 장의 BGR 이미지로 만든다. 고른 사진이 바뀌어도 남아 있는 사진의 편집은 유지된다.
"""
from __future__ import annotations

import math
import os

import numpy as np
from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.capture.image_process import Adjust, apply_adjust, auto_levels
from app.ui.control_bar import tool_button
from app.ui.fit import HScroll
from app.ui.pro.image_canvas import ImageCanvas
from app.ui.theme import ICON, ICON_ACCENT

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

# (도구, 이름, 아이콘, 설명) — Pro 검토 편집 탭과 같은 도구
TOOLS = [
    ("magnify", "돋보기", "lens", "누르고 있는 동안 확대 렌즈 (기본)"),
    ("pan", "이동", "hand", "끌어서 이동 · 휠로 확대 축소"),
    ("text", "텍스트", "type", "누른 곳에 텍스트 주석"),
    ("arrow", "화살표", "arrow", "끌어서 화살표 주석"),
    ("circle", "원", "circle", "끌어서 원 · 타원 표시"),
    ("length", "길이", "ruler", "끌어서 길이 측정 (눈금 보정 시 mm)"),
    ("angle", "각도", "angle", "세 점 누르기 — 두 번째 점이 꼭짓점"),
]
_CHANNELS = [("rgb", "컬러"), ("green", "Red-free (녹색)"), ("red", "적색"), ("blue", "청색"), ("gray", "흑백")]


def grid_shape(n: int) -> tuple[int, int]:
    """사진 수 → (열, 행)."""
    if n <= 1:
        return 1, 1
    if n == 2:
        return 2, 1
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def _load_bgr(cap):
    path = cap.file_path if cap.media_type == "photo" else (cap.thumbnail_path or "")
    if not path or cv2 is None or not os.path.exists(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)          # 한글 경로 대응
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _tag(i: int, cap) -> str:
    eye = cap.eye if cap.eye in ("OD", "OS", "OU") else ""
    return f"{i + 1}" + (f"  {eye}" if eye else "") + (f"  {cap.captured_at[5:16]}" if cap.captured_at else "")


class _Cell(QFrame):
    """사진 한 칸 — 편집 캔버스 + 지금 편집 대상이면 노란 테두리."""

    def __init__(self, cap, img, parent=None):
        super().__init__(parent)
        self.setObjectName("MultiCell")
        self.cap = cap
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.canvas = ImageCanvas()
        self.canvas.setMinimumSize(60, 45)             # 칸이 많아도 창 최소 크기가 커지지 않게
        self.canvas._placeholder = "사진을 불러오지 못했습니다"
        self.canvas.set_image(img)
        lay.addWidget(self.canvas)
        self.set_active(False)

    def set_active(self, on: bool) -> None:
        if self.property("active") != on:
            self.setProperty("active", on)
            self.style().unpolish(self)
            self.style().polish(self)


class AdjustPopup(QFrame):
    """보정 창 (도구줄의 '보정' 아래에 뜨는 작은 창) — 지금 칸 또는 모든 칸에."""

    def __init__(self, view: "MultiView"):
        super().__init__(view, Qt.WindowType.Popup)
        self.setObjectName("MultiAdjust")
        self.view = view
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        form = QFormLayout()
        form.setSpacing(6)

        def slider(lo, hi, val):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(val)
            s.setFixedWidth(180)
            s.valueChanged.connect(self._apply)
            return s
        self.s_bright = slider(-100, 100, 0)
        self.s_contrast = slider(20, 300, 100)
        self.s_gamma = slider(20, 300, 100)
        self.s_sat = slider(0, 200, 100)
        self.c_channel = QComboBox()
        for _k, label in _CHANNELS:
            self.c_channel.addItem(label)
        self.c_channel.currentIndexChanged.connect(self._apply)
        self.c_sharpen = QComboBox()
        self.c_sharpen.addItems(["없음", "약", "중", "강"])
        self.c_sharpen.currentIndexChanged.connect(self._apply)
        self.chk_neg = QCheckBox("네거티브")
        self.chk_neg.toggled.connect(self._apply)
        form.addRow("밝기", self.s_bright)
        form.addRow("대비", self.s_contrast)
        form.addRow("감마", self.s_gamma)
        form.addRow("채도", self.s_sat)
        form.addRow("채널", self.c_channel)
        form.addRow("선명하게", self.c_sharpen)
        form.addRow("", self.chk_neg)
        lay.addLayout(form)
        self.chk_all = QCheckBox("모든 사진에 같이 적용")
        lay.addWidget(self.chk_all)
        row = QHBoxLayout()
        self.b_auto = QPushButton("자동 대비")
        self.b_reset = QPushButton("초기화")
        self.b_auto.clicked.connect(self.auto_contrast)
        self.b_reset.clicked.connect(self.reset)
        row.addWidget(self.b_auto)
        row.addWidget(self.b_reset)
        lay.addLayout(row)
        self._base = Adjust()

    def _widgets(self):
        return (self.s_bright, self.s_contrast, self.s_gamma, self.s_sat, self.c_channel, self.c_sharpen, self.chk_neg)

    def load(self, adj: Adjust) -> None:
        """지금 칸의 보정값으로 맞춘다 (신호 없이)."""
        self._base = adj.copy()
        for w in self._widgets():
            w.blockSignals(True)
        self.s_bright.setValue(int(round(adj.brightness)))
        self.s_contrast.setValue(int(round(adj.contrast * 100)))
        self.s_gamma.setValue(int(round(adj.gamma * 100)))
        self.s_sat.setValue(int(round(adj.saturation * 100)))
        self.c_channel.setCurrentIndex([k for k, _ in _CHANNELS].index(adj.channel))
        self.c_sharpen.setCurrentIndex(int(adj.sharpen))
        self.chk_neg.setChecked(adj.negative)
        for w in self._widgets():
            w.blockSignals(False)

    def value(self) -> Adjust:
        adj = self._base.copy()            # 흑 · 백점 등 이 창에 없는 값은 그대로
        adj.brightness = float(self.s_bright.value())
        adj.contrast = self.s_contrast.value() / 100.0
        adj.gamma = self.s_gamma.value() / 100.0
        adj.saturation = self.s_sat.value() / 100.0
        adj.channel = _CHANNELS[self.c_channel.currentIndex()][0]
        adj.sharpen = self.c_sharpen.currentIndex()
        adj.negative = self.chk_neg.isChecked()
        return adj

    def _apply(self, *_):
        self.view.apply_adjust(self.value(), all_cells=self.chk_all.isChecked())

    def auto_contrast(self) -> None:
        cv = self.view.active_canvas()
        img = cv.image() if cv is not None else None
        if img is None:
            return
        adj = self.value()
        lo, hi = auto_levels(apply_adjust(img, Adjust(channel=adj.channel)))
        adj.black, adj.white = lo, hi
        self._base = adj.copy()
        self.view.apply_adjust(adj, all_cells=self.chk_all.isChecked())

    def reset(self) -> None:
        self.load(Adjust())
        self.view.apply_adjust(Adjust(), all_cells=self.chk_all.isChecked())


class MultiView(QWidget):
    cellActivated = Signal(object)        # Capture — 칸을 두 번 누름 (큰 화면으로)
    saveEditedRequested = Signal()        # '편집본 저장'
    edited = Signal()                     # 편집 상태가 바뀜 (실행 취소 가능 여부 등)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MultiView")
        self.setMinimumSize(480, 360)
        self._cells: list[_Cell] = []
        self._active: _Cell | None = None
        self._tool = "magnify"
        self.px_per_mm = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.toolbar = self._build_toolbar()
        self.toolbar_scroll = HScroll(self.toolbar, on_compact=self._compact_toolbar)
        lay.addWidget(self.toolbar_scroll)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("MultiGrid")
        self.grid_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        lay.addWidget(self.grid_host, 1)
        self.lbl_empty = QLabel("오른쪽 목록에서 사진을 한 번씩 눌러 고른 뒤 '멀티'를 누르세요")
        self.lbl_empty.setObjectName("MultiEmpty")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(self.lbl_empty, 0, 0)
        self.adjust_popup = AdjustPopup(self)
        self.adjust_popup.hide()
        self._sync_buttons()

    # ---------------- 도구줄 ----------------
    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Dock")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(2)
        self._bar_buttons = []

        def btn(text, icon, tip, checkable=False, color=ICON, on_color=None):
            b = tool_button(text, icon, "Pause" if checkable else "ToolBtn", checkable=checkable, color=color,
                            tip=tip, icon_size=18, min_width=50, on_color=on_color)
            self._bar_buttons.append(b)
            row.addWidget(b)
            return b

        def sep():
            f = QFrame()
            f.setObjectName("DockSep")
            f.setFixedSize(1, 26)
            row.addSpacing(4)
            row.addWidget(f)
            row.addSpacing(4)

        self.b_fit = btn("맞춤", "fit", "모든 사진을 칸에 맞춤")
        self.b_zin = btn("확대", "zin", "고른 칸 확대 (휠로도 확대)")
        self.b_zout = btn("축소", "zout", "고른 칸 축소")
        sep()
        self.tool_buttons = {}
        for key, text, icon, tip in TOOLS:
            b = btn(text, icon, tip, checkable=True, on_color=ICON_ACCENT)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self.tool_buttons[key] = b
        sep()
        self.b_rot_l = btn("왼쪽", "rot-l", "고른 칸 왼쪽으로 90° 회전")
        self.b_rot_r = btn("오른쪽", "rot-r", "고른 칸 오른쪽으로 90° 회전")
        self.b_flip_h = btn("좌우", "flip-h", "고른 칸 좌우 반전")
        self.b_flip_v = btn("상하", "flip-v", "고른 칸 상하 반전")
        sep()
        self.b_adjust = btn("보정", "sliders", "밝기 · 대비 · 감마 · 채도 · 채널 · 선명하게 · 자동 대비")
        sep()
        self.b_undo = btn("취소", "undo", "고른 칸 실행 취소")
        self.b_redo = btn("다시", "redo", "고른 칸 다시 실행")
        self.b_orig = btn("원본", "history", "고른 칸을 원본으로 되돌리기")
        self.b_clear = btn("지우기", "eraser", "고른 칸의 주석 · 측정 모두 지우기")
        row.addStretch(1)
        self.b_save = btn("편집본 저장", "save", "편집 · 주석한 사진을 새 사진으로 저장 (원본은 그대로)", color=ICON_ACCENT)

        self.b_fit.clicked.connect(self.fit_all)
        self.b_zin.clicked.connect(lambda: self._on_active(lambda cv: cv.apply_zoom(1.25)))
        self.b_zout.clicked.connect(lambda: self._on_active(lambda cv: cv.apply_zoom(0.8)))
        self.b_rot_l.clicked.connect(lambda: self._on_active(lambda cv: cv.rotate(-1)))
        self.b_rot_r.clicked.connect(lambda: self._on_active(lambda cv: cv.rotate(1)))
        self.b_flip_h.clicked.connect(lambda: self._on_active(lambda cv: cv.flip(True)))
        self.b_flip_v.clicked.connect(lambda: self._on_active(lambda cv: cv.flip(False)))
        self.b_adjust.clicked.connect(self.show_adjust)
        self.b_undo.clicked.connect(lambda: self._on_active(lambda cv: cv.undo()))
        self.b_redo.clicked.connect(lambda: self._on_active(lambda cv: cv.redo()))
        self.b_orig.clicked.connect(lambda: self._on_active(lambda cv: cv.restore_original()))
        self.b_clear.clicked.connect(lambda: self._on_active(lambda cv: cv.clear_annotations()))
        self.b_save.clicked.connect(self.saveEditedRequested.emit)
        self.tool_buttons[self._tool].setChecked(True)
        return bar

    def _compact_toolbar(self, on: bool) -> None:
        for b in self._bar_buttons:
            b.set_text_visible(not on)
            b.setMinimumWidth(34 if on else 50)
        self.toolbar.layout().invalidate()
        self.toolbar.updateGeometry()

    # ---------------- 사진 ----------------
    def set_captures(self, caps: list) -> None:
        """고른 사진으로 칸을 다시 놓는다. 이미 있던 사진의 칸(편집 · 확대 상태)은 그대로 쓴다."""
        old = {c.cap.id: c for c in self._cells}
        cells = []
        for cap in caps:
            cell = old.pop(cap.id, None)
            if cell is None:
                cell = _Cell(cap, _load_bgr(cap))
                cv = cell.canvas
                cv.set_tool(self._tool)
                cv.set_px_per_mm(self.px_per_mm)
                cv.activated.connect(lambda c=cell: self.set_active(c))
                cv.edited.connect(self._on_edited)
                cv.viewport().installEventFilter(self)
            cells.append(cell)
        for cell in old.values():                     # 빠진 사진
            self.grid.removeWidget(cell)
            cell.hide()
            cell.setParent(None)
            cell.deleteLater()
        for cell in self._cells:
            self.grid.removeWidget(cell)
        self._cells = cells
        cols, _rows = grid_shape(len(cells))
        self.lbl_empty.setVisible(not cells)
        for i, cell in enumerate(cells):
            cell.canvas.set_caption(_tag(i, cell.cap))
            self.grid.addWidget(cell, i // cols, i % cols)
            cell.show()
        rows = math.ceil(len(cells) / cols) if cells else 1
        for c in range(max(cols, self.grid.columnCount())):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        for r in range(max(rows, self.grid.rowCount())):
            self.grid.setRowStretch(r, 1 if r < rows else 0)
        if self._active not in cells:
            self._active = None
        self.set_active(self._active or (cells[0] if cells else None))
        self._sync_buttons()

    def clear(self) -> None:
        self.set_captures([])

    def captures(self) -> list:
        return [c.cap for c in self._cells]

    def count(self) -> int:
        return len(self._cells)

    def canvases(self) -> list:
        return [c.canvas for c in self._cells]

    def canvas_for(self, cap_id):
        return next((c.canvas for c in self._cells if c.cap.id == cap_id), None)

    # ---------------- 편집 대상 · 도구 ----------------
    def set_active(self, cell) -> None:
        if isinstance(cell, ImageCanvas):
            cell = next((c for c in self._cells if c.canvas is cell), None)
        self._active = cell
        for c in self._cells:
            c.set_active(c is cell and len(self._cells) > 1)
        self._sync_buttons()

    def active_canvas(self):
        return self._active.canvas if self._active is not None else None

    def active_capture(self):
        return self._active.cap if self._active is not None else None

    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        if tool not in self.tool_buttons:
            tool = "magnify"
        self._tool = tool
        for c in self._cells:
            c.canvas.set_tool(tool)
        for k, b in self.tool_buttons.items():
            b.setChecked(k == tool)

    def set_px_per_mm(self, value: float) -> None:
        self.px_per_mm = float(value or 0.0)
        for c in self._cells:
            c.canvas.set_px_per_mm(self.px_per_mm)

    def fit_all(self) -> None:
        for c in self._cells:
            c.canvas.reset_view()

    def apply_adjust(self, adj: Adjust, all_cells: bool = False) -> None:
        targets = self.canvases() if all_cells else [self.active_canvas()]
        for cv in targets:
            if cv is not None and cv.image() is not None:
                cv.set_adjust(adj, record=True)
        self._sync_buttons()

    def show_adjust(self) -> None:
        cv = self.active_canvas()
        if cv is None:
            return
        self.adjust_popup.load(cv.adjust())
        pos = self.b_adjust.mapToGlobal(QPoint(0, self.b_adjust.height() + 4))
        self.adjust_popup.adjustSize()
        self.adjust_popup.move(pos)
        self.adjust_popup.show()

    def _on_active(self, fn) -> None:
        cv = self.active_canvas()
        if cv is not None and cv.image() is not None:
            fn(cv)
        self._sync_buttons()

    def _on_edited(self) -> None:
        self._sync_buttons()
        self.edited.emit()

    def _sync_buttons(self) -> None:
        cv = self.active_canvas()
        has = cv is not None and cv.image() is not None
        for b in (self.b_zin, self.b_zout, self.b_rot_l, self.b_rot_r, self.b_flip_h, self.b_flip_v, self.b_adjust):
            b.setEnabled(has)
        self.b_undo.setEnabled(bool(has and cv.can_undo()))
        self.b_redo.setEnabled(bool(has and cv.can_redo()))
        self.b_orig.setEnabled(bool(has and cv.is_modified()))
        self.b_clear.setEnabled(bool(has and cv.has_annotations()))
        self.b_fit.setEnabled(bool(self._cells))
        self.b_save.setEnabled(any(c.canvas.is_modified() for c in self._cells))

    def modified(self) -> list:
        """편집 · 보정 · 주석이 있는 칸: [(Capture, ImageCanvas)]."""
        return [(c.cap, c.canvas) for c in self._cells if c.canvas.image() is not None and c.canvas.is_modified()]

    def reset_edits(self, cap_ids=None) -> None:
        """편집을 지우고 원본으로 (편집본을 저장한 뒤 — 같은 편집을 두 번 저장하지 않게)."""
        for c in self._cells:
            if cap_ids is None or c.cap.id in cap_ids:
                c.canvas.set_image(c.canvas.original())
                c.canvas.set_adjust(Adjust())
        self._sync_buttons()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.MouseButtonDblClick and self._tool in ("magnify", "pan"):
            cell = next((c for c in self._cells if c.canvas.viewport() is obj), None)
            if cell is not None:
                self.cellActivated.emit(cell.cap)
                return True
        return super().eventFilter(obj, ev)

    # ---------------- 저장용 합성 ----------------
    def composite(self):
        """보이는 격자를 편집 · 보정 · 주석까지 반영해 한 장의 BGR 이미지로."""
        imgs = [c.canvas.render_to_bgr() for c in self._cells]
        real = [im for im in imgs if im is not None]
        if not real or cv2 is None:
            return None
        cols, rows = grid_shape(len(imgs))
        ref_h = max(im.shape[0] for im in real)
        ref_w = max(im.shape[1] for im in real)
        scale = min(1.0, 1600 / max(ref_w, 1))        # 칸 하나 최대 가로 1600px
        cw, ch = max(1, int(ref_w * scale)), max(1, int(ref_h * scale))
        gap = 8
        canvas = np.zeros((rows * ch + (rows - 1) * gap, cols * cw + (cols - 1) * gap, 3), dtype=np.uint8)
        for i, im in enumerate(imgs):
            if im is None:
                continue
            r, c = divmod(i, cols)
            s = min(cw / im.shape[1], ch / im.shape[0])
            w, h = max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))
            x0 = c * (cw + gap) + (cw - w) // 2
            y0 = r * (ch + gap) + (ch - h) // 2
            canvas[y0:y0 + h, x0:x0 + w] = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
            cap = self._cells[i].cap
            eye = cap.eye if cap.eye in ("OD", "OS", "OU") else ""
            label = f"{i + 1}" + (f" {eye}" if eye else "")
            fs = max(0.8, ch / 500)
            cv2.putText(canvas, label, (c * (cw + gap) + 14, r * (ch + gap) + int(36 * fs)),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), int(5 * fs), cv2.LINE_AA)
            cv2.putText(canvas, label, (c * (cw + gap) + 14, r * (ch + gap) + int(36 * fs)),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), max(1, int(2 * fs)), cv2.LINE_AA)
        return canvas
