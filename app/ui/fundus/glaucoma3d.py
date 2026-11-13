"""3D 보기 · 녹내장 창 — 안저 검토 화면의 활성 영상으로 연다.

탭 1  3D 보기              안저 사진을 안구 안쪽에 입혀 돌려 본다 (자동 회전 · 화각 · 보기 전환 · 확대)
탭 2  녹내장 설명           같은 3D 안구에 녹내장 단계별 변화를 덧그리고 시야 예시를 보여 준다 (환자 설명용)
탭 3  시신경유두 3D · C/D   유두 부분의 입체 지형 + 유두·함몰 타원으로 C/D 비율 계산
계산·렌더링은 app.services.glaucoma (Qt 없음).
"""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.capture.frame_utils import bgr_to_qimage
from app.services import glaucoma as G

_FOVS = [(45, "45° (일반 안저카메라)"), (60, "60°"), (120, "120° (광각)"), (200, "200° (초광각)")]
_STAGE_TEXT = (
    "정상: 시신경유두의 함몰이 작고, 시야 전체가 고르게 보입니다.",
    "초기: 함몰이 조금 커지고 신경섬유층이 얇아지기 시작합니다. 시야 한쪽에 활 모양의 흐린 부분이 생기지만 "
    "본인은 거의 느끼지 못합니다.",
    "중기: 함몰이 더 커지고 신경섬유층 결손이 넓어집니다. 주변 시야가 뚜렷하게 좁아집니다.",
    "말기: 함몰이 유두 대부분을 차지합니다. 가운데만 남아 터널 속에서 보는 것처럼 보입니다. "
    "손상된 시신경은 되돌릴 수 없어 조기 발견과 꾸준한 치료가 중요합니다.",
)
NOTE_MODEL = "설명용 모형입니다. 이 환자의 실제 진행 단계를 뜻하지 않습니다."
NOTE_3D = "안저 사진을 안구 안쪽 면에 입힌 그림입니다. 사진 화각을 실제 촬영 범위에 맞춰 고르세요."
NOTE_RELIEF = "입체 지형은 사진 밝기로 추정한 표현이며 실제 깊이 측정값이 아닙니다. C/D 는 그린 타원에서 계산한 참고값입니다."


class _DragView(QLabel):
    """그림을 보여 주고 끌기(회전)·클릭(위치 지정)을 알린다."""
    dragged = Signal(int, int)
    clicked = Signal(float, float)            # 그림 안의 위치 (0~1)

    def __init__(self, size: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#0b0d10; border-radius:8px;")
        self._last: QPoint | None = None
        self._moved = False

    def show_bgr(self, img: np.ndarray) -> None:
        pm = QPixmap.fromImage(bgr_to_qimage(np.ascontiguousarray(img)))
        self.setPixmap(pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._last, self._moved = e.position().toPoint(), False

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._last is None:
            return
        p = e.position().toPoint()
        d = p - self._last
        if abs(d.x()) + abs(d.y()) > 0:
            self._moved = True
            self._last = p
            self.dragged.emit(d.x(), d.y())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._last is not None and not self._moved:
            self.clicked.emit(e.position().x() / self.width(), e.position().y() / self.height())
        self._last = None


def _muted(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Muted")
    lb.setWordWrap(True)
    return lb


class _EyePane(QWidget):
    """3D 안구 그림 + 조작(끌어서 회전 · 자동 회전 · 화각 · 확대). staged=True 면 녹내장 단계와 시야 예시가 붙는다."""

    def __init__(self, owner: "Glaucoma3DDialog", staged: bool, parent=None):
        super().__init__(parent)
        self.owner, self.staged = owner, staged
        self.stage = 0
        self.yaw, self.pitch = 22.0, -8.0
        self._spin_dir = 1.0
        lay = QHBoxLayout(self)
        self.view = _DragView(460)
        self.view.setToolTip("끌어서 돌리기")
        self.view.dragged.connect(self.drag)
        lay.addWidget(self.view)

        side = QVBoxLayout()
        self.stage_group = QButtonGroup(self)
        if staged:
            side.addWidget(QLabel("녹내장 단계"))
            seg = QHBoxLayout()
            seg.setSpacing(4)
            for i, name in enumerate(G.STAGES):
                b = QPushButton(name)
                b.setObjectName("ProBtn")
                b.setCheckable(True)
                b.setChecked(i == 0)
                self.stage_group.addButton(b, i)
                seg.addWidget(b)
            self.stage_group.idClicked.connect(self.set_stage)
            side.addLayout(seg)

        form = QFormLayout()
        self.c_fov = QComboBox()
        for deg, text in _FOVS:
            self.c_fov.addItem(text, deg)
        self.c_fov.setToolTip("이 사진이 찍은 범위. 넓을수록 안구 안쪽을 더 많이 덮습니다")
        self.c_fov.currentIndexChanged.connect(self.render)
        form.addRow("사진 화각", self.c_fov)
        self.c_view = QComboBox()
        for key, text in (("color", "컬러"), ("redfree", "감각망막 (적색 제거)"), ("choroid", "맥락막 (녹색 제거)")):
            self.c_view.addItem(text, key)
        self.c_view.currentIndexChanged.connect(self.render)
        self.s_zoom = QSlider(Qt.Orientation.Horizontal)
        self.s_zoom.setRange(100, 300)
        self.s_zoom.valueChanged.connect(self.render)
        if not staged:
            form.addRow("보기", self.c_view)
            form.addRow("확대", self.s_zoom)
        side.addLayout(form)
        self.b_spin = QPushButton("자동 회전")
        self.b_spin.setObjectName("ProBtn")
        self.b_spin.setCheckable(True)
        self.b_spin.toggled.connect(self._on_spin_toggled)
        side.addWidget(self.b_spin)
        b_front = QPushButton("정면으로")
        b_front.setObjectName("ProBtn")
        b_front.clicked.connect(self.reset_view)
        side.addWidget(b_front)

        self.l_field, self.l_stage = QLabel(), QLabel()
        if staged:
            side.addSpacing(6)
            side.addWidget(QLabel("환자가 보는 시야 (예시)"))
            self.l_field.setFixedSize(300, 198)
            self.l_field.setStyleSheet("background:#0b0d10; border-radius:6px;")
            side.addWidget(self.l_field)
            self.l_stage.setWordWrap(True)
            self.l_stage.setMinimumHeight(74)
            self.l_stage.setAlignment(Qt.AlignmentFlag.AlignTop)
            side.addWidget(self.l_stage)
        side.addStretch(1)
        side.addWidget(_muted(NOTE_MODEL if staged else NOTE_3D))
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(330)
        lay.addWidget(panel)

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._spin)

    def fov(self) -> int:
        return int(self.c_fov.currentData())

    def set_fov(self, deg: int) -> None:
        i = self.c_fov.findData(deg)
        if i >= 0:
            self.c_fov.setCurrentIndex(i)

    def set_stage(self, stage: int) -> None:
        self.stage = max(0, min(3, int(stage)))
        b = self.stage_group.button(self.stage)
        if b and not b.isChecked():
            b.setChecked(True)
        self.render()

    def render(self) -> None:
        o = self.owner
        tex = G.channel_view(o.texture(), self.c_view.currentData())
        img = G.render_eyeball(tex, self.yaw, self.pitch, self.fov(), 460, self.stage if self.staged else 0,
                               o.disc_uv(), o.disc.w / o.side, self.s_zoom.value() / 100)
        self.view.show_bgr(img)
        if self.staged:
            f = G.field_simulation(self.stage, 300, o.scene)
            self.l_field.setPixmap(QPixmap.fromImage(bgr_to_qimage(np.ascontiguousarray(f))))
            self.l_stage.setText(_STAGE_TEXT[self.stage])

    def drag(self, dx: int, dy: int) -> None:
        self.yaw = float(np.clip(self.yaw + dx * 0.5, -75, 75))
        self.pitch = float(np.clip(self.pitch + dy * 0.5, -60, 60))
        self.render()

    def reset_view(self) -> None:
        self.b_spin.setChecked(False)
        self.yaw, self.pitch = 0.0, 0.0
        self.render()

    def set_spinning(self, on: bool) -> None:
        self.b_spin.setChecked(on)

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def _on_spin_toggled(self, on: bool) -> None:
        self._timer.start() if on else self._timer.stop()

    def _spin(self) -> None:
        self.yaw += 1.5 * self._spin_dir
        if abs(self.yaw) >= 55:
            self._spin_dir = -self._spin_dir
        self.render()


class Glaucoma3DDialog(QDialog):
    """tab: '3d' (3D 보기 — 자동 회전으로 열림) · 'glaucoma' (녹내장 설명) · 'disc' (시신경유두 3D · C/D)."""
    TABS = ("3d", "glaucoma", "disc")

    def __init__(self, image_bgr: np.ndarray, eye: str | None = None, title: str = "", tab: str = "3d", parent=None):
        super().__init__(parent)
        self.setWindowTitle("3D 보기 · 녹내장" + (f" — {title}" if title else ""))
        self.eye = eye
        self._img = image_bgr
        h, w = image_bgr.shape[:2]
        side = max(h, w)                                   # 정사각형으로 맞춘 사진 (안구에 입힐 텍스처)
        sq = np.zeros((side, side, 3), np.uint8)
        self._ox, self._oy = (side - w) // 2, (side - h) // 2
        sq[self._oy:self._oy + h, self._ox:self._ox + w] = image_bgr
        self.side = side
        k = min(1.0, 900 / side)
        self._tex = cv2.resize(sq, (round(side * k), round(side * k)), interpolation=cv2.INTER_AREA) if k < 1 else sq

        self.disc = G.detect_disc(image_bgr)
        self.cup = G.estimate_cup(image_bgr, self.disc)
        self.r_yaw, self.r_pitch = -25.0, 55.0
        self.scene = G.sample_scene(300)

        self.eye_pane = _EyePane(self, staged=False)
        self.glaucoma_pane = _EyePane(self, staged=True)
        self.eye_pane.c_fov.currentIndexChanged.connect(lambda i: self.glaucoma_pane.c_fov.setCurrentIndex(i))
        self.glaucoma_pane.c_fov.currentIndexChanged.connect(lambda i: self.eye_pane.c_fov.setCurrentIndex(i))
        tabs = QTabWidget()
        tabs.addTab(self.eye_pane, "3D 보기")
        tabs.addTab(self.glaucoma_pane, "녹내장 설명")
        tabs.addTab(self._build_disc_tab(), "시신경유두 3D · C/D")
        self.tabs = tabs
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)

        self._sync_sliders()
        self._render_eye()
        self._render_disc()
        tabs.currentChanged.connect(self._on_tab)
        tabs.setCurrentIndex(self.TABS.index(tab) if tab in self.TABS else 0)
        if tabs.currentIndex() == 0:
            self.eye_pane.set_spinning(True)               # 3D 보기는 자동 회전으로 열린다

    # ================= 공통 =================
    def texture(self) -> np.ndarray:
        return self._tex

    def disc_uv(self) -> tuple[float, float]:
        return ((self.disc.cx + self._ox) / self.side, (self.disc.cy + self._oy) / self.side)

    @property
    def stage(self) -> int:
        return self.glaucoma_pane.stage

    @property
    def stage_group(self) -> QButtonGroup:
        return self.glaucoma_pane.stage_group

    def set_stage(self, stage: int) -> None:
        self.glaucoma_pane.set_stage(stage)

    def _render_eye(self) -> None:
        self.eye_pane.render()
        self.glaucoma_pane.render()

    def _on_eye_drag(self, dx: int, dy: int) -> None:
        self.eye_pane.drag(dx, dy)

    def _on_tab(self, idx: int) -> None:
        for i, pane in enumerate((self.eye_pane, self.glaucoma_pane)):   # 보이지 않는 탭은 돌리지 않는다
            if i != idx:
                pane.set_spinning(False)

    # ================= 탭 2: 시신경유두 3D · C/D =================
    def _slider(self, lo: int, hi: int) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.valueChanged.connect(self._on_slider)
        return s

    def _build_disc_tab(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        col = QVBoxLayout()
        self.v_crop = _DragView(300)
        self.v_crop.setToolTip("클릭: 유두 중심을 그 자리로")
        self.v_crop.clicked.connect(self._on_crop_click)
        col.addWidget(_muted("유두(파랑) · 함몰(노랑) — 클릭해 중심 이동"))
        col.addWidget(self.v_crop)
        col.addStretch(1)
        lay.addLayout(col)

        col2 = QVBoxLayout()
        self.v_relief = _DragView(380)
        self.v_relief.setToolTip("끌어서 돌리기")
        self.v_relief.dragged.connect(self._on_relief_drag)
        col2.addWidget(_muted("입체 지형 — 끌어서 돌리기"))
        col2.addWidget(self.v_relief)
        col2.addStretch(1)
        lay.addLayout(col2)

        side = QVBoxLayout()
        form = QFormLayout()
        self.s_dw, self.s_dh = self._slider(2, 40), self._slider(2, 40)        # 영상 한 변의 %
        self.s_cw, self.s_ch = self._slider(5, 100), self._slider(5, 100)      # 유두의 %
        self.s_depth = self._slider(0, 60)
        self.s_depth.blockSignals(True)
        self.s_depth.setValue(20)
        self.s_depth.blockSignals(False)
        form.addRow("유두 가로", self.s_dw)
        form.addRow("유두 세로", self.s_dh)
        form.addRow("함몰 가로", self.s_cw)
        form.addRow("함몰 세로", self.s_ch)
        form.addRow("입체감", self.s_depth)
        side.addLayout(form)
        b_auto = QPushButton("자동으로 다시 찾기")
        b_auto.setObjectName("ProBtn")
        b_auto.clicked.connect(self.auto_detect)
        side.addWidget(b_auto)
        side.addSpacing(8)
        self.l_cd = QLabel()
        self.l_cd.setTextFormat(Qt.TextFormat.RichText)
        side.addWidget(self.l_cd)
        self.l_comment = QLabel()
        self.l_comment.setWordWrap(True)
        side.addWidget(self.l_comment)
        side.addStretch(1)
        side.addWidget(_muted(NOTE_RELIEF))
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(280)
        lay.addWidget(panel)
        return page

    def _sync_sliders(self) -> None:
        """타원 값 → 슬라이더 (신호 없이)."""
        h, w = self._img.shape[:2]
        vals = ((self.s_dw, self.disc.w / w * 100), (self.s_dh, self.disc.h / h * 100),
                (self.s_cw, self.cup.w / max(1e-6, self.disc.w) * 100), (self.s_ch, self.cup.h / max(1e-6, self.disc.h) * 100))
        for s, v in vals:
            s.blockSignals(True)
            s.setValue(int(round(v)))
            s.blockSignals(False)

    def _on_slider(self) -> None:
        h, w = self._img.shape[:2]
        self.disc.w, self.disc.h = self.s_dw.value() / 100 * w, self.s_dh.value() / 100 * h
        self.cup.w, self.cup.h = self.s_cw.value() / 100 * self.disc.w, self.s_ch.value() / 100 * self.disc.h
        self._render_disc()

    def auto_detect(self) -> None:
        self.disc = G.detect_disc(self._img)
        self.cup = G.estimate_cup(self._img, self.disc)
        self._sync_sliders()
        self._render_disc()
        self._render_eye()

    def _crop_half(self) -> float:
        return max(self.disc.w, self.disc.h) * 1.15

    def _on_crop_click(self, fx: float, fy: float) -> None:
        half = self._crop_half()
        dx, dy = (fx - 0.5) * 2 * half, (fy - 0.5) * 2 * half
        self.disc.cx += dx
        self.disc.cy += dy
        self.cup.cx += dx
        self.cup.cy += dy
        self._render_disc()
        self._render_eye()

    def _on_relief_drag(self, dx: int, dy: int) -> None:
        self.r_yaw = float(np.clip(self.r_yaw + dx * 0.6, -80, 80))
        self.r_pitch = float(np.clip(self.r_pitch + dy * 0.5, 15, 80))
        self._render_disc()

    def ratios(self) -> dict:
        return G.cd_ratios(self.disc, self.cup)

    def _render_disc(self) -> None:
        n, half = 240, self._crop_half()
        tex = G.crop_square(self._img, self.disc.cx, self.disc.cy, half, n)
        k = n / (2 * half)
        loc = lambda e: G.Ellipse(n / 2 + (e.cx - self.disc.cx) * k, n / 2 + (e.cy - self.disc.cy) * k, e.w * k, e.h * k)  # noqa: E731
        overlays = [(loc(self.disc), (255, 190, 60)), (loc(self.cup), (60, 220, 255))]
        flat = cv2.resize(tex, (300, 300), interpolation=cv2.INTER_LINEAR)
        s = 300 / n
        for el, color in overlays:
            cv2.ellipse(flat, (int(el.cx * s), int(el.cy * s)), (max(1, int(el.w * s / 2)), max(1, int(el.h * s / 2))),
                        0, 0, 360, color, 2, cv2.LINE_AA)
        self.v_crop.show_bgr(flat)
        self.v_relief.show_bgr(G.render_relief(tex, G.relief_height(tex), self.r_yaw, self.r_pitch,
                                               self.s_depth.value() / 100, 380, overlays))
        r = self.ratios()
        self.l_cd.setText(
            f"<table cellspacing='4'><tr><td>수직 C/D</td><td><b style='font-size:18px'>{r['vertical']:.2f}</b></td></tr>"
            f"<tr><td>수평 C/D</td><td><b>{r['horizontal']:.2f}</b></td></tr>"
            f"<tr><td>면적 C/D</td><td><b>{r['area']:.2f}</b></td></tr>"
            f"<tr><td>테(rim) 면적</td><td><b>{r['rim_area'] * 100:.0f}%</b></td></tr></table>")
        self.l_comment.setText(G.cd_comment(r["vertical"]))

    def closeEvent(self, e) -> None:  # noqa: N802
        self.eye_pane.set_spinning(False)
        self.glaucoma_pane.set_spinning(False)
        super().closeEvent(e)
