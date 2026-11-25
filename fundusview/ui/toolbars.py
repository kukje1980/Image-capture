"""VK-2 style toolbars.

The Kowa VK-2 capture screen is a black image area with two toolbars:

* the **Command toolbar** — one column of large buttons on the right edge
  (INPUT DATA, ID# SEARCH, OPEN LIST, PREV, NEXT, MULTI, SCALE, TOOLS,
  EDIT DATA, CAPTURE, SAVE, DDV, PRINT, EXIT);
* the **Image Processing toolbar** — a row whose buttons show a small fundus
  photo with the effect applied (SHARPEN, GAMMA, ENHANCE, CONTST, BRIGHT,
  RED / GREEN / BLUE FILTER, NEGATIVE, FLIP VRT / HRZ, ZOOM, LENGTH,
  C/D RATIO, ANGLE, LOOP, UNDO, ORIGINAL).

Both are rebuilt here with the same order. Every entry is a key handled by
``MainWindow._on_action``:

* ``tool:<name>`` — left-mouse tool of the 2D view (exclusive)
* ``chan:<name>`` — colour filter (exclusive; clicking the active one returns to colour)
* ``op:<name>``   — processing step pushed onto the photo's processing stack
* ``adj:<name>``  — gamma / contrast / brightness slider popup
* plain keys     — commands
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QToolBar, QVBoxLayout, QWidget

from .. import imaging
from . import icons, theme
from .icons import icon as line_icon
from .image_view import TOOL_HINTS

# (key, label, tooltip, icon, VK-2 name) — every command; CMDBAR says which are on the command toolbar
COMMANDS = (
    ("search", "환자 검색", "환자 ID·이름으로 찾기 (Ctrl+F)", "search", "ID# SEARCH"),
    ("list", "환자 목록", "환자 목록 창 열기/닫기 (Ctrl+0) — 환자를 찾아 두 번 누르면 그 환자의 사진", "log",
     "OPEN LIST"),
    ("prev", "이전", "이전 사진 (PageUp · ←) — 사진 왼쪽 끝의 ◀ 와 같음: Simple · Multi에서는 고른 칸에 같은 눈의 이전 사진", "prev", "PREV"),
    ("next", "다음", "다음 사진 (PageDown · →) — 사진 오른쪽 끝의 ▶ 와 같음: Simple · Multi에서는 고른 칸에 같은 눈의 다음 사진", "next", "NEXT"),
    ("view:simple", "Simple", "Simple (Ctrl+1) — 누르면 최신 OD | OS 두 장 (OD 왼쪽 · OS 오른쪽)\n"
                              "사진 목록을 클릭하면 더하고(번호) 다시 클릭하면 뺍니다 — 고른 장수에 맞게 화면이 나뉩니다 "
                              "(1 · 2 · 4 · 6 · 9 · 16)\n칸을 누르면 그 사진만 보정 · 아래 사진을 더블클릭: 크게 보기 (Detail)",
     "simple", "—"),
    ("view:multi", "Multi", "Multi (Ctrl+2) — 16장 보기에서 클릭해 고른 사진(번호)만 한 화면에\n"
                            "다시 누르면 16장 보기로 돌아갑니다 (고른 번호는 그대로) · "
                            "더블클릭: Simple로", "multi16", "MULTI"),
    ("view:all", "Detail", "Detail (Ctrl+5) — 사진 한 장을 크게, 오른쪽에 황반과 시신경 유두를 확대해서\n"
                           "다시 누르면 보던 화면으로 · 큰 사진을 더블클릭: Simple로 · 사진 좌우의 ◀ ▶ 또는 ← → 키: 이전 / 다음 사진 · "
                           "사진 목록의 다른 사진을 클릭하면 Simple에서 함께 (여러 장 고르기) · 더블클릭: 그 사진을 크게", "detail", "—"),
    ("fit", "화면 맞춤", "화면에 맞춤 — ▾ 로 배율(100~800%)과 확대 위치(후극부·주변부)", "fit", "SCALE"),
    ("tools", "도구", "영상 처리 툴바 보이기/숨기기", "tools", "TOOLS"),
    ("edit", "정보 수정", "이 사진의 환자·검사 정보 수정/환자 지정", "edit", "EDIT DATA"),
    ("import", "가져오기", "사진 파일 가져오기 — ▾ 로 폴더·지금 검사", "import", "CAPTURE"),
    ("save", "저장", "편집 영상 저장 — ▾ 로 파일·환자 기록·클립보드", "save", "SAVE"),
    ("discpair", "스테레오 보기", "고른 두 사진(같은 눈 — 사진 목록에서 차례로 클릭)을 스테레오로: 위글 · 평행 · 교차 · "
                              "적청 · 깊이 지도 — 보험 청구용 한 장도 그 안에", "discpair", "—"),
    ("view3d", "3D", "광각 사진을 3D 안구 모형으로 보기 (Ctrl+3) — 다시 누르면 보던 화면으로\n"
                     "Simple에 사진이 두 장이면 두 장 모두 3D로 나란히", "eye3d", "—"),
    ("montage", "Montage", "몽타주 — Simple · Multi에서 고른 사진(2장 이상, 같은 눈)을 자동·수동으로 맞춰 한 장으로 "
                           "합칩니다\n반투명 겹치기 · 기준점 맞추기 · 3D 안구에서 보기", "montage", "—"),
    ("glaucoma", "Glaucoma", "녹내장 분석 — 보고 있는 사진의 디스크 C/D · 유두 3D 입체 · 광각 RNFL 분석,\n"
                             "사진 목록에서 같은 눈의 사진 두 장을 클릭해 고르면 (몽타주처럼) 스테레오 보기 · 경과 비교(깜빡임)\n"
                             "▾ 스테레오 보기: 고른 두 사진을 위글 · 평행 · 교차 · 적청 · 깊이 지도로 (보험 청구용 한 장도 그 안에)\n"
                             "▾ 시간별 비교: 같은 눈의 유두 사진 여러 장을 시간순으로 나란히 · 겹쳐서", "glaucoma", "—"),
    ("print", "인쇄", "화면 영상과 환자 정보를 인쇄", "print", "PRINT"),
    ("settings", "설정", "감시 폴더·라이브러리·파일 이름 규칙", "settings", "—"),
    ("exit", "종료", "프로그램 종료", "exit", "EXIT"),
)
# the command toolbar, top to bottom (환자 검색 · 정보 수정 · 가져오기 · 저장 are in the menus; 디스크 2장 is
# under Glaucoma ▾)
CMDBAR = ("list", "prev", "next", "view:simple", "view:multi", "view:all", "fit", "tools", "view3d", "montage",
          "glaucoma", "print", "settings", "exit")
# the views among them: lit while on screen
VIEW_COMMANDS = ("view:simple", "view:multi", "view:all", "view3d")

# VK-2 order first, then this viewer's extras. icon "fundus:<effect>" = photo thumbnail.
PROCESSING = (
    ("op:sharpen", "선명", "선명하게 (누를 때마다 누적) — ▾ 로 약·강", "fundus:sharpen", "SHARPEN"),
    ("adj:gamma", "감마", "감마 조정 — 그래프(입력 → 출력 곡선)를 클릭하거나 끌어서 (어두운 부분 밝게)", "fundus:gamma", "GAMMA"),
    ("op:enhance", "향상", "국소 대비 향상 — 미세 혈관·병변 — ▾ 로 평활화·노이즈 감소", "fundus:enhance", "ENHANCE"),
    ("adj:contrast", "대비", "대비 조정", "fundus:contrast", "CONTST"),
    ("adj:bright", "밝기", "밝기 조정", "fundus:bright", "BRIGHT"),
    ("chan:red", "R 필터", "적색 성분만 (다시 누르면 컬러)", "fundus:red", "RED FILTER"),
    ("chan:green", "G 필터", "녹색 성분만 — 흑백 (다시 누르면 컬러)", "fundus:green", "GREEN FILTER"),
    ("chan:blue", "B 필터", "청색 성분만 (다시 누르면 컬러)", "fundus:blue", "BLUE FILTER"),
    ("negative", "네거티브", "반전 영상", "fundus:negative", "NEGATIVE"),
    ("flip_v", "상하반전", "위아래 뒤집기", "flip_v", "FLIP VRT"),
    ("flip_h", "좌우반전", "좌우 뒤집기", "flip_h", "FLIP HRZ"),
    ("tool:zoom", "확대", TOOL_HINTS["zoom"], "zoom", "ZOOM"),
    ("tool:length", "길이", TOOL_HINTS["length"], "length", "LENGTH"),
    ("tool:cd_length", "C/D", "C/D 비 — " + TOOL_HINTS["cd_length"] + " (▾ 면적)", "cd", "C/D RATIO"),
    ("tool:angle", "각도", TOOL_HINTS["angle"], "angle", "ANGLE"),
    ("slideshow", "연속", "이 환자의 사진을 차례로 (클릭하면 멈춤)", "loop", "LOOP"),
    ("undo", "실행취소", "마지막 처리 되돌리기 (Ctrl+Z)", "undo", "UNDO"),
    ("original", "원본", "모든 처리·조정·측정 해제", "fundus:original", "ORIGINAL"),
    None,
    ("chan:redfree", "Red-free", "레드프리 — 녹색 + RNFL 강화 0.9: 신경섬유층·혈관·출혈 "
                                 "(녹내장 분석 → 광각 분석의 레드프리와 같음 · 다시 누르면 컬러)", "fundus:redfree", "—"),
    ("auto", "자동대비", "밝기 범위 자동 맞춤", "fundus:auto", "—"),
    ("histogram", "히스토그램", "히스토그램·레벨 조정", "histogram", "—"),
    ("tool:pan", "이동", TOOL_HINTS["pan"], "pan", "—"),
    ("tool:loupe", "돋보기", TOOL_HINTS["loupe"], "loupe", "—"),
    ("rot_cw", "회전", "오른쪽으로 90° — ▾ 로 왼쪽", "rot_cw", "—"),
    ("tool:text", "글자", TOOL_HINTS["text"] + " (▾ 화살표)", "text", "—"),
    ("tool:profile", "회색조", TOOL_HINTS["profile"], "profile", "—"),
    ("annot_undo", "지우기", "마지막 측정·글자 지우기 (Delete) — ▾ 로 모두", "annot_clear", "—"),
)

# in the 영상 처리 menu (and the keys: wheel · drag · Delete) but not on the toolbar — 0.13.9
PROCBAR_HIDDEN = ("tool:zoom", "slideshow", "histogram", "tool:pan", "tool:loupe", "tool:profile", "annot_undo")
# the image processing toolbar, left to right
PROCBAR = tuple(spec for spec in PROCESSING if spec is None or spec[0] not in PROCBAR_HIDDEN)

# Drop-down extras of a button (key, label)
MENUS = {
    "op:sharpen": (("op:sharpen_light", "선명하게 (약)"), ("op:sharpen", "선명하게"),
                   ("op:sharpen_strong", "선명하게 (강)")),
    "op:enhance": (("op:enhance", "국소 대비 향상"), ("op:equalize", "히스토그램 평활화"),
                   ("op:denoise", "노이즈 감소 (중간값)"), ("op:denoise_avg", "노이즈 감소 (평균)")),
    "tool:cd_length": (("tool:cd_length", "C/D 비 (길이)"), ("tool:cd_area", "C/D 비 (면적)")),
    "rot_cw": (("rot_cw", "오른쪽으로 90°"), ("rot_ccw", "왼쪽으로 90°")),
    "tool:text": (("tool:text", "글자"), ("tool:arrow", "화살표 + 글자")),
    "annot_undo": (("annot_undo", "마지막 측정 지우기"), ("annot_clear", "측정·글자 모두 지우기")),
    "multi": tuple((f"multi:{n}", f"{n}장") for n in (1, 2, 4, 6, 9, 16)),     # Simple's 화면 분할
    "glaucoma": (("glaucoma", "녹내장 분석"), ("discpair", "스테레오 보기 (고른 두 사진)"),
                 ("timeline", "시간별 비교 (이 눈의 유두 사진 여러 장)")),
    # None = separator; region:* zoom onto a part of an (ultra-)wide-field photo
    "fit": (("fit", "화면에 맞춤"), ("actual", "100% (실제 크기)"), ("zoom2", "200%"), ("zoom4", "400%"),
            ("zoom8", "800%"), None,
            ("region:posterior", "후극부 (황반·시신경)"), ("region:superior", "위쪽 주변부"),
            ("region:inferior", "아래쪽 주변부"), ("region:nasal", "코쪽 주변부"),
            ("region:temporal", "귀쪽 주변부")),
    "import": (("import_files", "파일 가져오기…"), ("import_dir", "폴더 가져오기…"),
               ("scan", "감시 폴더 지금 검사")),
    "save": (("save_file", "파일로 저장…"), ("save_record", "환자 기록에 새 사진으로 저장"),
             ("copy", "클립보드로 복사 (Ctrl+C)")),
}
CHECKABLE = ("negative", "auto", "slideshow", "list", "tools") + VIEW_COMMANDS


# ---------------------------------------------------------------------------
# VK-2 style icons: a small fundus photo with the effect applied
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _sample() -> np.ndarray:
    from ..demo import synth_fundus
    return synth_fundus(size=(72, 72), circle=(36, 36, 34), projection="equidistant", seed=3)


def _effect(name: str) -> np.ndarray:
    rgb = _sample()
    if name == "sharpen":
        return imaging.apply_op(imaging.apply_op(rgb, "sharpen_strong"), "sharpen_strong")
    if name == "enhance":
        return imaging.apply_op(rgb, "enhance")
    if name == "gamma":
        return imaging.adjust(rgb, gamma=2.2)
    if name == "contrast":
        return imaging.adjust(rgb, contrast=1.9)
    if name == "bright":
        return imaging.adjust(rgb, brightness=0.3)
    if name in ("red", "green", "blue", "redfree"):
        out = imaging.adjust(rgb, channel=name, auto=True)
        if name in ("red", "blue"):   # VK-2 shows the filter in its colour
            tint = np.array([1.0, 0.25, 0.2] if name == "red" else [0.25, 0.45, 1.0])
            out = (out * tint).clip(0, 255).astype(np.uint8)
        return out
    if name == "negative":
        return imaging.adjust(rgb, invert=True)
    if name == "auto":
        return imaging.adjust(rgb, auto=True)
    return rgb


@lru_cache(maxsize=None)
def fundus_icon(name: str) -> QIcon:
    """The sample photo with effect ``name``, in the rounded square of the other toolbar icons."""
    rgb = np.ascontiguousarray(_effect(name))
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    k = 2                                             # (sharp on a Retina screen too)
    pm = QPixmap(icons.S * k, icons.S * k)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.scale(k, k)
    tile, radius = icons.TILE, icons.TILE_RADIUS
    clip = QPainterPath()
    clip.addRoundedRect(tile, radius, radius)
    p.setClipPath(clip)
    p.fillPath(clip, QColor(0, 0, 0))
    p.drawImage(tile.adjusted(1, 1, -1, -1), img)
    p.setClipping(False)
    edge = QLinearGradient(0, tile.top(), 0, tile.bottom())      # a light edge, as on the colour tiles
    edge.setColorAt(0.0, QColor(255, 255, 255, 110))
    edge.setColorAt(1.0, QColor(255, 255, 255, 40))
    p.setPen(QPen(QBrush(edge), 1.4))
    p.drawRoundedRect(tile.adjusted(0.7, 0.7, -0.7, -0.7), radius - 0.7, radius - 0.7)
    p.end()
    return QIcon(pm)


def icon_for(spec: str) -> QIcon:
    return fundus_icon(spec[7:]) if spec.startswith("fundus:") else line_icon(spec)


# ---------------------------------------------------------------------------
# gamma / contrast / brightness popups (VK-2 opens a small slider for these)
# ---------------------------------------------------------------------------
class FitToolBar(QObject):
    """Keeps every button of a toolbar on screen: where the bar is too short for its buttons (a low
    window — a laptop, a display scaled 125 ~ 150 %), Qt puts the last ones behind the » at its end,
    and on the command toolbar those are Glaucoma · 인쇄 · 설정 · 종료. So the buttons get smaller
    one step at a time — smaller pictures, then pictures without their names (the name is in the
    tooltip) — until all of them fit, and larger again as soon as there is room."""

    STEPS = ((1.0, True), (0.8, True), (0.65, True), (0.85, False), (0.65, False), (0.5, False))

    def __init__(self, bar: QToolBar, icon_px: int):
        super().__init__(bar)
        self.bar, self.icon_px, self.step = bar, icon_px, 0
        self._busy = False
        bar.installEventFilter(self)
        bar.orientationChanged.connect(lambda _o: self.fit())

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.fit()
        return False

    def _apply(self, step: int) -> None:
        scale, names = self.STEPS[step]
        px = max(12, round(self.icon_px * scale))
        self.bar.setIconSize(QSize(px, px))
        self.bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if names
                                    else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.step = step

    def _needs(self) -> int:
        lay = self.bar.layout()
        if lay is not None:
            lay.invalidate()
        hint = self.bar.sizeHint()
        return hint.height() if self.bar.orientation() == Qt.Orientation.Vertical else hint.width()

    def fit(self) -> None:
        if self._busy:
            return
        bar = self.bar
        room = bar.height() if bar.orientation() == Qt.Orientation.Vertical else bar.width()
        if room <= 0:
            return
        self._busy = True
        try:
            before = self.step
            for step in range(len(self.STEPS)):
                self._apply(step)
                if self._needs() <= room:
                    break
            if self.step != before:
                bar.updateGeometry()
        finally:
            self._busy = False


class SliderPopup(QFrame):
    """A slider under a toolbar button; ``slider`` holds the value."""
    pressed = Signal()

    def __init__(self, title: str, lo: int, hi: int, default: int, fmt, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("sliderPopup")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.default, self._fmt = default, fmt
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        head.addWidget(QLabel(f"<b>{title}</b>"))
        self.value = QLabel()
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.value, 1)
        lay.addLayout(head)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(default)
        self.slider.setMinimumWidth(240)
        self.slider.valueChanged.connect(self._show)
        self.slider.sliderPressed.connect(self.pressed.emit)
        lay.addWidget(self.slider)
        reset = QPushButton("초기화")
        reset.clicked.connect(lambda: (self.pressed.emit(), self.slider.setValue(self.default)))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(reset)
        lay.addLayout(row)
        self._show(default)

    def _show(self, v: int) -> None:
        self.value.setText(self._fmt(v))

    def show_at(self, pos: QPoint) -> None:
        self.adjustSize()
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            pos.setX(max(screen.left(), min(pos.x(), screen.right() - self.width())))
            pos.setY(max(screen.top(), min(pos.y(), screen.bottom() - self.height())))
        self.move(pos)
        self.show()
        self.slider.setFocus()



class GammaCurve(QWidget):
    """감마 as a graph: across the brightness of the photo (입력), up the brightness shown (출력). The
    curve is 출력 = 입력 ^ (1 / 감마); a click or a drag on the graph bends it through that point —
    above the diagonal the dark parts get lighter, below it darker. ``slider`` holds the value × 100."""
    pressed = Signal()                     # a drag begins (the window: one step of 실행 취소)
    PAD_L, PAD_T, PAD_R, PAD_B = 26, 10, 10, 24

    def __init__(self, slider: QSlider, parent=None):
        super().__init__(parent)
        self.slider = slider
        self._at = 0.5                     # where on 입력 the handle sits (the last point clicked)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("그래프를 클릭하거나 끌면 곡선이 그 점을 지나도록 감마가 바뀝니다\n"
                        "대각선 위: 어두운 부분이 밝게 · 대각선 아래: 어둡게 · 더블클릭: 초기화 (1.00)")
        slider.valueChanged.connect(lambda _v: self.update())

    def sizeHint(self) -> QSize:
        return QSize(260, 250)

    def minimumSizeHint(self) -> QSize:
        return QSize(200, 190)

    def plot(self) -> QRectF:
        """The square of the graph inside the widget (the axis labels are outside it)."""
        w = self.width() - self.PAD_L - self.PAD_R
        h = self.height() - self.PAD_T - self.PAD_B
        side = max(10.0, min(w, h))
        return QRectF(self.PAD_L + (w - side) / 2, self.PAD_T + (h - side) / 2, side, side)

    def gamma(self) -> float:
        return max(self.slider.value(), 1) / 100.0

    def point(self, x: float) -> QPointF:
        """The place on the widget of the curve at 입력 ``x`` (0 … 1)."""
        r = self.plot()
        y = min(1.0, max(0.0, x)) ** (1.0 / self.gamma())
        return QPointF(r.left() + x * r.width(), r.bottom() - y * r.height())

    def gamma_at(self, pos) -> float:
        """The 감마 whose curve goes through ``pos`` (a place on the widget), kept inside the slider's
        range (a point next to the edges counts as a little inside: every curve meets the corners)."""
        r = self.plot()
        x = (pos.x() - r.left()) / r.width()
        y = (r.bottom() - pos.y()) / r.height()
        x, y = min(0.97, max(0.03, x)), min(0.97, max(0.03, y))
        g = math.log(x) / math.log(y)
        self._at = x
        return min(self.slider.maximum(), max(self.slider.minimum(), round(g * 100))) / 100.0

    def _set(self, pos) -> None:
        self.slider.setValue(round(self.gamma_at(pos) * 100))
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            self._set(e.position())
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._set(e.position())
            e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            self._at = 0.5
            self.slider.setValue(100)
            e.accept()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.plot()
        p.fillRect(r, QColor(18, 18, 20))
        grid = QPen(QColor(255, 255, 255, 34), 1)
        p.setPen(grid)
        for i in range(1, 4):
            x, y = r.left() + r.width() * i / 4, r.top() + r.height() * i / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor(255, 255, 255, 80), 1, Qt.PenStyle.DashLine))      # 감마 1.00: no change
        p.drawLine(r.bottomLeft(), r.topRight())
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        path = QPainterPath(self.point(0.0))
        for i in range(1, 65):
            path.lineTo(self.point(i / 64))
        p.setPen(QPen(QColor(theme.ORANGE), 2.2))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255), 1.5))
        p.setBrush(QColor(theme.ORANGE))
        p.drawEllipse(self.point(self._at), 5.5, 5.5)
        p.setPen(self.palette().color(self.foregroundRole()))
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.drawText(QRectF(r.left(), r.bottom() + 3, r.width(), self.PAD_B - 3),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "입력 (사진의 밝기) →")
        p.save()
        p.translate(r.left() - 6, r.bottom())
        p.rotate(-90)
        p.drawText(QRectF(0, -self.PAD_L + 4, r.height(), self.PAD_L - 6),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, "출력 (화면의 밝기) →")
        p.restore()
        p.end()


class GammaPopup(SliderPopup):
    """GAMMA: the curve as a graph to click and drag on (``GammaCurve``), over the slider (fine steps)."""

    def __init__(self, title: str, lo: int, hi: int, default: int, fmt, parent=None):
        super().__init__(title, lo, hi, default, fmt, parent)
        self.curve = GammaCurve(self.slider)
        self.curve.pressed.connect(self.pressed.emit)
        self.layout().insertWidget(1, self.curve)
