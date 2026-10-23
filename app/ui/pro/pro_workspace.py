"""Pro 모드 작업공간 — 전문가용 영상 검토 화면 (VK-2 스타일 워크플로).

표시 모드
  LIVE     실시간 영상. CAPTURE(Space)로 정지/재개, SAVE로 환자 DB 저장
  1화면    단일 영상. PREV/NEXT(←/→)로 이동, 확대·이동, 보정, 텍스트/화살표 주석
  MULTI    16장(4×4) / 36장(6×6) 그리드. 클릭=비교 선택(최대 2), 더블클릭=1화면
  비교     선택한 2장 좌우 비교. 확대·스크롤 동기화, 보정 동일 적용
기타
  보정본 저장  보정·주석을 반영한 새 영상으로 저장(원본 보존, 코멘트 '보정본'/'주석')
  코멘트       영상별 코멘트 편집      환자정보  진단명·담당의 등 편집
  인쇄 / PDF   머리말·환자정보·진단명·꼬리말이 포함된 A4 보고서
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.capture.image_process import Adjust, apply_adjust, auto_levels, histogram
from app.ui import icons
from app.ui.patient_dialog import PatientDialog
from app.ui.pro import print_util
from app.ui.pro.image_canvas import ImageCanvas
from app.ui.pro.multi_grid import MultiGrid
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

log = logging.getLogger(__name__)

MODES = ["live", "single", "multi", "compare"]
_EYE_KO = {"OD": "우안(OD)", "OS": "좌안(OS)", "OU": "양안(OU)"}
_CHANNELS = ["rgb", "green", "red", "blue", "gray"]
_DENOISE = ["none", "median", "average"]
# (도구, 버튼 텍스트, 설명, 허용 모드)
_TOOLS = [
    ("pan", "이동", "이동 / 휠 확대", ("single", "compare")),
    ("magnify", "돋보기", "누르고 있는 동안 확대 렌즈", ("single", "compare", "live")),
    ("crop", "자르기", "드래그한 영역만 남김", ("single",)),
    ("text", "텍스트", "클릭한 위치에 텍스트 주석", ("single", "compare")),
    ("arrow", "화살표", "드래그해 화살표 주석", ("single", "compare")),
    ("circle", "원", "드래그해 원·타원 표시", ("single", "compare")),
    ("length", "길이", "드래그해 길이 측정 (눈금 보정 시 mm)", ("single", "compare")),
    ("angle", "각도", "세 점 클릭 — 두 번째 점이 꼭짓점", ("single", "compare")),
    ("calibrate", "눈금", "실제 길이를 아는 선을 그어 mm 단위 보정", ("single",)),
]
_TOOL_ICONS = {"pan": "hand", "magnify": "lens", "crop": "crop", "text": "type", "arrow": "arrow",
               "circle": "circle", "length": "ruler", "angle": "angle", "calibrate": "calib"}


def _icon(name: str, color: str = ICON, on: str | None = None) -> QIcon:
    """선형 아이콘. on 을 주면 체크(선택) 상태용 색을 따로 둔다."""
    ic = icons.icon(name, color, 18, disabled="#4a5262")
    if on:
        ic.addPixmap(icons.pixmap(name, on, 18), QIcon.Mode.Normal, QIcon.State.On)
    return ic


def caption_of(cap, number=None, total=None) -> str:
    parts = [cap.captured_at or ""]
    eye = _EYE_KO.get(cap.eye or "", "")
    if eye:
        parts.append(eye)
    if cap.note:
        parts.append(cap.note)
    text = "  ·  ".join(p for p in parts if p)
    return f"[{number}/{total}]  {text}" if number else text


def load_bgr(path: str | None):
    if not path or cv2 is None or not os.path.exists(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)          # 한글 경로 대응
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class ProWorkspace(QWidget):
    savedCapture = Signal()
    patientUpdated = Signal(object)

    def __init__(self, db, service, config, get_eye, parent=None):
        super().__init__(parent)
        self.setObjectName("ProWorkspace")
        self.db = db
        self.service = service
        self.config = config
        self.get_eye = get_eye
        self._patient = None
        self._caps: list = []
        self._idx = -1
        self._mode = "multi"
        self._live = None
        self._frozen = False
        self._frozen_frame = None
        self._pair = (None, None)
        self._adj = Adjust()
        self._tool = "pan"
        self._build()
        self._cmp_active = self.cmp_left
        for cv in self._canvases():
            cv.edited.connect(lambda cv=cv: self._on_canvas_edited(cv))
            cv.activated.connect(lambda cv=cv: self._on_canvas_activated(cv))
            cv.calibrated.connect(self.set_px_per_mm)
        self._shortcuts()
        self.set_px_per_mm(getattr(config, "px_per_mm", 0.0) or 0.0)
        self.set_mode("multi")
        self._update_info()

    # ================= UI =================
    def _btn(self, text, tip, checkable=False, obj="ProBtn", icon=None, color=ICON) -> QPushButton:
        b = QPushButton(icons.gap(text) if icon else text)
        b.setObjectName(obj)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setMinimumHeight(34)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if icon:
            b.setIcon(_icon(icon, color, on=ICON_ON_ACCENT if checkable else None))
            b.setIconSize(QSize(15, 15))
        return b

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("ProSep")
        f.setFixedWidth(1)
        return f

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        bar = QFrame()
        bar.setObjectName("ProToolbar")
        tl = QHBoxLayout(bar)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(4)

        self.b_live = self._btn("LIVE", "실시간 영상", True, "ProSegBtn", "live")
        self.b_single = self._btn("1화면", "단일 영상 보기", True, "ProSegBtn", "single")
        self.b_multi = self._btn("MULTI", "다중 영상 그리드 (16/36)", True, "ProSegBtn", "review")
        self.b_cmp = self._btn("비교", "선택한 2장 나란히 비교", True, "ProSegBtn", "compare")
        self.mode_group = QButtonGroup(self)
        seg = QFrame()
        seg.setObjectName("ProSeg")
        sgl = QHBoxLayout(seg)
        sgl.setContentsMargins(2, 2, 2, 2)
        sgl.setSpacing(2)
        for b, m in ((self.b_live, "live"), (self.b_single, "single"),
                     (self.b_multi, "multi"), (self.b_cmp, "compare")):
            self.mode_group.addButton(b)
            b.setMinimumHeight(30)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            sgl.addWidget(b)
        tl.addWidget(seg)
        tl.addWidget(self._sep())

        self.b_capture = self._btn("CAPTURE", "라이브 정지/재개 (Space)", True, "ProCapture", "freeze", ICON_ACCENT)
        self.b_save = self._btn("SAVE", "정지 영상을 환자 DB에 저장", icon="save")
        self.c_eye = QComboBox()
        self.c_eye.addItems(["안구 미지정", "OD 우안", "OS 좌안", "OU 양안"])
        self.c_eye.setToolTip("저장할 영상의 안구 방향")
        tl.addWidget(self.c_eye)
        tl.addWidget(self.b_capture)
        tl.addWidget(self.b_save)
        tl.addWidget(self._sep())

        self.b_prev = self._btn("PREV", "이전 영상 / 페이지 (←)", icon="chev-l")
        self.b_next = self._btn("NEXT", "다음 영상 / 페이지 (→)", icon="chev-r")
        self.b_next.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.c_per = QComboBox()
        self.c_per.addItems(["16장", "36장"])
        self.c_per.setToolTip("MULTI 표시 장수")
        tl.addWidget(self.b_prev)
        tl.addWidget(self.b_next)
        tl.addWidget(self.c_per)
        tl.addWidget(self._sep())

        # 편집 도구·실행 취소·편집본 저장은 사이드 패널 '편집' 탭에 배치 (툴바 폭 절약)
        self.tool_buttons = {}
        self.tool_group = QButtonGroup(self)
        for t, text, tip, _modes in _TOOLS:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setObjectName("ProTool")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumHeight(50)
            b.setIcon(_icon(_TOOL_ICONS[t], ICON, on=ICON_ON_ACCENT))
            b.setIconSize(QSize(18, 18))
            self.tool_group.addButton(b)
            b.clicked.connect(lambda _=False, t=t: self.set_tool(t))
            self.tool_buttons[t] = b
        self.b_pan, self.b_text, self.b_arrow = (self.tool_buttons[k] for k in ("pan", "text", "arrow"))
        self.b_pan.setChecked(True)
        self.b_rot_l = self._btn("", "반시계 방향 90° 회전", icon="rot-l")
        self.b_rot_r = self._btn("", "시계 방향 90° 회전", icon="rot-r")
        self.b_flip_h = self._btn("", "좌우 반전", icon="flip-h")
        self.b_flip_v = self._btn("", "상하 반전", icon="flip-v")
        self.b_undo = self._btn("실행 취소", "마지막 편집 취소 (Ctrl+Z)", icon="undo")
        self.b_redo = self._btn("다시 실행", "취소한 편집 다시 실행 (Ctrl+Y)", icon="redo")
        self.b_orig = self._btn("원본", "모든 보정·편집을 지우고 원본으로", icon="history")
        self.b_clear = self._btn("주석 지우기", "현재 화면의 주석·측정 모두 삭제", icon="eraser")
        self.b_edit_save = self._btn("편집본 저장", "보정·편집·주석·측정을 반영한 새 영상으로 저장 (원본 보존)",
                                     obj="ProPrimary", icon="save", color=ICON_ON_ACCENT)

        self.b_comment = self._btn("코멘트", "현재 영상 코멘트 편집", obj="ProGhost", icon="comment")
        self.b_patient = self._btn("환자정보", "진단명·담당의 등 환자 정보 편집", obj="ProGhost", icon="user")
        for b in (self.b_comment, self.b_patient):
            tl.addWidget(b)
        tl.addStretch(1)
        self.b_print = self._btn("인쇄", "현재 화면 영상 보고서 인쇄", obj="ProPrimary", icon="printer",
                                 color=ICON_ON_ACCENT)
        self.b_pdf = self._btn("PDF", "PDF 보고서로 저장", icon="download")
        tl.addWidget(self.b_print)
        tl.addWidget(self.b_pdf)
        root.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(8)
        self.stack = QStackedWidget()
        self.stack.setObjectName("ProDisplay")
        self.live_canvas = ImageCanvas()
        self.live_canvas._placeholder = "라이브 영상 대기 중"
        self.single_canvas = ImageCanvas()
        self.multi = MultiGrid()
        cmp = QWidget()
        cl = QHBoxLayout(cmp)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.cmp_left = ImageCanvas()
        self.cmp_right = ImageCanvas()
        self.cmp_left.link(self.cmp_right)
        cl.addWidget(self.cmp_left)
        cl.addWidget(self.cmp_right)
        for w in (self.live_canvas, self.single_canvas, self.multi, cmp):
            self.stack.addWidget(w)
        body.addWidget(self.stack, 1)
        body.addWidget(self._build_side())
        root.addLayout(body, 1)

        self.info = QLabel()
        self.info.setObjectName("ProInfo")
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setVisible(False)          # 환자 요약은 상단 환자 배너에 표시
        root.addWidget(self.info)

        self.b_capture.toggled.connect(self._on_capture_toggled)
        self.b_save.clicked.connect(self.save_live)
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_next.clicked.connect(lambda: self.step(1))
        self.c_per.currentIndexChanged.connect(lambda i: self.set_per_page(36 if i == 1 else 16))
        self.b_clear.clicked.connect(self.clear_annotations)
        self.b_edit_save.clicked.connect(self.save_edited)
        self.b_comment.clicked.connect(self.edit_comment)
        self.b_patient.clicked.connect(self.edit_patient)
        self.b_print.clicked.connect(self.print_current)
        self.b_pdf.clicked.connect(self._pdf_dialog)
        self.multi.openRequested.connect(self.open_index)
        self.multi.selectionChanged.connect(self._on_selection)

    def _build_side(self) -> QFrame:
        side = QFrame()
        side.setObjectName("ProSide")
        side.setFixedWidth(276)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        card = QFrame()
        card.setObjectName("ProCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 6, 10, 8)
        cl.setSpacing(2)
        h1 = QLabel("영상 정보")
        h1.setObjectName("PanelHeader")
        cl.addWidget(h1)
        self.lbl_img = QLabel("-")
        self.lbl_img.setWordWrap(True)
        self.lbl_img.setObjectName("Muted")
        cl.addWidget(self.lbl_img)
        lay.addWidget(card)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("ProTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._scroll(self._tab_adjust()), "보정")
        self.tabs.addTab(self._scroll(self._tab_filter()), "필터")
        self.tabs.addTab(self._scroll(self._tab_edit()), "편집")
        lay.addWidget(self.tabs, 1)

        self.lbl_sel = QLabel("MULTI에서 영상 2장을 클릭해 선택한 뒤 '비교'를 누르세요.")
        self.lbl_sel.setWordWrap(True)
        self.lbl_sel.setObjectName("Muted")
        lay.addWidget(self.lbl_sel)
        return side

    @staticmethod
    def _scroll(w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidget(w)
        return sa

    def _slider_row(self, form: QFormLayout, label: str, lo: int, hi: int, val: int, fmt) -> QSlider:
        s = self._slider(lo, hi, val)
        v = QLabel()
        v.setObjectName("Muted")
        v.setFixedWidth(34)
        v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(s, 1)
        row.addWidget(v)
        form.addRow(label, row)
        self._value_labels.append((s, v, fmt))
        return s

    def _tab_adjust(self) -> QWidget:
        w = QWidget()
        w.setObjectName("ProTabPage")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(6)
        self._value_labels = []
        pct = lambda v: f"{v / 100:.2f}"  # noqa: E731
        form = QFormLayout()
        form.setSpacing(5)
        self.s_bright = self._slider_row(form, "밝기", -100, 100, 0, str)
        self.s_contrast = self._slider_row(form, "대비", 20, 300, 100, pct)
        self.s_gamma = self._slider_row(form, "감마", 20, 300, 100, pct)
        self.s_sat = self._slider_row(form, "채도", 0, 200, 100, pct)
        lay.addLayout(form)

        lay.addWidget(self._sub("색균형 (RGB)"))
        form2 = QFormLayout()
        form2.setSpacing(5)
        self.s_r = self._slider_row(form2, "R", 50, 150, 100, pct)
        self.s_g = self._slider_row(form2, "G", 50, 150, 100, pct)
        self.s_b = self._slider_row(form2, "B", 50, 150, 100, pct)
        for sl, name in ((self.s_r, "SliderR"), (self.s_g, "SliderG"), (self.s_b, "SliderB")):
            sl.setObjectName(name)
        lay.addLayout(form2)

        lay.addWidget(self._sub("레벨 · 히스토그램"))
        self.hist = QLabel()
        self.hist.setFixedSize(236, 64)
        self.hist.setObjectName("Histogram")
        lay.addWidget(self.hist)
        form3 = QFormLayout()
        form3.setSpacing(5)
        self.s_black = self._slider_row(form3, "흑점", 0, 250, 0, str)
        self.s_white = self._slider_row(form3, "백점", 5, 255, 255, str)
        lay.addLayout(form3)

        form4 = QFormLayout()
        form4.setSpacing(5)
        self.c_channel = QComboBox()
        self.c_channel.addItems(["컬러", "Red-free (녹색)", "적색", "청색", "흑백"])
        form4.addRow("채널", self.c_channel)
        self.chk_neg = QCheckBox("네거티브 (NEGA)")
        form4.addRow("", self.chk_neg)
        lay.addLayout(form4)

        r1 = QHBoxLayout()
        self.b_auto = self._btn("자동 대비", "", icon="wand")
        self.b_auto.setToolTip("히스토그램 양끝 0.5%를 잘라 흑·백점 자동 설정")
        self.b_reset = self._btn("초기화", "보정 초기화", icon="history")
        r1.addWidget(self.b_auto)
        r1.addWidget(self.b_reset)
        lay.addLayout(r1)
        lay.addStretch(1)

        for sl in (self.s_bright, self.s_contrast, self.s_gamma, self.s_sat, self.s_r, self.s_g, self.s_b,
                   self.s_black, self.s_white):
            sl.valueChanged.connect(self._on_adjust)
        self.c_channel.currentIndexChanged.connect(self._on_adjust)
        self.chk_neg.toggled.connect(self._on_adjust)
        self.b_auto.clicked.connect(self.auto_contrast)
        self.b_reset.clicked.connect(self.reset_adjust)
        self._update_value_labels()
        return w

    def _tab_filter(self) -> QWidget:
        w = QWidget()
        w.setObjectName("ProTabPage")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(8)
        form = QFormLayout()
        form.setSpacing(6)
        self.c_denoise = QComboBox()
        self.c_denoise.addItems(["없음", "Median (3×3)", "평균 (3×3)"])
        self.c_sharpen = QComboBox()
        self.c_sharpen.addItems(["없음", "약", "중", "강"])
        self.c_enhance = QComboBox()
        self.c_enhance.addItems(["없음", "약", "중", "강"])
        form.addRow("노이즈 제거", self.c_denoise)
        form.addRow("선명하게", self.c_sharpen)
        form.addRow("국소 대비 향상", self.c_enhance)
        lay.addLayout(form)
        tip = QLabel("· 노이즈 제거: 어두운 영상의 잡티 감소\n"
                     "· 선명하게: 경계(각막·수정체 단면)를 또렷하게\n"
                     "· 국소 대비 향상: 미세한 밝기 차이(혼탁·부종)를 강조\n"
                     "· 보정 탭의 Red-free는 혈관·출혈 관찰에 유용")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        lay.addWidget(tip)
        lay.addStretch(1)
        for c in (self.c_denoise, self.c_sharpen, self.c_enhance):
            c.currentIndexChanged.connect(self._on_adjust)
        return w

    def _tab_edit(self) -> QWidget:
        w = QWidget()
        w.setObjectName("ProTabPage")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(2, 8, 4, 4)
        lay.setSpacing(6)

        lay.addWidget(self._sub("보기"))
        g0 = QGridLayout()
        g0.setSpacing(4)
        self.b_fit = self._btn("맞춤", "화면 맞춤", icon="fit")
        self.b_zin = self._btn("확대", "확대", icon="zin")
        self.b_zout = self._btn("축소", "축소", icon="zout")
        g0.addWidget(self.b_fit, 0, 0)
        g0.addWidget(self.b_zin, 0, 1)
        g0.addWidget(self.b_zout, 0, 2)
        lay.addLayout(g0)

        lay.addWidget(self._sub("회전 · 반전"))
        g1 = QGridLayout()
        g1.setSpacing(4)
        g1.addWidget(self.b_rot_l, 0, 0)
        g1.addWidget(self.b_rot_r, 0, 1)
        g1.addWidget(self.b_flip_h, 0, 2)
        g1.addWidget(self.b_flip_v, 0, 3)
        lay.addLayout(g1)

        lay.addWidget(self._sub("도구 (주석 · 측정)"))
        g2 = QGridLayout()
        g2.setSpacing(4)
        for k, (t, *_rest) in enumerate(_TOOLS):
            g2.addWidget(self.tool_buttons[t], k // 3, k % 3)
        lay.addLayout(g2)
        cal = QHBoxLayout()
        self.lbl_calib = QLabel()
        self.lbl_calib.setObjectName("Muted")
        self.lbl_calib.setWordWrap(True)
        self.b_calib_clear = QPushButton("해제")
        self.b_calib_clear.setToolTip("눈금 보정 해제 (px 단위로 측정)")
        self.b_calib_clear.setFixedWidth(52)
        cal.addWidget(self.lbl_calib, 1)
        cal.addWidget(self.b_calib_clear)
        lay.addLayout(cal)

        lay.addWidget(self._sub("편집 이력"))
        g3 = QGridLayout()
        g3.setSpacing(4)
        g3.addWidget(self.b_undo, 0, 0)
        g3.addWidget(self.b_redo, 0, 1)
        g3.addWidget(self.b_orig, 1, 0)
        g3.addWidget(self.b_clear, 1, 1)
        g3.addWidget(self.b_edit_save, 2, 0, 1, 2)
        lay.addLayout(g3)
        lay.addStretch(1)

        self.b_fit.clicked.connect(self._fit_all)
        self.b_zin.clicked.connect(lambda: self._zoom(1.25))
        self.b_zout.clicked.connect(lambda: self._zoom(0.8))
        self.b_rot_l.clicked.connect(lambda: self.rotate(-1))
        self.b_rot_r.clicked.connect(lambda: self.rotate(1))
        self.b_flip_h.clicked.connect(lambda: self.flip(True))
        self.b_flip_v.clicked.connect(lambda: self.flip(False))
        self.b_undo.clicked.connect(self.undo)
        self.b_redo.clicked.connect(self.redo)
        self.b_orig.clicked.connect(self.restore_original)
        self.b_calib_clear.clicked.connect(lambda: self.set_px_per_mm(0.0))
        return w

    @staticmethod
    def _sub(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("PanelHeader")
        return lbl

    @staticmethod
    def _slider(lo, hi, val) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _shortcuts(self) -> None:
        for key, fn in ((QKeySequence(Qt.Key.Key_Left), lambda: self.step(-1)),
                        (QKeySequence(Qt.Key.Key_Right), lambda: self.step(1)),
                        (QKeySequence(Qt.Key.Key_Space), self._space),
                        (QKeySequence.StandardKey.Undo, self.undo),
                        (QKeySequence.StandardKey.Redo, self.redo),
                        (QKeySequence("Ctrl+Y"), self.redo),
                        (QKeySequence(Qt.Key.Key_Escape), lambda: self.set_tool("pan"))):
            sc = QShortcut(key, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    def _space(self) -> None:
        if self._mode == "live":
            self.b_capture.toggle()

    # ================= 데이터 =================
    def set_patient(self, patient) -> None:
        self._patient = patient
        self.multi.clear_selection()
        self.reload()
        self._update_info()

    def reload(self, select_last: bool = True) -> None:
        if self._patient is None:
            self._caps = []
        else:
            self._caps = [c for c in self.db.captures.list_by_patient(self._patient.id, order="asc")
                          if c.media_type == "photo"]
        self.multi.set_captures(self._caps)
        if select_last or not (0 <= self._idx < len(self._caps)):
            self._idx = len(self._caps) - 1
        self._show_current()
        self._update_info()

    def captures(self) -> list:
        return list(self._caps)

    def current_index(self) -> int:
        return self._idx

    def mode(self) -> str:
        return self._mode

    def _update_info(self) -> None:
        p = self._patient
        if p is None:
            self.info.setText("환자를 선택하세요")
            return
        sex = {"M": "남", "F": "여", "O": "기타"}.get(p.sex or "", "")
        bits = [f"<b>{p.name}</b> ({p.chart_no or '-'})"]
        if sex:
            bits.append(sex)
        if p.birth_date:
            bits.append(p.birth_date)
        bits.append(f"진단명: <b>{p.diagnosis or '-'}</b>")
        bits.append(f"담당의: {p.doctor or '-'}")
        bits.append(f"영상 {len(self._caps)}장")
        self.info.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(bits))

    # ================= 모드 =================
    def set_mode(self, mode: str) -> None:
        if mode == "compare" and not self._prepare_compare():
            mode = self._mode if self._mode != "compare" else "multi"
        self._mode = mode
        self.stack.setCurrentIndex(MODES.index(mode))
        {"live": self.b_live, "single": self.b_single, "multi": self.b_multi,
         "compare": self.b_cmp}[mode].setChecked(True)
        live = mode == "live"
        self.b_capture.setEnabled(live)
        self.b_save.setEnabled(live)
        self.c_per.setEnabled(mode == "multi")
        ann = mode in ("single", "compare")
        for t, *_x, modes in _TOOLS:
            self.tool_buttons[t].setEnabled(mode in modes)
        for b in (self.b_clear, self.b_edit_save):
            b.setEnabled(ann)
        self.b_comment.setEnabled(mode == "single")
        if mode == "compare":
            self._cmp_active = self.cmp_left
        if mode == "single":
            self._show_current()
        if live:
            self.live_canvas.set_adjust(self._adj)
            if self._live is not None and not self._frozen:
                self.live_canvas.set_image(self._live, keep_view=True)
        if getattr(self, "_tool", "pan") != "pan":
            self.set_tool(self._tool)            # 이 모드에서 못 쓰는 도구면 이동으로
        self._update_side()
        self._refresh_edit_state()

    def _show_current(self) -> None:
        if not (0 <= self._idx < len(self._caps)):
            self.single_canvas.set_image(None)
            self._update_side()
            return
        cap = self._caps[self._idx]
        self.single_canvas.set_image(load_bgr(cap.file_path))
        self.single_canvas.set_adjust(self._adj)
        self.single_canvas.set_caption(caption_of(cap, self._idx + 1, len(self._caps)))
        self._update_side()
        self._refresh_edit_state()

    def _update_side(self) -> None:
        if self._mode == "single" and 0 <= self._idx < len(self._caps):
            c = self._caps[self._idx]
            self.lbl_img.setText(
                f"{self._idx + 1} / {len(self._caps)}\n촬영: {c.captured_at}\n"
                f"안구: {_EYE_KO.get(c.eye or '', '미지정')}\n코멘트: {c.note or '-'}")
        elif self._mode == "multi":
            self.lbl_img.setText(
                f"페이지 {self.multi.page() + 1} / {self.multi.page_count()}  ·  "
                f"{self.multi.per_page()}장 보기\n전체 {len(self._caps)}장  ·  선택 {len(self.multi.selection())}장")
        elif self._mode == "compare":
            rows = [f"{'좌' if i == 0 else '우'}: {c.captured_at} {_EYE_KO.get(c.eye or '', '')}"
                    for i, c in enumerate(self._pair) if c]
            self.lbl_img.setText("2장 비교 (확대·이동 동기화)\n" + "\n".join(rows))
        elif self._mode == "live":
            self.lbl_img.setText("LIVE — " + ("정지됨 · SAVE로 저장" if self._frozen else "실시간"))
        else:
            self.lbl_img.setText("영상이 없습니다")

    # ================= 탐색 =================
    def step(self, delta: int) -> None:
        if self._mode == "multi":
            self.multi.go_page(delta)
            self._update_side()
        elif self._mode == "single" and self._caps:
            self._idx = min(max(0, self._idx + delta), len(self._caps) - 1)
            self._show_current()

    def open_index(self, idx: int) -> None:
        if 0 <= idx < len(self._caps):
            self._idx = idx
            self.set_mode("single")

    def set_per_page(self, n: int) -> None:
        self.multi.set_per_page(n)
        blk = self.c_per.blockSignals(True)
        self.c_per.setCurrentIndex(1 if n == 36 else 0)
        self.c_per.blockSignals(blk)
        self._update_side()

    def select_for_compare(self, i: int, j: int) -> None:
        self.multi.set_selection([i, j])

    def _on_selection(self, sel: list) -> None:
        self.lbl_sel.setText(
            f"선택 {len(sel)}/2 — 2장이면 '비교'를 누르세요." if sel
            else "MULTI에서 영상 2장을 클릭해 선택한 뒤 '비교'를 누르세요.")
        self._update_side()

    # ================= 비교 =================
    def _prepare_compare(self) -> bool:
        sel = self.multi.selection()
        if len(sel) == 2:
            i, j = sorted(sel)
        elif self._mode == "single" and self._idx > 0:
            i, j = self._idx - 1, self._idx
        else:
            if self.isVisible():
                QMessageBox.information(self, "2장 비교", "MULTI 화면에서 비교할 영상 2장을 클릭해 선택하세요.")
            return False
        a, b = self._caps[i], self._caps[j]
        self._pair = (a, b)
        for cv, cap, num in ((self.cmp_left, a, i + 1), (self.cmp_right, b, j + 1)):
            cv.set_image(load_bgr(cap.file_path))
            cv.set_adjust(self._adj)
            cv.set_caption(caption_of(cap, num, len(self._caps)))
        return True

    # ================= 보정 · 편집 대상 =================
    def _canvases(self) -> list:
        return [self.live_canvas, self.single_canvas, self.cmp_left, self.cmp_right]

    def _target_canvases(self) -> list:
        return {"single": [self.single_canvas], "compare": [self.cmp_left, self.cmp_right],
                "live": [self.live_canvas]}.get(self._mode, [])

    def active_canvas(self):
        """편집 명령(회전·실행 취소·자동 대비 등)이 적용될 캔버스."""
        if self._mode == "single":
            return self.single_canvas
        if self._mode == "compare":
            return self._cmp_active
        if self._mode == "live":
            return self.live_canvas
        return None

    def _on_canvas_activated(self, cv) -> None:
        if self._mode == "compare" and cv in (self.cmp_left, self.cmp_right):
            self._cmp_active = cv
            self._refresh_edit_state()

    def _on_canvas_edited(self, cv) -> None:
        if cv is self.active_canvas():
            self._sync_controls(cv.adjust())
        self._refresh_edit_state()

    # ================= 보정 =================
    def _read_controls(self) -> Adjust:
        black = self.s_black.value()
        white = max(self.s_white.value(), black + 5)
        return Adjust(
            brightness=float(self.s_bright.value()),
            contrast=self.s_contrast.value() / 100.0,
            gamma=self.s_gamma.value() / 100.0,
            negative=self.chk_neg.isChecked(),
            channel=_CHANNELS[self.c_channel.currentIndex()],
            saturation=self.s_sat.value() / 100.0,
            r_gain=self.s_r.value() / 100.0,
            g_gain=self.s_g.value() / 100.0,
            b_gain=self.s_b.value() / 100.0,
            black=int(black),
            white=int(white),
            sharpen=self.c_sharpen.currentIndex(),
            denoise=_DENOISE[self.c_denoise.currentIndex()],
            enhance=self.c_enhance.currentIndex(),
        )

    def _control_widgets(self) -> tuple:
        return (self.s_bright, self.s_contrast, self.s_gamma, self.s_sat, self.s_r, self.s_g, self.s_b,
                self.s_black, self.s_white, self.c_channel, self.chk_neg, self.c_denoise, self.c_sharpen,
                self.c_enhance)

    def _sync_controls(self, adj: Adjust) -> None:
        """슬라이더·콤보를 adj 값으로 (시그널 없이) 맞춘다."""
        for w in self._control_widgets():
            w.blockSignals(True)
        self.s_bright.setValue(int(round(adj.brightness)))
        self.s_contrast.setValue(int(round(adj.contrast * 100)))
        self.s_gamma.setValue(int(round(adj.gamma * 100)))
        self.s_sat.setValue(int(round(adj.saturation * 100)))
        self.s_r.setValue(int(round(adj.r_gain * 100)))
        self.s_g.setValue(int(round(adj.g_gain * 100)))
        self.s_b.setValue(int(round(adj.b_gain * 100)))
        self.s_black.setValue(int(adj.black))
        self.s_white.setValue(int(adj.white))
        self.c_channel.setCurrentIndex(_CHANNELS.index(adj.channel))
        self.chk_neg.setChecked(adj.negative)
        self.c_denoise.setCurrentIndex(_DENOISE.index(adj.denoise))
        self.c_sharpen.setCurrentIndex(int(adj.sharpen))
        self.c_enhance.setCurrentIndex(int(adj.enhance))
        for w in self._control_widgets():
            w.blockSignals(False)
        self._adj = adj.copy()
        self._update_value_labels()

    def _update_value_labels(self) -> None:
        for sl, lbl, fmt in getattr(self, "_value_labels", []):
            lbl.setText(fmt(sl.value()))

    def _on_adjust(self, *_) -> None:
        self._adj = self._read_controls()
        self._update_value_labels()
        for cv in self._target_canvases():
            cv.set_adjust(self._adj, record=True)
        self._refresh_edit_state()

    def set_adjust(self, adj: Adjust) -> None:
        self._sync_controls(adj)
        self._on_adjust()

    def adjust(self) -> Adjust:
        return self._adj

    def reset_adjust(self) -> None:
        self.set_adjust(Adjust())

    def auto_contrast(self) -> None:
        """자동 대비: 현재 채널·노이즈 설정 기준 휘도 0.5%~99.5%를 흑·백점으로."""
        cv = self.active_canvas()
        img = cv.image() if cv is not None else None
        if img is None:
            return
        pre = apply_adjust(img, Adjust(channel=self._adj.channel, denoise=self._adj.denoise))
        lo, hi = auto_levels(pre)
        adj = self._adj.copy()
        adj.black, adj.white = lo, hi
        self.set_adjust(adj)

    def _fit_all(self) -> None:
        for cv in self._canvases():
            cv.reset_view()

    def _zoom(self, f: float) -> None:
        if self._mode == "compare":
            self.cmp_left.zoom_by(f)
        elif self._mode == "single":
            self.single_canvas.apply_zoom(f)
        elif self._mode == "live":
            self.live_canvas.apply_zoom(f)

    # ================= 편집 (기하 · 이력) =================
    def rotate(self, k: int) -> None:
        if self._mode == "single":
            self.single_canvas.rotate(k)

    def flip(self, horizontal: bool) -> None:
        if self._mode == "single":
            self.single_canvas.flip(horizontal)

    def undo(self) -> bool:
        cv = self.active_canvas()
        return bool(cv and cv.undo())

    def redo(self) -> bool:
        cv = self.active_canvas()
        return bool(cv and cv.redo())

    def restore_original(self) -> bool:
        cv = self.active_canvas()
        return bool(cv and cv.restore_original())

    def set_px_per_mm(self, value: float) -> None:
        """눈금 보정값(px/mm) 적용·저장. 0이면 해제(px 단위)."""
        value = max(0.0, float(value or 0.0))
        self.config.px_per_mm = value
        try:
            self.config.save()
        except Exception:  # noqa: BLE001
            log.warning("px_per_mm 저장 실패", exc_info=True)
        for cv in self._canvases():
            cv.set_px_per_mm(value)
        self.lbl_calib.setText(f"눈금: 1 mm = {value:.1f} px" if value > 0 else "눈금: 미보정 (px 단위)")
        self.b_calib_clear.setEnabled(value > 0)

    def _refresh_edit_state(self) -> None:
        cv = self.active_canvas()
        has = cv is not None and cv.image() is not None
        edit_mode = self._mode in ("single", "compare")
        self.b_undo.setEnabled(bool(has and edit_mode and cv.can_undo()))
        self.b_redo.setEnabled(bool(has and edit_mode and cv.can_redo()))
        self.b_orig.setEnabled(bool(has and edit_mode and cv.is_modified()))
        for b in (self.b_rot_l, self.b_rot_r, self.b_flip_h, self.b_flip_v):
            b.setEnabled(bool(has and self._mode == "single"))
        self.b_auto.setEnabled(bool(has))
        self._update_hist(cv.image() if has else None)

    def _update_hist(self, img) -> None:
        W, H = self.hist.width(), self.hist.height()
        pm = QPixmap(W, H)
        pm.fill(QColor("#0b1220"))
        if img is not None:
            hh = histogram(img[::4, ::4])
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            peak = max(1, int(np.percentile(hh["lum"], 99.5)))
            path = QPainterPath(QPointF(0, H))
            for i, v in enumerate(hh["lum"]):
                path.lineTo(i * (W - 1) / 255, H - min(1.0, v / peak) * (H - 4))
            path.lineTo(W, H)
            p.fillPath(path, QColor(203, 213, 225, 150))
            for key, col in (("r", "#f87171"), ("g", "#4ade80"), ("b", "#60a5fa")):
                pts = [QPointF(i * (W - 1) / 255, H - min(1.0, v / peak) * (H - 4)) for i, v in enumerate(hh[key])]
                p.setPen(QPen(QColor(col), 1))
                p.drawPolyline(pts)
            p.setPen(QPen(QColor("#facc15"), 1, Qt.PenStyle.DashLine))
            for lv in (self._adj.black, self._adj.white):
                x = lv * (W - 1) / 255
                p.drawLine(QPointF(x, 0), QPointF(x, H))
            p.end()
        self.hist.setPixmap(pm)

    # ================= 주석 · 도구 =================
    def set_tool(self, tool: str) -> None:
        allowed = {t: modes for t, *_x, modes in _TOOLS}
        if tool not in allowed or (self._mode in ("single", "compare", "live")
                                   and self._mode not in allowed[tool] and tool != "pan"):
            tool = "pan"
        for cv in (self.single_canvas, self.cmp_left, self.cmp_right, self.live_canvas):
            cv.set_tool(tool if cv is not self.live_canvas or tool == "magnify" else "pan")
        self.tool_buttons[tool].setChecked(True)
        self._tool = tool

    def clear_annotations(self) -> None:
        for cv in (self.single_canvas, self.cmp_left, self.cmp_right):
            cv.clear_annotations()

    # ================= LIVE =================
    def set_live_frame(self, frame) -> None:
        self._live = frame
        if self._mode == "live" and not self._frozen:
            self.live_canvas.set_image(frame, keep_view=True)

    def _on_capture_toggled(self, on: bool) -> None:
        self._frozen = on
        if on:
            self._frozen_frame = None if self._live is None else self._live.copy()
            if self._frozen_frame is not None:
                self.live_canvas.set_image(self._frozen_frame, keep_view=True)
            self.b_capture.setText(icons.gap("RESUME"))
            self.b_capture.setIcon(_icon("play", "#ffffff"))
        else:
            self._frozen_frame = None
            self.b_capture.setText(icons.gap("CAPTURE"))
            self.b_capture.setIcon(_icon("freeze", ICON_ACCENT))
        self._update_side()

    def current_eye(self) -> str:
        if self.get_eye is not None:
            return self.get_eye()
        return ["NA", "OD", "OS", "OU"][self.c_eye.currentIndex()]

    def _require_patient(self) -> bool:
        if self._patient is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            return False
        return True

    def save_live(self):
        if not self._require_patient():
            return None
        frame = self._frozen_frame if (self._frozen and self._frozen_frame is not None) else self._live
        if frame is None:
            QMessageBox.information(self, "확인", "저장할 영상이 없습니다.")
            return None
        cap = self.service.save_photo(frame, self._patient, eye=self.current_eye())
        self.reload()
        self.savedCapture.emit()
        if self._frozen:
            self.b_capture.setChecked(False)
        return cap

    # ================= 편집 저장 / 코멘트 / 환자 =================
    def save_edited(self) -> list:
        if not self._require_patient():
            return []
        if self._mode == "single" and 0 <= self._idx < len(self._caps):
            targets = [(self.single_canvas, self._caps[self._idx])]
        elif self._mode == "compare":
            targets = [(self.cmp_left, self._pair[0]), (self.cmp_right, self._pair[1])]
        else:
            targets = []
        saved = []
        for cv, src in targets:
            if cv.image() is None or src is None:
                continue
            if not cv.is_modified():
                continue
            kinds = cv.annotation_kinds()
            if any(k in ("length", "angle") for k in kinds):
                note = "측정"
            elif kinds:
                note = "주석"
            elif cv.geometry_changed():
                note = "편집본"
            else:
                note = "보정본"
            saved.append(self.service.save_photo(cv.render_to_bgr(), self._patient,
                                                 eye=src.eye or "NA", note=note))
        if not saved:
            QMessageBox.information(self, "편집본 저장", "보정·편집·주석이 없어 저장할 내용이 없습니다.")
            return []
        self.clear_annotations()
        self.reset_adjust()                       # 저장본엔 보정이 이미 반영됨 → 이중 적용 방지
        self.reload(select_last=(self._mode == "single"))
        self.savedCapture.emit()
        return saved

    def edit_comment(self) -> None:
        if not (self._mode == "single" and 0 <= self._idx < len(self._caps)):
            return
        cap = self._caps[self._idx]
        text, ok = QInputDialog.getText(self, "코멘트", "이 영상의 코멘트:", text=cap.note or "")
        if ok:
            self.set_comment(text)

    def set_comment(self, text: str) -> None:
        if not (0 <= self._idx < len(self._caps)):
            return
        cap = self._caps[self._idx]
        note = (text or "").strip() or None
        self.db.captures.update_note(cap.id, note)
        cap.note = note
        self.multi.set_captures(self._caps, keep_page=True)
        self._show_current()
        self.savedCapture.emit()

    def edit_patient(self) -> None:
        if not self._require_patient():
            return
        dlg = PatientDialog(self, patient=self._patient)
        if not dlg.exec():
            return
        p = dlg.get_patient()
        try:
            self.db.patients.update(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "오류", f"수정 실패: {e}")
            return
        self._patient = p
        self._update_info()
        self.patientUpdated.emit(p)

    # ================= 인쇄 =================
    def print_items(self) -> list:
        if self._mode == "single" and self.single_canvas.image() is not None:
            return [(self.single_canvas.render_to_bgr(), caption_of(self._caps[self._idx]))]
        if self._mode == "compare":
            return [(cv.render_to_bgr(), caption_of(c))
                    for cv, c in ((self.cmp_left, self._pair[0]), (self.cmp_right, self._pair[1]))
                    if cv.image() is not None and c is not None]
        if self._mode == "live" and self.live_canvas.image() is not None:
            return [(self.live_canvas.render_to_bgr(), "LIVE " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))]
        if self._mode == "multi":
            items = []
            for i in (self.multi.selection() or self.multi.page_indices()):
                img = load_bgr(self._caps[i].file_path)
                if img is not None:
                    items.append((apply_adjust(img, self._adj), caption_of(self._caps[i])))
            return items
        return []

    def export_pdf(self, path: str) -> int:
        items = self.print_items()
        if not items:
            return 0
        printer = print_util.make_pdf_printer(path)
        return print_util.render_report(printer, self._patient, items,
                                        clinic=getattr(self.config, "clinic_name", "") or "")

    def _default_pdf_path(self) -> str:
        base = getattr(self.config, "export_root", "") or os.path.expanduser("~")
        chart = (self._patient.chart_no if self._patient else None) or "report"
        return os.path.join(base, f"{chart}_{datetime.now():%Y%m%d_%H%M}.pdf")

    def _pdf_dialog(self) -> None:
        if not self.print_items():
            QMessageBox.information(self, "PDF", "출력할 영상이 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "PDF 보고서 저장", self._default_pdf_path(), "PDF (*.pdf)")
        if path:
            n = self.export_pdf(path)
            QMessageBox.information(self, "PDF", f"{n}쪽 보고서를 저장했습니다.\n{path}")

    def print_current(self) -> None:
        items = self.print_items()
        if not items:
            QMessageBox.information(self, "인쇄", "출력할 영상이 없습니다.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec():
            print_util.render_report(printer, self._patient, items,
                                     clinic=getattr(self.config, "clinic_name", "") or "")
