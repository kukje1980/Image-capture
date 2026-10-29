"""Main window, laid out like the Kowa VK-2 capture screen: patients · thumbnails ·
2D / 3D / multi / compare views, the Command toolbar on the right edge and the
Image Processing toolbar along the bottom (see toolbars.py)."""
from __future__ import annotations

import json
import math
import os
from collections import OrderedDict
from datetime import date
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QCursor, QDesktopServices, QFont, QIcon, QImage, \
    QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QPushButton, QRadioButton, QSlider, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__, autosetup, discpair, imaging, measure
from .. import projection as proj
from ..config import Settings
from ..db import Database
from ..importer import ImportResult, safe_component
from ..models import MODALITY_LABELS
from ..profiles import get_profile
from ..watcher import ImportService
from .dialogs import ImageDialog, PatientDialog, SettingsDialog, source_label
from .disc_pair import DiscPairDialog
from .eye3d import EyeView
from .histogram import HistogramDialog
from .image_view import TOOL_HINTS, TOOLS, ImageView, from_qimage
from .multi_view import MultiView
from .toolbars import CHECKABLE, COMMANDS, MENUS, PROCESSING, SliderPopup, icon_for

UNASSIGNED = -1
SEX_LABEL = {"M": "남", "F": "여", "O": "기타"}
THUMB_TEXT = Qt.ItemDataRole.UserRole + 1    # thumbnail caption without the ② mark
SECOND_PICK = QColor(168, 104, 28)           # background of the second picked photo (②)


class Bridge(QObject):
    """Carries worker-thread callbacks into the GUI thread (queued signals)."""
    result = Signal(object)
    status = Signal(str)
    detected = Signal(object)   # autosetup.detect() result


def age_on(birth: str | None, on: str | None = None) -> int | None:
    try:
        b = date.fromisoformat(birth)
        d = date.fromisoformat(on) if on else date.today()
    except (TypeError, ValueError):
        return None
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db: Database):
        super().__init__()
        self.settings = settings
        self.db = db
        self.bridge = Bridge()
        self.service = ImportService(db, settings, on_result=self.bridge.result.emit,
                                     on_status=self.bridge.status.emit)
        self.bridge.result.connect(self._on_import_result)
        self.bridge.status.connect(self._on_status)
        self.bridge.detected.connect(self._on_detected)
        self.current = None          # images row
        self.compare = None
        self._patient_ref: int | None = None  # UNASSIGNED / patient id / None
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._proc_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._ops: list[str] = []            # processing stack (VK-2 image processing toolbar)
        self._levels: tuple[int, int] = (0, 255)
        self._channel, self._auto, self._invert = "rgb", False, False
        self._history: list[dict] = []       # undo snapshots
        self._multi_lock = False
        self._3d_dirty = True
        self.setWindowTitle(f"{APP_TITLE}  v{__version__}")
        self.resize(1600, 960)
        self.setAcceptDrops(True)
        self._build()
        self.refresh_patients()
        QTimer.singleShot(200, self._startup)

    # =====================================================================
    # layout (VK-2: black image area, Command toolbar on the right edge,
    # Image Processing toolbar along the bottom, green text on the image)
    # =====================================================================
    def _act(self, key: str, label: str, tip: str = "", icon: str | None = None, vk: str = "",
             checkable: bool = False) -> QAction:
        a = QAction(label, self)
        if icon:
            a.setIcon(icon_for(icon))
            a.setIconVisibleInMenu(False)
        vk_txt = f"<br><span style='color:#889'>VK-2: {vk}</span>" if vk and vk != "—" else ""
        a.setToolTip(f"<b>{label}</b><br>{tip}{vk_txt}" if tip else label)
        a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(lambda checked=False, k=key: self._on_action(k, checked if a.isCheckable() else None))
        return a

    def _make_actions(self) -> None:
        self.acts: dict[str, QAction] = {}
        for key, label, tip, ic, vk in COMMANDS:
            self.acts[key] = self._act(key, label, tip, ic, vk, checkable=key in CHECKABLE)
        self._tool_group = QActionGroup(self)
        self._chan_group = QActionGroup(self)
        self._chan_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        for spec in PROCESSING:
            if spec is None:
                continue
            key, label, tip, ic, vk = spec
            checkable = (key in CHECKABLE or key.startswith(("tool:", "chan:", "adj:"))
                         or key in ("op:sharpen", "op:enhance"))   # lit while applied
            a = self._act(key, label, tip, ic, vk, checkable=checkable)
            if key.startswith("tool:"):
                self._tool_group.addAction(a)
            elif key.startswith("chan:"):
                self._chan_group.addAction(a)
            self.acts[key] = a
        self.acts["tool:zoom"].setChecked(True)
        # drop-down entries are plain actions (no check marks in the drop-downs)
        self.menus: dict[str, QMenu] = {}
        for key, items in MENUS.items():
            m = QMenu(self)
            for item in items:
                if item is None:
                    m.addSeparator()
                else:
                    m.addAction(self._act(*item))
            self.menus[key] = m
        self.acts["captions"] = self._act("captions", "화면 글자 표시", "사진 위에 환자·날짜를 녹색 글자로 (VK-2 방식)",
                                          checkable=True)
        self.acts["captions"].setChecked(True)
        self.acts["overlay"] = self._act("overlay", "원·시신경 표시", "검출한 영상 원과 시신경 유두 위치 표시",
                                         checkable=True)
        for key, seq in (("prev", "PgUp"), ("next", "PgDown"), ("undo", "Ctrl+Z"), ("search", "Ctrl+F"),
                         ("print", "Ctrl+P")):
            self.acts[key].setShortcut(QKeySequence(seq))

    def _toolbar(self, name: str, title: str, area, specs, icon_px: int) -> QToolBar:
        tb = QToolBar(title, self)
        tb.setObjectName(name)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(icon_px, icon_px))
        tb.setFloatable(False)
        self.addToolBar(area, tb)
        for spec in specs:
            if spec is None:
                tb.addSeparator()
                continue
            a = self.acts[spec[0]]
            tb.addAction(a)
            if spec[0] in self.menus:
                btn = tb.widgetForAction(a)
                btn.setMenu(self.menus[spec[0]])
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        return tb

    def _build_menus(self) -> None:
        mb = self.menuBar()
        A = self.acts
        m = mb.addMenu("파일(&F)")
        for a in self.menus["import"].actions():
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_watch)
        m.addAction(self.act_follow)
        m.addAction(self.act_log)
        m.addSeparator()
        for a in self.menus["save"].actions():
            m.addAction(a)
        m.addAction(A["discpair"])
        m.addAction(A["print"])
        m.addSeparator()
        m.addAction("원본 폴더 열기", self._open_folder)
        m.addSeparator()
        m.addAction(A["exit"])

        m = mb.addMenu("보기(&V)")
        for i, label in enumerate(("2D 보기", "3D 안구", "다중 보기", "비교")):
            a = m.addAction(label, lambda i=i: self.tabs.setCurrentIndex(i))
            a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
        sub = m.addMenu("다중 보기 장수")
        for a in self.menus["multi"].actions():
            sub.addAction(a)
        m.addSeparator()
        m.addAction(A["list"])
        self.act_thumbs = m.addAction("사진 목록 (썸네일)")
        self.act_thumbs.setCheckable(True)
        self.act_thumbs.setChecked(True)
        m.addAction(self.tb_cmd.toggleViewAction())
        m.addAction(self.tb_proc.toggleViewAction())
        m.addSeparator()
        m.addAction(A["captions"])
        m.addAction(A["overlay"])
        m.addSeparator()
        for a in self.menus["fit"].actions():
            m.addAction(a)
        m.addAction("툴바 기본 위치로", self._reset_toolbars)

        m = mb.addMenu("영상 처리(&I)")
        for spec in PROCESSING:
            if spec is None:
                m.addSeparator()
                continue
            key, label = spec[0], spec[1]
            if key in self.menus:
                sub = m.addMenu(label)
                for a in self.menus[key].actions():
                    sub.addAction(a)
            else:
                m.addAction(A[key])
        m.addSeparator()
        m.addAction(self._act("chan:rgb", "컬러 (필터 해제)"))
        m.addAction(self._act("adj_reset", "감마·대비·밝기 초기화"))

        m = mb.addMenu("환자(&P)")
        m.addAction(A["search"])
        m.addAction(A["edit"])
        m.addAction("환자 정보 수정…", self._edit_patient)
        m.addAction("환자 삭제 (영상은 미분류로)…", self._delete_patient)

        m = mb.addMenu("설정(&S)")
        m.addAction(A["settings"])

        m = mb.addMenu("도움말(&H)")
        m.addAction("마우스·단축키", self._show_help)
        m.addAction("프로그램 정보", lambda: QMessageBox.about(
            self, APP_TITLE, f"<b>{APP_TITLE}</b><br>버전 {__version__}<br><br>"
            "SYSEYE RetiCam 3100 Plus 등 안저 카메라 사진을 자동으로 가져와 보는 뷰어입니다."))

    def _build(self) -> None:
        self.act_watch = QAction("폴더 감시 (자동 가져오기)", self, checkable=True)
        self.act_watch.toggled.connect(self._toggle_watch)
        self.act_follow = QAction("새 영상 자동 표시", self, checkable=True)
        self.act_follow.setChecked(True)
        self.act_follow.setToolTip("새 사진이 들어오면 그 환자와 사진을 바로 엽니다")
        self.act_log = QAction("가져오기 기록", self, checkable=True)
        self._make_actions()

        # -- left: patients (VK-2 OPEN LIST) -----------------------------------
        self.left = QWidget()
        ll = QVBoxLayout(self.left)
        ll.setContentsMargins(6, 6, 0, 6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("환자 ID · 이름 · 생년월일 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._search_timer.start(200))
        self._search_timer = QTimer(self, singleShot=True, timeout=self.refresh_patients)
        ll.addWidget(self.search)
        self.patients = QTableWidget(0, 6)
        self.patients.setHorizontalHeaderLabels(["환자 ID", "이름", "생년월일", "성별", "영상", "최근 검사"])
        self.patients.verticalHeader().setVisible(False)
        self.patients.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.patients.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.patients.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.patients.horizontalHeader()
        for col in range(6):  # long ids (RetiCam PID2026…-…) must not squeeze the name
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setStretchLastSection(True)
        self.patients.itemSelectionChanged.connect(self._on_patient_selected)
        self.patients.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.patients.customContextMenuRequested.connect(self._patient_menu)
        self.patients.doubleClicked.connect(lambda _: self._edit_patient())
        ll.addWidget(self.patients)

        # -- centre: patient line + thumbnails + views ------------------------------
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(4, 6, 4, 0)
        cl.setSpacing(4)
        top = QHBoxLayout()
        self.banner = QLabel("환자를 선택하세요")
        self.banner.setObjectName("banner")
        top.addWidget(self.banner, 1)
        self.f_date = QComboBox()
        self.f_date.setMinimumWidth(110)
        self.f_date.currentIndexChanged.connect(self._fill_thumbs)
        self.f_eye = QComboBox()
        for k, v in (("", "양안"), ("OD", "OD (우안)"), ("OS", "OS (좌안)")):
            self.f_eye.addItem(v, k)
        self.f_eye.currentIndexChanged.connect(self._fill_thumbs)
        self.f_mod = QComboBox()
        self.f_mod.addItem("전체 종류", "")
        for k, v in MODALITY_LABELS.items():
            self.f_mod.addItem(v, k)
        self.f_mod.currentIndexChanged.connect(self._fill_thumbs)
        for w, tip in ((self.f_date, "검사일"), (self.f_eye, "눈"), (self.f_mod, "촬영 종류")):
            w.setToolTip(tip)
            top.addWidget(w)
        cl.addLayout(top)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setFlow(QListWidget.Flow.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(120, 120))
        self.thumbs.setGridSize(QSize(140, 164))
        self.thumbs.setFixedHeight(182)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thumbs.setToolTip("Ctrl+클릭: 두 번째 사진(②) 선택/해제 — 비교 · 디스크 2장 · "
                               "오른쪽 클릭: 환자 지정·다시 분석")
        self.thumbs.viewport().installEventFilter(self)
        self.thumbs.currentItemChanged.connect(lambda cur, _: cur and self._show_image(cur.data(Qt.ItemDataRole.UserRole)))
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        cl.addWidget(self.thumbs)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.view2d = ImageView()
        self.view2d.toggle_captions(True)
        self.view2d.discPicked.connect(self._on_disc_picked)
        self.view2d.measured.connect(self._on_measured)
        self.view2d.hovered.connect(lambda t: self.lbl_hover.setText(t))
        self.view2d.clicked.connect(self._stop_slideshow)
        self.tabs.addTab(self.view2d, "2D 보기")
        self.tabs.addTab(self._build_3d(), "3D 안구")
        self.multi = MultiView()
        self.multi.selected.connect(self._select_from_multi)
        self.multi.opened.connect(lambda iid: (self._select_from_multi(iid), self.tabs.setCurrentIndex(0)))
        self.multi.layoutChanged.connect(lambda _: self._fill_multi())
        self.tabs.addTab(self.multi, "다중 보기")
        cmp_w = QWidget()
        cmp_l = QVBoxLayout(cmp_w)
        cmp_l.setContentsMargins(0, 0, 0, 0)
        self.cmp_labels = (QLabel(), QLabel())
        lab_row = QHBoxLayout()
        for lab in self.cmp_labels:
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab_row.addWidget(lab)
        cmp_l.addLayout(lab_row)
        cmp_split = QSplitter(Qt.Orientation.Horizontal)
        self.cmp_views = (ImageView(), ImageView())
        for v in self.cmp_views:
            cmp_split.addWidget(v)
        cmp_l.addWidget(cmp_split, 1)
        self.cmp_sync = QCheckBox("확대·이동 동기화")
        self.cmp_sync.setChecked(True)
        cmp_row = QHBoxLayout()
        cmp_row.addWidget(self.cmp_sync)
        cmp_row.addStretch()
        b_pair = QPushButton("디스크 2장 (보험 청구용)…")
        b_pair.setToolTip("이 두 사진의 시신경 유두만 확대해 한 장으로 만듭니다")
        b_pair.clicked.connect(lambda: self._on_action("discpair"))
        cmp_row.addWidget(b_pair)
        cmp_l.addLayout(cmp_row)
        a, b = self.cmp_views
        for src, dst in ((a, b), (b, a)):
            src.horizontalScrollBar().valueChanged.connect(
                lambda val, d=dst: self.cmp_sync.isChecked() and d.horizontalScrollBar().setValue(val))
            src.verticalScrollBar().valueChanged.connect(
                lambda val, d=dst: self.cmp_sync.isChecked() and d.verticalScrollBar().setValue(val))
            src.zoomChanged.connect(lambda f, s=src, d=dst: self.cmp_sync.isChecked()
                                    and abs(d.zoom - f) > 1e-9 and d.sync_from(s))
        self.tabs.addTab(cmp_w, "비교")
        self.tabs.currentChanged.connect(self._on_tab)
        cl.addWidget(self.tabs, 1)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.left)
        self.split.addWidget(centre)
        self.split.setSizes([400, 1000])
        self.split.setStretchFactor(1, 1)
        self.setCentralWidget(self.split)

        # -- VK-2 toolbars ---------------------------------------------------------------
        self.tb_cmd = self._toolbar("cmdbar", "명령 툴바", Qt.ToolBarArea.RightToolBarArea, COMMANDS, 26)
        self.tb_proc = self._toolbar("procbar", "영상 처리 툴바", Qt.ToolBarArea.BottomToolBarArea, PROCESSING, 28)
        self.tb_proc.visibilityChanged.connect(lambda v: self.acts["tools"].setChecked(v))
        self.acts["tools"].setChecked(True)
        self.acts["list"].setChecked(True)
        self.pop_gamma = SliderPopup("감마", 20, 400, 100, lambda v: f"{v / 100:.2f}", self)
        self.pop_contrast = SliderPopup("대비", 10, 300, 100, lambda v: f"{v}%", self)
        self.pop_bright = SliderPopup("밝기", -100, 100, 0, lambda v: f"{v:+d}", self)
        self.s_gamma, self.s_contrast, self.s_bright = (
            p.slider for p in (self.pop_gamma, self.pop_contrast, self.pop_bright))
        for p in (self.pop_gamma, self.pop_contrast, self.pop_bright):
            p.slider.valueChanged.connect(self._schedule_adjust)
            p.pressed.connect(self._push_history)
        self._build_menus()
        self.act_thumbs.toggled.connect(self.thumbs.setVisible)
        self.acts["captions"].toggled.connect(self.view2d.toggle_captions)
        self.acts["overlay"].toggled.connect(self.view2d.toggle_overlays)

        # -- log dock -------------------------------------------------------------
        self.log = QTableWidget(0, 4)
        self.log.setHorizontalHeaderLabels(["시각", "구분", "내용", "파일"])
        self.log.verticalHeader().setVisible(False)
        self.log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.log.doubleClicked.connect(self._open_log_path)
        dock = QDockWidget("가져오기 기록", self)
        dock.setWidget(self.log)
        dock.setObjectName("log")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        dock.hide()
        self.act_log.toggled.connect(dock.setVisible)
        dock.visibilityChanged.connect(lambda v: (self.act_log.setChecked(v), v and self._fill_log()))

        # -- status bar (VK-2: Image Info | Patient ID | Name | messages) ---------------
        sb = QStatusBar()
        self.lbl_watch = QLabel("감시 꺼짐")
        self.lbl_info = QLabel("")
        self.lbl_info.setObjectName("imageInfo")
        self.lbl_status = QLabel("")
        self.lbl_measure = QLabel("")
        self.lbl_measure.setObjectName("measure")
        self.lbl_measure.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_measure.hide()
        self.lbl_hover = QLabel("")
        self.lbl_hover.setStyleSheet("color:#556")
        sb.addWidget(self.lbl_watch)
        sb.addWidget(self.lbl_info)
        sb.addWidget(self.lbl_status, 1)
        sb.addPermanentWidget(self.lbl_measure)
        sb.addPermanentWidget(self.lbl_hover)
        # current 2D magnification; its menu = 화면 맞춤 ▾ (zoom steps, wide-field regions)
        self.btn_zoom = QToolButton()
        self.btn_zoom.setText("배율 맞춤")
        self.btn_zoom.setToolTip("2D 배율 — 눌러서 배율이나 확대 위치(후극부·주변부) 고르기 · +/−/0/1 키")
        self.btn_zoom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_zoom.setAutoRaise(True)
        self.btn_zoom.setMenu(self.menus["fit"])
        self.view2d.zoomChanged.connect(self._show_zoom)
        sb.addPermanentWidget(self.btn_zoom)
        self.setStatusBar(sb)

        a = QAction(self)
        a.setShortcut(QKeySequence("Ctrl+C"))
        a.triggered.connect(lambda: self._on_action("copy"))
        self.addAction(a)
        self._slide_timer = QTimer(self, interval=2000, timeout=lambda: self._step(1, wrap=True))
        self._adjust_timer = QTimer(self, singleShot=True, timeout=self._apply_adjust)
        self._results: list[ImportResult] = []
        self._result_timer = QTimer(self, singleShot=True, timeout=self._flush_results)

    def _build_3d(self) -> QWidget:
        """3D tab: a compact control bar over the eye model (formerly the right panel)."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("bar3d")
        g = QGridLayout(bar)
        g.setContentsMargins(8, 4, 8, 4)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(2)
        # 간단히 (the light original) / 자세히 (anatomical model), remembered in the settings
        self.b_simple = QPushButton("간단히")
        self.b_detailed = QPushButton("자세히")
        self.b_simple.setToolTip("가볍고 빠른 기본 안구 모형 — 사진을 보는 데 집중")
        self.b_detailed.setToolTip("실제 해부 구조: 공막 혈관, 굴절하는 각막·홍채, 안구벽 단면, 섬모체·수정체, 외안근")
        self._detail_group = QButtonGroup(self)
        for b in (self.b_simple, self.b_detailed):
            b.setCheckable(True)
            b.setObjectName("detail3d")
            self._detail_group.addButton(b)
        self.b_simple.clicked.connect(lambda: self._set_3d_detail("simple"))
        self.b_detailed.clicked.connect(lambda: self._set_3d_detail("detailed"))
        self.r_out = QRadioButton("외부 (안구 모형)")
        self.r_in = QRadioButton("내부 (망막 시점)")
        self.r_out.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_out)
        grp.addButton(self.r_in)
        self.r_out.toggled.connect(self._on_3d_mode)
        self.s_cut = QSlider(Qt.Orientation.Horizontal)
        self.s_cut.setRange(-30, 100)
        self.s_cut.setValue(25)
        self.s_cut.setFixedWidth(120)
        self.s_cut.valueChanged.connect(self._on_cut)
        self.sp_fov = QDoubleSpinBox()
        self.sp_fov.setRange(10, 240)
        self.sp_fov.setDecimals(1)
        self.sp_fov.setSuffix("°")
        self.sp_fov.valueChanged.connect(self._on_mapping)
        self.c_fovtype = QComboBox()
        self.c_fovtype.addItem("안구 중심각", "internal")
        self.c_fovtype.addItem("외부각(동공)", "external")
        self.c_fovtype.currentIndexChanged.connect(self._on_mapping)
        self.c_proj = QComboBox()
        for k in proj.PROJECTIONS:
            self.c_proj.addItem(proj.PROJECTION_LABELS[k], k)
        self.c_proj.currentIndexChanged.connect(self._on_mapping)
        self.sp_roll = QDoubleSpinBox()
        self.sp_roll.setRange(-180, 180)
        self.sp_roll.setSuffix("°")
        self.sp_roll.valueChanged.connect(self._on_mapping)
        row1 = QHBoxLayout()
        for item in (self.b_simple, self.b_detailed, QLabel("  "), self.r_out, self.r_in, QLabel("  앞쪽 절개"),
                     self.s_cut, QLabel("  화각"), self.sp_fov,
                     self.c_fovtype, QLabel("  투영"), self.c_proj, QLabel("  회전"), self.sp_roll):
            row1.addWidget(item)
        row1.addStretch()
        self.c_nerve = QCheckBox("시신경")
        self.c_nerve.setChecked(True)
        self.c_nerve.toggled.connect(lambda on: (setattr(self.eye3d, "show_nerve", on), self.eye3d.update()))
        self.c_muscle = QCheckBox("외안근")
        self.c_muscle.setToolTip("네 곧은근과 두 빗근의 부착부(절단면)를 함께 표시")
        self.c_muscle.toggled.connect(lambda on: (setattr(self.eye3d, "show_muscles", on), self.eye3d.update()))
        self.c_grid = QCheckBox("각도 격자(10°)")
        self.c_grid.toggled.connect(lambda on: (setattr(self.eye3d, "show_grid", on), self.eye3d.update()))
        self.c_adj3d = QCheckBox("영상 처리 적용")
        self.c_adj3d.setChecked(True)
        self.c_adj3d.toggled.connect(lambda _: self._mark_3d_dirty())
        row2 = QHBoxLayout()
        for c in (self.c_nerve, self.c_muscle, self.c_grid, self.c_adj3d):
            row2.addWidget(c)
        self.eye3d = EyeView()
        self.eye3d.setToolTip("드래그: 회전 · 휠: 커서 쪽으로 확대 · 오른쪽 드래그: 확대 · "
                              "가운데/Shift+드래그: 이동 · +/−: 확대·축소 · 더블클릭·0: 처음 보기")
        self.lbl_zoom3d = QLabel("배율 ×1.0")
        self.lbl_zoom3d.setObjectName("hint3d")
        self.lbl_zoom3d.setToolTip("처음 보기 대비 확대 배율 · 더블클릭 또는 0: 처음 보기")
        self.eye3d.zoomChanged.connect(lambda m: self.lbl_zoom3d.setText(f"배율 ×{m:.1f}"))
        self.eye3d.glError.connect(lambda m: QMessageBox.warning(
            self, "3D", m + "\n\n설정 > 일반 > 3D 렌더링을 '소프트웨어 렌더링'으로 바꾸고 다시 시작해 보세요."))
        for label, fn in (("정면 보기", self.eye3d.front_view), ("시점 초기화", self.eye3d.reset_view),
                          ("화각·투영 저장", self._save_mapping), ("화면 저장…", self._save_3d)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row2.addWidget(b)
        self.lbl_3d = QLabel("")
        self.lbl_3d.setObjectName("hint3d")
        row2.addWidget(self.lbl_zoom3d)
        row2.addWidget(self.lbl_3d, 1)
        self._set_3d_detail(self.settings.view3d_detail, save=False)
        g.addLayout(row1, 0, 0)
        g.addLayout(row2, 1, 0)
        lay.addWidget(bar)
        lay.addWidget(self.eye3d, 1)
        return w

    def _reset_toolbars(self) -> None:
        for tb, area in ((self.tb_cmd, Qt.ToolBarArea.RightToolBarArea),
                         (self.tb_proc, Qt.ToolBarArea.BottomToolBarArea)):
            self.addToolBar(area, tb)
            tb.show()

    def _show_help(self) -> None:
        QMessageBox.information(self, "마우스·단축키", (
            "<b>사진 보기</b><br>"
            "위/아래 드래그: 확대·축소 (위로 끌면 확대, 아래로 끌면 축소, 누른 곳 중심)<br>"
            "휠: 커서 위치 확대·축소 · 오른쪽 버튼 드래그: 어떤 도구에서든 확대·축소<br>"
            "+/−: 확대·축소 · 0: 화면 맞춤 · 1: 100%<br>"
            "확대하면 오른쪽 위 미니맵에 전체 사진과 보이는 곳이 나옵니다 — 눌러서 이동<br>"
            "화면 맞춤 ▾ 또는 아래쪽 [배율]: 400·800%, 후극부·위/아래/코/귀쪽 주변부로 바로 확대<br>"
            "가운데 버튼 드래그(이동 도구는 왼쪽 드래그): 이동 · 더블클릭: 화면 맞춤<br>"
            "오른쪽 클릭: 메뉴 (시신경 위치 지정, 돋보기 배율, 미니맵)<br><br>"
            "<b>3D 안구</b><br>"
            "간단히 / 자세히: 가벼운 기본 모형 / 실제 해부 구조<br>"
            "드래그: 회전 · 휠: 커서가 가리키는 곳으로 확대 · 가운데 버튼 또는 Shift+드래그: 이동<br>"
            "+/−: 확대·축소 · 더블클릭 또는 0: 처음 보기<br><br>"
            "<b>단축키</b><br>"
            "PageUp / PageDown: 이전 / 다음 사진 · Ctrl+1~4: 2D / 3D / 다중 / 비교<br>"
            "Ctrl+Z: 처리 실행 취소 · Delete: 마지막 측정 지우기 · Ctrl+C: 화면 복사<br>"
            "Ctrl+F: 환자 검색 · Ctrl+P: 인쇄<br><br>"
            "<b>두 사진 고르기 · 디스크 2장</b><br>"
            "사진을 클릭하고 두 번째 사진을 Ctrl+클릭(②, 다시 Ctrl+클릭하면 해제) → 비교 탭<br>"
            "[디스크 2장]: 두 사진의 시신경 유두만 확대해 한 장으로 (OD 왼쪽 · OS 오른쪽, 보험 청구용)<br><br>"
            "<b>사진 가져오기</b><br>"
            "자동입니다. 레티캠 등 장비 폴더와 [문서\\안저사진 가져오기] 폴더를 감시해 "
            "새 사진의 환자 ID·이름을 읽고 환자별로 정리합니다."))

    # =====================================================================
    # startup / watching
    # =====================================================================
    def _startup(self) -> None:
        # Automatic import: the inbox + the capture software's folders. Drive
        # probing can block on a disconnected network drive -> worker thread.
        import threading
        auto = self.settings.auto_detect
        threading.Thread(target=lambda: self.bridge.detected.emit(autosetup.detect() if auto else []),
                         name="fundus-autosetup", daemon=True).start()
        if self.settings.last_patient:
            self._select_patient_id(self.settings.last_patient)

    def _on_detected(self, found) -> None:
        added = autosetup.apply(self.settings, found)
        if added:
            try:
                self.settings.save()
            except OSError:
                pass
            names = ", ".join(f.path for f in added)
            self.lbl_status.setText(f"자동으로 감시 폴더 추가: {names}")
            self.db.log("info", f"감시 폴더 자동 추가: {names}")
        if self.settings.watch_folders and self.settings.watch_on_startup:
            if self.act_watch.isChecked():
                self._toggle_watch(True)   # restart with the new folders
            else:
                self.act_watch.setChecked(True)

    def _toggle_watch(self, on: bool) -> None:
        if on:
            errors = self.service.start_watching()
            folders = [f.path for f in self.settings.watch_folders if f.enabled]
            self.lbl_watch.setText(f"● 자동 가져오기 ({len(folders)}개 폴더)")
            self.lbl_watch.setToolTip("감시 중인 폴더:\n" + "\n".join(folders))
            self.lbl_watch.setStyleSheet("color:#1d7a46; font-weight:600")
            if errors:
                QMessageBox.warning(self, "폴더 감시", "\n".join(errors))
        else:
            self.service.stop_watching()
            self.lbl_watch.setText("자동 가져오기 꺼짐")
            self.lbl_watch.setToolTip("파일 > 폴더 감시 로 다시 켭니다")
            self.lbl_watch.setStyleSheet("color:#a33")

    def _scan_now(self) -> None:
        import threading
        threading.Thread(target=lambda: self.bridge.status.emit(
            f"검사 완료 — 새 파일 {self.service.scan_all(full=True)}개"), daemon=True).start()

    def _import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "가져올 사진 파일", "", "영상 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.dcm);;모든 파일 (*)")
        if files:
            n = self.service.import_paths(files, force=True)
            self.lbl_status.setText(f"{n}개 파일 가져오기 대기")

    def _import_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "가져올 폴더")
        if d:
            n = self.service.import_paths([d])
            self.lbl_status.setText(f"{n}개 파일 가져오기 대기")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        n = self.service.import_paths(paths, force=True)
        self.lbl_status.setText(f"{n}개 파일 가져오기 대기")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            old_lib = str(self.settings.library)
            before = list(self.settings.watch_folders)
            dlg.apply()
            autosetup.remember_removed(self.settings, before)
            if dlg.redetect:
                autosetup.apply(self.settings, autosetup.detect())
            self.settings.save()
            if str(self.settings.library) != old_lib:
                QMessageBox.information(self, "설정", "라이브러리 폴더 변경은 프로그램을 다시 시작하면 적용됩니다.")
            if self.settings.watch_folders:   # importing is automatic: (re)start watching
                if self.act_watch.isChecked():
                    self._toggle_watch(True)
                else:
                    self.act_watch.setChecked(True)

    def _on_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def _on_import_result(self, res: ImportResult) -> None:
        # Coalesce: a first scan can deliver thousands of results.
        self._results.append(res)
        if not self._result_timer.isActive():
            self._result_timer.start(300)

    def _flush_results(self) -> None:
        results, self._results = self._results, []
        imported = [r for r in results if r.status == "imported"]
        errors = [r for r in results if r.status == "error"]
        if imported:
            more = f" 외 {len(imported) - 1}건" if len(imported) > 1 else ""
            self.lbl_status.setText(f"새 영상: {imported[-1].message}  ({Path(imported[-1].path).name}){more}")
        elif errors:
            self.lbl_status.setText(f"오류: {Path(errors[-1].path).name} — {errors[-1].message}")
        self.refresh_patients(keep=True)
        if self.log.isVisible():
            self._fill_log()
        if not imported:
            return
        last = imported[-1]
        target = last.patient_ref if last.patient_ref is not None else UNASSIGNED
        # Follow only live captures, not a bulk import of an existing archive.
        live = self.service.queued <= 2 and len(imported) <= 4
        if self.act_follow.isChecked() and live:
            self._select_patient_ref(target)
            self._fill_thumbs(select_id=last.image_id)
        elif any((r.patient_ref if r.patient_ref is not None else UNASSIGNED) == self._patient_ref
                 for r in imported):
            self._fill_dates()
            self._fill_thumbs(select_id=self.current["id"] if self.current else None)

    # =====================================================================
    # patients
    # =====================================================================
    def refresh_patients(self, keep: bool = False) -> None:
        sel = self._patient_ref if keep else None
        rows = self.db.list_patients(self.search.text().strip())
        n_un = self.db.count_unassigned()
        self.patients.blockSignals(True)
        self.patients.setRowCount(0)
        entries = []
        if n_un:
            entries.append((UNASSIGNED, ["★ 미분류", "환자 ID 없음", "", "", str(n_un), ""]))
        for r in rows:
            entries.append((r["id"], [r["patient_id"], r["name"] or "", r["birth_date"] or "",
                                      SEX_LABEL.get(r["sex"] or "", ""), str(r["n_images"]), r["last_exam"] or ""]))
        for ref, cols in entries:
            i = self.patients.rowCount()
            self.patients.insertRow(i)
            for j, text in enumerate(cols):
                it = QTableWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, ref)
                if ref == UNASSIGNED:
                    it.setForeground(Qt.GlobalColor.darkRed)
                self.patients.setItem(i, j, it)
        self.patients.resizeColumnToContents(0)
        self.patients.blockSignals(False)
        if sel is not None:
            self._select_patient_ref(sel, quiet=True)

    def _row_ref(self, row: int):
        it = self.patients.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _select_patient_ref(self, ref, quiet: bool = False) -> None:
        """Select the row of ``ref``; ``quiet`` only restores the highlight."""
        for r in range(self.patients.rowCount()):
            if self._row_ref(r) == ref:
                self.patients.blockSignals(True)
                self.patients.selectRow(r)
                self.patients.blockSignals(False)
                if not quiet:
                    self._on_patient_selected()
                return

    def _select_patient_id(self, pid: str) -> None:
        row = self.db.find_patient(pid)
        if row is not None:
            self._select_patient_ref(row["id"])

    def _on_patient_selected(self) -> None:
        rows = self.patients.selectionModel().selectedRows()
        if not rows:
            return
        ref = self._row_ref(rows[0].row())
        if ref != self._patient_ref:
            self.compare = None          # the second pick belongs to the previous patient
        self._patient_ref = ref
        if ref == UNASSIGNED:
            self.banner.setText("미분류 영상 — 사진을 선택하고 오른쪽 [정보 수정] 버튼으로 환자를 지정하세요")
        else:
            p = self.db.get_patient(ref)
            if p is None:
                return
            self.settings.last_patient = p["patient_id"]
            age = age_on(p["birth_date"])
            bits = [f"<b style='font-size:16px'>{p['name'] or '(이름 없음)'}</b>", p["patient_id"]]
            if p["birth_date"]:
                bits.append(f"{p['birth_date']}" + (f" ({age}세)" if age is not None else ""))
            if p["sex"]:
                bits.append(SEX_LABEL.get(p["sex"], p["sex"]))
            self.banner.setText("  ·  ".join(bits))
        self._fill_dates()
        self._fill_thumbs()

    def _patient_menu(self, pos) -> None:
        row = self.patients.rowAt(pos.y())
        ref = self._row_ref(row) if row >= 0 else None
        if ref in (None, UNASSIGNED):
            return
        menu = QMenu(self)
        menu.addAction("환자 정보 수정…", self._edit_patient)
        menu.addAction("환자 삭제 (영상은 미분류로)…", self._delete_patient)
        menu.exec(self.patients.viewport().mapToGlobal(pos))

    def _edit_patient(self) -> None:
        if self._patient_ref in (None, UNASSIGNED):
            return
        p = self.db.get_patient(self._patient_ref)
        dlg = PatientDialog(self.db, p, self)
        if dlg.exec():
            target = dlg.merged_into or self._patient_ref
            self.refresh_patients()
            self._select_patient_ref(target)

    def _delete_patient(self) -> None:
        p = self.db.get_patient(self._patient_ref)
        if p is None:
            return
        ok = QMessageBox.question(self, "환자 삭제",
                                  f"{p['patient_id']} {p['name'] or ''} 환자를 삭제할까요?\n"
                                  "영상은 지워지지 않고 '미분류'로 옮겨집니다.")
        if ok == QMessageBox.StandardButton.Yes:
            self.db.delete_patient(p["id"])
            self.refresh_patients()

    # =====================================================================
    # thumbnails
    # =====================================================================
    def _images(self):
        if self._patient_ref is None:
            return []
        return self.db.images_for_patient(None if self._patient_ref == UNASSIGNED else self._patient_ref)

    def _fill_dates(self) -> None:
        self.f_date.blockSignals(True)
        self.f_date.clear()
        self.f_date.addItem("전체", "")
        for d in sorted({r["exam_date"] for r in self._images() if r["exam_date"]}, reverse=True):
            self.f_date.addItem(d, d)
        self.f_date.blockSignals(False)

    def _fill_thumbs(self, *_, select_id: int | None = None) -> None:
        if select_id is not None and self.f_date.findData(
                (self.db.get_image(select_id) or {"exam_date": ""})["exam_date"] or "") < 0:
            self._fill_dates()
        d, eye = self.f_date.currentData() or "", self.f_eye.currentData() or ""
        mod = self.f_mod.currentData() or ""
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        first = None
        target = None
        for r in self._images():
            if (d and r["exam_date"] != d) or (eye and r["laterality"] != eye) or (mod and r["modality"] != mod):
                if r["id"] != select_id:
                    continue
            mod_label = MODALITY_LABELS.get(r["modality"] or "", r["modality"] or "")
            fov = f"{r['fov_deg']:g}°" if r["fov_deg"] else ""
            text = f"{r['exam_date'] or '날짜 없음'}  {r['laterality'] or ''}\n{mod_label} {fov}".strip()
            it = QListWidgetItem(QIcon(QPixmap(r["thumb_path"] or "")), text)
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            it.setData(THUMB_TEXT, text)
            it.setToolTip(f"{r['exam_date'] or ''} {r['exam_time'] or ''}\n{r['device'] or ''}\n"
                          f"{Path(r['original_path'] or r['file_path']).name}")
            self.thumbs.addItem(it)
            first = first or it
            if r["id"] == select_id:
                target = it
        self.thumbs.blockSignals(False)
        pick = target or first
        if pick:
            self.thumbs.setCurrentItem(pick)  # -> currentItemChanged -> _show_image
            self.thumbs.scrollToItem(pick)
        else:
            self._show_image(None)
        self._mark_pair()

    def eventFilter(self, obj, e):
        # Ctrl+click on a thumbnail picks the second photo (②) and leaves the shown one alone
        if (e.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                         QEvent.Type.MouseButtonDblClick)
                and obj is self.thumbs.viewport()
                and e.button() == Qt.MouseButton.LeftButton
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            item = self.thumbs.itemAt(e.position().toPoint())
            if e.type() == QEvent.Type.MouseButtonPress and item is not None:
                self._pick_second(item.data(Qt.ItemDataRole.UserRole))
            return True
        return super().eventFilter(obj, e)

    def _pick_second(self, image_id: int) -> None:
        """Ctrl+click: toggle ``image_id`` as the second photo next to the shown one."""
        if self.current is None or image_id == self.current["id"]:
            return
        if self.compare is not None and self.compare["id"] == image_id:
            self.compare = None
            self._mark_pair()
            self.lbl_status.setText("두 번째 사진 선택을 해제했습니다")
            if self.tabs.currentIndex() == 3:
                self._fill_compare()
            return
        self._set_compare(image_id)

    def _mark_pair(self) -> None:
        """Show the second picked photo in the strip: ② and an amber background."""
        cid = self.compare["id"] if self.compare is not None else None
        for i in range(self.thumbs.count()):
            it = self.thumbs.item(i)
            second = cid is not None and it.data(Qt.ItemDataRole.UserRole) == cid
            base = it.data(THUMB_TEXT) or it.text()
            it.setText(f"② {base}" if second else base)
            it.setData(Qt.ItemDataRole.BackgroundRole, QBrush(SECOND_PICK) if second else None)

    def _thumb_menu(self, pos) -> None:
        item = self.thumbs.itemAt(pos)
        if not item:
            return
        iid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("환자 지정/정보 수정…", lambda: (self._show_image(iid), self._edit_image()))
        cur = self.current["id"] if self.current else None
        if iid != cur:
            menu.addAction("비교 대상으로 (오른쪽)", lambda: self._set_compare(iid))
            menu.addAction("디스크 2장 (보고 있는 사진과)…", lambda: self._disc_pair(iid))
        elif self.compare is not None:
            menu.addAction("디스크 2장 (② 사진과)…", lambda: self._disc_pair())
            menu.addAction("두 번째 사진(②) 선택 해제", lambda: self._pick_second(self.compare["id"]))
        menu.addAction("원본 폴더 열기", lambda: (self._show_image(iid), self._open_folder()))
        menu.addSeparator()
        menu.addAction("다시 분석 (원·시신경 검출)", lambda: self._reanalyse(iid))
        menu.addAction("목록에서 제거…", lambda: self._remove_image(iid))
        menu.exec(self.thumbs.viewport().mapToGlobal(pos))

    # =====================================================================
    # image display
    # =====================================================================
    def _load(self, row) -> np.ndarray | None:
        if row["id"] in self._cache:
            self._cache.move_to_end(row["id"])
            return self._cache[row["id"]]
        path = row["display_path"] or row["file_path"]
        if not path or not os.path.exists(path):
            alt = row["original_path"]
            path = alt if alt and os.path.exists(alt) else None
        if path is None:
            return None
        try:
            rgb = imaging.load_rgb(path)
        except Exception as exc:
            self.lbl_status.setText(f"영상을 열 수 없음: {exc}")
            return None
        self._cache[row["id"]] = rgb
        while len(self._cache) > 6:
            self._cache.popitem(last=False)
        return rgb

    def _show_image(self, image_id: int | None) -> None:
        row = self.db.get_image(image_id) if image_id is not None else None
        prev, self.current = self.current, row
        if row is not None and self.compare is not None and self.compare["id"] == row["id"]:
            # clicked the ② photo: it is shown now, the one shown before becomes ②
            self.compare = prev if prev is not None and prev["id"] != row["id"] else None
            self._mark_pair()
        if row is None:
            self.view2d.set_rgb(None)
            self.view2d.set_captions()
            self.eye3d.set_image(None)
            self.lbl_info.setText("")
            self.lbl_info.setToolTip("")
            return
        if self._load(row) is None:
            self.view2d.set_rgb(None)
            self.view2d.set_captions()
            self.lbl_info.setText("<span style='color:#b33'>파일을 찾을 수 없음</span>")
            return
        # processing steps (sharpen, enhance ...) belong to the photo on screen
        self._ops, self._levels, self._history = [], (0, 255), []
        self.view2d.set_rgb(self._display_rgb(row))
        self._sync_palette()
        circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else None
        disc = (row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None
        self.view2d.set_overlays(circle, disc)
        self._fill_info(row)
        self._load_mapping(row)
        self._mark_3d_dirty()
        if self.tabs.currentIndex() == 2 and not self._multi_lock:
            self._fill_multi()

    def _fill_info(self, row) -> None:
        meta = json.loads(row["meta_json"] or "{}")
        src = meta.get("sources", {})

        def with_src(text, *fields):
            s = next((source_label(src.get(f)) for f in fields if src.get(f)), "")
            return f"{text}  <span style='color:#99a'>({s})</span>" if s and text and text != "-" else (text or "-")

        p = self.db.get_patient(row["patient_ref"]) if row["patient_ref"] else None
        if p:
            who = with_src(f"{p['patient_id']} {p['name'] or ''}", "patient_id")
        else:
            guess = " ".join(x for x in (meta.get("patient_id"), meta.get("name")) if x)
            who = "<span style='color:#b33'>미분류</span>" + (f" — 추출값: {guess}" if guess else "")
        eye = {"OD": "OD (우안)", "OS": "OS (좌안)", "OU": "OU"}.get(row["laterality"] or "", "")
        mod = MODALITY_LABELS.get(row["modality"] or "", row["modality"] or "")
        device = row["device"] or get_profile(row["profile"]).name
        ftype = "안구 중심각" if row["fov_type"] == "internal" else "외부각"
        fov = f"{row['fov_deg']:g}°" if row["fov_deg"] else ""
        name = Path(row["original_path"] or row["file_path"]).name
        # VK-2: green text on the photo — counter, eye, name / ID, date / time
        n, i = self.thumbs.count(), self.thumbs.currentRow()
        self.view2d.set_captions(
            f"{i + 1}/{n}" if n and i >= 0 else "",
            {"OD": "OD (R)", "OS": "OS (L)", "OU": "OU"}.get(row["laterality"] or "", ""),
            f"{p['name'] or ''}\n{p['patient_id']}" if p else "미분류",
            f"{row['exam_date'] or ''}\n{row['exam_time'] or ''}".strip())
        # status bar "Image Info"; the tooltip says where every value came from
        self.lbl_info.setText("  ·  ".join(x for x in (eye or "눈 미상", mod, device, fov,
                                                        f"{row['width']}×{row['height']}") if x))
        rows = (("환자", who), ("검사일시", with_src(f"{row['exam_date'] or '-'} {row['exam_time'] or ''}", "exam_date")),
                ("눈", with_src(eye or "-", "laterality")), ("촬영 종류", with_src(mod or "-", "modality")),
                ("장비", with_src(device, "device")),
                ("화각", with_src(f"{fov} ({ftype})" if fov else "-", "fov_deg")), ("파일", name))
        self.lbl_info.setToolTip("<table>" + "".join(f"<tr><td><b>{k}</b>&nbsp;</td><td>{v}</td></tr>"
                                                     for k, v in rows) + "</table>")

    # -- adjustments -----------------------------------------------------------
    def _adjust_params(self) -> dict:
        return dict(brightness=self.s_bright.value() / 200.0, contrast=self.s_contrast.value() / 100.0,
                    gamma=self.s_gamma.value() / 100.0, channel=self._channel,
                    invert=self._invert, auto=self._auto, levels=self._levels)

    def _adjusted(self, rgb: np.ndarray) -> np.ndarray:
        return imaging.adjust(rgb, **self._adjust_params())

    def _processed(self, row, rgb: np.ndarray | None = None, ops=None) -> np.ndarray | None:
        """Photo with the processing stack applied (cached per image + stack)."""
        ops = tuple(self._ops if ops is None else ops)
        rgb = self._load(row) if rgb is None else rgb
        if rgb is None or not ops:
            return rgb
        key = (row["id"], rgb.shape, ops)
        if key in self._proc_cache:
            self._proc_cache.move_to_end(key)
            return self._proc_cache[key]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            out = imaging.apply_ops(rgb, ops)
        finally:
            QApplication.restoreOverrideCursor()
        self._proc_cache[key] = out
        while len(self._proc_cache) > 4:
            self._proc_cache.popitem(last=False)
        return out

    def _display_rgb(self, row) -> np.ndarray | None:
        rgb = self._processed(row)
        return None if rgb is None else self._adjusted(rgb)

    def _schedule_adjust(self, *_):
        self._adjust_timer.start(60)

    def _apply_adjust(self) -> None:
        self._sync_palette()
        if self.current is None:
            return
        rgb = self._display_rgb(self.current)
        if rgb is not None:
            self.view2d.set_rgb(rgb, keep_view=True)
            if self.c_adj3d.isChecked():
                self._mark_3d_dirty()
        if self.tabs.currentIndex() == 2:
            self._fill_multi()
        if self.tabs.currentIndex() == 3:
            self._fill_compare()

    # -- undo / original (VK-2 [UNDO] / [ORIGINAL]) --------------------------------------
    def _snapshot(self) -> dict:
        return dict(ops=list(self._ops), levels=self._levels, bright=self.s_bright.value(),
                    contrast=self.s_contrast.value(), gamma=self.s_gamma.value(),
                    channel=self._channel, auto=self._auto, invert=self._invert)

    def _push_history(self) -> None:
        snap = self._snapshot()
        if not self._history or self._history[-1] != snap:
            self._history.append(snap)
            del self._history[:-30]

    def _set_adjust_state(self, st: dict) -> None:
        sliders = (self.s_bright, self.s_contrast, self.s_gamma)
        for w in sliders:
            w.blockSignals(True)
        self._ops = list(st.get("ops", []))
        self._levels = tuple(st.get("levels", (0, 255)))
        self.s_bright.setValue(st.get("bright", 0))
        self.s_contrast.setValue(st.get("contrast", 100))
        self.s_gamma.setValue(st.get("gamma", 100))
        self._channel = st.get("channel", "rgb")
        self._auto = st.get("auto", False)
        self._invert = st.get("invert", False)
        for w in sliders:
            w.blockSignals(False)
        for pop in (self.pop_gamma, self.pop_contrast, self.pop_bright):
            pop._show(pop.slider.value())    # value label (signals were blocked)
        self._apply_adjust()

    def _undo(self) -> None:
        if not self._history:
            self.lbl_status.setText("되돌릴 처리가 없습니다")
            return
        self._set_adjust_state(self._history.pop())
        self.lbl_status.setText("실행 취소")

    def _original(self) -> None:
        self._history = []
        self._set_adjust_state({})
        self.view2d.reset_orientation()
        self.view2d.clear_annotations()
        self._on_measured("")
        self.lbl_status.setText("원본으로 되돌렸습니다")

    def _sync_palette(self) -> None:
        """Light up the toolbar buttons whose effect is on the photo (VK-2 pushed state)."""
        A = self.acts
        for ch in ("red", "green", "blue", "redfree"):
            A[f"chan:{ch}"].setChecked(self._channel == ch)
        A["auto"].setChecked(self._auto)
        A["negative"].setChecked(self._invert)
        A["slideshow"].setChecked(self._slide_timer.isActive())
        A["adj:gamma"].setChecked(self.s_gamma.value() != 100)
        A["adj:contrast"].setChecked(self.s_contrast.value() != 100)
        A["adj:bright"].setChecked(self.s_bright.value() != 0)
        A["op:sharpen"].setChecked(any(o.startswith("sharpen") for o in self._ops))
        A["op:enhance"].setChecked(any(not o.startswith("sharpen") for o in self._ops))
        tool = self.view2d.tool
        A["tool:" + {"cd_area": "cd_length", "arrow": "text"}.get(tool, tool)].setChecked(True)
        steps = [imaging.OP_LABELS.get(o, o) for o in self._ops]
        if self._channel != "rgb":
            steps.append(imaging.CHANNEL_LABELS[self._channel])
        steps += [label for on, label in ((self._auto, "자동 대비"), (self._invert, "네거티브"),
                                          (self.s_gamma.value() != 100, f"감마 {self.s_gamma.value() / 100:.2f}"),
                                          (self.s_contrast.value() != 100, f"대비 {self.s_contrast.value()}%"),
                                          (self.s_bright.value() != 0, f"밝기 {self.s_bright.value():+d}"),
                                          (tuple(self._levels) != (0, 255),
                                           f"레벨 {self._levels[0]}–{self._levels[1]}")) if on]
        self.tb_proc.setToolTip("적용된 처리: " + (" → ".join(steps) if steps else "없음 (원본)"))

    # -- toolbar commands (toolbars.py: COMMANDS / PROCESSING / MENUS) -----------------------
    TWO_D = ("fit", "actual", "zoom2", "zoom4", "zoom8", "rot_cw", "rot_ccw", "flip_h", "flip_v",
             "annot_undo", "annot_clear")

    def _on_action(self, key: str, checked: bool | None = None) -> None:
        """``checked`` is the new state when a checkable button was clicked, None
        when called from a menu entry or code."""
        v = self.view2d
        if key.startswith(("tool:", "region:")) or key in self.TWO_D:
            if self.tabs.currentIndex() != 0:   # 2D tools: go to the 2D view first
                self.tabs.setCurrentIndex(0)
        if key.startswith("tool:"):
            tool = key[5:]
            v.set_tool(tool)
            self.lbl_status.setText(f"{TOOLS[tool]} — {TOOL_HINTS[tool]}")
            v.setFocus()
        elif key.startswith("chan:"):
            ch = key[5:]
            if checked is False and ch == self._channel:   # clicked the lit filter again
                ch = "rgb"
            self._push_history()
            self._channel = ch
            self._apply_adjust()
        elif key.startswith("op:"):
            self._push_history()
            op = key[3:]
            self._ops.append(op)
            self._apply_adjust()
            self.lbl_status.setText(f"{imaging.OP_LABELS.get(op, op)} 적용 (실행 취소: Ctrl+Z)")
        elif key.startswith("adj:"):
            self._show_slider(key)
        elif key == "adj_reset":
            self._push_history()
            self._set_adjust_state({**self._snapshot(), "bright": 0, "contrast": 100, "gamma": 100})
        elif key in ("auto", "negative"):
            self._push_history()
            attr = "_auto" if key == "auto" else "_invert"
            setattr(self, attr, (not getattr(self, attr)) if checked is None else checked)
            self._apply_adjust()
        elif key == "undo":
            self._undo()
        elif key == "original":
            self._original()
        elif key == "histogram":
            self._histogram()
        elif key == "fit":
            v.fit()
        elif key in ("actual", "zoom2", "zoom4", "zoom8"):
            v.zoom_to({"actual": 1.0, "zoom2": 2.0, "zoom4": 4.0, "zoom8": 8.0}[key])
        elif key.startswith("region:"):
            self._zoom_region(key[7:])
        elif key in ("rot_cw", "rot_ccw"):
            v.rotate90(key == "rot_cw")
        elif key in ("flip_h", "flip_v"):
            v.flip(key == "flip_h")
        elif key in ("prev", "next"):
            self._step(-1 if key == "prev" else 1)
        elif key == "slideshow":
            self._stop_slideshow() if self._slide_timer.isActive() else self._start_slideshow()
        elif key == "annot_undo":
            v.undo_annotation()
        elif key == "annot_clear":
            v.clear_annotations()
            self._on_measured("")
        elif key == "copy":
            self._copy_view()
        elif key == "save_file":
            self._save_view_file()
        elif key in ("save", "save_record"):
            self._save_view_record()
        elif key == "print":
            self._print_view()
        elif key == "discpair":
            self._disc_pair()
        # -- command toolbar ---------------------------------------------------------
        elif key == "search":
            self.acts["list"].setChecked(True)
            self.left.show()
            self.search.setFocus()
            self.search.selectAll()
        elif key == "list":
            self.left.setVisible(self.left.isHidden() if checked is None else checked)
        elif key in ("multi", "view3d"):
            tab = 2 if key == "multi" else 1
            self.tabs.setCurrentIndex(0 if self.tabs.currentIndex() == tab else tab)
        elif key.startswith("multi:"):
            self.multi.set_count(int(key[6:]))
            self.tabs.setCurrentIndex(2)
        elif key == "tools":
            self.tb_proc.setVisible(self.tb_proc.isHidden() if checked is None else checked)
        elif key == "edit":
            self._edit_image()
        elif key in ("import", "import_files"):
            self._import_files()
        elif key == "import_dir":
            self._import_dir()
        elif key == "scan":
            self._scan_now()
        elif key == "settings":
            self._open_settings()
        elif key == "exit":
            if QMessageBox.question(self, "종료", "프로그램을 종료할까요?\n(종료하면 자동 가져오기도 멈춥니다)") \
                    == QMessageBox.StandardButton.Yes:
                self.close()
        self._sync_palette()
        self.acts["list"].setChecked(not self.left.isHidden())

    def _show_slider(self, key: str) -> None:
        """VK-2 GAMMA / CONTST / BRIGHT: a slider pops up next to the button."""
        pop = {"adj:gamma": self.pop_gamma, "adj:contrast": self.pop_contrast, "adj:bright": self.pop_bright}[key]
        btn = self.tb_proc.widgetForAction(self.acts[key])
        if btn is not None and btn.isVisible():
            pop.adjustSize()
            area = self.toolBarArea(self.tb_proc)
            if area == Qt.ToolBarArea.BottomToolBarArea:
                pos = btn.mapToGlobal(QPoint(0, -pop.height() - 2))
            elif area == Qt.ToolBarArea.RightToolBarArea:
                pos = btn.mapToGlobal(QPoint(-pop.width() - 2, 0))
            else:
                pos = btn.mapToGlobal(QPoint(0, btn.height() + 2))
        else:
            pos = QCursor.pos()
        pop.show_at(pos)

    def _on_measured(self, text: str) -> None:
        self.lbl_measure.setText(text)
        self.lbl_measure.setVisible(bool(text))
        if text:
            self.lbl_status.setText(text)

    def _histogram(self) -> None:
        if self.current is None:
            return
        rgb = self._processed(self.current)
        if rgb is None:
            return
        self._push_history()
        dlg = HistogramDialog(imaging.histogram(rgb), self._levels, self)

        def on_levels(lo, hi):
            self._levels = (lo, hi)
            self._schedule_adjust()

        dlg.levelsChanged.connect(on_levels)
        dlg.exec()

    # -- navigation / slideshow (VK-2 previous / next / loop) ------------------------------
    def _step(self, d: int, wrap: bool = False) -> None:
        n = self.thumbs.count()
        if n == 0:
            return
        i = self.thumbs.currentRow() + d
        if wrap:
            i %= n
        if 0 <= i < n:
            self.thumbs.setCurrentRow(i)

    def _start_slideshow(self) -> None:
        if self.thumbs.count() > 1:
            self._slide_timer.start()
            self.lbl_status.setText("연속 보기 중 — 사진을 클릭하면 멈춥니다")
        self._sync_palette()

    def _stop_slideshow(self) -> None:
        if self._slide_timer.isActive():
            self._slide_timer.stop()
            self.lbl_status.setText("연속 보기 멈춤")
        self._sync_palette()

    # -- output: clipboard / file / patient record / print -----------------------------------
    def _rendered(self) -> QImage | None:
        if self.current is None or not self.view2d.has_image():
            return None
        return self.view2d.render_image()

    def _copy_view(self) -> None:
        img = self._rendered()
        if img is not None:
            QApplication.clipboard().setImage(img)
            self.lbl_status.setText("클립보드에 복사했습니다 (측정·글자 포함)")

    def _save_view_file(self) -> None:
        img = self._rendered()
        if img is None:
            return
        stem = Path(self.current["original_path"] or self.current["file_path"]).stem
        path, _ = QFileDialog.getSaveFileName(self, "영상 저장", f"{stem}_편집.png",
                                              "PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if path:
            img.save(path, quality=95)
            self.lbl_status.setText(f"저장했습니다: {path}")

    def _save_view_record(self) -> None:
        img = self._rendered()
        if img is None:
            return
        rgb = from_qimage(img)
        steps = [imaging.OP_LABELS.get(o, o) for o in self._ops]
        note = "편집 영상" + (f" ({', '.join(steps)})" if steps else "")
        new_id = self.service.importer.add_derived(self.current, rgb, note)
        self.lbl_status.setText("편집 영상을 이 환자 기록에 추가했습니다")
        self._fill_dates()
        self._fill_thumbs(select_id=new_id)

    def _print_view(self) -> None:
        img = self._rendered()
        if img is None:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        row = self.current
        p = self.db.get_patient(row["patient_ref"]) if row["patient_ref"] else None
        header = "  ·  ".join(x for x in (
            (p["name"] or "") if p else "미분류", p["patient_id"] if p else "",
            (p["birth_date"] or "") if p else "", f"검사일 {row['exam_date'] or '-'} {row['exam_time'] or ''}",
            row["laterality"] or "", row["device"] or "") if x)
        painter = QPainter(printer)
        page = printer.pageLayout().paintRectPixels(printer.resolution())
        f = QFont()
        f.setPointSize(11)
        painter.setFont(f)
        line_h = painter.fontMetrics().height()
        painter.drawText(0, line_h, header)
        area_top = int(line_h * 1.8)
        avail_w, avail_h = page.width(), page.height() - area_top - line_h * 2
        scale = min(avail_w / img.width(), avail_h / img.height())
        tw, th = int(img.width() * scale), int(img.height() * scale)
        painter.drawImage(QRect(int((avail_w - tw) / 2), area_top, tw, th), img)
        painter.setPen(QColor(90, 90, 90))
        painter.drawText(0, area_top + th + line_h * 1.5, f"{APP_TITLE}  ·  {date.today().isoformat()}")
        painter.end()
        self.lbl_status.setText("인쇄를 보냈습니다")

    # -- multi view (VK-2 multiple images) ------------------------------------------------------
    def _fill_multi(self) -> None:
        ids = [self.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.thumbs.count())]
        if not ids:
            self.multi.populate([], None)
            return
        cur = self.current["id"] if self.current else ids[0]
        start = ids.index(cur) if cur in ids else 0
        n = self.multi.count
        start = max(0, min(start, len(ids) - n)) if len(ids) > n else 0
        items = []
        for iid in ids[start:start + n]:
            row = self.db.get_image(iid)
            rgb = self._load(row) if row else None
            if rgb is None:
                continue
            small = imaging.downscale(rgb, 1400 if n <= 4 else 900)
            small = self._adjusted(imaging.apply_ops(small, self._ops) if self._ops else small)
            mod = MODALITY_LABELS.get(row["modality"] or "", "")
            items.append((iid, f"{row['exam_date'] or ''} {row['exam_time'] or ''}  {row['laterality'] or ''}  {mod}",
                          small))
        self.multi.populate(items, cur)

    def _select_from_multi(self, image_id: int) -> None:
        self._multi_lock = True
        try:
            for i in range(self.thumbs.count()):
                if self.thumbs.item(i).data(Qt.ItemDataRole.UserRole) == image_id:
                    self.thumbs.setCurrentRow(i)
                    break
        finally:
            self._multi_lock = False

    # -- 3D ----------------------------------------------------------------------
    def _load_mapping(self, row) -> None:
        prof = get_profile(row["profile"])
        for w in (self.sp_fov, self.c_fovtype, self.c_proj, self.sp_roll):
            w.blockSignals(True)
        self.sp_fov.setValue(row["fov_deg"] or prof.fov_deg)
        self.c_fovtype.setCurrentIndex(max(self.c_fovtype.findData(row["fov_type"] or prof.fov_type), 0))
        self.c_proj.setCurrentIndex(max(self.c_proj.findData(row["projection"] or prof.projection), 0))
        self.sp_roll.setValue(0)
        for w in (self.sp_fov, self.c_fovtype, self.c_proj, self.sp_roll):
            w.blockSignals(False)
        self._push_mapping()

    def _push_mapping(self) -> None:
        row = self.current
        prof = get_profile(row["profile"]) if row else get_profile(None)
        self.eye3d.set_mapping(fov_deg=self.sp_fov.value(), fov_type=self.c_fovtype.currentData(),
                               projection=self.c_proj.currentData(), viewpoint=prof.viewpoint,
                               roll_deg=self.sp_roll.value(), radial_c=prof.radial_c)
        if row is not None:
            circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else None
            disc = (row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None
            self.eye3d.set_disc(row["laterality"], disc, circle)
            # the 2D measurements use the same eye geometry as the 3D view
            self.view2d.geometry = measure.Geometry(
                *circle, fov_deg=self.sp_fov.value(), fov_type=self.c_fovtype.currentData(),
                projection=self.c_proj.currentData(), viewpoint=prof.viewpoint,
                radial_c=prof.radial_c) if circle and row["modality"] not in ("montage", "disc") else None
        tmax = math.degrees(self.eye3d.theta_max)
        self.lbl_3d.setText(f"망막 범위: 후극에서 {tmax:.0f}° (안구 중심각 {2 * tmax:.0f}°)")

    def _on_mapping(self, *_):
        self._push_mapping()

    def _save_mapping(self) -> None:
        if self.current is None:
            return
        self.db.update_image(self.current["id"], fov_deg=self.sp_fov.value(),
                             fov_type=self.c_fovtype.currentData(), projection=self.c_proj.currentData())
        self.current = self.db.get_image(self.current["id"])
        self._fill_info(self.current)
        self.lbl_status.setText("이 영상의 화각·투영을 저장했습니다")

    def _on_cut(self, v: int) -> None:
        self.eye3d.cut = v / 100.0 if v < 100 else 1.0
        self.eye3d.update()

    # -- 2D zoom ---------------------------------------------------------------------
    def _show_zoom(self, z: float) -> None:
        fit = self.view2d._fit
        self.btn_zoom.setText(f"배율 맞춤 ({z * 100:.0f}%)" if fit else f"배율 {z * 100:.0f}%")

    REGIONS = {"posterior": "후극부", "superior": "위쪽 주변부", "inferior": "아래쪽 주변부",
               "nasal": "코쪽 주변부", "temporal": "귀쪽 주변부"}

    def region_rect(self, name: str) -> QRectF | None:
        """Part of the current photo to zoom onto (``measure.fundus_region``), or None."""
        row = self.current
        rgb = self._load(row) if row is not None else None
        if rgb is None:
            return None
        circle = ((row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"]
                  else imaging.detect_circle(rgb))
        disc = (row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None
        rect = measure.fundus_region(name, circle, disc, row["laterality"], (rgb.shape[1], rgb.shape[0]))
        return QRectF(*rect) if rect else None

    def _zoom_region(self, name: str) -> None:
        rect = self.region_rect(name)
        if rect is None:
            self.lbl_status.setText("눈(OD/OS)과 시신경 위치를 알 수 없어 코쪽·귀쪽을 정할 수 없습니다"
                                    if name in ("nasal", "temporal") else "사진이 없습니다")
            return
        self.view2d.zoom_to_rect(rect)
        self.view2d.setFocus()
        self.lbl_status.setText(f"{self.REGIONS[name]} 확대 — 0: 전체 보기 · 미니맵을 눌러 이동")

    def _set_3d_detail(self, detail: str, save: bool = True) -> None:
        detail = detail if detail in EyeView.DETAILS else "simple"
        (self.b_detailed if detail == "detailed" else self.b_simple).setChecked(True)
        self.eye3d.set_detail(detail)
        self.c_muscle.setEnabled(detail == "detailed")     # the simple model has no muscles
        self.c_muscle.setToolTip("네 곧은근과 두 빗근의 부착부(절단면)를 함께 표시"
                                 + ("" if detail == "detailed" else " — 자세히 보기에서"))
        if save and self.settings.view3d_detail != detail:
            self.settings.view3d_detail = detail
            self.settings.save()

    def _on_3d_mode(self, outside: bool) -> None:
        self.s_cut.setEnabled(outside)
        self.eye3d.set_mode("outside" if outside else "inside")

    def _mark_3d_dirty(self) -> None:
        self._3d_dirty = True
        if self.tabs.currentIndex() == 1:
            self._update_3d()

    def _update_3d(self) -> None:
        self._3d_dirty = False
        row = self.current
        if row is None:
            self.eye3d.set_image(None)
            return
        rgb = self._load(row)
        if rgb is None:
            return
        circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else imaging.detect_circle(rgb)
        tex = self._display_rgb(row) if self.c_adj3d.isChecked() else rgb
        self.eye3d.set_image(tex, imaging.fundus_alpha(rgb, circle), circle)

    def _save_3d(self) -> None:
        if self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(1)
        img = self.eye3d.grabFramebuffer()
        path, _ = QFileDialog.getSaveFileName(self, "3D 화면 저장", "eye3d.png", "PNG (*.png)")
        if path:
            img.save(path)

    def _on_disc_picked(self, x: float, y: float) -> None:
        if self.current is None:
            return
        self._set_disc(self.current["id"], x, y)
        self.lbl_status.setText("시신경 유두 위치를 저장했습니다 (3D 시신경에 반영)")

    def _set_disc(self, image_id: int, x: float, y: float) -> None:
        """Store a photo's optic disc position (2D right-click menu, disc pair clicks)."""
        self.db.update_image(image_id, disc_x=x, disc_y=y)
        if self.current is not None and self.current["id"] == image_id:
            self.current = self.db.get_image(image_id)
            self.view2d.set_overlays((self.current["circle_cx"], self.current["circle_cy"],
                                      self.current["circle_r"]), (x, y))
            self._push_mapping()

    def _on_tab(self, i: int) -> None:
        if i == 1 and self._3d_dirty:
            self._update_3d()
        if i == 2:
            self._fill_multi()
        if i == 3:
            self._fill_compare()

    # -- compare -------------------------------------------------------------------
    def _set_compare(self, image_id: int) -> None:
        if self.current is not None and image_id == self.current["id"]:
            return
        self.compare = self.db.get_image(image_id)
        self._mark_pair()
        self.lbl_status.setText("두 사진을 골랐습니다 (② = 두 번째) — [디스크 2장]으로 시신경 유두 2장 만들기 · "
                                "Ctrl+클릭으로 해제")
        self.tabs.setCurrentIndex(3)
        self._fill_compare()

    def _fill_compare(self) -> None:
        for view, lab, row in zip(self.cmp_views, self.cmp_labels, (self.current, self.compare)):
            if row is None:
                view.set_rgb(None)
                lab.setText("Ctrl+클릭으로 비교할 사진을 고르세요" if row is self.compare else "")
                continue
            rgb = self._load(row)
            view.set_rgb(self._adjusted(self._processed(row, rgb)) if rgb is not None else None)
            mod = MODALITY_LABELS.get(row["modality"] or "", "")
            lab.setText(f"<b>{row['exam_date'] or ''}</b> {row['laterality'] or ''} {mod}")

    # -- disc pair (디스크 2장 — discpair.py, disc_pair.py) ---------------------------------------
    def _disc_source(self, row, rgb: np.ndarray) -> discpair.DiscSource:
        prof = get_profile(row["profile"])
        circle = ((row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"]
                  else imaging.detect_circle(rgb))
        geo = measure.Geometry(*circle, fov_deg=row["fov_deg"] or prof.fov_deg,
                               fov_type=row["fov_type"] or prof.fov_type,
                               projection=row["projection"] or prof.projection,
                               viewpoint=prof.viewpoint, radial_c=prof.radial_c)
        eye = row["laterality"] if row["laterality"] in ("OD", "OS") else None
        if row["disc_x"] is not None:
            disc, found = (row["disc_x"], row["disc_y"]), "saved"
            eye = eye or imaging.laterality_from_disc(disc, circle)
        else:
            disc, found = discpair.expected_disc(geo, eye, (rgb.shape[1], rgb.shape[0])), "estimated"
        when = f"{row['exam_date'] or ''} {row['exam_time'] or ''}".strip()
        fov = f"{row['fov_deg']:g}°" if row["fov_deg"] else ""
        caption = "  ·  ".join(x for x in (when or "검사일 미상", row["device"] or prof.name, fov,
                                           MODALITY_LABELS.get(row["modality"] or "", "")) if x)
        return discpair.DiscSource(row["id"], rgb, disc, geo, eye, when, caption, found)

    def _build_disc_pair(self, second_id: int | None = None):
        """``(dialog, "")`` for the shown photo and ``second_id`` (default: the ② photo),
        or ``(None, why not)``."""
        if self.current is None:
            return None, "사진을 고르세요."
        first = self.db.get_image(self.current["id"])
        if second_id is None or second_id == first["id"]:
            second_id = self.compare["id"] if self.compare is not None else None
        second = self.db.get_image(second_id) if second_id is not None else None
        if second is None or second["id"] == first["id"]:
            return None, ("사진 두 장을 고르세요.\n\n썸네일에서 한 장을 클릭한 뒤 두 번째 사진을 Ctrl+클릭하면 "
                          "② 표시가 붙습니다. 그다음 [디스크 2장]을 누르세요.")
        if first["patient_ref"] is None or second["patient_ref"] is None:
            return None, "미분류 사진은 쓸 수 없습니다.\n먼저 [정보 수정]으로 환자를 지정하세요."
        if first["patient_ref"] != second["patient_ref"]:
            return None, "서로 다른 환자의 사진입니다."
        for row in (first, second):
            if row["modality"] in ("anterior", "disc"):
                return None, f"{MODALITY_LABELS[row['modality']]} 사진에서는 시신경 유두를 자를 수 없습니다."
        sources = []
        for row in (first, second):
            rgb = self._load(row)
            if rgb is None:
                return None, f"영상을 열 수 없습니다: {Path(row['original_path'] or row['file_path']).name}"
            sources.append(self._disc_source(row, rgb))
        p = self.db.get_patient(first["patient_ref"])
        dates = [r["exam_date"] for r in (first, second) if r["exam_date"]]
        on = min(dates) if dates else None
        age = age_on(p["birth_date"], on)
        bits = [p["name"] or "(이름 없음)", f"ID {p['patient_id']}"]
        if p["birth_date"]:
            bits.append(p["birth_date"] + (f" ({age}세)" if age is not None else ""))
        if p["sex"]:
            bits.append(SEX_LABEL.get(p["sex"], p["sex"]))
        stem = "_".join(x for x in (p["patient_id"], p["name"] or "", "디스크", on or "") if x)
        dlg = DiscPairDialog(sources, patient_line="  ·  ".join(bits),
                             footer=f"{APP_TITLE}  ·  작성 {date.today().isoformat()}",
                             file_stem=safe_component(stem, "디스크"), save_record=self._save_disc_pair,
                             adjust=self._adjusted, parent=self)
        dlg.discPicked.connect(self._set_disc)
        return dlg, ""

    def _disc_pair(self, second_id: int | None = None) -> None:
        dlg, why = self._build_disc_pair(second_id)
        if dlg is None:
            QMessageBox.information(self, "디스크 2장", why)
            return
        dlg.exec()

    def _save_disc_pair(self, rgb: np.ndarray, sources) -> int:
        """Store the sheet as a new photo of the patient (modality ``disc``)."""
        rows = [self.db.get_image(s.image_id) for s in sources]
        eyes = [s.eye for s in sources]
        lat = "OU" if set(eyes) == {"OD", "OS"} else (eyes[0] if eyes[0] and eyes[0] == eyes[1] else None)
        note = "디스크 2장 (" + " · ".join(e or "?" for e in eyes) + ")"
        new_id = self.service.importer.add_derived(
            rows[0], rgb, note, suffix="디스크2장", derived_from=[r["id"] for r in rows],
            laterality=lat, modality="disc", fov_deg=None, fov_type=None, projection=None,
            circle_cx=None, circle_cy=None, circle_r=None)
        self.refresh_patients(keep=True)
        self._fill_dates()
        self._fill_thumbs(select_id=self.current["id"] if self.current else None)
        self.lbl_status.setText("디스크 2장을 이 환자 기록에 저장했습니다")
        return new_id

    # -- edit / misc -------------------------------------------------------------------
    def _edit_image(self) -> None:
        if self.current is None:
            return
        dlg = ImageDialog(self.db, self.current, self)
        if dlg.exec():
            ref = dlg.apply()
            iid = self.current["id"]
            self.refresh_patients()
            self._select_patient_ref(ref if ref is not None else UNASSIGNED)
            self._fill_dates()
            self._fill_thumbs(select_id=iid)

    def _open_folder(self) -> None:
        if self.current is None:
            return
        for p in (self.current["original_path"], self.current["file_path"]):
            if p and os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))
                return
        QMessageBox.information(self, "원본 폴더", "원본 파일이 더 이상 없습니다.")

    def _reanalyse(self, image_id: int) -> None:
        row = self.db.get_image(image_id)
        rgb = self._load(row) if row else None
        if rgb is None:
            return
        circle = imaging.detect_circle(rgb)
        prof = get_profile(row["profile"])
        tmax = math.degrees(proj.theta_max(row["fov_deg"] or prof.fov_deg, row["fov_type"] or prof.fov_type,
                                           prof.viewpoint))
        disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / max(tmax, 5)), search=prof.disc_search)
        self.db.update_image(image_id, circle_cx=circle[0], circle_cy=circle[1], circle_r=circle[2],
                             disc_x=disc[0] if disc else None, disc_y=disc[1] if disc else None)
        self._show_image(image_id)

    def _remove_image(self, image_id: int) -> None:
        ok = QMessageBox.question(self, "목록에서 제거",
                                  "이 영상을 뷰어 데이터베이스에서 제거할까요?\n"
                                  "(원본 파일과 라이브러리 사본은 지우지 않습니다)")
        if ok == QMessageBox.StandardButton.Yes:
            self.db.delete_image(image_id)
            self._cache.pop(image_id, None)
            if self.compare is not None and self.compare["id"] == image_id:
                self.compare = None
            self.refresh_patients(keep=True)
            self._fill_thumbs()

    def _fill_log(self) -> None:
        rows = self.db.recent_logs(300)
        self.log.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate((r["at"].replace("T", " "), r["level"], r["message"], r["path"] or "")):
                it = QTableWidgetItem(v)
                if r["level"] == "error":
                    it.setForeground(Qt.GlobalColor.red)
                self.log.setItem(i, j, it)
        self.log.resizeColumnToContents(0)

    def _open_log_path(self, index) -> None:
        it = self.log.item(index.row(), 3)
        if it and it.text() and os.path.exists(it.text()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(it.text()).parent)))

    def closeEvent(self, e):
        try:
            self.settings.save()
        except OSError:
            pass
        self.service.shutdown()
        super().closeEvent(e)
