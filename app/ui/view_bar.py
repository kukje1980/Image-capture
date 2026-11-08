"""촬영 화면 위쪽 보기 막대: 큰 화면 · 멀티 화면(4분할) · 확대 화면 · 3D 화면 + 보기별 조절.

확대: －/배율/＋/가운데,  3D: 높이 슬라이더 · 색(원본/높이 컬러맵) · 시점 초기화 · 3D 저장.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT

VIEWS = ("single", "multi", "zoom", "3d")
VIEW_LABEL = {"single": "큰 화면", "multi": "멀티 화면", "zoom": "확대 화면", "3d": "3D 화면"}
_VIEW_ICON = {"single": "single", "multi": "quad", "zoom": "zin", "3d": "cube"}
_VIEW_TIP = {
    "single": "큰 화면 — 실시간 영상 1화면",
    "multi": "멀티 화면 — 4분할 정지영상, '정지영상'으로 칸을 채움",
    "zoom": "확대 화면 — 휠·＋/－로 확대, 드래그로 이동 (사진 캡처는 원본 전체 프레임 저장)",
    "3d": "3D 화면 — 밝기를 높이로 바꾼 입체 표면 (드래그 회전 · 휠 확대)",
}
_HINT = {
    "single": "",
    "multi": "'정지영상'으로 칸 채우기 · 칸 클릭으로 교체",
    "zoom": "휠 확대 · 드래그 이동 · 더블클릭 가운데 · 저장은 원본 전체",
    "3d": "밝을수록 높게 · 드래그 회전 · 휠 확대 · 저장은 원본 전체",
}


class ViewBar(QFrame):
    viewChanged = Signal(str)
    zoomStep = Signal(int)
    zoomCenter = Signal()
    d3HeightChanged = Signal(int)          # 0~100
    d3ColorChanged = Signal(str)           # tex | map
    d3Reset = Signal()
    d3Save = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ViewBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 10, 5)
        lay.setSpacing(10)

        seg = QFrame()
        seg.setObjectName("ViewSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self._group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for v in VIEWS:
            b = QPushButton(icons.gap(VIEW_LABEL[v]))
            b.setObjectName("ViewBtn")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            ic = icons.icon(_VIEW_ICON[v], ICON, 16)
            ic.addPixmap(icons.pixmap(_VIEW_ICON[v], ICON_ACCENT, 16), ic.Mode.Normal, ic.State.On)
            b.setIcon(ic)
            b.setIconSize(QSize(15, 15))
            b.setToolTip(_VIEW_TIP[v])
            b.clicked.connect(lambda _=False, v=v: self.viewChanged.emit(v))
            self._group.addButton(b)
            self.buttons[v] = b
            sl.addWidget(b)
        self.buttons["single"].setChecked(True)
        lay.addWidget(seg)

        # 확대 조절
        self.zoom_box = QWidget()
        self.zoom_box.setObjectName("ViewOpts")
        zl = QHBoxLayout(self.zoom_box)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(4)
        self.btn_zoom_out = self._tool("", "zout", "축소 (휠 아래)")
        self.lbl_zoom = QLabel("×2.0")
        self.lbl_zoom.setObjectName("ZoomLevel")
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_zoom.setMinimumWidth(44)
        self.btn_zoom_in = self._tool("", "zin", "확대 (휠 위)")
        self.btn_zoom_center = self._tool("가운데", "fit", "가운데로 · 더블클릭으로도 초기화")
        for w in (self.btn_zoom_out, self.lbl_zoom, self.btn_zoom_in, self.btn_zoom_center):
            zl.addWidget(w)
        self.btn_zoom_out.clicked.connect(lambda: self.zoomStep.emit(-1))
        self.btn_zoom_in.clicked.connect(lambda: self.zoomStep.emit(1))
        self.btn_zoom_center.clicked.connect(self.zoomCenter.emit)
        lay.addWidget(self.zoom_box)

        # 3D 조절
        self.d3_box = QWidget()
        self.d3_box.setObjectName("ViewOpts")
        dl = QHBoxLayout(self.d3_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(6)
        lbl = QLabel("높이")
        lbl.setObjectName("ViewOptLabel")
        self.sl_height = QSlider(Qt.Orientation.Horizontal)
        self.sl_height.setRange(0, 100)
        self.sl_height.setValue(40)
        self.sl_height.setFixedWidth(110)
        self.sl_height.setToolTip("높이(밝기 차이)를 얼마나 크게 보일지")
        self.cb_color = QComboBox()
        self.cb_color.addItem("원본 색", "tex")
        self.cb_color.addItem("높이 컬러맵", "map")
        self.cb_color.setToolTip("표면 색")
        self.btn_d3_reset = self._tool("시점", "history", "시점 초기화 (더블클릭)")
        self.btn_d3_save = self._tool("3D 저장", "save",
                                      "지금 보이는 3D 화면을 사진으로 저장 (메모 '3D')")
        for w in (lbl, self.sl_height, self.cb_color, self.btn_d3_reset, self.btn_d3_save):
            dl.addWidget(w)
        self.sl_height.valueChanged.connect(self.d3HeightChanged.emit)
        self.cb_color.currentIndexChanged.connect(
            lambda _i: self.d3ColorChanged.emit(self.cb_color.currentData()))
        self.btn_d3_reset.clicked.connect(self.d3Reset.emit)
        self.btn_d3_save.clicked.connect(self.d3Save.emit)
        lay.addWidget(self.d3_box)

        lay.addStretch(1)
        self.hint = QLabel("")
        self.hint.setObjectName("ViewHint")
        lay.addWidget(self.hint)
        self.set_view("single")

    def _tool(self, text: str, icon_name: str, tip: str) -> QPushButton:
        b = QPushButton(icons.gap(text))
        b.setObjectName("ViewOpt")
        b.setIcon(icons.icon(icon_name, ICON, 16))
        b.setIconSize(QSize(15, 15))
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    # ---- 공개 API ----
    def set_view(self, view: str) -> None:
        """표시만 바꾼다 (신호 없음)."""
        if view not in self.buttons:
            view = "single"
        self.buttons[view].setChecked(True)
        self.zoom_box.setVisible(view == "zoom")
        self.d3_box.setVisible(view == "3d")
        self.hint.setText(_HINT[view])

    def current(self) -> str:
        return next((v for v, b in self.buttons.items() if b.isChecked()), "single")

    def set_zoom_label(self, z: float) -> None:
        self.lbl_zoom.setText(f"×{z:.1f}")

    def set_d3(self, height: int, color: str) -> None:
        for w in (self.sl_height, self.cb_color):
            w.blockSignals(True)
        self.sl_height.setValue(max(0, min(100, int(height))))
        self.cb_color.setCurrentIndex(1 if color == "map" else 0)
        for w in (self.sl_height, self.cb_color):
            w.blockSignals(False)
