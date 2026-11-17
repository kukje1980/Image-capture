"""Main window — the photos. The program opens with the 환자 목록 window over it (patient_list.py,
VK-2 OPEN LIST): a patient picked there shows here, opened as 설정 → 일반 → 환자를 열면 says — its
newest OD | OS on 다중 보기 (the first setting), or the VK-2 way: its photos 16 to a screen on 16장
보기 (photo_grid.py; a click picks, [멀티] shows the picked ones on 다중 보기). The patient list is
the only one: the command toolbar's [환자 목록], the menu bar's 환자 목록 (Ctrl+0) and 환자 검색
(Ctrl+F) bring that window up; the patient is the same in both windows.

The photo screen is laid out like the Kowa VK-2 capture screen: the views (모두 보기 / 다중 보기 /
16장 보기 / 3D) with the photo strip (thumbnails) under them, the Command toolbar on the left edge and
the Image Processing toolbar along the bottom (see toolbars.py).

검토 (review_view.py) shows both eyes side by side and an eye next to its earlier exams; it has
its own timeline, so the photo strip is hidden while it is shown (not shown since v0.3.0).

모두 보기 shows the big 2D view with the 황반 and 시신경 유두 enlarged on the right (where they
are is shown by a frame on the big photo). The 2D view and the 3D eye are moved between that tab
and their own tabs (like 크게 보기 does for the 3D eye), so the tools and the 3D state stay the same.

A patient opens (설정 → 일반 → 환자를 열면: 최신 OD | OS) on 다중 보기 with its newest OD and OS photo
picked (OD left); a plain click on the photo strip adds a photo to the multi view or takes it away,
and the layout fits the number picked (``_click_pick``). A double click shows the photo large on
모두 보기."""
from __future__ import annotations

import json
import math
import os
import time
from collections import OrderedDict
from datetime import date
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QCursor, QDesktopServices, QFont, QIcon, QImage, \
    QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFrame, QGraphicsRectItem, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QStatusBar, QStyle,
    QTableWidget,
    QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__, autosetup, discpair, imaging, measure, placement
from .. import projection as proj
from ..config import Settings
from ..db import Database
from ..importer import ImportResult, safe_component
from ..models import MODALITY_LABELS
from ..profiles import get_profile, set_lens_curves
from ..review import EYES, eye_series
from .. import share
from ..watcher import ImportService
from .dialogs import ImageDialog, PatientDialog, SettingsDialog, source_label
from .disc_pair import DiscPairDialog
from .glaucoma_dialog import GlaucomaDialog, Photo
from .eye3d import EyeView
from .histogram import HistogramDialog
from . import motion, theme
from .image_view import TOOL_HINTS, TOOLS, ImageView, from_qimage
from ..montage import span_text as mt_span_text
from .montage_dialog import MontageDialog, MontageSource, confirm_sources
from .keys import IS_MAC, keys
from .multi_view import MultiView
from .patient_list import SEX_LABEL, UNASSIGNED, PatientListWindow, age_on
from .photo_grid import GridPhoto, PhotoGrid
from .review_view import ReviewPage
from .landmarks_view import LandmarkPhoto
from .slit_scan import SLIT, ScanPhotoView, SlitScanShow, ViewTween
from .thumbs import EYE_ROLE, PICK_ROLE, ThumbDelegate, ThumbStrip, eye_badge_html, eye_row
from .toolbars import CHECKABLE, COMMANDS, MENUS, PROCESSING, SliderPopup, icon_for
from .widgets import ElidedLabel, Segmented, Switch, card, segment
from .widgets import row as setting_row

THUMB_TEXT = Qt.ItemDataRole.UserRole + 1    # thumbnail caption without the ② mark
SMALL_KEEP = 48                              # reduced photos of the multi cells kept for the next screens
UNKNOWN_EYE = "?"                            # 눈 filter: the photos of an unknown eye (미상) — not in 양안
SECOND_PICK = QColor(168, 104, 28)           # background of the second picked photo (②)
MAX_PICKS = 16                               # photos picked for the multi view (4×4)
# the views of the workspace: 모두 보기 · 다중 보기 under the photos, 3D the icon above them (보기 menu:
# Ctrl+1~4). 16장 보기 (VK-2 방식: 사진 16장을 한 화면에) is there only when 설정 → 일반 → 환자를 열면 is
# the VK-2 way
TABS = (("grid", "16장", "Ctrl+4"), ("all", "모두 보기", "Ctrl+1"), ("multi", "다중 보기", "Ctrl+2"),
        ("3d", "3D", "Ctrl+3"))
GRID_MODE = "grid"                           # Settings.open_view of the VK-2 way (the other: "odos")
# views no longer shown (검토 · 2D 보기 · 비교): whatever led there stays on 모두 보기, whose big
# photo is the 2D view with all its tools
GONE_VIEWS = {"review": "all", "2d": "all", "cmp": "all"}
PATIENT_LIST_KEY = "Ctrl+0"                  # the 환자 목록 window
THUMB_ICON = (64, 64)                        # 사진 목록(아래): the photo …
THUMB_GRID = (96, 104)                       # … and its cell, two short lines of caption under it
OV_ZOOM = 4.0                                # 확대 화면: 사진 전체 폭의 1/4 을 칸에 (×4)


def gl_available() -> bool:
    """Can this PC make an OpenGL context? (offscreen tests and broken drivers cannot —
    then 모두 보기 shows a button for the 3D tab instead of starting OpenGL at startup)."""
    if os.getenv("FUNDUSVIEW_NO_GL_PANE") == "1" or QApplication.platformName() in ("offscreen", "minimal"):
        return False
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        ctx = QOpenGLContext()
        if not ctx.create():
            return False
        surf = QOffscreenSurface()
        surf.setFormat(ctx.format())
        surf.create()
        ok = surf.isValid() and ctx.makeCurrent(surf)
        if ok:
            ctx.doneCurrent()
        return bool(ok)
    except Exception:
        return False


class _FullScreen3D(QWidget):
    """Top-level window that holds the 3D eye (and the photo) on the whole screen."""
    closed = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Window)
        self.setStyleSheet("background: #000;")

    def closeEvent(self, e) -> None:
        self.closed.emit()
        super().closeEvent(e)


class Preloader(QObject):
    """Decodes photos ahead of time on a worker thread — the next and the previous photo of the
    strip — so stepping through an exam never waits for a file (a 24-megapixel JPEG takes 0.3 s)."""
    loaded = Signal(int, object)          # image id, RGB array (None: could not be read)

    def __init__(self, parent=None):
        super().__init__(parent)
        from concurrent.futures import ThreadPoolExecutor

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fundus-preload")
        self._busy: set[int] = set()
        self.loaded.connect(lambda image_id, _: self._busy.discard(image_id))

    def request(self, image_id: int, path: str) -> None:
        if image_id not in self._busy:
            self._busy.add(image_id)
            self._pool.submit(self._run, image_id, path)

    def _run(self, image_id: int, path) -> None:
        try:
            if callable(path):             # a photo of a server (share.py): fetched here, off the window
                path = path()
            rgb = imaging.load_rgb(path)
        except Exception:                  # shown (with the reason) when the photo is opened
            rgb = None
        try:
            self.loaded.emit(image_id, rgb)
        except RuntimeError:               # the window is gone
            pass

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class Bridge(QObject):
    """Carries worker-thread callbacks into the GUI thread (queued signals)."""
    result = Signal(object)
    status = Signal(str)
    detected = Signal(object)   # autosetup.detect() result
    shared = Signal()           # another computer changed the shared library (share.py)


class _WhereChip(QLabel):
    """The name of the place passed (들어가며 보기) or of the slit's way, on a pill over the eye's bottom."""

    def __init__(self, eye: QWidget):
        super().__init__(eye)
        self.setObjectName("where3d")
        self.setStyleSheet("#where3d { background: rgba(28, 28, 30, 215); color: #f2f2f7; border-radius: 13px;"
                           " padding: 5px 14px; font-weight: 600; }")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        eye.installEventFilter(self)
        self.hide()

    def say(self, text: str, hold: float = 0.0) -> None:
        self._timer.stop()
        if not text:
            self.hide()
            return
        self.setText(text)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        if hold > 0.0:
            self._timer.start(int(hold * 1000))

    def _place(self) -> None:
        eye = self.parentWidget()
        self.move(max(8, (eye.width() - self.width()) // 2), max(8, eye.height() - self.height() - 16))

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False


class _WidthHint(QWidget):
    """A row whose width is set from outside (``want``): the menu bar sizes its corner by the hint."""
    want = 0

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(self.want or hint.width(), hint.height())


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db: Database):
        super().__init__()
        self.settings = settings
        self.db = db
        set_lens_curves(settings.lens_curves)         # 카메라 각도 보정: the measured lens of the camera
        if not settings.smooth_motion:        # 보기 → 부드러운 움직임 (off: everything changes at once)
            motion.set_enabled(False)
        if settings.ui_version < self.UI_VERSION:     # a new look: its 3D defaults, once
            if settings.ui_version < 3:
                settings.view3d_detail, settings.auto_rotate3d, settings.glass3d = "detailed", True, 80
                settings.autofind3d = True
            # 4: the photo as taken — 표면 높낮이 and 입체 조명 stay off until switched on in 망막 입체
            settings.surface3d, settings.relief3d = False, False
            settings.ui_version = self.UI_VERSION
        self.bridge = Bridge()
        # 설정 → 공유: connected to a server, the database and the photos are the server's (share.py)
        self.remote = isinstance(db, share.RemoteDatabase)
        self.share_server: share.ShareServer | None = None
        self._share_sig = None                # the open patient's photos, as last listed
        if self.remote:
            db.on_error = self.bridge.status.emit
            self.service = share.RemoteImportService(db, settings, on_result=self.bridge.result.emit,
                                                     on_status=self.bridge.status.emit)
        else:
            self.service = ImportService(db, settings, on_result=self.bridge.result.emit,
                                         on_status=self.bridge.status.emit)
        self.bridge.shared.connect(self._on_shared_change)
        self.bridge.result.connect(self._on_import_result)
        self.bridge.status.connect(self._on_status)
        self.bridge.detected.connect(self._on_detected)
        self.current = None          # images row
        self.compare = None
        self._patient_ref: int | None = None  # UNASSIGNED / patient id / None
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._fovea_tried: set[int] = set()     # photos whose fovea was looked for in this session
        self._preloader = Preloader(self)
        self._preloader.loaded.connect(self._on_preloaded)
        self._preload_timer = QTimer(self, singleShot=True, timeout=self._preload_neighbours)
        self._proc_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._ops: list[str] = []            # processing stack (VK-2 image processing toolbar)
        self._levels: tuple[int, int] = (0, 255)
        self._channel, self._auto, self._invert = "rgb", False, False
        self._history: list[dict] = []       # undo snapshots
        self._multi_lock = False
        self._picks: list[int] = []          # photos picked for the multi view (plain click), in order
        self._default_picks: list[int] = []  # what a patient opens with: its newest OD and OS (see _set_default_picks)
        self._multi_hint = False             # the picks were clicked away: the multi view says how to pick
        self._montage_dlg = None             # the open 몽타주 editor (tests reach it here)
        self._pick_pre: tuple | None = None  # (image id, picks, hint before the click) — a double click undoes it
        self._per_photo: dict[int, dict] = {}  # processing of each picked photo {"state", "history"}
        self._3d_dirty = True
        self._review_dirty = True            # the 검토 tab's photos are read when it is shown
        self._hold_follow = False            # a bulk import (--demo) must not jump to the workspace
        self._hold_release = False
        self._closing = False
        self._small: OrderedDict[tuple, np.ndarray] = OrderedDict()   # reduced photos of the multi cells (id, side)
        self._list_shown = False             # the 환자 목록 window came up with the main window
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
        tip = keys(tip)
        if icon:
            a.setIcon(icon_for(icon))
            a.setIconVisibleInMenu(False)
        vk_txt = f"<br><span style='color:{theme.TEXT3}'>VK-2: {vk}</span>" if vk and vk != "—" else ""
        a.setToolTip(f"<b>{label}</b><br>{tip}{vk_txt}" if tip else label)
        a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(lambda checked=False, k=key: self._on_action(k, checked if a.isCheckable() else None))
        return a

    def _top_button(self, icon: str, label: str, tip: str) -> QToolButton:
        """An icon button of the row above the photos (3D · Montage · Glaucoma)."""
        b = QToolButton()
        b.setObjectName("viewBarButton")
        b.setIcon(icon_for(icon))
        b.setIconSize(QSize(20, 20))
        b.setText(label)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setAutoRaise(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        return b

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
        self.acts["captions"] = self._act("captions", "화면 글자 표시", "사진 위 구석에 사진 번호와 눈(OD/OS)을 작게 표시",
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
        m.addAction(A["glaucoma"])
        m.addAction("몽타주 만들기 (고른 사진)…", lambda: self.open_montage())
        m.addAction(A["print"])
        m.addSeparator()
        m.addAction("원본 폴더 열기", self._open_folder)
        m.addSeparator()
        m.addAction(A["exit"])

        m = mb.addMenu("보기(&V)")
        self.act_patients = m.addAction("환자 목록", self.show_patient_list)
        self.act_patients.setShortcut(QKeySequence(PATIENT_LIST_KEY))
        self.act_patients.setToolTip("환자 목록 창 — 환자를 찾아 누르면 그 환자의 사진이 한 화면에 16장씩 나옵니다")
        m.addSeparator()
        self.view_acts = {}
        for key, label, shortcut in TABS:
            a = m.addAction("16장 보기" if key == "grid" else label, lambda k=key: self._go(k))
            a.setShortcut(QKeySequence(shortcut))
            self.view_acts[key] = a
        sub = m.addMenu("다중 보기 장수")
        for a in self.menus["multi"].actions():
            sub.addAction(a)
        m.addSeparator()
        self.act_thumbs = m.addAction("사진 목록 (썸네일)")
        self.act_thumbs.setCheckable(True)
        self.act_thumbs.setChecked(True)
        m.addAction(self.tb_cmd.toggleViewAction())
        m.addAction(self.tb_proc.toggleViewAction())
        m.addSeparator()
        m.addAction(A["captions"])
        m.addAction(A["overlay"])
        m.addSeparator()
        self.act_smooth = m.addAction("부드러운 움직임")
        self.act_smooth.setCheckable(True)
        self.act_smooth.setChecked(bool(self.settings.smooth_motion))
        self.act_smooth.setToolTip("확대·회전·화면 전환이 미끄러지듯 이어집니다 (원격 접속 등 느린 화면에서는 끄세요)")
        self.act_smooth.toggled.connect(self._on_smooth)
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
        m.addAction(self.act_patients)
        m.addAction(A["search"])
        m.addAction(A["edit"])
        m.addAction("환자 정보 수정…", self._edit_patient)
        m.addAction("환자 삭제 (영상은 미분류로)…", self._delete_patient)

        m = mb.addMenu("설정(&S)")
        m.addAction(A["settings"])
        m.addAction("카메라 각도 보정…", self.open_calibration)

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

        # -- centre: patient line + thumbnails + views ------------------------------
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(4, 6, 4, 0)
        cl.setSpacing(4)
        # the patient line: [환자 목록], the patient and the photo filters — in the right end of the menu
        # bar (see _build_menus), so the photos get its whole row
        self._centre_lay = cl
        self._line_in_menubar = False
        self._banner_busy = False             # _fit_banner is laying the menu bar out (no re-entry)
        self.top_w = _WidthHint()
        self.top_w.setObjectName("patientLine")
        top = QHBoxLayout(self.top_w)
        top.setContentsMargins(10, 0, 6, 0)
        top.setSpacing(6)
        self.btn_patients = QPushButton("환자 목록")
        self.btn_patients.setObjectName("back")
        self.btn_patients.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_patients.setToolTip(keys(f"환자 목록 창을 엽니다 ({PATIENT_LIST_KEY})"))
        self.btn_patients.clicked.connect(self.show_patient_list)
        top.addWidget(self.btn_patients)
        self.banner = ElidedLabel("환자를 선택하세요")
        self.banner.setObjectName("banner")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.banner, 1)
        self.f_date = QComboBox()
        self.f_date.setMinimumWidth(110)
        self.f_date.currentIndexChanged.connect(self._fill_thumbs)
        self.f_eye = QComboBox()
        # 양안 = OD · OS (· OU): photos of an unknown eye (미상) are only under 미상
        for k, v in (("", "양안"), ("OD", "OD (우안)"), ("OS", "OS (좌안)"), (UNKNOWN_EYE, "미상")):
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
        # thumbnail rows · multi view of the picked photos (VK-2: pick photos, then MULTI)
        self.btn_rows = QToolButton()
        self.btn_rows.setAutoRaise(True)
        self.btn_rows.clicked.connect(lambda: self._set_thumb_rows(1 if self._thumb_rows != 1 else 2, save=True))
        self.lbl_picks = QLabel("")
        self.lbl_picks.setStyleSheet(f"color:{theme.YELLOW}; font-weight:600")
        self.btn_clear_picks = QToolButton()
        self.btn_clear_picks.setText("선택 해제")
        self.btn_clear_picks.setAutoRaise(True)
        self.btn_clear_picks.setToolTip("멀티로 고른 사진을 모두 해제")
        self.btn_clear_picks.clicked.connect(self.clear_picks)
        self.btn_multi = QPushButton("멀티")
        self.btn_multi.setObjectName("multiButton")
        self.btn_multi.setToolTip("고른 사진을 다중 보기에 모아 보고, 칸을 눌러 그 사진만 보정합니다\n"
                                  "(사진을 클릭하면 바로 다중 보기에 더해지고, 다시 클릭하면 빠집니다 · "
                                  "더블클릭 = 크게)")
        self.btn_multi.clicked.connect(self.open_picks)
        # 3D · Montage · Glaucoma: icon buttons in the row above the photos (see view_bar below)
        self.btn_3d = self._top_button("eye3d", "3D", keys("광각 사진을 3D 안구 모형으로 보기 (Ctrl+3)\n"
                                                           "다시 누르면 모두 보기"))
        self.btn_3d.setCheckable(True)
        self.btn_3d.clicked.connect(lambda: self._on_action("view3d"))
        self.btn_montage = self._top_button("montage", "Montage",
                                            "몽타주 — 고른 사진(2장 이상, 같은 눈)을 자동·수동으로 맞춰 한 장으로 합칩니다\n"
                                            "반투명 겹치기 · 기준점 맞추기 · 3D 안구에서 보기")
        self.btn_montage.clicked.connect(lambda: self.open_montage())
        self.btn_glaucoma = self._top_button("glaucoma", "Glaucoma",
                                             keys("녹내장 분석 — 보고 있는 사진의 디스크 C/D · 광각 RNFL 분석,\n"
                                                  "두 번째 사진을 Ctrl+클릭(②)하면 스테레오 보기 · 경과 비교"))
        self.btn_glaucoma.clicked.connect(lambda: self.open_glaucoma())
        self.thumbs = ThumbStrip()                 # OD 위 줄 · OS 아래 줄 (or one line)
        self.thumbs.setObjectName("thumbStrip")
        self.thumbs.setIconSize(QSize(*THUMB_ICON))          # small: the height saved goes to the photos
        self.thumbs.setGridSize(QSize(*THUMB_GRID))
        self.thumbs.setFixedHeight(THUMB_GRID[1] + 10)
        self.thumbs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thumbs.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbs.setItemDelegate(ThumbDelegate(self.thumbs))
        self.thumbs.setToolTip(keys("클릭: 다중 보기에 더하기(번호) — 고른 장수에 맞게 화면이 나뉩니다 · "
                               "다시 클릭: 빼기 · 더블클릭: 크게 보기\n"
                               "Ctrl+클릭: 두 번째 사진(②) 선택/해제 — 비교 · 디스크 2장 · "
                               "오른쪽 클릭: 환자 지정·다시 분석"))
        self.thumbs.viewport().installEventFilter(self)
        self.thumbs.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.thumbs.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._thumb_wheel = motion.SmoothWheel(self.thumbs)      # the wheel glides through the photos
        self.thumbs.currentItemChanged.connect(lambda cur, _: cur and self._show_image(cur.data(Qt.ItemDataRole.UserRole)))
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        # 16장 보기 (VK-2 방식): the photos of the strip, 16 on one screen — picked the same way
        self.grid = PhotoGrid()
        self.grid.setToolTip(keys("클릭: 멀티로 고르기(번호) · 다시 클릭: 빼기 · 더블클릭: 크게 보기 · "
                                  "Ctrl+클릭: 두 번째 사진(②)\n골랐으면 [멀티]: 고른 사진만 다중 보기로 · "
                                  "휠: 다음 / 이전 16장"))
        self.grid.pressed.connect(lambda iid: self._press_photo(iid, stay=True))
        self.grid.activated.connect(self._open_photo)
        self.grid.secondPicked.connect(self._pick_second)
        self.grid.menuRequested.connect(self._photo_menu)
        self.grid.pageChanged.connect(self._sync_grid_bar)
        self._thumb_rows = 0
        self._set_thumb_rows(getattr(self.settings, "thumb_rows", 2) or 2)
        self._sync_picks_ui()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("views")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()                # the views are switched in the line under the photos
        self.view2d = ImageView()
        self.view2d.crossfade = True            # the next photo fades in over the last
        self.view2d.dblclick_loupe = True       # a double click: the loupe on / off
        self.view2d.toggle_captions(True)
        self.view2d.discPicked.connect(self._on_disc_picked)
        self.view2d.foveaPicked.connect(self._on_fovea_picked)
        self.view2d.measured.connect(self._on_measured)
        self.view2d.hovered.connect(lambda t: self.lbl_hover.setText(t))
        self.view2d.clicked.connect(self._stop_slideshow)
        # the 2D page holds view2d — 모두 보기 borrows it (see _place_overview)
        self.page2d = QWidget()
        self._lay2d = QVBoxLayout(self.page2d)
        self._lay2d.setContentsMargins(0, 0, 0, 0)
        self._lay2d.addWidget(self.view2d)
        self.page3d = self._build_3d()
        self.page_all = self._build_overview()
        self.tabs.addTab(self.page_all, "모두 보기")
        self.tabs.addTab(self.page2d, "2D 보기")
        self.tabs.addTab(self.page3d, "3D 안구")
        self.multi = MultiView()
        self.multi.selected.connect(self._select_from_multi)
        self.multi.opened.connect(self.open_large)
        self.multi.layoutChanged.connect(self._on_multi_layout)
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
            v.dblclick_loupe = True
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
        # 검토: both eyes · an eye and its earlier exams (the first tab; the workspace still opens on 모두 보기)
        self.review = ReviewPage(self._load, self._image_path)
        self.review.handOff.connect(self._review_hand_off)
        self.review.status.connect(lambda t: self.lbl_status.setText(t))
        self.tabs.insertTab(0, self.review, "검토")
        self.tabs.addTab(self.grid, "16장 보기")
        self.tabs.setCurrentWidget(self.page_all)
        self._pages = {"review": self.review, "all": self.page_all, "2d": self.page2d, "3d": self.page3d,
                       "multi": self.multi, "cmp": cmp_w, "grid": self.grid}
        self._ov_on = False
        self._tab_fade = motion.Crossfade(self.tabs.findChild(QStackedWidget) or self.tabs)
        self.tabs.tabBar().tabBarClicked.connect(
            lambda i: i != self.tabs.currentIndex() and self._tab_fade.snap())
        self.tabs.currentChanged.connect(self._on_tab)
        # the row above the photos: 화면 분할 (다중 보기 only), then 3D · Montage · Glaucoma
        self.view_bar = QWidget()
        self.view_bar.setObjectName("viewBar")
        vbar = QHBoxLayout(self.view_bar)
        vbar.setContentsMargins(4, 0, 4, 0)
        vbar.setSpacing(4)
        self.multi_bar = self.multi.take_topbar()
        self.multi_bar.hide()                # shown on the 다중 보기 tab (_on_tab)
        vbar.addWidget(self.multi_bar)
        vbar.addSpacing(6)
        for b in (self.btn_3d, self.btn_montage, self.btn_glaucoma):
            vbar.addWidget(b)
        vbar.addStretch(1)
        cl.addWidget(self.view_bar)
        cl.addWidget(self.tabs, 1)
        # 화면 아래 한 줄: 보기 전환(모두 보기 · 다중 보기), 멀티, 그리고 사진 목록 — 3D는 위 줄의 아이콘
        self.lbl_picks.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_buttons = {}
        for key, label, shortcut in TABS:
            if key == "3d":
                self.view_buttons[key] = self.btn_3d
                continue
            vb = QPushButton(label)
            vb.setToolTip(keys(f"{label} ({shortcut})"))
            vb.clicked.connect(lambda _=False, k=key: self._go(k))
            self.view_buttons[key] = vb
        self.view_buttons["grid"].setToolTip(keys("16장 보기 (Ctrl+4) — 이 환자의 사진을 한 화면에 16장씩 (VK-2 방식)\n"
                                                  "클릭해 고르고 [멀티]를 누르면 고른 사진만 다중 보기로 모입니다"))
        self.seg_views = Segmented([self.view_buttons[k] for k in ("grid", "all", "multi")], on_card=False)
        self.seg_views.setFixedWidth(258)
        self.view_buttons["all"].setChecked(True)
        # 16장 보기: the grid is the photo list, so the strip's place shows the grid's pages instead
        self.grid_bar = QWidget()
        self.grid_bar.setObjectName("gridBar")
        gb = QHBoxLayout(self.grid_bar)
        gb.setContentsMargins(12, 4, 12, 4)
        gb.setSpacing(8)
        self.btn_grid_prev = QToolButton()
        self.btn_grid_prev.setText("◀ 이전 16장")
        self.btn_grid_next = QToolButton()
        self.btn_grid_next.setText("다음 16장 ▶")
        for b, d in ((self.btn_grid_prev, -1), (self.btn_grid_next, 1)):
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, d=d: self.grid.set_page(self.grid.page() + d))
        self.lbl_grid_page = QLabel("")
        self.lbl_grid_page.setStyleSheet("font-weight:600")
        lbl_hint = QLabel(keys("클릭: 멀티로 고르기(번호) · 다시 클릭: 빼기 · 더블클릭: 크게 보기 · "
                               "Ctrl+클릭: 두 번째 사진(②)\n골랐으면 [멀티]: 고른 사진만 다중 보기로 — "
                               "다시 여기로 오려면 [16장]"))
        lbl_hint.setStyleSheet(f"color:{theme.TEXT3}")
        gb.addWidget(self.btn_grid_prev)
        gb.addWidget(self.lbl_grid_page)
        gb.addWidget(self.btn_grid_next)
        gb.addSpacing(18)
        gb.addWidget(lbl_hint, 1)
        self.grid_bar.hide()
        strip = QHBoxLayout()
        strip.setSpacing(4)
        side = QGridLayout()
        side.setContentsMargins(8, 4, 6, 4)
        side.setHorizontalSpacing(6)
        side.setVerticalSpacing(4)
        side.addWidget(self.seg_views, 0, 0, 1, 3)
        self.btn_multi.setStyleSheet("padding: 4px 6px;")
        side.addWidget(self.btn_multi, 1, 0, 1, 3)
        self.btn_clear_picks.setStyleSheet("padding: 2px 4px;")
        picks = QHBoxLayout()
        picks.setSpacing(6)
        picks.addWidget(self.btn_rows)
        picks.addStretch(1)
        picks.addWidget(self.lbl_picks)
        picks.addWidget(self.btn_clear_picks)
        side.addLayout(picks, 2, 0, 1, 3)
        side.setRowStretch(3, 1)
        side_w = QWidget()
        side_w.setObjectName("thumbSide")
        side_w.setLayout(side)
        side_w.setFixedWidth(274)
        self._side_w = side_w
        strip.addWidget(side_w)
        strip.addWidget(self.thumbs, 1)
        strip.addWidget(self.grid_bar, 1)
        strip.setContentsMargins(0, 0, 0, 0)
        self.strip_w = QWidget()         # hidden on the 검토 tab (its timeline lists the photos there)
        self.strip_w.setLayout(strip)
        cl.addWidget(self.strip_w)
        self._place_overview(True)       # 처음은 모두 보기

        self.setCentralWidget(centre)
        # the patient list: a window of its own (VK-2 OPEN LIST), the only list of patients
        self.patient_list = PatientListWindow(self.db, self)
        self.patient_list.patientSelected.connect(self._pick_patient)
        self.patient_list.openRequested.connect(self.open_patient)
        self.patient_list.photoRequested.connect(self._open_listed_photo)
        self.patient_list.examChecked.connect(self._on_exam_checked)
        self.patient_list.editRequested.connect(self._edit_patient)
        self.patient_list.deleteRequested.connect(self._delete_patient)
        self.patient_list.importRequested.connect(self._import_files)
        self.patient_list.filesDropped.connect(self.review_import)
        self.patient_list.shown.connect(lambda on: self.acts["list"].setChecked(on))
        self.review.examPicked.connect(self.patient_list.set_exam)

        # -- VK-2 toolbars ---------------------------------------------------------------
        self.tb_cmd = self._toolbar("cmdbar", "명령 툴바", Qt.ToolBarArea.LeftToolBarArea, COMMANDS, 26)
        self.tb_proc = self._toolbar("procbar", "영상 처리 툴바", Qt.ToolBarArea.BottomToolBarArea, PROCESSING, 28)
        self.tb_proc.visibilityChanged.connect(lambda v: self.acts["tools"].setChecked(v))
        self.acts["tools"].setChecked(True)
        self.acts["list"].setChecked(False)
        self.pop_gamma = SliderPopup("감마", 20, 400, 100, lambda v: f"{v / 100:.2f}", self)
        self.pop_contrast = SliderPopup("대비", 10, 300, 100, lambda v: f"{v}%", self)
        self.pop_bright = SliderPopup("밝기", -100, 100, 0, lambda v: f"{v:+d}", self)
        self.s_gamma, self.s_contrast, self.s_bright = (
            p.slider for p in (self.pop_gamma, self.pop_contrast, self.pop_bright))
        for p in (self.pop_gamma, self.pop_contrast, self.pop_bright):
            p.slider.valueChanged.connect(self._schedule_adjust)
            p.pressed.connect(self._push_history)
        self._build_menus()
        mb = self.menuBar()
        self._line_in_menubar = not mb.isNativeMenuBar()
        if self._line_in_menubar:
            mb.setCornerWidget(self.top_w, Qt.Corner.TopRightCorner)
            mb.installEventFilter(self)
        else:                                    # the system's menu bar (Mac): a row of its own
            self._centre_lay.insertWidget(0, self.top_w)
        # (16장 보기 is the photo list itself: the strip stays away there)
        self.act_thumbs.toggled.connect(lambda on: self.thumbs.setVisible(on and self._tab() != "grid"))
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
        # what just happened / what to do next: cut with … (the whole text in the tool tip) rather than
        # making the window wider — a long hint must never set the window's smallest width
        self.lbl_status = ElidedLabel("")
        self.lbl_status.PAD = 4
        self.lbl_measure = QLabel("")
        self.lbl_measure.setObjectName("measure")
        self.lbl_measure.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_measure.hide()
        self.lbl_hover = QLabel("")
        self.lbl_hover.setStyleSheet(f"color:{theme.TEXT3}")
        sb.addWidget(self.lbl_watch)
        self.lbl_share = QLabel("")               # server: the address the other computers connect to
        self.lbl_share.setStyleSheet(f"color:{theme.GREEN}; font-weight:600")
        self.lbl_share.hide()
        sb.addWidget(self.lbl_share)
        self._share_busy = False
        self._share_timer = QTimer(self, timeout=self._poll_share)
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
        self._apply_open_view()                      # 설정 → 일반 → 환자를 열면 (16장 보기 or not)

    def _build_3d(self) -> QWidget:
        """3D tab: the eye, a slim bar with the main choices and actions above it, and the settings in
        grouped cards beside it (each control under the heading it belongs to)."""
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        main = QWidget()
        lay = QVBoxLayout(main)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("bar3d")
        top = QHBoxLayout(bar)
        top.setContentsMargins(10, 6, 10, 6)
        top.setSpacing(8)

        # -- the viewpoint (the look, 자세히 / 간단히, is in 설정 → 일반 → 3D 모형) -----------------------
        self.r_out = segment("외부", "안구 모형을 바깥에서 봅니다")
        self.r_in = segment("내부", "동공을 지나 안으로 들어가 망막을 바라봅니다 (망막 시점)")
        self.seg_mode = Segmented([self.r_out, self.r_in], on_card=False)
        self.r_out.setChecked(True)
        self.r_out.toggled.connect(self._on_3d_mode)

        # -- how the eye is opened (outside): the front cut, or cut along the photo's vertical
        # meridian and seen from the side; the slider sets the depth of either (right end = closed)
        self.c_view3d = QComboBox(w)            # the choice itself (the two segments show and set it)
        self.c_view3d.hide()
        tips = {"front": "앞부분을 잘라 안쪽 망막을 봅니다 (깊이 슬라이더: 자르는 깊이)",
                "section": "사진의 세로 자오선을 따라 안구를 잘라 옆에서 봅니다 — 공막·맥락막·망막 층, "
                           "홍채·수정체·각막 단면과 화각 (깊이 슬라이더 왼쪽 끝 = 정확히 반)"}
        self._view_buttons = {}
        for label, key in (("앞쪽 절개", "front"), ("세로 단면", "section")):
            self.c_view3d.addItem(label, key)
            self.c_view3d.setItemData(self.c_view3d.count() - 1, tips[key], Qt.ItemDataRole.ToolTipRole)
            b = segment(label, tips[key])
            b.clicked.connect(lambda _=False, k=key: self.c_view3d.setCurrentIndex(self.c_view3d.findData(k)))
            self._view_buttons[key] = b
        self.seg_view = Segmented(list(self._view_buttons.values()))
        self._view_buttons["front"].setChecked(True)
        self.c_view3d.currentIndexChanged.connect(lambda _: (self._sync_view_buttons(),
                                                             self._set_3d_view(self.c_view3d.currentData())))
        self._cut_values = {"front": 25, "section": 0}
        self.s_cut = QSlider(Qt.Orientation.Horizontal)
        self.s_cut.setRange(-30, 100)
        self.s_cut.setValue(25)
        self.s_cut.setMinimumWidth(120)
        self.s_cut.setToolTip("자르는 깊이 (오른쪽 끝 = 닫힌 안구)")
        self.s_cut.valueChanged.connect(self._on_cut)
        self.s_glass = QSlider(Qt.Orientation.Horizontal)
        self.s_glass.setRange(0, 100)
        self.s_glass.setValue(int(self.settings.glass3d))
        self.s_glass.setMinimumWidth(120)
        self.s_glass.setToolTip("공막을 유리처럼 비쳐 보이게 합니다 — 사진이 있는 망막은 진하게 남아, 안구를 돌리면 "
                                "안쪽 망막이 입체로 보입니다 (왼쪽 끝 = 불투명한 흰 공막)")
        self.s_glass.valueChanged.connect(self._on_glass)
        self.c_xray3d = Switch("망막 투시")
        self.c_xray3d.setToolTip("공막·맥락막 바깥 면에 망막의 사진을 그대로 비춰 봅니다 "
                                 "(바깥에서 보므로 좌우가 뒤집혀 보입니다)")
        self.c_xray3d.toggled.connect(self._on_xray)

        # -- 망막 입체: the retina's relief (relief.py) and the light on it -----------------------
        self.c_surface3d = Switch("표면 높낮이")
        self.c_surface3d.setToolTip("혈관은 솟고, 시신경 유두의 함몰(cup)과 황반의 오목(pit)은 파이도록 사진이 얹힌 "
                                    "망막 표면을 실제로 올리고 내립니다 — 돌려 보면 높낮이가 보입니다 (자세히 보기)\n"
                                    "꺼 두면(기본) 촬영한 사진 그대로 망막에 얹습니다")
        self.c_surface3d.setChecked(bool(self.settings.surface3d))
        self.c_surface3d.toggled.connect(self._on_surface)
        self.s_height3d = QSlider(Qt.Orientation.Horizontal)
        self.s_height3d.setRange(0, 100)
        self.s_height3d.setValue(int(self.settings.surface_height3d))
        self.s_height3d.setMinimumWidth(120)
        self.s_height3d.setToolTip("높낮이를 얼마나 크게 보일지 (실제보다 과장해서 보여 줍니다)")
        self.s_height3d.valueChanged.connect(self._on_height)
        self.c_simple3d = Switch("단순하게 보기")
        self.c_simple3d.setToolTip("공막·홍채·수정체·시신경을 단순한 모양과 색으로 그려 사진이 얹힌 망막과 그 입체가 "
                                   "잘 보이게 합니다 (자세히 보기)")
        self.c_simple3d.setChecked(bool(self.settings.simple3d))
        self.c_simple3d.toggled.connect(self._on_simple)

        # -- effects ---------------------------------------------------------------------------
        self.c_relief3d = Switch("입체 조명")
        self.c_relief3d.setToolTip("표면의 높낮이에 비스듬한 빛을 비춰 혈관과 유두·황반이 도드라져 보이게 합니다 "
                                   "(안구를 돌리면 빛이 따라 움직입니다)\n"
                                   "꺼 두면(기본) 사진의 밝기를 바꾸지 않습니다")
        self.c_relief3d.setChecked(bool(self.settings.relief3d))
        self.c_relief3d.toggled.connect(self._on_relief)
        self.c_spin3d = Switch("자동 회전")
        self.c_spin3d.setToolTip("손을 떼고 있으면 안구가 천천히 돕니다 (만지면 멈췄다가 다시 돕니다)")
        self.c_spin3d.setChecked(bool(self.settings.auto_rotate3d))
        self.c_spin3d.toggled.connect(self._on_spin)
        self.c_fov3d = Switch("화각 표시")
        self.c_fov3d.setToolTip("세로 단면에는 안구 중심에서 잰 화각(선·각도), 다른 보기에는 망막 위 촬영 범위의 경계")
        self.c_fov3d.toggled.connect(self._on_fov_marks)
        self.c_side3d = Switch("사진 나란히")
        self.c_side3d.setToolTip("3D 안구 오른쪽에 사진을 평면으로 함께 보여 줍니다 (검은 바탕)")
        self.c_side3d.toggled.connect(self._on_side_photo)

        # -- what is shown -----------------------------------------------------------------------
        self.c_nerve = Switch("시신경")
        self.c_nerve.setChecked(True)
        self.c_nerve.toggled.connect(lambda on: (setattr(self.eye3d, "show_nerve", on), self.eye3d.update()))
        self.c_muscle = Switch("외안근")
        self.c_muscle.setToolTip("네 곧은근과 두 빗근의 부착부(절단면)를 함께 표시")
        self.c_muscle.toggled.connect(lambda on: (setattr(self.eye3d, "show_muscles", on), self.eye3d.update()))
        self.c_grid = Switch("각도 격자")
        self.c_grid.setToolTip("후극에서 10°마다 링 (30°마다 진하게)")
        self.c_grid.toggled.connect(lambda on: (setattr(self.eye3d, "show_grid", on), self.eye3d.update()))
        self.c_adj3d = Switch("영상 처리 적용")
        self.c_adj3d.setToolTip("2D에서 조정한 밝기·대비·필터를 3D의 사진에도 적용 (끄면 찍은 그대로)")
        self.c_adj3d.setChecked(False)
        self.c_adj3d.toggled.connect(lambda _: self._mark_3d_dirty())

        # -- how the photo lies on the retina ------------------------------------------------------
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
        for wdg in (self.sp_fov, self.c_fovtype, self.c_proj, self.sp_roll):
            wdg.setFixedWidth(148)
        b_save_map = QPushButton("화각·투영 저장")
        b_save_map.setObjectName("plain")
        b_save_map.setToolTip("이 사진의 화각·투영을 저장해 다음에도 이대로 엽니다")
        b_save_map.clicked.connect(self._save_mapping)
        self.c_align3d = Switch("실제 위치에 맞춤")
        self.c_align3d.setToolTip("사진의 황반을 안구 뒤쪽 한가운데(후극)에, 시신경 유두를 코쪽 제자리에 오도록 사진을 얹습니다 —\n"
                                  "사진 중심이 황반이 아니어도(유두 중심 · 주변부 촬영) 망막의 실제 위치에 놓입니다.\n"
                                  "황반·유두를 잘못 찾았으면 2D 사진에서 오른쪽 클릭으로 직접 지정하세요. 끄면 사진 중심을 후극에 둡니다.")
        self.c_align3d.setChecked(self.settings.align3d)
        self.c_align3d.toggled.connect(self._on_align)
        self.b_fit_fov = QPushButton("황반–유두 거리로 크기 맞춤")
        self.b_fit_fov.setObjectName("plain")
        self.b_fit_fov.setToolTip("화각을 모르는 사진: 황반과 시신경 유두 사이가 보통 거리(약 4.5 mm)가 되도록 화각을 정합니다\n"
                                  "(이 거리는 사람마다 조금 다르므로 대략 맞춰집니다 — 장비의 화각을 알면 그 값을 쓰세요)")
        self.b_fit_fov.clicked.connect(self._fit_fov)
        self.lbl_3d = QLabel("")
        self.lbl_3d.setObjectName("caption")
        self.lbl_3d.setWordWrap(True)

        # -- the bar: the main choices on the left, the actions on the right --------------------------
        # 슬릿 스캔: the photo flat next to the eye and the scan presentation
        self.b_scan = QPushButton("▶ 슬릿 스캔")
        self.b_scan.setObjectName("scan3d")
        self.b_scan.setToolTip("슬릿이 고른 방향으로 사진을 훑는 동안 안구에서 같은 망막 위치를 보여 줍니다 — 위아래는 "
                               "옆에서 본 세로 단면에서 빛이 동공을 지나 망막에 닿는 모습, 좌우는 앞을 연 안구의 망막 "
                               "위로 (사진 나란히). 안구를 누르거나 돌리면 멈춥니다.")
        self.b_scan.clicked.connect(self._toggle_scan)
        self.b_full3d = QPushButton("크게 보기")
        self.b_full3d.setToolTip("3D 안구와 사진을 화면 전체로 (Esc: 돌아가기 · Space: 슬릿 스캔)")
        self.b_full3d.clicked.connect(self._toggle_full_3d)
        self.eye3d = EyeView()
        self.eye3d.setToolTip("드래그: 회전 · 휠: 커서 쪽으로 확대 · 오른쪽 드래그: 확대 · "
                              "가운데/Shift+드래그: 이동 · +/−: 확대·축소 · 더블클릭·0: 처음 보기")
        self.lbl_zoom3d = QLabel("배율 ×1.0")
        self.lbl_zoom3d.setObjectName("hint3d")
        self.lbl_zoom3d.setToolTip("처음 보기 대비 확대 배율 · 더블클릭 또는 0: 처음 보기")
        self.eye3d.zoomChanged.connect(lambda m: self.lbl_zoom3d.setText(f"배율 ×{m:.1f}"))
        self.eye3d.glError.connect(self._on_gl_error)
        self.b_inspector = QPushButton("설정")
        self.b_inspector.setObjectName("toggle")
        self.b_inspector.setCheckable(True)
        self.b_inspector.setChecked(True)
        self.b_inspector.setToolTip("오른쪽 설정 패널 보이기 / 숨기기")
        top.addWidget(self.seg_mode)
        top.addWidget(self.lbl_zoom3d)
        top.addStretch(1)
        top.addWidget(self.b_scan)
        top.addWidget(self.b_full3d)
        top.addWidget(self.b_inspector)
        view_row = QWidget()
        vr = QHBoxLayout(view_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.setSpacing(6)
        for label, tip, fn in (("정면", "정면에서 보기", lambda: self.eye3d.front_view(animate=True)),
                               ("처음 시점", "처음 시점으로 (더블클릭 · 0)",
                                lambda: self.eye3d.reset_view(animate=True)),
                               ("화면 저장…", "지금 보이는 3D 화면을 그림으로 저장", self._save_3d)):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            vr.addWidget(b, 1)
        self.eye3d.relief = self.RELIEF if self.settings.relief3d else 0.0
        self.eye3d.glass = self.settings.glass3d / 100.0
        self.eye3d.relief_on = bool(self.settings.surface3d)
        self.eye3d.relief_amount = self.settings.surface_height3d / 100.0 * self.HEIGHT_MAX
        self.eye3d.simple = 1.0 if self.settings.simple3d else 0.0
        self.s_height3d.setEnabled(self.c_surface3d.isChecked())
        self.eye3d.journeyChanged.connect(self._on_journey)
        self._where = _WhereChip(self.eye3d)

        # 들어가며 보기: from the whole eye through the cornea, the pupil and the lens to the retina
        self.b_journey = QPushButton("▶ 들어가기")
        self.b_journey.setObjectName("scan3d")
        self.b_journey.setToolTip("안구 전체에서 각막·앞방·동공·수정체·유리체를 지나 망막까지 들어갑니다 "
                                  "(다시 누르면 나옵니다 · 자세히 보기)")
        self.b_journey.clicked.connect(self._play_journey)
        journey_note = QLabel("각막 → 동공 → 수정체 → 망막")
        journey_note.setObjectName("caption")
        journey_row = QWidget()
        jr = QHBoxLayout(journey_row)
        jr.setContentsMargins(0, 0, 0, 0)
        jr.setSpacing(8)
        jr.addWidget(self.b_journey)
        jr.addWidget(journey_note, 1)
        self.s_journey = QSlider(Qt.Orientation.Horizontal)
        self.s_journey.setRange(0, 100)
        self.s_journey.setMinimumWidth(120)
        self.s_journey.setToolTip("왼쪽 끝 = 안구 전체, 오른쪽 끝 = 망막 (끌어서 원하는 곳에서 멈춰 보세요)")
        self.s_journey.valueChanged.connect(self._scrub_journey)

        # 슬릿 스캔: which way the slit crosses the photo
        self._slit_buttons = {}
        for key, label, tip in (("down", "↓", "위에서 아래로 (세로 단면)"), ("up", "↑", "아래에서 위로 (세로 단면)"),
                                ("right", "→", "왼쪽에서 오른쪽으로 (앞을 연 안구의 망막 위로)"),
                                ("left", "←", "오른쪽에서 왼쪽으로 (앞을 연 안구의 망막 위로)"),
                                ("all", "상하좌우", "위↓ 아래↑ 왼→ 오른← 네 방향을 차례로")):
            b = segment(label, tip)
            b.clicked.connect(lambda _=False, k=key: self._on_slit_dir(k))
            self._slit_buttons[key] = b
        self.seg_slit = Segmented(list(self._slit_buttons.values()))
        self.lbl_slit = QLabel("")
        self.lbl_slit.setObjectName("caption")
        self.lbl_slit.setWordWrap(True)

        # 슬릿 스캔: the button in its card too (as the bar's)
        self.b_scan2 = QPushButton("▶ 슬릿 스캔")
        self.b_scan2.setObjectName("scan3d")
        self.b_scan2.setToolTip(self.b_scan.toolTip())
        self.b_scan2.clicked.connect(self._toggle_scan)

        # 사진: the photo on the eye — its device and eye, the disc and the macula found automatically
        # (or marked here), as in the web page
        self.lbl_photo3d = QLabel("")
        self.lbl_photo3d.setObjectName("caption")
        self.lbl_photo3d.setWordWrap(True)
        self.c_device3d = QComboBox()
        for key, label in (("generic", "일반 안저카메라 (45°)"), ("reticam", "RetiCam 3100 Plus (176°)"),
                           ("apollo", "APOLLO (135° · 165°)"), ("kowa_vk2", "Kowa VK-2 (45°)")):
            self.c_device3d.addItem(label, key)
        self.c_device3d.setToolTip("장비를 고르면 그 장비의 화각·투영으로 사진을 안구에 얹습니다 (사진 맞춤에서 고칠 수 있음)")
        self.c_device3d.activated.connect(lambda _: self._on_device3d(self.c_device3d.currentData()))
        self.c_eye3d = QComboBox()
        for key, label in (("auto", "자동 (유두 위치로)"), ("OD", "OD · 우안"), ("OS", "OS · 좌안")):
            self.c_eye3d.addItem(label, key)
        self.c_eye3d.setToolTip("이 사진의 눈 — 자동: 시신경 유두와 황반의 위치로 정합니다")
        self.c_eye3d.activated.connect(lambda _: self._on_eye3d(self.c_eye3d.currentData()))
        for wdg in (self.c_device3d, self.c_eye3d):
            wdg.setFixedWidth(170)
        self.c_autofind3d = Switch("황반·유두 자동으로 찾기")
        self.c_autofind3d.setToolTip("사진의 시신경 유두와 황반을 자동으로 찾아 안구의 제자리에 맞춥니다 (사진을 가져올 때 "
                                     "찾아 둔 것) — 끄면 직접 지정한 것만 씁니다")
        self.c_autofind3d.setChecked(bool(self.settings.autofind3d))
        self.c_autofind3d.toggled.connect(self._on_autofind3d)
        self.photo3d = LandmarkPhoto()
        self.photo3d.setToolTip("사진 — 유두(노란 원)와 황반(하늘색 원)")
        self.photo3d.picked.connect(self._on_photo3d_picked)
        self.lbl_found3d = QLabel("")
        self.lbl_found3d.setObjectName("caption")
        self.lbl_found3d.setTextFormat(Qt.TextFormat.RichText)
        self.b_mark_fovea = QPushButton("황반 지정")
        self.b_mark_fovea.setToolTip("자동으로 찾은 위치가 틀렸을 때: 사진에서 황반(중심와)을 눌러 정합니다")
        self.b_mark_disc = QPushButton("유두 지정")
        self.b_mark_disc.setToolTip("자동으로 찾은 위치가 틀렸을 때: 사진에서 시신경 유두를 눌러 정합니다")
        for b, what in ((self.b_mark_fovea, "fovea"), (self.b_mark_disc, "disc")):
            b.setObjectName("toggle")              # grey, blue while on (as the page's small buttons)
            b.setCheckable(True)
            b.clicked.connect(lambda on, w=what: self._set_marking3d(w if on else None))
        self.b_redetect3d = QPushButton("다시 찾기")
        self.b_redetect3d.setToolTip("직접 정한 위치를 지우고 자동으로 다시 찾습니다")
        self.b_redetect3d.clicked.connect(self._redetect3d)
        fix_row = QWidget()
        fr = QHBoxLayout(fix_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(6)
        fix_note = QLabel("고치기")
        fix_note.setObjectName("caption")
        fr.addWidget(fix_note)
        fr.addStretch(1)
        for b in (self.b_mark_fovea, self.b_mark_disc, self.b_redetect3d):
            fr.addWidget(b)
        self.lbl_mark3d = QLabel("")
        self.lbl_mark3d.setObjectName("caption")
        self.lbl_mark3d.setWordWrap(True)
        self.lbl_mark3d.setStyleSheet("color: #64d2ff;")
        self.lbl_mark3d.hide()
        self._marking3d: str | None = None

        # 조작: how to handle the eye (as the page's card)
        keys_label = QLabel("<b>드래그</b> 회전 (놓으면 관성으로 더 돕니다) · <b>휠</b> 커서 쪽으로 확대 · "
                            "<b>오른쪽 드래그</b> 확대<br><b>Shift+드래그</b> 또는 <b>가운데 버튼</b> 이동 · "
                            "<b>더블클릭</b> 처음 보기 · <b>←↑→↓ + − 0</b><br><b>트랙패드</b> 두 손가락 벌리기·오므리기 확대")
        keys_label.setObjectName("caption")
        keys_label.setWordWrap(True)
        keys_label.setTextFormat(Qt.TextFormat.RichText)

        # -- the settings beside the eye: cards, in the web page's order -----------------------------
        body = QWidget()
        body.setObjectName("inspectorBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 10, 12, 12)
        bl.setSpacing(12)
        bl.addWidget(card("사진", self.lbl_photo3d, setting_row("장비", self.c_device3d), setting_row("눈", self.c_eye3d),
                          self.c_autofind3d, self.photo3d, self.lbl_found3d, fix_row, self.lbl_mark3d))
        bl.addWidget(card("망막 입체", self.c_surface3d, setting_row("높이", self.s_height3d), self.c_relief3d))
        bl.addWidget(card("시점", view_row))
        bl.addWidget(card("들어가며 보기", journey_row, setting_row("위치", self.s_journey)))
        bl.addWidget(card("안구 열기", self.seg_view, setting_row("깊이", self.s_cut), setting_row("공막 투명도", self.s_glass),
                          self.c_xray3d))
        bl.addWidget(card("슬릿 스캔", self.seg_slit, self.lbl_slit, self.b_scan2))
        bl.addWidget(card("효과", self.c_spin3d, self.c_fov3d, self.c_side3d))
        bl.addWidget(card("표시", self.c_simple3d, self.c_nerve, self.c_muscle, self.c_grid, self.c_adj3d))
        bl.addWidget(card("사진 맞춤", self.c_align3d, setting_row("화각", self.sp_fov),
                          setting_row("화각 기준", self.c_fovtype), setting_row("투영", self.c_proj),
                          setting_row("회전", self.sp_roll), self.b_fit_fov, b_save_map))
        bl.addWidget(self.lbl_3d)
        bl.addWidget(card("조작", keys_label))
        bl.addStretch(1)
        self.inspector = QScrollArea()
        self.inspector.setObjectName("inspectorScroll")
        self.inspector.setWidgetResizable(True)
        self.inspector.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector.setWidget(body)
        self.inspector.setFixedWidth(320)
        self.b_inspector.toggled.connect(self.inspector.setVisible)
        self._inspector_wheel = motion.SmoothWheel(self.inspector, step=72.0)

        self.scan_photo = ScanPhotoView()
        self.scan_photo.hide()
        self.split3d = QSplitter(Qt.Orientation.Horizontal)
        self.split3d.setChildrenCollapsible(False)
        self.split3d.addWidget(self.eye3d)
        self.split3d.addWidget(self.scan_photo)
        self.split3d.setStyleSheet("QSplitter::handle { background: #000; }")
        self._show = SlitScanShow(self.eye3d, self.scan_photo, self)
        self._show.finished.connect(self._on_scan_finished)
        self._show.stopped.connect(self._on_scan_stopped)
        self._show.passChanged.connect(self._where.say)
        self._on_slit_dir(self.settings.slit_dir3d if self.settings.slit_dir3d in self._slit_buttons else "down",
                          save=False)
        self._tween = ViewTween(self.eye3d, self)
        self._full3d: QWidget | None = None
        self._set_3d_detail(self.settings.view3d_detail, save=False)
        lay.addWidget(bar)
        self._lay3d = lay
        lay.addWidget(self.split3d, 1)
        outer.addWidget(main, 1)
        outer.addWidget(self.inspector)
        return w

    def _sync_view_buttons(self) -> None:
        """The 앞쪽 절개 / 세로 단면 segments show what the (hidden) selector holds."""
        b = self._view_buttons.get(self.c_view3d.currentData())
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def _on_glass(self, v: int) -> None:
        self.settings.glass3d = int(v)
        self.eye3d.glass = v / 100.0
        self.eye3d.update()

    def _reset_toolbars(self) -> None:
        for tb, area in ((self.tb_cmd, Qt.ToolBarArea.LeftToolBarArea),
                         (self.tb_proc, Qt.ToolBarArea.BottomToolBarArea)):
            self.addToolBar(area, tb)
            tb.setVisible(True)

    def _show_help(self) -> None:
        QMessageBox.information(self, "마우스·단축키", keys(
            "<b>사진 보기</b><br>"
            "마우스 확대·축소는 휠로만: 커서 위치를 중심으로 (Mac 트랙패드는 두 손가락 벌리기·오므리기)<br>"
            "왼쪽 드래그: 사진 이동 (길이·각도 같은 도구를 쓰는 중에는 가운데 버튼 드래그)<br>"
            "+/−: 확대·축소 · 0: 화면 맞춤 · 1: 100%<br>"
            "확대하면 오른쪽 위 미니맵에 전체 사진과 보이는 곳이 나옵니다 — 눌러서 이동<br>"
            "화면 맞춤 ▾ 또는 아래쪽 [배율]: 400·800%, 후극부·위/아래/코/귀쪽 주변부로 바로 확대<br>"
            "더블클릭: 돋보기 켜기·끄기 (마우스를 따라다님, Esc로도 끔)<br>"
            "오른쪽 클릭: 메뉴 (시신경 유두 · 황반 위치 지정, 돋보기 배율, 미니맵)<br><br>"
            "<b>3D 안구</b><br>"
            "위 막대: 간단히 / 자세히 (가벼운 기본 모형 / 실제 해부 구조) · 외부 / 내부 · ▶ 슬릿 스캔 · "
            "크게 보기 · 설정 (오른쪽 패널 열고 닫기)<br>"
            "설정 패널 — <b>망막 입체</b>: 표면 높낮이 · 높이 · 입체 조명 / <b>시점</b>: 정면 · 처음 시점 · 화면 저장 / "
            "<b>들어가며 보기</b>: ▶ 들어가기 · 위치 / <b>안구 열기</b>: 앞쪽 절개 · 세로 단면, 깊이, 공막 투명도, "
            "망막 투시 / <b>슬릿 스캔</b>: 방향 ↓ ↑ → ← · 상하좌우 / <b>효과</b>: 자동 회전 · 화각 표시 · 사진 나란히 / "
            "<b>표시</b>: 단순하게 보기 · 시신경 · 외안근 · 각도 격자 / <b>사진 맞춤</b>: 실제 위치에 맞춤 · 화각 · "
            "투영 · 회전<br>"
            "사진 맞춤 → 실제 위치에 맞춤: 사진의 황반을 안구 뒤쪽 한가운데(후극)에, 시신경 유두를 코쪽 제자리에 "
            "오도록 얹습니다 — 잘못 찾았으면 2D 사진에서 오른쪽 클릭으로 황반·유두를 직접 지정<br>"
            "공막 투명도: 공막이 유리처럼 비쳐 보이고, 사진이 있는 망막은 진하게 그대로 남습니다 "
            "(0 = 흰 공막) — 안구를 돌리면 망막이 안구 속 어디에 있는지 보입니다<br>"
            "▶ 슬릿 스캔: 위아래는 단면에 화각 → 슬릿이 사진을 훑으며 빛이 동공을 지나 망막에, 좌우는 앞을 연 안구의 "
            "망막 위로 → 사진을 입힌 3D 안구 (누르면 멈춤) · 크게 보기: 화면 전체 (Space 재생, Esc 돌아가기)<br>"
            "드래그: 회전 (돌리다 놓으면 관성으로 더 돕니다) · 휠: 커서가 가리키는 곳으로 확대 · "
            "가운데 버튼 또는 Shift+드래그: 이동<br>"
            "+/−: 확대·축소 · 더블클릭 또는 0: 처음 보기<br>"
            "망막 입체: 표면 높낮이 — 혈관은 솟고 유두 함몰·황반 오목은 파여 보임, 입체 조명 — 그 높낮이에 비스듬한 빛 · "
            "단순하게 보기: 공막·홍채·수정체·시신경을 단순하게 그려 망막을 강조 · "
            "자동 회전: 손을 떼고 있으면 천천히 돕니다<br>"
            "들어가며 보기 · 내부: 안구 전체에서 각막 → 앞방 → 동공 → 수정체 → 유리체 → 망막까지 끊김 없이 들어갑니다 "
            "(위치 막대로 원하는 곳에서 멈춤)<br>"
            "보기 → 부드러운 움직임: 끄면 확대·회전·전환이 바로 바뀝니다 (원격 접속 등 느린 화면)<br><br>"
            "<b>단축키</b><br>"
            "PageUp / PageDown: 이전 / 다음 사진 · Ctrl+1: 모두 보기 · Ctrl+2: 다중 보기 · Ctrl+3: 3D · "
            "Ctrl+4: 16장 보기 (VK-2 방식일 때) · Ctrl+0: 환자 목록<br>"
            "Ctrl+Z: 처리 실행 취소 · Delete: 마지막 측정 지우기 · Ctrl+C: 화면 복사<br>"
            "Ctrl+F: 환자 검색 · Ctrl+P: 인쇄<br><br>"
            "<b>환자 목록 (따로 뜨는 창, 처음에 나옴)</b><br>"
            "검색 조건: 환자 ID · 이름 · 생년월일 · 검사일(전체 · 오늘 · 최근 7일 · 기간) · 열 제목을 누르면 정렬<br>"
            "환자를 한 번 누르면 오른쪽에 검사 목록과 사진 16장 · 두 번 누르거나 Enter: 사진 보기 "
            "(설정 → 일반 → 환자를 열면: 최신 OD | OS 두 장 · VK-2 방식 16장) · 사진을 누르면 크게 · Esc: 닫기<br>"
            "다시 열기: 명령 툴바의 [환자 목록] · 메뉴 줄의 [환자 목록] · Ctrl+0 · 환자 검색(Ctrl+F)<br><br>"
            "<b>모두 보기</b><br>"
            "큰 사진 + 오른쪽에 황반과 시신경 유두를 확대해 보여 줍니다 (큰 사진 위 점선 틀이 그 자리)<br>"
            "칸 제목이나 칸을 더블클릭하면 큰 사진을 그 쪽으로 확대 · 큰 사진 전체로: 0<br>"
            "잘못 찾았으면 큰 사진에서 오른쪽 클릭 → 황반 / 시신경 유두로 지정<br>"
            "화면 아래 줄의 [모두 보기 | 다중 보기] 로 보기를 바꿉니다 · 사진 위 줄: [3D] · [Montage] · [Glaucoma]<br><br>"
            "<b>사진 목록 · 멀티</b><br>"
            "위 줄 OD · 아래 줄 OS (줄마다 최신 사진부터), 사진마다 왼쪽 위에 눈(OD 파랑 · OS 주황) · "
            "▤ 버튼: 눈별 / 한 줄 · 미상 사진은 눈 고르기 → 미상<br>"
            "클릭: 다중 보기에 더하기(번호) — 1장 · 2장 · 4칸 · 6칸 … 고른 장수에 맞게 화면이 저절로 나뉩니다<br>"
            "다시 클릭: 빼기 · 더블클릭: 그 사진을 크게 · [멀티]: 고른 사진의 다중 보기로 돌아가기<br>"
            "다중 보기에서 칸을 누르면 그 사진만 보정 (밝기·대비·감마·Red-free·선명하게 …)<br><br>"
            "<b>16장 보기 (VK-2 방식)</b><br>"
            "설정 → 일반 → 환자를 열면: VK-2 방식을 고르면 환자를 열 때 사진 16장이 한 화면에 나옵니다<br>"
            "클릭: 고르기(번호) · [멀티]: 고른 사진만 다중 보기로 · 더블클릭: 크게 · [16장]: 다시 16장으로 · "
            "휠 · ◀ ▶: 다음 / 이전 16장<br><br>"
            "<b>두 사진 고르기 · 디스크 2장</b><br>"
            "두 번째 사진을 Ctrl+클릭(②, 다시 Ctrl+클릭하면 해제) → [디스크 2장] · [녹내장](스테레오 · 경과 비교)<br>"
            "[디스크 2장]: 두 사진의 시신경 유두만 확대해 한 장으로 (OD 왼쪽 · OS 오른쪽, 보험 청구용)<br><br>"
            "<b>여러 컴퓨터에서 함께 쓰기</b><br>"
            "설정 → 공유: 서버(이 컴퓨터의 자료를 함께 쓰기) · 서버에 연결(다른 컴퓨터의 자료 보기) · "
            "웹 브라우저로 http://서버주소:8765<br><br>"
            "<b>사진 가져오기</b><br>"
            f"자동입니다. 레티캠 등 장비 폴더와 가져오기 폴더 [{self.settings.inbox}]를 감시해 "
            "새 사진의 환자 ID·이름을 읽고 환자별로 정리합니다. 폴더는 설정에서 바꾸거나 더할 수 있습니다."
            + ("<br><br><b>맥</b><br>⌘ = Ctrl · 트랙패드: 두 손가락 스크롤 또는 벌리기/오므리기로 확대·축소, "
               "두 손가락 클릭 = 오른쪽 클릭 · PageUp/PageDown = fn+↑/fn+↓ · 지우기 = delete(⌫)"
               if IS_MAC else "")))

    # =====================================================================
    # startup / watching
    # =====================================================================
    def _startup(self) -> None:
        # Automatic import: the inbox + the capture software's folders. Drive
        # probing can block on a disconnected network drive -> worker thread.
        import threading
        if self._closing:                       # closed before the first 200 ms were over
            return
        self._apply_share()
        if self.remote:                         # the server watches the cameras' folders
            if self.settings.last_patient and self._patient_ref is None:
                self._select_patient_id(self.settings.last_patient)
            return
        auto = self.settings.auto_detect
        threading.Thread(target=lambda: self.bridge.detected.emit(autosetup.detect() if auto else []),
                         name="fundus-autosetup", daemon=True).start()
        if self.settings.last_patient and self._patient_ref is None:   # (not when one was picked already)
            self._select_patient_id(self.settings.last_patient)

    def _on_detected(self, found) -> None:
        if self._closing:                       # the answer came after the window (and the database) closed
            return
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

    # -- sharing (설정 → 공유, share.py) -----------------------------------------------------------
    def _apply_share(self) -> None:
        """Start / stop answering the other computers (server), or show where this one is connected."""
        if self.share_server is not None:
            self.share_server.stop()
            self.share_server = None
        if self.remote:
            self.act_watch.setEnabled(False)
            self.lbl_watch.setText(f"● 서버 연결: {self.db.host}")
            self.lbl_watch.setToolTip(f"{self.db.url} 의 자료를 보고 있습니다 (설정 → 공유)\n"
                                      "사진 자동 가져오기는 서버 컴퓨터가 합니다")
            self.lbl_watch.setStyleSheet(f"color:{theme.GREEN}; font-weight:600")
            import threading
            threading.Thread(target=self.db.prune_cache, name="fundus-cache", daemon=True).start()
            self._share_timer.start(3000)
            return
        self.lbl_share.hide()
        if self.settings.share_mode != share.MODE_SERVER:
            return
        if not self.settings.share_key:
            self.settings.share_key = share.new_key()
        try:
            self.share_server = share.ShareServer(self.db, self.settings, self.service.importer,
                                                  on_change=self.bridge.shared.emit)
            self.share_server.start()
        except OSError as e:
            self.share_server = None
            self.lbl_status.setText(f"공유를 시작하지 못했습니다 (포트 {self.settings.share_port}): {e}")
            return
        self.lbl_share.setText(f"● 공유 중 {self.share_server.address}")
        self.lbl_share.setToolTip("다른 컴퓨터의 뷰어(설정 → 공유 → 서버에 연결)나 웹 브라우저에서\n"
                                  f"{self.share_server.address} 로 접속합니다 · 접속 암호: {self.settings.share_key}")
        self.lbl_share.show()

    def _poll_share(self) -> None:
        """Connected to a server: has anything changed there? Asked on a worker thread."""
        if self._closing or self._share_busy:
            return
        self._share_busy = True

        def ask():
            try:
                was = self.db.online
                changed = self.db.changed()
                if changed or (self.db.online and not was):
                    self.bridge.shared.emit()
                elif not self.db.online:
                    self.bridge.status.emit(f"서버({self.db.host})에 연결할 수 없습니다 — 다시 연결하는 중")
            except RuntimeError:               # the window is gone
                pass
            finally:
                self._share_busy = False
        import threading
        threading.Thread(target=ask, name="fundus-share-poll", daemon=True).start()

    def _photo_sig(self):
        return (self._patient_ref, tuple((r["id"], r["exam_date"], r["laterality"], r["modality"], r["note"])
                                         for r in self._images()))

    def _on_shared_change(self) -> None:
        """Another computer changed the library: the patient list, and the open patient's photos
        when they are no longer the ones listed."""
        if self._closing:
            return
        self.refresh_patients()
        if self._patient_ref is not None and self._photo_sig() != self._share_sig:
            self._fill_dates()
            self._fill_thumbs(select_id=self.current["id"] if self.current else None)

    def _toggle_watch(self, on: bool) -> None:
        if on:
            errors = self.service.start_watching()
            folders = [f.path for f in self.settings.watch_folders if f.enabled]
            self.lbl_watch.setText(f"● 자동 가져오기 ({len(folders)}개 폴더)")
            self.lbl_watch.setToolTip("감시 중인 폴더:\n" + "\n".join(folders))
            self.lbl_watch.setStyleSheet(f"color:{theme.GREEN}; font-weight:600")
            if errors:
                QMessageBox.warning(self, "폴더 감시", "\n".join(errors))
        else:
            self.service.stop_watching()
            self.lbl_watch.setText("자동 가져오기 꺼짐")
            self.lbl_watch.setToolTip("파일 > 폴더 감시 로 다시 켭니다")
            self.lbl_watch.setStyleSheet(f"color:{theme.TEXT3}")

    def _scan_now(self) -> None:
        import threading
        threading.Thread(target=lambda: self.bridge.status.emit(
            f"검사 완료 — 새 파일 {self.service.scan_all(full=True)}개"), daemon=True).start()

    def _import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self._dialog_parent(), "가져올 사진 파일", "", "영상 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.dcm);;모든 파일 (*)")
        if files:
            self.review_import(files)

    def _import_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self._dialog_parent(), "가져올 폴더")
        if d:
            self.review_import([d])

    def review_import(self, paths: list[str]) -> int:
        """Photos picked by hand (사진 가져오기, 폴더 가져오기, drag & drop): the patient data
        read from them is shown first (확인 창) — the user confirms it, corrects it, or names
        the patient of photos that do not say — and then they are imported. Returns the
        number of photos queued (0: cancelled, or nothing to import)."""
        from .import_dialog import ImportReviewDialog

        dlg = ImportReviewDialog(self.service, self.db, paths, self._dialog_parent(), current_ref=self._patient_ref)
        if dlg.exec() != ImportReviewDialog.DialogCode.Accepted:
            return 0
        n = self.service.import_items(dlg.result_items())
        self.lbl_status.setText(f"{n}개 파일 가져오기 대기" if n else "새로 가져올 사진이 없습니다")
        return n

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            # after the drop has returned: the file manager must not wait for the dialog
            QTimer.singleShot(0, lambda: self.review_import(paths))

    def open_calibration(self) -> None:
        """설정 → 카메라 각도 보정: the lens curve of the wide-field camera from the photos (calibrate.py)."""
        from .calibrate_dialog import CalibrationDialog

        self._calibration_dlg = dlg = CalibrationDialog(self.db, self.settings, self, on_applied=self._lens_changed)
        dlg.exec()

    def _lens_changed(self) -> None:
        """Another lens curve: the photo on screen, its measurements and the 3D eye follow."""
        if self.current is not None:
            self._show_image(self.current["id"])

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            old_lib = str(self.settings.library)
            old_inbox = str(self.settings.inbox)
            old_share = (self.settings.share_mode, self.settings.share_port, self.settings.share_key,
                         self.settings.server_url)
            before = list(self.settings.watch_folders)
            old_view = self.settings.open_view
            dlg.apply()
            self._set_3d_detail(self.settings.view3d_detail, save=False)
            self._apply_open_view()
            if self.settings.open_view != old_view and self.current is not None:
                self._set_default_picks(self.patient_list.current_exam())   # the other way at once:
                self._show_opening()                                        # OD | OS / 16장 보기
            autosetup.remember_removed(self.settings, before)
            if dlg.redetect:
                autosetup.apply(self.settings, autosetup.detect())
            try:   # a new 가져오기 폴더 is watched at once, the old one no longer
                inbox = autosetup.change_inbox(self.settings, old_inbox)
            except OSError as e:
                inbox = None
                QMessageBox.warning(self, "가져오기 폴더", f"가져오기 폴더를 만들 수 없습니다: {e}")
            self.settings.save()
            if str(self.settings.library) != old_lib:
                QMessageBox.information(self, "설정", "라이브러리 폴더 변경은 프로그램을 다시 시작하면 적용됩니다.")
            new_share = (self.settings.share_mode, self.settings.share_port, self.settings.share_key,
                         self.settings.server_url)
            if new_share != old_share:
                if self.remote or self.settings.share_mode == share.MODE_CLIENT:
                    QMessageBox.information(self, "공유", "서버 연결 설정은 프로그램을 다시 시작하면 적용됩니다.")
                else:
                    self._apply_share()       # sharing this computer's library: on / off at once
            if self.remote:
                return
            if self.settings.watch_folders:   # importing is automatic: (re)start watching
                if self.act_watch.isChecked():
                    self._toggle_watch(True)
                else:
                    self.act_watch.setChecked(True)
            if inbox is not None:             # after the restart, whose "폴더 감시 중" would hide it
                self.lbl_status.setText(f"가져오기 폴더: {inbox.path} — 넣은 사진을 바로 가져옵니다")
                self.db.log("info", f"가져오기 폴더 변경: {old_inbox} → {inbox.path}")

    def _on_status(self, text: str) -> None:
        self.lbl_status.setText(text)
        if self._hold_follow and text == "대기 중":          # the held import is through
            if self._result_timer.isActive() or self._results:
                self._hold_release = True                    # its last results are still to be shown
            else:
                self._hold_follow = False

    def hold_follow(self) -> None:
        """Do not follow new photos (새 영상 자동 표시) until the import queued next is through —
        ``--demo`` fills the library at startup and the patient list must stay on screen.
        Call it right before ``service.import_paths``."""
        self._hold_follow, self._hold_release = True, False

    _refresh_cost = 0.0     # seconds the last listing of the patients took (see _on_import_result)

    def _on_import_result(self, res: ImportResult) -> None:
        # Coalesce: a first scan can deliver thousands of results.
        self._results.append(res)
        if not self._result_timer.isActive():
            # … and with thousands of patients listing them takes a while: never more than a
            # fifth of the time goes into showing results, the rest is the user's
            self._result_timer.start(int(min(5000, max(300, 5000 * self._refresh_cost))))

    def _flush_results(self) -> None:
        results, self._results = self._results, []
        imported = [r for r in results if r.status in ("imported", "assigned")]
        errors = [r for r in results if r.status == "error"]
        if imported:
            more = f" 외 {len(imported) - 1}건" if len(imported) > 1 else ""
            self.lbl_status.setText(f"새 영상: {imported[-1].message}  ({Path(imported[-1].path).name}){more}")
        elif errors:
            self.lbl_status.setText(f"오류: {Path(errors[-1].path).name} — {errors[-1].message}")
        t0 = time.perf_counter()
        self.refresh_patients()
        self._refresh_cost = time.perf_counter() - t0
        if self.log.isVisible():
            self._fill_log()
        if not imported:
            return
        last = imported[-1]
        target = last.patient_ref if last.patient_ref is not None else UNASSIGNED
        # Follow only live captures, not a bulk import of an existing archive.
        live = self.service.queued <= 2 and len(imported) <= 4
        if self._hold_follow:                      # see hold_follow: wait until that import is through
            live = False
            if self._hold_release:
                self._hold_follow = self._hold_release = False
        if self.act_follow.isChecked() and live:
            self._select_patient_ref(target)
            if self._picks == self._default_picks:  # not changed by hand: the newest OD | OS, the new one in
                self._set_default_picks()
            self._fill_thumbs(select_id=last.image_id)
            # the new photo is shown, wherever the windows were: the patient list makes way for it
            self.patient_list.hide()
            self._raise_main()
            if self._tab() == "review" and last.image_id not in self.review.slot_ids():
                self._go("all")                    # not one of the two photos under review: the big view
            elif self._tab() == "multi" and last.image_id not in self._picks:
                self._go("all")                    # not on the multi view (unknown eye …): the big view
        elif any((r.patient_ref if r.patient_ref is not None else UNASSIGNED) == self._patient_ref
                 for r in imported):
            self._fill_dates()
            self._fill_thumbs(select_id=self.current["id"] if self.current else None)

    # =====================================================================
    # patients
    # =====================================================================
    def refresh_patients(self) -> None:
        """List the patients again (after an import, an edit, a deletion). The patient on screen stays —
        unless it is gone (deleted, merged into another): then nobody is."""
        self.patient_list.refresh()
        ref = self._patient_ref
        if ref not in (None, UNASSIGNED) and self.db.get_patient(ref) is None:
            self._set_patient(None)

    def _select_patient_ref(self, ref) -> None:
        """Make ``ref`` (UNASSIGNED / ``patients.id`` / None) the patient on screen, in both windows."""
        self._set_patient(ref)

    def _pick_patient(self, ref) -> None:
        """A patient was picked in the patient list: the same patient in both windows — here its
        newest OD | OS on 다중 보기, or 16장 보기 in the VK-2 way (3D stays: it shows the OD photo)."""
        if self._closing or ref == self._patient_ref:
            return
        self._select_patient_ref(ref)
        if self._patient_ref == ref and self._tab() != "3d" and (self._picks or self._grid_mode()):
            self._go("grid" if self._grid_mode() else "multi")

    def open_patient(self, ref, where: str = "all") -> None:
        """[사진 보기] · double click · Enter in the patient list: the patient's photos here, the
        patient list making way for them. ``where`` "all" / "multi" (사진 보기): as 설정 → 일반 →
        환자를 열면 says — the newest OD and OS photo of the selected exam side by side on 다중 보기,
        picked in the strip so that a click adds or takes away photos (without photos of a known eye,
        미분류 …: the exam's photo on 모두 보기), or the VK-2 way: 16장 보기 from the exam's photo.
        ``where`` "3d": that photo in 3D."""
        if ref != self._patient_ref:
            self._select_patient_ref(ref)
        if self._patient_ref != ref or not self._images():
            self.lbl_status.setText("이 환자는 아직 사진이 없습니다 — [사진 가져오기]로 사진을 넣으세요")
            return
        self.patient_list.hide()
        self._raise_main()
        self._set_default_picks(self.patient_list.current_exam())
        if where in ("all", "multi"):
            self._show_opening()
            return
        row = self.patient_list.shortcut_photo()      # the selected exam's photo
        if row is not None:
            self._select_from_multi(row["id"])
        self._go(where)

    def _show_opening(self) -> None:
        """The view a patient opens on (설정 → 일반 → 환자를 열면), the picks made already
        (``_set_default_picks``): its newest OD | OS on 다중 보기 — or, the VK-2 way, 16장 보기 from the
        selected exam's photo; without photos of a known eye that photo on 모두 보기."""
        if not self._grid_mode() and self._picks:
            self._select_from_multi(self._picks[0])
            self._refill_multis()
            self._go("multi")
            self.lbl_status.setText("최신 사진 OD | OS — 사진 목록에서 클릭하면 다중 보기에 더해지고, "
                                    "다시 클릭하면 빠집니다 · 더블클릭: 크게 보기")
            return
        row = self.patient_list.shortcut_photo()      # the selected exam's photo
        if row is not None:
            self._select_from_multi(row["id"])
        self._go("grid" if self._grid_mode() else "all")
        if self._grid_mode():
            self.lbl_status.setText("16장 보기 — 사진을 클릭해 고르고(번호) [멀티]를 누르면 고른 사진만 다중 보기로 · "
                                    "더블클릭: 크게 보기")

    def _set_default_picks(self, exam: str | None = None) -> None:
        """Pick what a patient opens with on 다중 보기: its newest OD and newest OS photo, OD on the
        left (as the patient faces you) — of the exam ``exam``, an eye not taken then from its
        latest exam before (None: the newest exam). Colour photos first (review.eye_photo); the
        strip's eye and kind filters are kept. 미분류 photos are not picked — nor any photo in the
        VK-2 way (설정 → 일반 → 환자를 열면: there the photos are picked by hand on 16장 보기)."""
        rows = self._images() if self._patient_ref not in (None, UNASSIGNED) and not self._grid_mode() else []
        want_eye, want_mod = self.f_eye.currentData() or "", self.f_mod.currentData() or ""
        if want_mod:
            rows = [r for r in rows if r["modality"] == want_mod]
        picks = []
        for eye in EYES:
            series = eye_series(rows, eye, exam) if want_eye in ("", eye) else []
            if series:
                picks.append(series[0]["id"])
        self._picks, self._pick_pre, self._multi_hint = picks, None, False
        self._default_picks = list(picks)
        self._mark_picks()
        self._fit_multi_count()

    def _strip_ids(self) -> list[int]:
        """The photos of the strip (the patient's, through the date · eye · kind filters), in its order."""
        return [self.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.thumbs.count())]

    def open_large(self, image_id: int) -> None:
        """That photo large (모두 보기) — a double click on a cell of 다중 보기, a photo of the 16 in
        the patient list; [다중 보기] brings the multi view back as it was."""
        self._select_from_multi(image_id)
        self._go("all")

    def _open_listed_photo(self, image_id: int) -> None:
        """A photo of the 16 in the patient list: large here, the list makes way for it."""
        ref = self.patient_list.current()
        if ref != self._patient_ref:
            self._select_patient_ref(ref)
        self.patient_list.hide()
        self._raise_main()
        self.open_large(image_id)

    def _raise_main(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_exam_checked(self, exam_date: str) -> None:
        """Another exam was selected in the patient list (or picked in the timeline): its newest
        OD | OS on 다중 보기 unless other photos were picked by hand; it is the current exam of the
        검토 tab now, earlier ones are its priors."""
        if self._tab() == "review" and not self._review_dirty:
            self.review.set_current_exam(exam_date)
        else:
            self._review_dirty = True
        if self._grid_mode() and self.patient_list.current() == self._patient_ref:
            # 16장 보기: the page with the exam's newest photo (as the patient list's 16)
            first = next((g.image_id for g in self.grid.items()
                          if (self.db.get_image(g.image_id) or {"exam_date": None})["exam_date"] == exam_date), None)
            if first is not None:
                self.grid.show_photo(first)
        elif (self.patient_list.current() == self._patient_ref and self._picks == self._default_picks
                and self._patient_ref not in (None, UNASSIGNED)):
            self._set_default_picks(exam_date)
            if self._picks:
                self._select_from_multi(self._picks[0])
            self._refill_multis()

    def _fill_review(self) -> None:
        if self._review_dirty:
            self._review_dirty = False
            self.review.set_photos(self._images(), self.patient_list.current_exam())

    def _review_hand_off(self, where: str, image_id: int, second) -> None:
        """검토 → 2D 보기 / 3D 안구 / 녹내장 with the photo of the active view."""
        self._select_from_multi(image_id)
        if self.current is None or self.current["id"] != image_id:
            return
        if where == "glaucoma":
            self.open_glaucoma(second)
        else:
            self._go(where)

    # -- the 환자 목록 window ---------------------------------------------------------------------------
    def show_patient_list(self, search: bool = False) -> None:
        """The 환자 목록 window in front ([환자 목록] · Ctrl+0; ``search``: with the cursor in its
        환자 ID box — 환자 검색, Ctrl+F)."""
        pl = self.patient_list
        pl.place_over(self)
        pl.set_current(self._patient_ref)
        pl.show()
        pl.raise_()
        pl.activateWindow()
        if search:
            pl.focus_search()
        else:
            pl.table.setFocus()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._list_shown:                 # the program opens with the patient list in front
            self._list_shown = True
            QTimer.singleShot(0, lambda: None if self._closing else self.show_patient_list())

    def _dialog_parent(self) -> QWidget:
        """A dialog asked for from the patient list opens over it."""
        pl = self.patient_list
        return pl if pl.isVisible() and pl.isActiveWindow() else self

    def _select_patient_id(self, pid: str) -> None:
        row = self.db.find_patient(pid)
        if row is not None:
            self._select_patient_ref(row["id"])

    def _set_patient(self, ref) -> None:
        """The patient on screen: UNASSIGNED (★ 미분류), a ``patients.id`` or None (nobody)."""
        p = self.db.get_patient(ref) if ref not in (None, UNASSIGNED) else None
        if ref not in (None, UNASSIGNED) and p is None:
            ref = None                         # deleted or merged away
        changed = ref != self._patient_ref
        if changed:
            self.compare = None                # the second pick belongs to the previous patient
            self._picks, self._per_photo, self._pick_pre = [], {}, None   # so do the multi picks
        self._patient_ref = ref
        self.patient_list.set_current(ref)     # the patient list shows the same patient
        if ref is None:
            self.banner.setText("환자를 선택하세요")
        elif ref == UNASSIGNED:
            self.banner.setText("미분류 영상 — [정보 수정]으로 환자를 지정하세요")
        else:
            self.settings.last_patient = p["patient_id"]
            age = age_on(p["birth_date"])
            bits = [p["name"] or "(이름 없음)", p["patient_id"]]
            if p["birth_date"]:
                bits.append(f"{p['birth_date']}" + (f" ({age}세)" if age is not None else ""))
            if p["sex"]:
                bits.append(SEX_LABEL.get(p["sex"], p["sex"]))
            self.banner.setText("  ·  ".join(bits))
        self._fit_banner()
        self._fill_dates()
        if changed:                      # the newest OD | OS are picked: 다중 보기 shows them, OD selected
            self._set_default_picks(self.patient_list.current_exam())
            keep = self._picks[0] if self._picks else None
        else:                            # the same patient again (its data edited …): the same photo
            keep = self.current["id"] if self.current is not None else None
        self._fill_thumbs(select_id=keep)
        if changed:                      # 다중 보기 on screen: this patient's photos, not the last one's
            self._refill_multis()

    def _edit_patient(self) -> None:
        if self._patient_ref in (None, UNASSIGNED):
            return
        p = self.db.get_patient(self._patient_ref)
        dlg = PatientDialog(self.db, p, self._dialog_parent())
        if dlg.exec():
            target = dlg.merged_into or self._patient_ref
            self.refresh_patients()
            self._select_patient_ref(target)

    def _delete_patient(self) -> None:
        p = self.db.get_patient(self._patient_ref)
        if p is None:
            return
        ok = QMessageBox.question(self._dialog_parent(), "환자 삭제",
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
        if not _:                              # not a filter of the strip: the patient or its photos changed
            self._review_dirty = True
            if self._tab() == "review":
                self._fill_review()
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        first = None
        target = None
        # OD first, then OS, then OU (newest first in each): the strip's rows by eye, and the order of
        # 이전 / 다음 in both layouts
        images = sorted(self._images(), key=lambda r: eye_row(r["laterality"]))

        def dated(r) -> bool:                  # the date and kind filters
            return not (d and r["exam_date"] != d) and not (mod and r["modality"] != mod)

        def known(r) -> bool:
            return r["laterality"] in ("OD", "OS", "OU")

        # 미상 (eye unknown) photos stay out of 양안 — unless they are all there is (no empty strip)
        hide_unknown = eye == "" and any(dated(r) and known(r) for r in images)
        grid = []                              # 16장 보기: the same photos, in the same order
        for r in images:
            if (not dated(r) or (eye in ("OD", "OS") and r["laterality"] != eye)
                    or (eye == UNKNOWN_EYE and known(r)) or (hide_unknown and not known(r))):
                if r["id"] != select_id:       # (the photo to show stays, whatever the filters)
                    continue
            mod_label = MODALITY_LABELS.get(r["modality"] or "", r["modality"] or "")
            text = f"{r['exam_date'] or '날짜 없음'}\n{mod_label}".strip()       # (no field angle: the date and kind)
            it = QListWidgetItem(QIcon(QPixmap(r["thumb_path"] or "")), text)
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            it.setSizeHint(QSize(THUMB_GRID[0] - 4, THUMB_GRID[1] - 2))    # the whole cell: both caption lines
            it.setData(THUMB_TEXT, text)
            it.setData(EYE_ROLE, r["laterality"] or "")
            it.setToolTip(f"{r['exam_date'] or ''} {r['exam_time'] or ''}\n{r['device'] or ''}\n"
                          f"{Path(r['original_path'] or r['file_path']).name}")
            self.thumbs.addItem(it)
            when = f"{r['exam_date'] or '날짜 없음'} {(r['exam_time'] or '')[:5]}".strip()
            grid.append(GridPhoto(r["id"], r["thumb_path"], r["laterality"],
                                  " · ".join(t for t in (when, mod_label) if t)))
            first = first or it
            if r["id"] == select_id:
                target = it
        self.thumbs.blockSignals(False)
        # 16장 보기: the strip's photos newest first, both eyes together (the strip is by eye)
        newest = {r["id"]: k for k, r in enumerate(self._images())}
        grid.sort(key=lambda g: newest.get(g.image_id, 0))
        self.grid.set_items(grid, self.current["id"] if self.current is not None else None)
        pick = target or first
        if pick:
            self.thumbs.setCurrentItem(pick)  # -> currentItemChanged -> _show_image
            self.thumbs.scrollToItem(pick)
        else:
            self._show_image(None)
        self._mark_pair()
        self._fit_thumb_height()
        if self.remote or self.share_server is not None:
            self._share_sig = self._photo_sig()
        known = {r["id"] for r in self._images()}          # removed photos leave the picks
        if any(i not in known for i in self._picks):
            self._picks = [i for i in self._picks if i in known]
            self._per_photo = {k: v for k, v in self._per_photo.items() if k in known}
        self._mark_picks()

    # -- multi picks (VK-2: click the photos, then MULTI) ------------------------------------
    def picks(self) -> list[int]:
        return list(self._picks)

    def _set_thumb_rows(self, n: int, save: bool = False) -> None:
        """The photo list: 1 = all photos in one scrolling line; otherwise by eye — OD in the top
        row, OS in the row under it (OU in a third row when there are any). 미상: see _fill_thumbs."""
        n = 1 if n == 1 else 2
        self._thumb_rows = n
        self.thumbs.set_by_eye(n != 1)
        self._fit_thumb_height()
        if n == 1:
            self.btn_rows.setText("▤ 1줄")
            self.btn_rows.setToolTip("사진 목록을 한 줄로 보기 (OD 다음 OS) — 누르면 눈별로 (OD 위 줄 · OS 아래 줄)")
        else:
            self.btn_rows.setText("▤ OD/OS")
            self.btn_rows.setToolTip("사진 목록을 눈별로 보기 — OD는 위 줄, OS는 아래 줄\n누르면 한 줄로")
        cur = self.thumbs.currentItem()
        if cur is not None:
            self.thumbs.scrollToItem(cur)
        if save:
            self.settings.thumb_rows = n
            try:
                self.settings.save()
            except OSError:
                pass

    def _fit_thumb_height(self) -> None:
        """One row per eye in the list (only OD photos: one row), or the one line — and room for the
        sideways scroll bar when the photos run past the strip (unless it floats over them)."""
        t = self.thumbs
        rows, cols = t.grid_shape()
        h = rows * t.gridSize().height() + 10
        bar = t.horizontalScrollBar()
        if (cols * t.gridSize().width() > t.viewport().width()
                and not t.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient, None, bar)):
            h += bar.sizeHint().height()
        t.setFixedHeight(h)

    def _toggle_pick(self, image_id: int) -> bool:
        if image_id in self._picks:
            self._picks.remove(image_id)
            self._multi_hint = not self._picks         # all clicked away: the multi view says how to pick
        elif len(self._picks) >= MAX_PICKS:
            self.lbl_status.setText(f"멀티는 한 번에 {MAX_PICKS}장까지 고를 수 있습니다")
            return False
        else:
            self._picks.append(image_id)
        self._mark_picks()
        if self._picks:
            self.lbl_status.setText(f"{len(self._picks)}장 골랐습니다 — 다중 보기에 고른 차례대로 나옵니다 "
                                    "(다시 클릭하면 빠집니다)")
        self._refill_multis()
        return True

    def _click_pick(self, image_id: int) -> None:
        """A plain click on a photo of the strip — the multi view follows the clicks: a photo not
        picked joins it as the selected cell; a picked one leaves it while the multi view is on
        screen, and elsewhere (모두 보기 · 3D) brings the multi view back with that photo selected.
        The layout fits the number picked: 1 · 2 · 4 · 6 · 9 · 16."""
        shown = self._tab() == "multi"
        before = list(self._picks)
        if (image_id not in self._picks or shown) and not self._toggle_pick(image_id):
            return                                     # (as many as fit are picked already)
        if image_id in self._picks:
            target = image_id
        elif self.current is not None and self.current["id"] in self._picks:
            target = self.current["id"]
        elif self._picks:                              # the selected photo left: the one in its place
            target = self._picks[min(before.index(image_id), len(self._picks) - 1)]
        else:
            target = None
        if not shown:
            self._fit_multi_count()
            self._go("multi")                          # -> _on_tab -> _fill_multi
        if target is not None and (self.current is None or self.current["id"] != target):
            self._select_from_multi(target)
        n = len(self._picks)
        self.lbl_status.setText(f"다중 보기 {n}장 — 사진을 클릭하면 더하고, 다시 클릭하면 뺍니다 · 더블클릭: 크게 보기"
                                if n else "사진 목록에서 사진을 클릭하면 다중 보기에 모입니다")

    def clear_picks(self) -> None:
        self._picks, self._per_photo, self._pick_pre = [], {}, None
        self._multi_hint = True
        self._mark_picks()
        self._refill_multis()

    def _fit_multi_count(self) -> None:
        """다중 보기 is split for the photos picked (1 · 2 · 4 · 6 · 9 · 16) — without refilling it."""
        if self._picks:
            self.multi.set_count(MultiView.fit(len(self._picks)), quiet=True)
        elif self._multi_hint:
            self.multi.set_count(1, quiet=True)

    def _refill_multis(self) -> None:
        """The picks changed: 다중 보기 is split for them and filled again when on screen."""
        self._fit_multi_count()
        if self._tab() == "multi":
            self._fill_multi()

    def _on_multi_layout(self, _n: int) -> None:
        """화면 분할 chosen by hand: with nothing picked, consecutive photos from the shown one (VK-2)."""
        if not self._picks:
            self._multi_hint = False
        self._fill_multi()

    def open_picks(self) -> None:
        """[멀티]: the picked photos in the multi view, one cell each, the first one selected."""
        if not self._picks:
            self.lbl_status.setText("사진 목록에서 사진을 클릭하면 다중 보기에 바로 모입니다 (다시 클릭하면 빠집니다)")
            return
        n = len(self._picks)
        if self.current is None or self.current["id"] not in self._picks:
            self._select_from_multi(self._picks[0])
        self._refill_multis()
        self._go("multi")                     # -> _on_tab -> _fill_multi (unless it is on screen: filled)
        self.lbl_status.setText(f"고른 사진 {n}장 — 칸을 누르면 그 사진만 보정됩니다 (밝기·대비·Red-free·선명하게 …)")

    def _mark_picks(self) -> None:
        for i in range(self.thumbs.count()):
            it = self.thumbs.item(i)
            iid = it.data(Qt.ItemDataRole.UserRole)
            it.setData(PICK_ROLE, self._picks.index(iid) + 1 if iid in self._picks else 0)
        self.grid.set_picks(self._picks)
        self._sync_picks_ui()

    def _sync_picks_ui(self) -> None:
        n = len(self._picks)
        self.btn_multi.setText(f"멀티 {n}" if n else "멀티")
        self.lbl_picks.setText(f"{n}장 선택" if n else "")
        self.btn_clear_picks.setVisible(n > 0)
        self.btn_montage.setEnabled(n >= 2)

    @staticmethod
    def _adjusted_with(rgb: np.ndarray, st: dict) -> np.ndarray:
        """``imaging.adjust`` with a saved processing state (see ``_snapshot``)."""
        return imaging.adjust(rgb, brightness=st.get("bright", 0) / 200.0, contrast=st.get("contrast", 100) / 100.0,
                              gamma=st.get("gamma", 100) / 100.0, channel=st.get("channel", "rgb"),
                              invert=st.get("invert", False), auto=st.get("auto", False),
                              levels=tuple(st.get("levels", (0, 255))))

    def _photo_state(self, image_id: int) -> dict:
        """Processing of a picked photo: live for the one on screen, saved for the others."""
        if self.current is not None and self.current["id"] == image_id:
            return self._snapshot()
        return self._per_photo.get(image_id, {}).get("state", {})

    def _load_state(self, st: dict, history: list | None = None) -> None:
        """Put a saved processing state on the toolbar without redrawing (the caller shows the photo)."""
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
        self._history = list(history or [])
        for w in sliders:
            w.blockSignals(False)
        for pop in (self.pop_gamma, self.pop_contrast, self.pop_bright):
            pop._show(pop.slider.value())

    def _fit_banner(self) -> None:
        """The patient line in the menu bar: as wide as its text when there is room, else cut with …."""
        if not hasattr(self, "top_w") or not self._line_in_menubar or self._banner_busy:
            return
        mb = self.menuBar()
        acts = [a for a in mb.actions() if a.isVisible()]
        menus = mb.actionGeometry(acts[-1]).right() if acts else 0
        fixed = self.btn_patients.sizeHint().width() + sum(
            w.sizeHint().width() + 6 for w in (self.f_date, self.f_eye, self.f_mod) if not w.isHidden())
        room = mb.width() - menus - 40
        w = max(fixed, min(fixed + self.banner.full_width() + 30, room))   # (cut to the room, not the menus)
        if self.top_w.want != w:
            self.top_w.want = w              # the menu bar lays its corner out by the size hint
            self.top_w.updateGeometry()
            mb.updateGeometry()
            # lay the corner out again now. The nudge resizes the menu bar, which calls this again
            # from the event filter with one pixel more room: without the guard a line cut to the
            # room (a narrow window, a long name, wider fonts on Windows) grew by a pixel each time
            # and never stopped
            self._banner_busy = True
            try:
                mb.resize(mb.width() + 1, mb.height())
                mb.resize(mb.width() - 1, mb.height())
            finally:
                self._banner_busy = False

    def eventFilter(self, obj, e):
        try:
            self.thumbs.viewport()
        except RuntimeError:                  # closing down: the photo list is already gone
            return False
        if obj is self.menuBar() and e.type() == QEvent.Type.Resize:
            self._fit_banner()
        if obj is self.thumbs.viewport() and e.type() == QEvent.Type.Resize and e.size().width() != e.oldSize().width():
            QTimer.singleShot(0, self._fit_thumb_height)       # wider strip: the scroll bar may go
        # 모두 보기: the two enlarged panes keep their places when they change size
        if (getattr(self, "_ov_on", False) and e.type() == QEvent.Type.Resize
                and obj in (self.ov_zoom.viewport(), self.ov_macula.viewport())):
            QTimer.singleShot(0, self._ov_apply)
            return False
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
        # plain click = the photo joins / leaves the multi view (numbered), double click = that photo large
        if (e.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                         QEvent.Type.MouseButtonDblClick)
                and obj is self.thumbs.viewport()
                and e.button() == Qt.MouseButton.LeftButton
                and not e.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)):
            item = self.thumbs.itemAt(e.position().toPoint())
            if item is None:
                return super().eventFilter(obj, e)
            iid = item.data(Qt.ItemDataRole.UserRole)
            if e.type() == QEvent.Type.MouseButtonPress:
                self._press_photo(iid)
            elif e.type() == QEvent.Type.MouseButtonDblClick:
                self._open_photo(iid)
            return True
        return super().eventFilter(obj, e)

    def _press_photo(self, image_id: int, stay: bool = False) -> None:
        """A plain click on a photo of the strip: it joins / leaves the multi view (numbered) —
        on 16장 보기 (``stay``) it is picked or taken out there. The double click it may begin takes
        it back (``_open_photo``)."""
        self._stop_slideshow()
        self._pick_pre = (image_id, list(self._picks), self._multi_hint)
        if stay:
            self._toggle_pick(image_id)
        else:
            self._click_pick(image_id)

    def _open_photo(self, image_id: int) -> None:
        """A double click on a photo of the strip or of 16장 보기: the photo large on 모두 보기."""
        pre = self._pick_pre
        if pre is not None and pre[0] == image_id and (pre[1], pre[2]) != (self._picks, self._multi_hint):
            self._picks, self._multi_hint = list(pre[1]), pre[2]   # the first click of the double click
            self._mark_picks()
            self._fit_multi_count()
        self._pick_pre = None
        self._select_from_multi(image_id)        # -> _show_image
        self._go("2d")

    def _pick_second(self, image_id: int) -> None:
        """Ctrl+click: toggle ``image_id`` as the second photo next to the shown one."""
        if self.current is None or image_id == self.current["id"]:
            return
        if self.compare is not None and self.compare["id"] == image_id:
            self.compare = None
            self._mark_pair()
            self.lbl_status.setText("두 번째 사진 선택을 해제했습니다")
            if self._tab() == "cmp":
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
        self.grid.set_second(cid)

    def _thumb_menu(self, pos) -> None:
        item = self.thumbs.itemAt(pos)
        if item:
            self._photo_menu(item.data(Qt.ItemDataRole.UserRole), self.thumbs.viewport().mapToGlobal(pos))

    def _photo_menu(self, iid: int, global_pos) -> None:
        """Right click on a photo of the strip or of 16장 보기."""
        menu = QMenu(self)
        menu.addAction("멀티에서 빼기" if iid in self._picks else "멀티로 고르기", lambda: self._toggle_pick(iid))
        if self._picks:
            menu.addAction(f"멀티로 보기 ({len(self._picks)}장)", self.open_picks)
        if len(self._picks) >= 2:
            menu.addAction(f"몽타주 만들기 ({len(self._picks)}장)…", lambda: self.open_montage())
        row = self.db.get_image(iid)
        if row is not None and self._montage_definition(row):
            menu.addAction("몽타주 다시 편집…", lambda: self.edit_montage(iid))
        menu.addSeparator()
        menu.addAction("환자 지정/정보 수정…", lambda: (self._show_image(iid), self._edit_image()))
        cur = self.current["id"] if self.current else None
        if iid != cur:
            menu.addAction("비교 대상으로 (오른쪽)", lambda: self._set_compare(iid))
            menu.addAction("디스크 2장 (보고 있는 사진과)…", lambda: self._disc_pair(iid))
            menu.addAction("녹내장 분석 (보고 있는 사진과)…", lambda: self.open_glaucoma(iid))
        elif self.compare is not None:
            menu.addAction("디스크 2장 (② 사진과)…", lambda: self._disc_pair())
            menu.addAction("녹내장 분석 (② 사진과)…", lambda: self.open_glaucoma())
            menu.addAction("두 번째 사진(②) 선택 해제", lambda: self._pick_second(self.compare["id"]))
        menu.addAction("원본 폴더 열기", lambda: (self._show_image(iid), self._open_folder()))
        menu.addSeparator()
        menu.addAction("다시 분석 (원·시신경 검출)", lambda: self._reanalyse(iid))
        menu.addAction("목록에서 제거…", lambda: self._remove_image(iid))
        menu.exec(global_pos)

    # =====================================================================
    # image display
    # =====================================================================
    @staticmethod
    def _image_path(row) -> str | None:
        path = row["display_path"] or row["file_path"]
        if not path or not os.path.exists(path):
            alt = row["original_path"]
            path = alt if alt and os.path.exists(alt) else None
        return path

    def _load(self, row) -> np.ndarray | None:
        if row["id"] in self._cache:
            self._cache.move_to_end(row["id"])
            return self._cache[row["id"]]
        path = self._image_path(row)
        if path is None:
            return None
        try:
            rgb = imaging.load_rgb(path)
        except Exception as exc:
            self.lbl_status.setText(f"영상을 열 수 없음: {exc}")
            return None
        self._cache_put(row["id"], rgb)
        return rgb

    def _cache_put(self, image_id: int, rgb: np.ndarray) -> None:
        self._cache[image_id] = rgb
        while len(self._cache) > 6:
            self._cache.popitem(last=False)

    def _preload_neighbours(self) -> None:
        """Read the next and the previous photo of the strip in the background."""
        i = self.thumbs.currentRow()
        if i < 0 or self.current is None:
            return
        for j in (i + 1, i - 1):
            item = self.thumbs.item(j) if 0 <= j < self.thumbs.count() else None
            iid = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if iid is None or iid in self._cache:
                continue
            row = self.db.get_image(iid)
            if row is not None and self.remote:
                self._preloader.request(iid, lambda row=row: self._image_path(row))
                continue
            path = self._image_path(row) if row is not None else None
            if path is not None:
                self._preloader.request(iid, path)

    def _on_preloaded(self, image_id: int, rgb) -> None:
        if rgb is None or image_id in self._cache:
            return
        self._cache_put(image_id, rgb)
        if self.current is not None and self.current["id"] in self._cache:
            self._cache.move_to_end(self.current["id"])     # the photo on screen stays the newest

    def _show_image(self, image_id: int | None) -> None:
        row = self.db.get_image(image_id) if image_id is not None else None
        prev, self.current = self.current, row
        if prev is not None and prev["id"] in self._picks:
            # a picked photo keeps the processing it is left with (its cell on 다중 보기 shows it so)
            self._per_photo[prev["id"]] = {"state": self._snapshot(), "history": list(self._history)}
        self.grid.set_current(row["id"] if row is not None else None)
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
            self.lbl_info.setText("<span style='color:#ff6961'>파일을 찾을 수 없음</span>")
            return
        # processing steps (sharpen, enhance ...) belong to the photo on screen
        self._ops, self._levels, self._history = [], (0, 255), []
        if row["id"] in self._picks:          # a picked photo keeps its own processing (multi view)
            saved = self._per_photo.get(row["id"], {})
            self._load_state(saved.get("state", {}), saved.get("history"))
        self.view2d.set_rgb(self._display_rgb(row))
        self._sync_palette()
        row = self.current = self._ensure_fovea(row)
        self.view2d.set_overlays(*self._marks_of(row))
        self._fill_info(row)
        self._load_mapping(row)
        self._mark_3d_dirty()
        if self._tab() == "multi" and not self._multi_lock:
            self._fill_multi()
        if self._tab() == "all":
            self._fill_overview(multi=not self._multi_lock)
        self._preload_timer.start(180)        # once the browsing pauses: read the neighbours ahead

    @staticmethod
    def _marks_of(row) -> tuple:
        """Image circle, optic disc and fovea of a photo (pixels; None where not known)."""
        circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else None
        disc = (row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None
        fovea = (row["fovea_x"], row["fovea_y"]) if row["fovea_x"] is not None else None
        return circle, disc, fovea

    def _photo_camera(self, row, *, stored: bool = False) -> placement.Camera | None:
        """How the photo maps to directions: as set in 사진 맞춤 for the photo on screen, else as stored."""
        if not row["circle_r"]:
            return None
        prof = get_profile(row["profile"])
        if stored or self.current is None or row["id"] != self.current["id"]:
            fov, ftype, projection = (row["fov_deg"] or prof.fov_deg, row["fov_type"] or prof.fov_type,
                                      row["projection"] or prof.projection)
        else:
            fov, ftype, projection = self.sp_fov.value(), self.c_fovtype.currentData(), self.c_proj.currentData()
        return placement.Camera(row["circle_cx"], row["circle_cy"], row["circle_r"], fov, ftype, projection,
                                prof.viewpoint, prof.radial_c)

    def _find_fovea(self, row, rgb) -> tuple[float, float] | None:
        cam = self._photo_camera(row, stored=True)
        if cam is None or row["disc_x"] is None or row["modality"] in ("anterior", "disc", "glaucoma"):
            return None
        found = imaging.detect_fovea(rgb, cam, (row["disc_x"], row["disc_y"]), row["laterality"])
        return None if found is None else (found[0], found[1])

    def _ensure_fovea(self, row):
        """A photo imported before the fovea was looked for: find it once, when the photo is first shown."""
        if row["fovea_x"] is not None or row["disc_x"] is None or row["id"] in self._fovea_tried:
            return row
        self._fovea_tried.add(row["id"])
        rgb = self._load(row)
        fovea = self._find_fovea(row, rgb) if rgb is not None else None
        if fovea is None:
            return row
        self.db.update_image(row["id"], fovea_x=fovea[0], fovea_y=fovea[1])
        return self.db.get_image(row["id"])

    def _fill_info(self, row) -> None:
        meta = json.loads(row["meta_json"] or "{}")
        src = meta.get("sources", {})

        def with_src(text, *fields):
            s = next((source_label(src.get(f)) for f in fields if src.get(f)), "")
            return f"{text}  <span style='color:#8e8e93'>({s})</span>" if s and text and text != "-" else (text or "-")

        p = self.db.get_patient(row["patient_ref"]) if row["patient_ref"] else None
        if p:
            who = with_src(f"{p['patient_id']} {p['name'] or ''}", "patient_id")
        else:
            guess = " ".join(x for x in (meta.get("patient_id"), meta.get("name")) if x)
            who = "<span style='color:#ff6961'>미분류</span>" + (f" — 추출값: {guess}" if guess else "")
        eye = {"OD": "OD (우안)", "OS": "OS (좌안)", "OU": "OU"}.get(row["laterality"] or "", "")
        mod = MODALITY_LABELS.get(row["modality"] or "", row["modality"] or "")
        device = row["device"] or get_profile(row["profile"]).name
        ftype = "안구 중심각" if row["fov_type"] == "internal" else "외부각"
        fov = f"{row['fov_deg']:g}°" if row["fov_deg"] else ""
        span = (self._montage_definition(row) or {}).get("span")
        if span:                                # a montage made here: what it covers, not its map's circle
            fov = mt_span_text(span)
        name = Path(row["original_path"] or row["file_path"]).name
        # on the photo: only its number and the eye (the patient and the date are in the line above
        # the tabs and in the photo list — no patient data on the picture)
        n, i = self.thumbs.count(), self.thumbs.currentRow()
        self.view2d.set_captions(
            f"{i + 1}/{n}" if n and i >= 0 else "",
            {"OD": "OD (R)", "OS": "OS (L)", "OU": "OU"}.get(row["laterality"] or "", ""))
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
        cid = self.current["id"]
        if cid in self._picks:                # this photo's own processing, kept for the multi view
            self._per_photo[cid] = {"state": self._snapshot(), "history": list(self._history)}
        if self._tab() == "multi":
            if cid in self._picks:            # only this cell changes (keeps every cell's zoom)
                small = self._multi_small(self.current, self._snapshot())
                if small is None or not self.multi.update_cell(cid, small):
                    self._fill_multi()
            else:
                self._fill_multi()
        if self._tab() == "cmp":
            self._fill_compare()
        if self._tab() == "all":
            self._fill_overview()

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
            if self._tab() not in ("2d", "all"):   # 2D tools: go to a view with the big 2D photo first
                self._go("2d")
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
            self.lbl_status.setText(keys(f"{imaging.OP_LABELS.get(op, op)} 적용 (실행 취소: Ctrl+Z)"))
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
            v.fit(animate=True)
        elif key in ("actual", "zoom2", "zoom4", "zoom8"):
            v.zoom_to({"actual": 1.0, "zoom2": 2.0, "zoom4": 4.0, "zoom8": 8.0}[key], animate=True)
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
        elif key == "glaucoma":
            self.open_glaucoma()
        # -- command toolbar ---------------------------------------------------------
        elif key == "search":                       # 환자 검색: the patient list, the cursor in 환자 ID
            self.show_patient_list(search=True)
        elif key == "list":                         # 환자 목록 (VK-2 OPEN LIST): the window up / away
            if self.patient_list.isHidden() if checked is None else checked:
                self.show_patient_list()
            else:
                self.patient_list.hide()
        elif key in ("multi", "view3d"):
            tab = "multi" if key == "multi" else "3d"
            self._go(self._home() if self._tab() == tab else tab)
        elif key.startswith("multi:"):
            self._multi_hint = False             # nothing picked: consecutive photos from the shown one
            self.multi.set_count(int(key[6:]))
            self._go("multi")
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
        self.acts["list"].setChecked(self.patient_list.isVisible())

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
        roi = self._ov_roi.isVisible()          # the 확대 화면 frames are for the screen only
        for item in self._ov_rois.values():
            item.setVisible(False)
        try:
            return self.view2d.render_image()
        finally:
            self._ov_roi.setVisible(roi)
            self._ov_sync_roi()

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
    def _multi_label(self, row, rank: int = 0) -> str:
        mod = MODALITY_LABELS.get(row["modality"] or "", "")
        num = f"<b style='color:#ffd60a'>{rank}</b>&nbsp; " if rank else ""
        return (f"{num}{eye_badge_html(row['laterality'])}&nbsp; "
                f"{row['exam_date'] or ''} {row['exam_time'] or ''}&nbsp; {mod}")

    def _small_photo(self, row, side: int) -> np.ndarray | None:
        """The photo at most ``side`` pixels across, for a cell of 다중 보기: from the whole photo when
        it is read already, else read reduced (a JPEG straight at 1/2 … 1/8 of its size), so 16 photos
        come up at once. Kept for the next screens (a photo's pixels never change: edits are new photos)."""
        key = (row["id"], side)
        if key in self._small:
            self._small.move_to_end(key)
            return self._small[key]
        full = self._cache.get(row["id"])
        if full is not None:
            small = imaging.downscale(full, side)
        else:
            path = self._image_path(row)
            if path is None:
                return None
            try:
                small = imaging.load_reduced(path, side)
            except Exception as exc:
                self.lbl_status.setText(f"영상을 열 수 없음: {exc}")
                return None
        self._small[key] = small
        while len(self._small) > SMALL_KEEP:
            self._small.popitem(last=False)
        return small

    def _multi_small(self, row, st: dict, n: int | None = None) -> np.ndarray | None:
        """Down-scaled photo for a multi cell with the processing state ``st``."""
        n = self.multi.count if n is None else n
        small = self._small_photo(row, 1400 if n <= 4 else 900)
        if small is None:
            return None
        ops = st.get("ops", [])
        return self._adjusted_with(imaging.apply_ops(small, ops) if ops else small, st)

    def _fill_multi(self, target: MultiView | None = None) -> None:
        """Fill the 다중 보기 tab, or ``target`` (모두 보기's 2 × 2 grid): the picked photos with
        their own processing; with none, consecutive photos from the shown one (VK-2) — or, once
        the picks were clicked away, how to pick."""
        mv = target or self.multi
        if self._picks:                       # the photos picked in the strip, each with its own processing
            n = mv.count
            items = []
            for k, iid in enumerate(self._picks[:n]):
                row = self.db.get_image(iid)
                small = self._multi_small(row, self._photo_state(iid), n) if row else None
                if small is not None:
                    items.append((iid, self._multi_label(row, k + 1), small))
            more = f" (화면에 {n}장 — 화면 분할을 늘리세요)" if len(self._picks) > n else ""
            mv.set_mode_text(f"고른 사진 {len(self._picks)}장{more}")
            mv.populate(items, self.current["id"] if self.current else None)
            return
        mv.set_mode_text("")
        if self._multi_hint and target is None:
            mv.populate([], None, empty="아래 사진 목록에서 사진을 클릭하면 여기에 모입니다\n\n"
                                        "고른 장수에 맞게 화면이 나뉩니다 (1장 · 2장 · 4칸 · 6칸 …) · "
                                        "다시 클릭: 빼기 · 더블클릭: 크게 보기")
            return
        ids = self._strip_ids()
        if not ids:
            mv.populate([], None)
            return
        cur = self.current["id"] if self.current else ids[0]
        start = ids.index(cur) if cur in ids else 0
        n = mv.count
        start = max(0, min(start, len(ids) - n)) if len(ids) > n else 0
        items = []
        for iid in ids[start:start + n]:
            row = self.db.get_image(iid)
            small = self._small_photo(row, 1400 if n <= 4 else 900) if row else None
            if small is None:
                continue
            small = self._adjusted(imaging.apply_ops(small, self._ops) if self._ops else small)
            items.append((iid, self._multi_label(row), small))
        mv.populate(items, cur)

    def _select_from_multi(self, image_id: int) -> None:
        self._multi_lock = True
        try:
            for i in range(self.thumbs.count()):
                if self.thumbs.item(i).data(Qt.ItemDataRole.UserRole) == image_id:
                    self.thumbs.setCurrentRow(i)
                    break
            else:                              # a picked photo hidden by the strip filters
                self._show_image(image_id)
        finally:
            self._multi_lock = False
        self.multi.mark_selected(self.current["id"] if self.current else None)

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
            circle, disc, fovea = self._marks_of(row)
            d3, f3 = self._marks_for_3d(row)
            self.eye3d.set_landmarks(row["laterality"], d3, f3, circle, align=self.c_align3d.isChecked())
            # the 2D measurements use the same eye geometry as the 3D view
            self.view2d.geometry = measure.Geometry(
                *circle, fov_deg=self.sp_fov.value(), fov_type=self.c_fovtype.currentData(),
                projection=self.c_proj.currentData(), viewpoint=prof.viewpoint,
                radial_c=prof.radial_c) if circle and (row["modality"] not in ("montage", "disc", "glaucoma")
                                                      or self._montage_definition(row)) else None
        self.lbl_3d.setText(self._placement_text())
        both = row is not None and row["disc_x"] is not None and row["fovea_x"] is not None
        self.b_fit_fov.setEnabled(bool(both))
        self._refresh_photo3d()

    def _placement_text(self) -> str:
        """What the 3D view did with the photo: how much retina it covers and where it was put."""
        tmax = math.degrees(self.eye3d.theta_max)
        pl = self.eye3d.placement
        lines = [f"망막 범위: 사진 중심에서 {tmax:.0f}° (안구 중심각 {2 * tmax:.0f}°)"]
        span = self.eye3d.cover_span() if self.eye3d.field_from_cover else None
        if span:                                # a montage: the map is a circle around all its photos
            lines = [f"촬영 범위: {mt_span_text(span)} (안구 중심각, 대략)"]
        where = {"fovea": "황반을 안구 뒤쪽 한가운데(후극)에 맞춤",
                 "disc": "황반이 사진에 없어 시신경 유두를 코쪽 제자리에 맞춤",
                 "centre": "황반·시신경 유두를 찾지 못해 사진 중심을 후극에 둠",
                 "off": "사진 중심을 후극에 둠 (실제 위치에 맞춤 꺼짐)"}[pl.by]
        if pl.by in ("fovea", "disc") and pl.offset_deg >= 0.5:
            where += f" — 사진 중심은 후극에서 {pl.offset_deg:.0f}°"
        lines.append(where)
        if pl.distance_deg is not None:
            off = abs(pl.distance_deg / placement.DISC_FOVEA_DEG - 1.0)
            lines.append(f"황반–유두 {pl.distance_deg:.1f}° · {pl.distance_mm:.1f} mm (보통 약 4.5 mm)"
                         + (" — 화각이 실제와 다를 수 있습니다" if off > 0.2 else ""))
        return "\n".join(lines)

    def _on_mapping(self, *_):
        self._push_mapping()

    def _on_align(self, on: bool) -> None:
        self.settings.align3d = bool(on)
        self.settings.save()
        self._push_mapping()

    def _fit_fov(self) -> None:
        """황반–유두 거리로 크기 맞춤: the field of view that puts the two 4.5 mm apart."""
        row = self.current
        cam = self._photo_camera(row) if row is not None else None
        if cam is None or row["disc_x"] is None or row["fovea_x"] is None:
            return
        fov = placement.fit_fov(cam, (row["fovea_x"], row["fovea_y"]), (row["disc_x"], row["disc_y"]))
        if fov is None:
            self.lbl_status.setText("황반–유두 거리로 화각을 정할 수 없습니다")
            return
        self.sp_fov.setValue(round(fov, 1))        # → _on_mapping
        self.lbl_status.setText(f"화각을 {fov:.1f}°로 맞췄습니다 (황반–유두 4.5 mm 기준) — [화각·투영 저장]으로 저장")

    def _save_mapping(self) -> None:
        if self.current is None:
            return
        self.db.update_image(self.current["id"], fov_deg=self.sp_fov.value(),
                             fov_type=self.c_fovtype.currentData(), projection=self.c_proj.currentData())
        self.current = self.db.get_image(self.current["id"])
        self._fill_info(self.current)
        self.lbl_status.setText("이 영상의 화각·투영을 저장했습니다")

    def _on_cut(self, v: int) -> None:
        if self._show.active():               # the user takes over from the presentation
            self._show.stop()
            self.s_cut.blockSignals(True)
            self.s_cut.setValue(v)
            self.s_cut.blockSignals(False)
        mode = self.c_view3d.currentData()
        self._cut_values[mode] = v
        if mode == "section":                 # 0: through the axis (half) … 100: closed
            self._tween._finish()
            self.eye3d.half = 1.0 - v / 100.0
        else:
            self.eye3d.cut = v / 100.0 if v < 100 else 1.0
        self.eye3d.update()

    # -- 세로 단면 · 망막 투시 · 슬릿 스캔 -------------------------------------------------
    def _sync_view_combo(self, mode: str) -> None:
        """Show ``mode`` in the selector and its depth on the slider (no signals)."""
        for w in (self.c_view3d, self.s_cut):
            w.blockSignals(True)
        self.c_view3d.setCurrentIndex(max(0, self.c_view3d.findData(mode)))
        self.s_cut.setRange(*((0, 100) if mode == "section" else (-30, 100)))
        self.s_cut.setValue(self._cut_values[mode])
        for w in (self.c_view3d, self.s_cut):
            w.blockSignals(False)
        self._sync_view_buttons()
        self.s_cut.setEnabled(self.r_out.isChecked())

    def _set_3d_view(self, mode: str, animate: bool = True) -> None:
        """앞쪽 절개 (front) or 세로 단면 (section), gliding to a fitting camera."""
        self._show.stop()
        self._sync_view_combo(mode)
        eye = self.eye3d
        eye.journey_leave()
        # the front stays closed while the section plane moves; the front cut opens at the end
        eye.cut = 1.0
        if mode == "section":
            goal, half, done = eye.section_pose(), 1.0 - self._cut_values["section"] / 100.0, None
        else:
            goal = None if eye.half < 0.5 else {
                "yaw": 38.0, "pitch": 18.0, "dist": eye.DIST0, "target": (0.0, 0.0, 0.0)}
            half, done = 0.0, lambda: self._on_cut(self.s_cut.value())
        if not self.r_out.isChecked():       # 내부: applies when going back outside
            goal = None
        self._tween.go(goal, half, eye.xray, duration=0.9 if animate else 0.0, done=done)
        self._apply_fov_marks()

    def _on_xray(self, on: bool) -> None:
        if self._show.active():               # stopping syncs the box to the eye: keep the user's choice
            self._show.stop()
            self.c_xray3d.blockSignals(True)
            self.c_xray3d.setChecked(on)
            self.c_xray3d.blockSignals(False)
        self._tween.go(None, self.eye3d.half, 1.0 if on else 0.0, duration=0.6)

    def _apply_fov_marks(self, *_) -> None:
        on = self.c_fov3d.isChecked()
        self._show.show_fov = on
        if self._show.playing:                # the presentation draws its own
            return
        eye = self.eye3d
        eye.fov_sweep = eye.fov_alpha = eye.fov_ring = 1.0 if on else 0.0
        eye.update()

    def _on_fov_marks(self, on: bool) -> None:
        self._apply_fov_marks()

    def _on_side_photo(self, on: bool) -> None:
        self.scan_photo.setVisible(on)
        self.eye3d.black = on or self._full3d is not None
        if on:
            total = max(2, self.split3d.width())
            self.split3d.setSizes([total // 2, total - total // 2])
        self.eye3d.update()

    def _toggle_scan(self) -> None:
        if self._show.playing:
            self._show.stop()
            return
        self._show.xray_after = self.c_xray3d.isChecked()
        if self.current is None:
            self.lbl_status.setText("사진을 먼저 고르세요")
            return
        if self._tab() != "3d":
            self._go("3d")
        if not self.r_out.isChecked():
            self.r_out.setChecked(True)
        if not self.c_side3d.isChecked():
            self.c_side3d.setChecked(True)
        self._tween._finish()
        if self.eye3d.detail != "detailed":   # the presentation shows the realistic eye (not saved as the look)
            self._set_3d_detail("detailed", save=False)
        self._show.show_fov = self.c_fov3d.isChecked()
        if self._show.first().stage == "section":
            self.eye3d.cut = 1.0              # 세로 단면: no front cut
            self._cut_values["section"] = 0
            self._sync_view_combo("section")
        else:                                 # right / left: on the eye opened at the front
            self._cut_values["front"] = 25
            self._sync_view_combo("front")
        self._show.start()
        self._scan_buttons("■ 멈춤")
        self.eye3d.setFocus()
        self.lbl_status.setText("슬릿 스캔 — 안구를 누르거나 돌리면 멈춥니다")

    def _sync_from_eye(self) -> None:
        """After the presentation: 세로 단면 at the eye's depth (or the front cut), 망막 투시 as the eye shows it."""
        if self.eye3d.half > 0.01:
            self._cut_values["section"] = round(100.0 * (1.0 - self.eye3d.half))
            self._sync_view_combo("section")
        else:
            self._cut_values["front"] = round(100.0 * self.eye3d.cut) if self.eye3d.cut < 1.0 else 100
            self._sync_view_combo("front")
        self.c_xray3d.blockSignals(True)
        self.c_xray3d.setChecked(self.eye3d.xray > 0.5)
        self.c_xray3d.blockSignals(False)

    def _scan_buttons(self, text: str) -> None:
        self.b_scan.setText(text)
        self.b_scan2.setText(text)

    def _on_scan_finished(self) -> None:
        """The presentation is over; the eye keeps turning until the user takes over."""
        self._scan_buttons("▶ 슬릿 스캔")
        self._sync_from_eye()

    def _on_scan_stopped(self) -> None:
        self._scan_buttons("▶ 슬릿 스캔")
        self._sync_from_eye()
        self._apply_fov_marks()

    def _toggle_full_3d(self) -> None:
        """The 3D eye (and the photo) on the whole screen, e.g. to explain a photo to a patient."""
        if self._full3d is not None:
            self._exit_full_3d()
            return
        win = _FullScreen3D()
        win.setWindowTitle("3D 안구")
        win.closed.connect(self._exit_full_3d)
        lay = QVBoxLayout(win)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.split3d)           # re-parented: the 3D view makes its GL context again
        for key, fn in (("Esc", self._exit_full_3d), ("F11", self._exit_full_3d), ("Space", self._toggle_scan)):
            QShortcut(QKeySequence(key), win, activated=fn)
        self._full3d = win
        self._full3d_note = QLabel("3D 안구를 화면 전체로 보고 있습니다 — Esc 또는 [돌아가기]")
        self._full3d_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._full3d_note.setObjectName("hint3d")
        self._lay3d.addWidget(self._full3d_note, 1)
        self.scan_photo.hint = "Space: 슬릿 스캔 · Esc: 돌아가기"
        self.eye3d.black = True
        self.b_full3d.setText("돌아가기")
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            win.setGeometry(screen.geometry())
        win.showFullScreen()
        self.eye3d.setFocus()

    def _exit_full_3d(self) -> None:
        win, self._full3d = self._full3d, None
        if win is None:
            return
        self._full3d_note.deleteLater()
        (self._ov_3d_lay if self._ov_on and self._ov_gl else self._lay3d).addWidget(self.split3d, 1)
        self.split3d.show()
        win.closed.disconnect(self._exit_full_3d)
        win.hide()
        win.deleteLater()
        self.scan_photo.hint = ""
        self.eye3d.black = self.c_side3d.isChecked()
        self.b_full3d.setText("크게 보기")

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
        detail = detail if detail in EyeView.DETAILS else "detailed"
        self.eye3d.set_detail(detail)
        self.c_muscle.setEnabled(detail == "detailed")     # the simple model has no muscles
        self.c_muscle.setToolTip("네 곧은근과 두 빗근의 부착부(절단면)를 함께 표시"
                                 + ("" if detail == "detailed" else " — 자세히 보기에서"))
        if save and self.settings.view3d_detail != detail:
            self.settings.view3d_detail = detail
            self.settings.save()

    def _on_3d_mode(self, outside: bool) -> None:
        self._show.stop()
        self._tween._finish()
        self.s_cut.setEnabled(outside)
        self.c_view3d.setEnabled(outside)
        self.seg_view.setEnabled(outside)
        if not outside and self.c_view3d.currentData() != "front":
            self._sync_view_combo("front")
        # 들어가며 보기: in through the cornea, the pupil and the lens / back out (at once when
        # 부드러운 움직임 is off); the simple model fades through black
        self.eye3d.enter("outside" if outside else "inside")

    # -- 들어가며 보기 --------------------------------------------------------------------
    WHERE = ((0.32, "안구 전체 — 각막 쪽으로"), (1.09, "각막 앞"), (0.83, "앞방 — 각막과 홍채 사이 (방수)"),
             (0.785, "동공 — 홍채 가운데"), (0.46, "수정체"), (0.0, "유리체 — 앞에 망막이 보입니다"))

    def _play_journey(self) -> None:
        eye = self.eye3d
        if eye.journey_running():
            eye.stop_motion()                 # stops where it is
            return
        self._show.stop()
        self._tween._finish()
        if eye.detail != "detailed":          # the way in shows the anatomical eye (not saved as the look)
            self._set_3d_detail("detailed", save=False)
        to = 0.0 if eye.journey_j >= 0.999 else 1.0
        eye.journey_play(to, done=eye.journey_end if to == 0.0 else None)

    def _scrub_journey(self, v: int) -> None:
        eye = self.eye3d
        self._show.stop()
        self._tween._finish()
        if eye.detail != "detailed":
            self._set_3d_detail("detailed", save=False)
        eye.journey_scrub(v / 100.0)

    def _on_journey(self, j: float) -> None:
        """The slider, the button, 외부 | 내부 and the name of the place passed follow the way."""
        eye = self.eye3d
        self.s_journey.blockSignals(True)
        self.s_journey.setValue(round(j * 100))
        self.s_journey.blockSignals(False)
        self.b_journey.setText("■ 멈춤" if eye.journey_running() else "◀ 나오기" if j >= 0.999 else "▶ 들어가기")
        inside = j >= 0.999
        if self.r_in.isChecked() != inside:
            for b in (self.r_out, self.r_in):
                b.blockSignals(True)
            (self.r_in if inside else self.r_out).setChecked(True)
            for b in (self.r_out, self.r_in):
                b.blockSignals(False)
            self.s_cut.setEnabled(not inside)
            self.c_view3d.setEnabled(not inside)
            self.seg_view.setEnabled(not inside)
        if j <= 0.001:
            self._where.say("")
            return
        if inside:
            self._where.say("망막 — 황반과 시신경 유두 (망막 시점)", hold=2.5)
            return
        z = float(np.linalg.norm(eye._view_basis()[0]))
        if j < self.WHERE[0][0]:
            self._where.say(self.WHERE[0][1])
            return
        for limit, name in self.WHERE[1:]:
            if z > limit:
                self._where.say(name)
                return

    # -- 슬릿 스캔: the way of the slit ----------------------------------------------------------
    def _on_slit_dir(self, key: str, save: bool = True) -> None:
        self._show.direction = key
        b = self._slit_buttons[key]
        if not b.isChecked():
            b.setChecked(True)
        p = SLIT.get(key)
        self.lbl_slit.setText(f"{p.name} — " + ("앞을 연 안구의 망막 위로 봅니다" if p.stage == "front"
                                                 else "세로 단면을 옆에서 봅니다") if p is not None
                              else "위↓ 아래↑ (세로 단면) 다음 왼→ 오른← (앞에서 본 망막) 차례로")
        if save and self.settings.slit_dir3d != key:
            self.settings.slit_dir3d = key
            self.settings.save()
        if self._show.playing:                # playing: again, the new way
            self._show.stop()
            self._toggle_scan()

    # -- 사진: the device, the eye, the disc and the macula (as the web page's 사진 card) -----------------------
    DEVICE_LABELS = {"generic": "45°", "reticam": "RetiCam 176°", "apollo": "APOLLO", "kowa_vk2": "VK-2 45°",
                     "kowa_vk2_id": "VK-2 45°"}

    @staticmethod
    def _by_hand(row, field: str) -> bool:
        """The disc or the macula was marked by hand (2D right-click or 황반 지정 · 유두 지정)."""
        try:
            return json.loads(row["meta_json"] or "{}").get("sources", {}).get(field) == "manual"
        except (ValueError, TypeError):
            return False

    def _set_landmark_source(self, image_id: int, field: str, source: str | None) -> None:
        row = self.db.get_image(image_id)
        if row is None:
            return
        meta = json.loads(row["meta_json"] or "{}")
        sources = meta.setdefault("sources", {})
        if source:
            sources[field] = source
        else:
            sources.pop(field, None)
        self.db.update_image(image_id, meta_json=meta)

    def _marks_for_3d(self, row) -> tuple:
        """The disc and the macula the 3D eye uses: as found or marked (자동으로 찾기 off: only marked)."""
        _, disc, fovea = self._marks_of(row)
        if not self.c_autofind3d.isChecked():
            disc = disc if self._by_hand(row, "disc") else None
            fovea = fovea if self._by_hand(row, "fovea") else None
        return disc, fovea

    def _refresh_photo3d(self) -> None:
        """The 사진 card: the photo's name, device and eye, the marks on it and where they came from."""
        row = self.current
        if row is None:
            self.lbl_photo3d.setText("")
            self.lbl_found3d.setText("")
            self.photo3d.set_photo(None)
            return
        circle, _, _ = self._marks_of(row)
        disc, fovea = self._marks_for_3d(row)
        self.photo3d.set_marks(circle, disc, fovea)
        eye = {"OD": "우안", "OS": "좌안"}.get(row["laterality"] or "", "")
        name = " · ".join(x for x in ((row["exam_date"] or "")[:10], self.DEVICE_LABELS.get(row["profile"], ""), eye) if x)
        self.lbl_photo3d.setText(name)
        for w in (self.c_device3d, self.c_eye3d):
            w.blockSignals(True)
        i = self.c_device3d.findData("kowa_vk2" if row["profile"] == "kowa_vk2_id" else row["profile"])
        self.c_device3d.setCurrentIndex(i if i >= 0 else 0)
        try:
            src = json.loads(row["meta_json"] or "{}").get("sources", {}).get("laterality")
        except (ValueError, TypeError):
            src = None
        self.c_eye3d.setCurrentIndex(self.c_eye3d.findData(
            row["laterality"] if row["laterality"] in ("OD", "OS") and src not in ("disc-estimate", "fovea-estimate")
            else "auto"))
        for w in (self.c_device3d, self.c_eye3d):
            w.blockSignals(False)

        def part(name, has, hand):
            color, how = (("#64d2ff", "직접 지정") if hand else ("#30d158", "자동으로 찾음")) if has else ("#636366", "없음")
            return f"<span style='color:{color}'>{name} {how}</span>"
        self.lbl_found3d.setText(part("유두", disc is not None, self._by_hand(row, "disc")) + " · "
                                 + part("황반", fovea is not None, self._by_hand(row, "fovea")))

    def _found_text(self) -> str:
        row = self.current
        disc, fovea = self._marks_for_3d(row) if row is not None else (None, None)
        return ("유두와 황반을 자동으로 찾아 제자리에 맞췄습니다" if disc and fovea else
                "유두를 찾았습니다 (황반은 사진에 없거나 찾지 못했습니다 — 유두를 코쪽 제자리에 맞춤)" if disc else
                "유두와 황반을 찾지 못했습니다 — 사진에서 직접 지정할 수 있습니다")

    def _on_autofind3d(self, on: bool) -> None:
        self.settings.autofind3d = bool(on)
        self._push_mapping()
        self.lbl_status.setText(self._found_text() if on else
                                "자동으로 찾기를 껐습니다 — 황반·유두를 직접 지정하거나 사진 중심을 후극에 둡니다")

    def _set_marking3d(self, what: str | None) -> None:
        self._marking3d = what
        self.b_mark_fovea.setChecked(what == "fovea")
        self.b_mark_disc.setChecked(what == "disc")
        self.photo3d.set_picking(what)
        self.lbl_mark3d.setText({"fovea": "위 사진에서 황반(중심와, 어두운 가운데)을 누르세요",
                                 "disc": "위 사진에서 시신경 유두(밝은 원판)의 가운데를 누르세요"}.get(what, ""))
        self.lbl_mark3d.setVisible(bool(what))

    def _on_photo3d_picked(self, x: float, y: float) -> None:
        what = self._marking3d
        self._set_marking3d(None)
        if what == "fovea":
            self._on_fovea_picked(x, y)
            self.lbl_status.setText("황반 위치를 정했습니다 — 3D에서 안구 뒤쪽 한가운데에 맞췄습니다")
        elif what == "disc":
            self._on_disc_picked(x, y)

    def _redetect3d(self) -> None:
        """다시 찾기: the marks made by hand are dropped and the disc and the macula found again."""
        row = self.current
        rgb = self._load(row) if row is not None else None
        if rgb is None:
            return
        self._set_marking3d(None)
        iid = row["id"]
        for field in ("disc", "fovea"):
            self._set_landmark_source(iid, field, None)
        row = self.db.get_image(iid)
        circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else imaging.detect_circle(rgb)
        prof = get_profile(row["profile"])
        cam = self._photo_camera(row)
        tmax = math.degrees(cam.tmax) if cam is not None else 45.0
        disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / max(tmax, 5.0)), search=prof.disc_search)
        fovea = None
        if disc is not None and cam is not None:
            try:
                src = json.loads(row["meta_json"] or "{}").get("sources", {}).get("laterality")
            except (ValueError, TypeError):
                src = None
            guessed = row["laterality"] not in ("OD", "OS") or src in ("disc-estimate", "fovea-estimate")
            found = imaging.detect_fovea(rgb, cam, disc[:2], None if guessed else row["laterality"], with_side=True)
            if found is not None:
                fovea = found[:2]
                if guessed and found[3] != row["laterality"]:
                    self._set_laterality(iid, found[3], "fovea-estimate")
        self.db.update_image(iid, disc_x=disc[0] if disc else None, disc_y=disc[1] if disc else None,
                             fovea_x=fovea[0] if fovea else None, fovea_y=fovea[1] if fovea else None)
        self._fovea_tried.add(iid)
        if not self.c_autofind3d.isChecked():
            self.c_autofind3d.setChecked(True)             # (→ _push_mapping)
        self.current = self.db.get_image(iid)
        self.view2d.set_overlays(*self._marks_of(self.current))
        self._push_mapping()
        self.lbl_status.setText("직접 정한 위치를 지우고 다시 찾았습니다 — " + self._found_text())

    def _set_laterality(self, image_id: int, eye: str, source: str) -> None:
        row = self.db.get_image(image_id)
        meta = json.loads(row["meta_json"] or "{}")
        meta.setdefault("sources", {})["laterality"] = source
        self.db.update_image(image_id, laterality=eye, meta_json=meta)

    def _on_eye3d(self, choice: str) -> None:
        """눈: OD / OS as stated, or 자동 — from the side of the disc the macula is found on."""
        row = self.current
        if row is None:
            return
        iid = row["id"]
        rgb = self._load(row)
        cam = self._photo_camera(row)
        disc = (row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None
        found = None
        if rgb is not None and cam is not None and disc is not None and not self._by_hand(row, "fovea"):
            found = imaging.detect_fovea(rgb, cam, disc, None if choice == "auto" else choice, with_side=True)
        if choice == "auto":
            eye = found[3] if found is not None else imaging.laterality_from_disc(
                (disc[0], disc[1], 9.0) if disc else None, (row["circle_cx"], row["circle_cy"], row["circle_r"]))
            self._set_laterality(iid, eye, "fovea-estimate" if found is not None else "disc-estimate")
        else:
            self._set_laterality(iid, choice, "manual")
        if found is not None:
            self.db.update_image(iid, fovea_x=found[0], fovea_y=found[1])
        self.current = self.db.get_image(iid)
        self._fill_info(self.current)
        self.view2d.set_overlays(*self._marks_of(self.current))
        self._push_mapping()
        self._fill_thumbs(select_id=iid)

    def _on_device3d(self, key: str) -> None:
        """장비: the device's field of view and projection for this photo (사진 맞춤 shows and keeps them)."""
        prof = get_profile(key)
        for w in (self.sp_fov, self.c_fovtype, self.c_proj):
            w.blockSignals(True)
        self.sp_fov.setValue(prof.fov_deg)
        self.c_fovtype.setCurrentIndex(max(0, self.c_fovtype.findData(prof.fov_type)))
        self.c_proj.setCurrentIndex(max(0, self.c_proj.findData(prof.projection)))
        for w in (self.sp_fov, self.c_fovtype, self.c_proj):
            w.blockSignals(False)
        self._push_mapping()
        self.lbl_status.setText(f"{self.c_device3d.currentText()}의 화각·투영으로 얹었습니다 — [화각·투영 저장]으로 저장")

    # -- 망막 입체 · 단순하게 보기 ---------------------------------------------------------------
    HEIGHT_MAX = 0.08       # 높이 100: the height of +1 in eye radii (≈ 1 mm, the relief exaggerated)

    def _on_surface(self, on: bool) -> None:
        self.settings.surface3d = bool(on)
        self.eye3d.relief_on = bool(on)
        self.s_height3d.setEnabled(on)
        self.eye3d.update()

    def _on_height(self, v: int) -> None:
        self.settings.surface_height3d = int(v)
        self.eye3d.relief_amount = v / 100.0 * self.HEIGHT_MAX
        self.eye3d.update()

    def _on_simple(self, on: bool) -> None:
        self.settings.simple3d = bool(on)
        eye, start, goal = self.eye3d, self.eye3d.simple, 1.0 if on else 0.0
        self._simple_tween = motion.Tween(lambda k: (setattr(eye, "simple", start + (goal - start) * k), eye.update()),
                                          0.45, motion.ease_in_out)
        self._simple_tween.start()

    # -- 효과: 입체 조명 · 자동 회전 -----------------------------------------------------------
    RELIEF = 0.6            # strength of 입체 조명
    SPIN = 10.0             # 자동 회전, degrees per second
    UI_VERSION = 4          # 2: the dark look — 자세히, 유리 공막 and 자동 회전 from the start; 3: the 3D tab
                            # as the web page (자세히, 황반·유두 자동으로 찾기); 4: the 3D eye shows the
                            # original photo (망막 입체 — 표면 높낮이 and 입체 조명 — off from the start)

    def _on_relief(self, on: bool) -> None:
        self.settings.relief3d = bool(on)
        self.eye3d.relief = self.RELIEF if on else 0.0
        self.eye3d.update()

    def _on_spin(self, on: bool) -> None:
        self.settings.auto_rotate3d = bool(on)
        self._apply_spin()

    def _on_smooth(self, on: bool) -> None:
        self.settings.smooth_motion = bool(on)
        motion.set_enabled(on)
        self._apply_spin()
        self.lbl_status.setText("부드러운 움직임을 켰습니다" if on else
                                "부드러운 움직임을 껐습니다 — 확대·회전·전환이 바로 바뀝니다")

    def _mark_3d_dirty(self) -> None:
        self._3d_dirty = True
        if self._tab() == "3d":
            self._update_3d()
        elif self._tab() == "all" and self._ov_gl:
            self._ov3d_timer.start(150)

    def _update_3d(self) -> None:
        self._3d_dirty = False
        self._show.stop()                     # another photo: the presentation was about the last one
        row = self.current
        if row is None:
            self.eye3d.set_image(None)
            self.scan_photo.set_image(None)
            return
        rgb = self._load(row)
        if rgb is None:
            return
        circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else imaging.detect_circle(rgb)
        tex = self._display_rgb(row) if self.c_adj3d.isChecked() else rgb
        alpha = imaging.fundus_alpha(rgb, circle)
        self.eye3d.field_from_cover = row["modality"] == "montage"    # its angle: what it covers, not its map
        self.eye3d.set_image(tex, alpha, circle)
        self.scan_photo.set_image(tex, alpha, circle)
        self.photo3d.set_photo(tex, alpha)
        self._refresh_photo3d()

    def grab_3d(self) -> QImage:
        """The 3D view as on the screen: with 사진 나란히 the eye and the photo side by side.
        (The eye comes from its framebuffer — QWidget.grab would lose the drawn field of view.)"""
        eye = self.eye3d.grabFramebuffer()
        if not self.scan_photo.isVisible():
            return eye
        dpr = eye.devicePixelRatio()
        out = QImage(round(self.split3d.width() * dpr), round(self.split3d.height() * dpr),
                     QImage.Format.Format_RGB32)
        out.setDevicePixelRatio(dpr)
        out.fill(QColor(0, 0, 0))
        p = QPainter(out)
        p.drawImage(self.eye3d.geometry().topLeft(), eye)
        p.drawPixmap(self.scan_photo.geometry().topLeft(), self.scan_photo.grab())
        p.end()
        return out

    def _save_3d(self) -> None:
        if self._tab() != "3d":
            self._go("3d")
        img = self.grab_3d()
        path, _ = QFileDialog.getSaveFileName(self, "3D 화면 저장", "eye3d.png", "PNG (*.png)")
        if path:
            img.save(path)

    def _on_disc_picked(self, x: float, y: float) -> None:
        if self.current is None:
            return
        self._set_landmark_source(self.current["id"], "disc", "manual")
        self._set_disc(self.current["id"], x, y)
        self.lbl_status.setText("시신경 유두 위치를 저장했습니다 (3D 시신경에 반영)")

    def _set_disc(self, image_id: int, x: float, y: float) -> None:
        """Store a photo's optic disc position (2D right-click menu, disc pair clicks)."""
        self.db.update_image(image_id, disc_x=x, disc_y=y)
        row = self.db.get_image(image_id)
        cam = self._photo_camera(row, stored=True)
        if cam is not None and row["fovea_x"] is not None and not self._by_hand(row, "fovea"):
            # a fovea that was looked for beside the old disc: keep it only if it still fits the new one
            a, b = cam.direction(row["fovea_x"], row["fovea_y"]), cam.direction(x, y)
            if a is None or b is None or not (12.0 <= placement.angle_between(a, b) <= 32.0):
                self.db.update_image(image_id, fovea_x=None, fovea_y=None)
                row = self.db.get_image(image_id)
        if row["fovea_x"] is None:
            rgb = self._load(row)
            fovea = self._find_fovea(row, rgb) if rgb is not None else None
            if fovea is not None:
                self.db.update_image(image_id, fovea_x=fovea[0], fovea_y=fovea[1])
                row = self.db.get_image(image_id)
        if self.current is not None and self.current["id"] == image_id:
            self.current = row
            self.view2d.set_overlays(*self._marks_of(row))
            self._push_mapping()

    def _on_fovea_picked(self, x: float, y: float) -> None:
        if self.current is None:
            return
        self._set_landmark_source(self.current["id"], "fovea", "manual")
        self.db.update_image(self.current["id"], fovea_x=x, fovea_y=y)
        self.current = self.db.get_image(self.current["id"])
        self.view2d.set_overlays(*self._marks_of(self.current))
        self._push_mapping()
        self.lbl_status.setText("황반 위치를 저장했습니다 (3D에서 안구 뒤쪽 한가운데에 맞춤)")

    # -- the first view: 모두 보기, or 16장 보기 in the VK-2 way (설정 → 일반 → 환자를 열면) ----------
    def _grid_mode(self) -> bool:
        return self.settings.open_view == GRID_MODE

    def _home(self) -> str:
        """The view a patient opens on, and the one the 다중 / 3D buttons go back to."""
        return "grid" if self._grid_mode() else "all"

    SEG_WIDTH = {False: 258, True: 330}      # the view switch: three segments · four (with 16장)

    def _apply_open_view(self) -> None:
        """The VK-2 way has 16장 보기 in the view switch and the 보기 menu; the other way has not."""
        on = self._grid_mode()
        self.view_buttons["grid"].setVisible(on)
        self.view_acts["grid"].setVisible(on)
        self.view_acts["grid"].setEnabled(on)
        self.seg_views.setFixedWidth(self.SEG_WIDTH[on])
        self._side_w.setFixedWidth(self.SEG_WIDTH[on] + 16)
        if not on and self._tab() == "grid":   # (not _go: the patient list stays if it is on screen)
            self.tabs.setCurrentWidget(self._pages["all"])

    def _sync_grid_bar(self) -> None:
        """16장 보기's line: how many photos, which of them are on screen, the page buttons."""
        g = self.grid
        n, pages = len(g.items()), g.pages()
        first, last = g.page_range()
        self.lbl_grid_page.setText(f"사진 {n}장" + (f"  ·  {first}–{last}  ({g.page() + 1} / {pages})"
                                                   if pages > 1 else ""))
        for b, ok in ((self.btn_grid_prev, g.page() > 0), (self.btn_grid_next, g.page() < pages - 1)):
            b.setVisible(pages > 1)
            b.setEnabled(ok)

    # -- tabs by name -----------------------------------------------------------------
    def _tab(self) -> str:
        w = self.tabs.currentWidget()
        return next((k for k, page in getattr(self, "_pages", {}).items() if page is w), "")

    def _go(self, key: str) -> None:
        key = GONE_VIEWS.get(key, key)
        if key == "grid" and not self._grid_mode():
            key = "all"                       # 16장 보기 belongs to the VK-2 way (설정 → 일반 → 환자를 열면)
        if self.tabs.currentWidget() is not self._pages[key]:
            self._tab_fade.snap()             # the page on screen fades into the next
        self.tabs.setCurrentWidget(self._pages[key])

    def _on_tab(self, i: int) -> None:
        key = self._tab()
        vb = getattr(self, "view_buttons", {}).get(key)
        if vb is not None and not vb.isChecked():
            vb.setChecked(True)
        self.btn_3d.setChecked(key == "3d")
        if key == "3d":
            self.seg_views.clear()            # 3D is the icon at the top, not a segment under the photos
        # 검토 has its own timeline: the photo strip and its filters are for the other tabs
        self.strip_w.setVisible(key != "review")
        self.view_bar.setVisible(key != "review")
        self.multi_bar.setVisible(key == "multi")
        # 16장 보기 is the photo list itself: its pages take the strip's place
        self.thumbs.setVisible(key != "grid" and self.act_thumbs.isChecked())
        self.grid_bar.setVisible(key == "grid")
        if key == "grid":
            self._sync_grid_bar()
        for w in (self.f_date, self.f_eye, self.f_mod):
            w.setVisible(key != "review")
        self._fit_banner()
        if key == "review":
            self._fill_review()
            self.review.views[self.review.active].setFocus()
        self._place_overview(key == "all")
        if key != "3d":
            self._show.stop()
            self._tween._finish()
        if self._3d_dirty and (key == "3d" or (key == "all" and self._ov_gl)):
            self._update_3d()
        if key == "3d" and self._gl_msg:
            msg, self._gl_msg = self._gl_msg, ""
            QMessageBox.warning(self, "3D", msg)
        if key == "multi":
            self._fill_multi()
        if key == "cmp":
            self._fill_compare()
        if key == "all":
            self._fill_overview()
        self._apply_spin()
        self._tab_fade.play()

    def _apply_spin(self) -> None:
        """자동 회전 turns the eye in the 3D tab only (not the small pane of 모두 보기)."""
        on = self.c_spin3d.isChecked() and self._tab() == "3d"
        self.eye3d.set_auto_rotate(self.SPIN if on else 0.0)

    # -- 모두 보기: 큰 2D + 다중 · 확대 · 3D -------------------------------------------------
    def _build_overview(self) -> QWidget:
        w = QWidget()
        self.ov_big = QWidget()                          # view2d goes here while 모두 보기 is shown
        self._ov_big_lay = QVBoxLayout(self.ov_big)
        self._ov_big_lay.setContentsMargins(0, 0, 0, 0)
        side = QSplitter(Qt.Orientation.Vertical)       # two equal panes, heights can be dragged
        side.setObjectName("ovSide")
        side.setChildrenCollapsible(False)
        side.setHandleWidth(4)
        self.ov_multi = MultiView(compact=True)          # (no longer shown beside the photo)
        self.ov_multi.hide()
        # the two places looked at first, enlarged: the macula and the optic disc of the big photo
        self.ov_macula = ImageView()
        self.ov_zoom = ImageView()                       # the disc
        for v, what in ((self.ov_macula, "황반"), (self.ov_zoom, "시신경 유두")):
            v.set_navigator(False)
            v.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # a small pane:
            v.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)     # move by dragging
            v.setToolTip(f"{what} 확대 — 휠: 배율 · 드래그: 이동 · "
                         f"더블클릭: 큰 사진을 {what} 쪽으로 확대\n"
                         "잘못 찾았으면 큰 사진에서 오른쪽 클릭 → 황반 / 시신경 유두로 지정")
            v.zoomChanged.connect(lambda _: self._ov_sync_roi())
            v.horizontalScrollBar().valueChanged.connect(lambda _: self._ov_sync_roi())
            v.verticalScrollBar().valueChanged.connect(lambda _: self._ov_sync_roi())
        self.ov_3d = QWidget()                           # (the 3D eye stays in its own tab)
        self._ov_3d_lay = QVBoxLayout(self.ov_3d)
        self._ov_3d_lay.setContentsMargins(0, 0, 0, 0)
        self._ov_gl = False
        self._gl_msg = ""
        self._ov3d_timer = QTimer(self)
        self._ov3d_timer.setSingleShot(True)
        self.ov_heads = {}
        self._ov_titles = {"macula": "황반", "zoom": "시신경 유두"}
        for key, body in (("macula", self.ov_macula), ("zoom", self.ov_zoom)):
            pane = QFrame()
            pane.setObjectName("ovPane")
            v = QVBoxLayout(pane)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            head = QPushButton(f"{self._ov_titles[key]}   ⤢")
            head.setObjectName("ovHead")
            head.setToolTip(f"큰 사진을 {self._ov_titles[key]} 쪽으로 확대 (큰 사진 전체로: 0 키)")
            head.clicked.connect(lambda _=False, k=key: self._ov_focus(k))
            body.activated.connect(lambda k=key: self._ov_focus(k))
            v.addWidget(head)
            v.addWidget(body, 1)
            body.setMinimumHeight(60)
            body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)   # equal heights
            side.addWidget(pane)
            side.setStretchFactor(side.count() - 1, 1)
            self.ov_heads[key] = head
        self.ov_split = QSplitter(Qt.Orientation.Horizontal)
        self.ov_split.setChildrenCollapsible(False)
        self.ov_split.addWidget(self.ov_big)
        self.ov_split.addWidget(side)
        self.ov_split.setStretchFactor(0, 3)
        self.ov_split.setStretchFactor(1, 1)
        self.ov_split.setSizes([900, 340])
        side.setSizes([300, 300])
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.ov_split)
        # where the two panes look: frames on the big photo (macula light blue, disc yellow — as the marks)
        self._ov_rois = {}
        for key, color in (("macula", QColor(80, 220, 255)), ("zoom", QColor(255, 214, 10))):
            roi = QGraphicsRectItem()
            roi.setPen(QPen(color, 0, Qt.PenStyle.DashLine))
            roi.setZValue(30)
            roi.setVisible(False)
            self.view2d.scene().addItem(roi)
            self._ov_rois[key] = roi
        self._ov_roi = self._ov_rois["zoom"]
        self.view2d.viewport().installEventFilter(self)
        for v in (self.ov_macula, self.ov_zoom):
            v.viewport().installEventFilter(self)
        self._ov_img: int | None = None
        self._ov_targets: dict = {}              # pane -> ((x, y), width) of the place it shows
        self._ov_center = None
        self._ov_press = None
        self._ov_busy = False
        return w

    def _ov_3d_button(self) -> None:
        b = QPushButton("3D 안구 보기 →")
        b.setObjectName("ovOpen3d")
        b.setToolTip("이 PC 에서는 3D 를 작은 화면에 함께 띄우지 않습니다 — 3D 안구 탭에서 봅니다")
        b.clicked.connect(lambda: self._go("3d"))
        self._ov_3d_lay.addWidget(b)

    def _on_gl_error(self, msg: str) -> None:
        msg += "\n\n설정 > 일반 > 3D 렌더링을 '소프트웨어 렌더링'으로 바꾸고 다시 시작해 보세요."
        if self._ov_gl and not self.eye3d._ok and self.split3d.parent() is self.ov_3d:
            # OpenGL failed in the small 3D pane: no pop-up at every start — the pane becomes a
            # button, and the message is shown when the 3D tab is opened
            self._ov_gl = False
            self._lay3d.addWidget(self.split3d, 1)
            self._ov_3d_button()
            self._gl_msg = msg
            return
        QMessageBox.warning(self, "3D", msg)

    def _place_overview(self, on: bool) -> None:
        """Move the 2D view (and the 3D eye) into 모두 보기 or back to their own tabs."""
        if on == self._ov_on:
            return
        self._ov_on = on
        if on:
            self._ov_big_lay.addWidget(self.view2d)
            if self._ov_gl and self._full3d is None:
                self._ov_3d_lay.addWidget(self.split3d, 1)
        else:
            self._lay2d.addWidget(self.view2d)
            if self._full3d is None and self.split3d.parent() is self.ov_3d:
                self._lay3d.addWidget(self.split3d, 1)
        self.view2d.show()
        self.split3d.show()
        for key, view in (("macula", self.ov_macula), ("zoom", self.ov_zoom)):
            self._ov_rois[key].setVisible(on and view.has_image())

    def _fill_overview(self, multi: bool = True) -> None:
        """모두 보기의 작은 화면 둘: 큰 화면과 같은 처리를 한 사진의 황반과 시신경 유두를 확대해서."""
        if not self._ov_on:
            return
        row = self.current
        rgb = self.view2d._rgb if row is not None else None     # what the big view shows now
        self._ov_busy = True                                    # set_rgb fits the view: not a pan
        try:
            for v in (self.ov_macula, self.ov_zoom):
                v.set_rgb(rgb)
        finally:
            self._ov_busy = False
        if rgb is None:
            self._ov_img, self._ov_targets = None, {}
            for roi in self._ov_rois.values():
                roi.setVisible(False)
            return
        self._ov_img = row["id"]
        h, w = rgb.shape[:2]
        _, disc, fovea = self._marks_of(row)
        # how much is shown: the macula with its surround, the disc with the vessels leaving it —
        # by the photo's own scale (the disc–fovea distance, about 15°) where both were found
        d = math.hypot(disc[0] - fovea[0], disc[1] - fovea[1]) if disc and fovea else None
        long = max(w, h)
        centre = (w / 2, h / 2)
        self._ov_targets = {"macula": (fovea or centre, 1.5 * d if d else long / 3),
                            "zoom": (disc or centre, 0.85 * d if d else long / OV_ZOOM)}
        for key, found in (("macula", fovea), ("zoom", disc)):
            note = "" if found else "  (찾지 못함 — 사진 가운데)"
            self.ov_heads[key].setText(f"{self._ov_titles[key]}{note}   ⤢")
        self._ov_apply()

    def _ov_focus(self, key: str) -> None:
        """The big photo zoomed to the place a pane shows (황반 / 시신경 유두), with its surround."""
        if key not in self._ov_targets or not self.view2d.has_image():
            return
        (x, y), w = self._ov_targets[key]
        w *= 2.0
        vw, vh = max(self.view2d.viewport().width(), 1), max(self.view2d.viewport().height(), 1)
        h = w * vh / vw
        self.view2d.zoom_to_rect(QRectF(x - w / 2, y - h / 2, w, h))

    def _ov_apply(self) -> None:
        """Each pane on its place, that place's width across the pane."""
        if not self._ov_on:
            return
        self._ov_busy = True                       # the scroll bars move: keep the asked-for centres
        try:
            for key, view in (("macula", self.ov_macula), ("zoom", self.ov_zoom)):
                if key not in self._ov_targets or not view.has_image():
                    continue
                (x, y), w = self._ov_targets[key]
                vw, vh = max(view.viewport().width(), 1), max(view.viewport().height(), 1)
                h = w * vh / vw
                view.zoom_to_rect(QRectF(x - w / 2, y - h / 2, w, h), animate=False)
        finally:
            self._ov_busy = False
        self._ov_sync_roi()

    def _ov_sync_roi(self) -> None:
        """큰 사진 위의 틀 = 두 확대 화면에 지금 보이는 곳 (확대 화면을 끌어 옮기면 틀도 따라감)."""
        for key, view in (("macula", self.ov_macula), ("zoom", self.ov_zoom)):
            roi = self._ov_rois[key]
            if not (self._ov_on and view.has_image()):
                roi.setVisible(False)
                continue
            vis = view.mapToScene(view.viewport().rect()).boundingRect()
            r = vis.intersected(QRectF(view._pix.pixmap().rect()))
            roi.setRect(r)
            roi.setVisible(not r.isEmpty())

    # -- compare -------------------------------------------------------------------
    def _set_compare(self, image_id: int) -> None:
        if self.current is not None and image_id == self.current["id"]:
            return
        self.compare = self.db.get_image(image_id)
        self._mark_pair()
        self.lbl_status.setText(keys("두 사진을 골랐습니다 (② = 두 번째) — [디스크 2장] · [녹내장](스테레오 · 경과 비교) · "
                                     "Ctrl+클릭으로 해제"))

    def _fill_compare(self) -> None:
        for view, lab, row in zip(self.cmp_views, self.cmp_labels, (self.current, self.compare)):
            if row is None:
                view.set_rgb(None)
                lab.setText(keys("Ctrl+클릭으로 비교할 사진을 고르세요") if row is self.compare else "")
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
            return None, keys("사진 두 장을 고르세요.\n\n썸네일에서 한 장을 클릭한 뒤 두 번째 사진을 Ctrl+클릭하면 "
                              "② 표시가 붙습니다. 그다음 [디스크 2장]을 누르세요.")
        if first["patient_ref"] is None or second["patient_ref"] is None:
            return None, "미분류 사진은 쓸 수 없습니다.\n먼저 [정보 수정]으로 환자를 지정하세요."
        if first["patient_ref"] != second["patient_ref"]:
            return None, "서로 다른 환자의 사진입니다."
        for row in (first, second):
            if row["modality"] in ("anterior", "disc", "glaucoma"):
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
        self.refresh_patients()
        self._fill_dates()
        self._fill_thumbs(select_id=self.current["id"] if self.current else None)
        self.lbl_status.setText("디스크 2장을 이 환자 기록에 저장했습니다")
        return new_id

    # -- glaucoma (녹내장 분석 — glaucoma.py, glaucoma_dialog.py) --------------------------------
    def _glaucoma_photo(self, row, rgb: np.ndarray) -> Photo:
        src = self._disc_source(row, rgb)
        fovea = (row["fovea_x"], row["fovea_y"]) if row["fovea_x"] is not None else None
        return Photo(row["id"], rgb, src.eye, src.disc,
                     discpair.disc_diameter_px(src.geometry, src.disc, (rgb.shape[1], rgb.shape[0])),
                     fovea, src.found == "saved", src.when, src.caption)

    def _build_glaucoma(self, second_id: int | None = None):
        """``(dialog, "")`` for the shown photo — with ``second_id`` (default: the ② photo, if one
        is picked) as its pair for stereo and progression — or ``(None, why not)``."""
        if self.current is None:
            return None, "사진을 고르세요."
        first = self.db.get_image(self.current["id"])
        if second_id is None or second_id == first["id"]:
            second_id = self.compare["id"] if self.compare is not None else None
        second = self.db.get_image(second_id) if second_id is not None else None
        rows = [first] + ([second] if second is not None and second["id"] != first["id"] else [])
        if len(rows) == 2 and first["patient_ref"] != second["patient_ref"]:
            return None, "서로 다른 환자의 사진입니다."
        photos = []
        for row in rows:
            if row["modality"] in ("anterior", "disc", "glaucoma"):
                return None, f"{MODALITY_LABELS[row['modality']]} 사진은 분석할 수 없습니다."
            rgb = self._load(row)
            if rgb is None:
                return None, f"영상을 열 수 없습니다: {Path(row['original_path'] or row['file_path']).name}"
            photos.append(self._glaucoma_photo(row, rgb))
        p = self.db.get_patient(first["patient_ref"]) if first["patient_ref"] else None
        bits = [p["name"] or "(이름 없음)", f"ID {p['patient_id']}"] if p is not None else ["미분류"]
        bits += [ph.caption for ph in photos]
        stem = "_".join(x for x in (p["patient_id"] if p is not None else "", "녹내장", first["exam_date"] or "") if x)
        dlg = GlaucomaDialog(photos[0], photos[1] if len(photos) == 2 else None, title_line="  ·  ".join(bits),
                             file_stem=safe_component(stem, "녹내장"), save_record=self._save_glaucoma, parent=self)
        return dlg, ""

    def open_glaucoma(self, second_id: int | None = None) -> None:
        dlg, why = self._build_glaucoma(second_id)
        if dlg is None:
            QMessageBox.information(self, "녹내장 분석", why)
            return
        dlg.exec()

    def _save_glaucoma(self, rgb: np.ndarray, note: str, eye: str | None, image_ids) -> int:
        """Store an analysis picture as a new photo of the patient (modality ``glaucoma``)."""
        rows = [self.db.get_image(i) for i in image_ids]
        new_id = self.service.importer.add_derived(
            rows[0], rgb, note, suffix="녹내장", derived_from=[r["id"] for r in rows],
            laterality=eye if eye in ("OD", "OS") else rows[0]["laterality"], modality="glaucoma",
            fov_deg=None, fov_type=None, projection=None, circle_cx=None, circle_cy=None, circle_r=None,
            disc_x=None, disc_y=None, fovea_x=None, fovea_y=None)
        self.refresh_patients()
        self._fill_dates()
        self._fill_thumbs(select_id=self.current["id"] if self.current else None)
        self.lbl_status.setText("녹내장 분석 화면을 이 환자 기록에 저장했습니다")
        return new_id

    # -- montage (몽타주 — montage.py, montage_dialog.py) ----------------------------------------
    @staticmethod
    def _montage_definition(row) -> dict | None:
        """The arrangement of a montage made here (None for photos and for a device's montage)."""
        if row["modality"] != "montage":
            return None
        try:
            d = json.loads(row["meta_json"] or "{}").get("montage")
        except (ValueError, AttributeError):
            return None
        return d if isinstance(d, dict) and d.get("shots") else None

    def _montage_source(self, row, rgb: np.ndarray) -> MontageSource:
        prof = get_profile(row["profile"])
        circle = ((row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"]
                  else imaging.detect_circle(rgb))
        label = row["exam_time"] or row["exam_date"] or Path(row["original_path"] or row["file_path"]).stem
        if row["exam_date"] and row["exam_time"]:
            label = f"{row['exam_date'][5:]} {row['exam_time'][:8]}"
        return MontageSource(
            row["id"], rgb, imaging.fundus_alpha(rgb, circle), circle,
            fov_deg=row["fov_deg"] or prof.fov_deg, fov_type=row["fov_type"] or prof.fov_type,
            projection=row["projection"] or prof.projection, viewpoint=prof.viewpoint, radial_c=prof.radial_c,
            label=label, disc=(row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None,
            laterality=row["laterality"] if row["laterality"] in ("OD", "OS") else None)

    def _montage_sources(self, ids: list[int]):
        """``(sources, "")`` for the photos ``ids``, or ``(None, why not)``."""
        if len(ids) < 2:
            return None, ("사진을 두 장 이상 고르세요.\n\n아래 사진 목록에서 같은 눈의 사진을 차례로 클릭해 번호를 "
                          "붙인 뒤 사진 위 줄의 [Montage]를 누르세요.")
        rows = [self.db.get_image(i) for i in ids]
        if any(r is None for r in rows):
            return None, "몽타주에 쓰인 사진 가운데 목록에서 지워진 것이 있습니다."
        if len({r["patient_ref"] for r in rows}) > 1:
            return None, "서로 다른 환자의 사진입니다."
        for r in rows:
            if r["modality"] in ("anterior", "disc", "glaucoma"):
                return None, f"{MODALITY_LABELS[r['modality']]} 사진은 몽타주에 쓸 수 없습니다."
        sources = []
        for r in rows:
            rgb = self._load(r)
            if rgb is None:
                return None, f"영상을 열 수 없습니다: {Path(r['original_path'] or r['file_path']).name}"
            sources.append(self._montage_source(r, rgb))
        return sources, ""

    def _montage_stem(self, row) -> str:
        p = self.db.get_patient(row["patient_ref"]) if row["patient_ref"] is not None else None
        bits = [p["patient_id"], p["name"] or ""] if p is not None else []
        bits += ["몽타주", row["laterality"] or "", row["exam_date"] or ""]
        return safe_component("_".join(x for x in bits if x), "몽타주")

    def open_montage(self, ids: list[int] | None = None, definition: dict | None = None) -> None:
        """몽타주 편집기 for the picked photos (or ``ids``; ``definition`` = a saved arrangement)."""
        if ids is None:
            ids = list(self._picks)
        sources, why = self._montage_sources(ids)
        if sources is None:
            QMessageBox.information(self, "몽타주", why)
            return
        if not confirm_sources(self, sources):
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dlg = MontageDialog(sources, file_stem=self._montage_stem(self.db.get_image(ids[0])),
                                save_record=self._save_montage, definition=definition,
                                fast=bool(getattr(self.settings, "montage_fast", False)),
                                on_fast=self._set_montage_fast,
                                relief3d=self.settings.relief3d, surface3d=self.settings.surface3d, parent=self)
        finally:
            QApplication.restoreOverrideCursor()
        self._montage_dlg = dlg
        try:
            dlg.exec()
        finally:
            self._montage_dlg = None
            dlg.deleteLater()

    def _set_montage_fast(self, on: bool) -> None:
        """몽타주 창의 '빠르게 저장' — remembered for the next montage."""
        self.settings.montage_fast = bool(on)
        self.settings.save()

    def edit_montage(self, image_id: int) -> None:
        row = self.db.get_image(image_id)
        d = self._montage_definition(row) if row is not None else None
        if d is None:
            return
        self.open_montage([s.get("image_id") for s in d["shots"]], definition=d)

    def _save_montage(self, res) -> int:
        """Store a montage (``montage_dialog.MontageResult``) as a new photo of the patient: modality
        몽타주, its eye geometry (equidistant, internal field of view) for the 3D view and measurements,
        and the arrangement for 다시 편집."""
        ids = [i for i in res.image_ids if i is not None]
        rows = [self.db.get_image(i) for i in ids]
        ref_id = res.definition["shots"][res.definition.get("ref", 0)].get("image_id")
        base = next((r for r in rows if r["id"] == ref_id), rows[0])
        meta = json.loads(base["meta_json"] or "{}")
        meta.update(derived_from=ids, montage=res.definition)
        cx, cy, r = res.geom.circle()
        new_id = self.service.importer.add_derived(
            base, res.rgb, f"몽타주 {len(ids)}장 ({mt_span_text(res.span)})", suffix="몽타주", derived_from=ids,
            laterality=res.laterality or base["laterality"], modality="montage", fov_deg=res.fov_deg,
            fov_type="internal", projection="equidistant", circle_cx=cx, circle_cy=cy, circle_r=r,
            disc_x=res.disc[0] if res.disc else None, disc_y=res.disc[1] if res.disc else None, meta_json=meta)
        self.refresh_patients()
        self._fill_dates()
        self._fill_thumbs(select_id=self.current["id"] if self.current else None)
        self.lbl_status.setText(f"몽타주({len(ids)}장)를 이 환자 기록에 저장했습니다 — 썸네일을 더블클릭하면 2D, "
                                "3D 안구 탭에서 안구 위에 볼 수 있습니다")
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
                             disc_x=disc[0] if disc else None, disc_y=disc[1] if disc else None,
                             fovea_x=None, fovea_y=None)
        self._fovea_tried.discard(image_id)     # looked for again when shown
        self._show_image(image_id)

    def _remove_image(self, image_id: int) -> None:
        ok = QMessageBox.question(self, "목록에서 제거",
                                  "이 영상을 뷰어 데이터베이스에서 제거할까요?\n"
                                  "(원본 파일과 라이브러리 사본은 지우지 않습니다)")
        if ok == QMessageBox.StandardButton.Yes:
            self.db.delete_image(image_id)
            self._cache.pop(image_id, None)
            for key in [k for k in self._small if k[0] == image_id]:
                del self._small[key]
            if self.compare is not None and self.compare["id"] == image_id:
                self.compare = None
            self.refresh_patients()
            self._fill_thumbs()

    def _fill_log(self) -> None:
        rows = self.db.recent_logs(300)
        self.log.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate((r["at"].replace("T", " "), r["level"], r["message"], r["path"] or "")):
                it = QTableWidgetItem(v)
                if r["level"] == "error":
                    it.setForeground(QColor(theme.RED))
                self.log.setItem(i, j, it)
        self.log.resizeColumnToContents(0)

    def _open_log_path(self, index) -> None:
        it = self.log.item(index.row(), 3)
        if it and it.text() and os.path.exists(it.text()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(it.text()).parent)))

    def closeEvent(self, e):
        self._closing = True
        self._show.stop()
        self._exit_full_3d()
        try:
            self.settings.save()
        except OSError:
            pass
        self._preload_timer.stop()
        pl = self.patient_list
        for t in (pl._search_timer, pl._select_timer, self._result_timer, self._share_timer):
            t.stop()                           # nothing reads the database after it is closed
        pl._pending = None
        pl.hide()
        if self.share_server is not None:
            self.share_server.stop()
            self.share_server = None
        self._preloader.shutdown()
        self.review.shutdown()
        self.service.shutdown()
        super().closeEvent(e)
