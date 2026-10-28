"""Right-hand tool palette (the VK-2 "Image Processing" toolbar, regrouped).

Buttons emit ``triggered(key)``:

* ``tool:<name>``  — left-mouse tool of the 2D view (exclusive, see image_view.TOOLS)
* ``chan:<name>``  — colour channel view (exclusive)
* ``op:<name>``    — processing step pushed onto the image's processing stack
* plain keys      — actions: fit, actual, prev, next, slideshow, rot_cw, rot_ccw,
  flip_h, flip_v, auto, negative, histogram, undo, original, annot_undo,
  annot_clear, copy, save_file, save_record, print
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from .image_view import TOOL_HINTS

SECTIONS = (
    ("보기", (
        ("tool:pan", "이동", "드래그로 이동"), ("tool:zoom", "확대/축소", "드래그로 확대·축소"),
        ("tool:loupe", "돋보기", "누르고 있으면 돋보기"), ("fit", "화면 맞춤", "더블클릭과 같음"),
        ("actual", "100%", "실제 크기"), ("slideshow", "연속 보기", "이 환자의 사진을 차례로 (클릭하면 멈춤)"),
        ("prev", "◀ 이전", "이전 사진 (PageUp)"), ("next", "다음 ▶", "다음 사진 (PageDown)"),
        ("rot_ccw", "↺ 90°", "왼쪽으로 회전"), ("rot_cw", "↻ 90°", "오른쪽으로 회전"),
        ("flip_h", "좌우 반전", "좌우 뒤집기"), ("flip_v", "상하 반전", "위아래 뒤집기"),
    )),
    ("영상 처리", (
        ("op:sharpen", "선명하게", "윤곽 선명화 (누를 때마다 누적)"), ("op:enhance", "향상", "국소 대비 향상 — 미세 혈관·병변"),
        ("auto", "자동 대비", "밝기 범위 자동 맞춤"), ("op:equalize", "평활화", "히스토그램 평활화"),
        ("op:denoise", "노이즈 감소", "중간값 필터"), ("histogram", "히스토그램", "히스토그램·레벨 조정"),
        ("chan:rgb", "컬러", "원래 색"), ("chan:redfree", "Red-free", "녹색 채널 (혈관·출혈)"),
        ("chan:red", "R 필터", "적색 성분만"), ("chan:green", "G 필터", "녹색 성분만 (흑백)"),
        ("chan:blue", "B 필터", "청색 성분만"), ("negative", "네거티브", "반전 영상"),
        ("undo", "실행 취소", "마지막 처리 되돌리기"), ("original", "원본", "모든 처리·조정 해제"),
    )),
    ("측정 · 표시", (
        ("tool:length", "길이", TOOL_HINTS["length"]), ("tool:angle", "각도", TOOL_HINTS["angle"]),
        ("tool:cd_length", "C/D 길이", TOOL_HINTS["cd_length"]), ("tool:cd_area", "C/D 면적", TOOL_HINTS["cd_area"]),
        ("tool:text", "글자", TOOL_HINTS["text"]), ("tool:arrow", "화살표", TOOL_HINTS["arrow"]),
        ("tool:profile", "회색조", TOOL_HINTS["profile"]), ("annot_undo", "측정 취소", "마지막 측정·글자 지우기 (Delete)"),
        ("annot_clear", "모두 지우기", "측정·글자 모두 지우기"),
    )),
    ("출력", (
        ("copy", "복사", "화면 영상(측정 포함)을 클립보드로"), ("save_file", "파일 저장", "PNG/JPEG 파일로 저장"),
        ("save_record", "기록에 저장", "편집 영상을 이 환자 기록에 새 사진으로 추가"), ("print", "인쇄", "인쇄"),
    )),
)
TOGGLES = ("negative", "auto", "slideshow")


class ToolPalette(QWidget):
    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("palette")
        self.setFixedWidth(176)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._chan_group = QButtonGroup(self)
        self._chan_group.setExclusive(True)
        for title, items in SECTIONS:
            head = QLabel(title)
            head.setObjectName("paletteHead")
            lay.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, (key, label, tip) in enumerate(items):
                b = QToolButton()
                b.setText(label)
                b.setToolTip(tip)
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                b.setMinimumHeight(26)
                if key.startswith("tool:"):
                    b.setCheckable(True)
                    self._tool_group.addButton(b)
                elif key.startswith("chan:"):
                    b.setCheckable(True)
                    self._chan_group.addButton(b)
                elif key in TOGGLES:
                    b.setCheckable(True)
                b.clicked.connect(lambda _=False, k=key: self.triggered.emit(k))
                grid.addWidget(b, i // 2, i % 2)
                self.buttons[key] = b
            lay.addLayout(grid)
        self.result = QLabel("측정 결과가 여기에 표시됩니다")
        self.result.setObjectName("paletteResult")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.result)
        lay.addStretch()
        self.buttons["tool:pan"].setChecked(True)
        self.buttons["chan:rgb"].setChecked(True)

    def set_checked(self, key: str, on: bool) -> None:
        b = self.buttons.get(key)
        if b is not None and b.isChecked() != on:
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)

    def set_enabled_for_tab(self, tab: int) -> None:
        """Measurement / view tools only apply to the 2D tab."""
        for key, b in self.buttons.items():
            two_d_only = key.startswith("tool:") or key in (
                "fit", "actual", "rot_cw", "rot_ccw", "flip_h", "flip_v", "annot_undo", "annot_clear",
                "copy", "save_file", "save_record", "print")
            b.setEnabled(tab == 0 or not two_d_only)
