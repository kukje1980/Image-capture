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

from functools import lru_cache

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from .. import imaging
from .icons import icon as line_icon
from .image_view import TOOL_HINTS

# (key, label, tooltip, icon, VK-2 name)
COMMANDS = (
    ("search", "환자 검색", "환자 ID·이름으로 찾기 (Ctrl+F)", "search", "ID# SEARCH"),
    ("list", "환자 목록", "왼쪽 환자 목록 보이기/숨기기", "log", "OPEN LIST"),
    ("prev", "이전", "이전 사진 (PageUp)", "prev", "PREV"),
    ("next", "다음", "다음 사진 (PageDown)", "next", "NEXT"),
    ("multi", "다중", "여러 장 함께 보기 — ▾ 로 1·2·4·6·9·16장", "multi", "MULTI"),
    ("fit", "화면 맞춤", "화면에 맞춤 — ▾ 로 배율(100~800%)과 확대 위치(후극부·주변부)", "fit", "SCALE"),
    ("tools", "도구", "영상 처리 툴바 보이기/숨기기", "tools", "TOOLS"),
    ("edit", "정보 수정", "이 사진의 환자·검사 정보 수정/환자 지정", "edit", "EDIT DATA"),
    ("import", "가져오기", "사진 파일 가져오기 — ▾ 로 폴더·지금 검사", "import", "CAPTURE"),
    ("save", "저장", "편집 영상 저장 — ▾ 로 파일·환자 기록·클립보드", "save", "SAVE"),
    ("view3d", "3D 안구", "광각 사진을 3D 안구 모형으로 보기", "eye3d", "—"),
    ("print", "인쇄", "화면 영상과 환자 정보를 인쇄", "print", "PRINT"),
    ("settings", "설정", "감시 폴더·라이브러리·파일 이름 규칙", "settings", "—"),
    ("exit", "종료", "프로그램 종료", "exit", "EXIT"),
)

# VK-2 order first, then this viewer's extras. icon "fundus:<effect>" = photo thumbnail.
PROCESSING = (
    ("op:sharpen", "선명", "선명하게 (누를 때마다 누적) — ▾ 로 약·강", "fundus:sharpen", "SHARPEN"),
    ("adj:gamma", "감마", "감마 조정 (어두운 부분 밝게)", "fundus:gamma", "GAMMA"),
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
    ("chan:redfree", "Red-free", "녹색 채널 — 혈관·출혈 (다시 누르면 컬러)", "fundus:redfree", "—"),
    ("auto", "자동대비", "밝기 범위 자동 맞춤", "fundus:auto", "—"),
    ("histogram", "히스토그램", "히스토그램·레벨 조정", "histogram", "—"),
    ("tool:pan", "이동", TOOL_HINTS["pan"], "pan", "—"),
    ("tool:loupe", "돋보기", TOOL_HINTS["loupe"], "loupe", "—"),
    ("rot_cw", "회전", "오른쪽으로 90° — ▾ 로 왼쪽", "rot_cw", "—"),
    ("tool:text", "글자", TOOL_HINTS["text"] + " (▾ 화살표)", "text", "—"),
    ("tool:profile", "회색조", TOOL_HINTS["profile"], "profile", "—"),
    ("annot_undo", "지우기", "마지막 측정·글자 지우기 (Delete) — ▾ 로 모두", "annot_clear", "—"),
)

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
    "multi": tuple((f"multi:{n}", f"{n}장") for n in (1, 2, 4, 6, 9, 16)),
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
CHECKABLE = ("negative", "auto", "slideshow", "list", "tools")


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
    rgb = np.ascontiguousarray(_effect(name))
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(1, 1, w - 2, h - 2)
    p.setClipPath(clip)
    p.drawImage(0, 0, img)
    p.end()
    return QIcon(pm)


def icon_for(spec: str) -> QIcon:
    return fundus_icon(spec[7:]) if spec.startswith("fundus:") else line_icon(spec)


# ---------------------------------------------------------------------------
# gamma / contrast / brightness popups (VK-2 opens a small slider for these)
# ---------------------------------------------------------------------------
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

