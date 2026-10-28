"""Main window: patients · thumbnails · 2D / 3D / compare views · info panel."""
from __future__ import annotations

import json
import math
import os
from collections import OrderedDict
from datetime import date
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QSplitter,
    QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__, imaging
from .. import projection as proj
from ..config import Settings
from ..db import Database
from ..importer import ImportResult
from ..models import MODALITY_LABELS
from ..profiles import get_profile
from ..watcher import ImportService
from .dialogs import ImageDialog, PatientDialog, SettingsDialog, source_label
from .eye3d import EyeView
from .image_view import ImageView

UNASSIGNED = -1
SEX_LABEL = {"M": "남", "F": "여", "O": "기타"}


class Bridge(QObject):
    """Carries worker-thread callbacks into the GUI thread (queued signals)."""
    result = Signal(object)
    status = Signal(str)


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
        self.current = None          # images row
        self.compare = None
        self._patient_ref: int | None = None  # UNASSIGNED / patient id / None
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._3d_dirty = True
        self.setWindowTitle(f"{APP_TITLE}  v{__version__}")
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        self._build()
        self.refresh_patients()
        QTimer.singleShot(200, self._startup)

    # =====================================================================
    # layout
    # =====================================================================
    def _build(self) -> None:
        tb = QToolBar("도구")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        self.act_watch = QAction("▶ 폴더 감시 시작", self, checkable=True)
        self.act_watch.toggled.connect(self._toggle_watch)
        tb.addAction(self.act_watch)
        act_scan = QAction("⟳ 지금 검사", self)
        act_scan.setToolTip("감시 폴더에서 아직 가져오지 않은 파일을 찾습니다")
        act_scan.triggered.connect(self._scan_now)
        tb.addAction(act_scan)
        tb.addSeparator()
        act_files = QAction("파일 가져오기…", self)
        act_files.triggered.connect(self._import_files)
        tb.addAction(act_files)
        act_dir = QAction("폴더 가져오기…", self)
        act_dir.triggered.connect(self._import_dir)
        tb.addAction(act_dir)
        tb.addSeparator()
        self.act_follow = QAction("새 영상 자동 표시", self, checkable=True)
        self.act_follow.setChecked(True)
        self.act_follow.setToolTip("새 사진이 들어오면 그 환자와 사진을 바로 엽니다")
        tb.addAction(self.act_follow)
        tb.addSeparator()
        act_settings = QAction("설정…", self)
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)
        act_log = QAction("가져오기 기록", self, checkable=True)
        tb.addAction(act_log)

        # -- left: patients ---------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 0, 6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("환자 ID · 이름 · 생년월일 검색")
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

        # -- centre ---------------------------------------------------------------
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(4, 6, 4, 6)
        self.banner = QLabel("환자를 선택하세요")
        self.banner.setObjectName("banner")
        cl.addWidget(self.banner)
        filt = QHBoxLayout()
        self.f_date = QComboBox()
        self.f_date.currentIndexChanged.connect(self._fill_thumbs)
        self.f_eye = QComboBox()
        for k, v in (("", "양안 전체"), ("OD", "OD (우안)"), ("OS", "OS (좌안)")):
            self.f_eye.addItem(v, k)
        self.f_eye.currentIndexChanged.connect(self._fill_thumbs)
        self.f_mod = QComboBox()
        self.f_mod.addItem("전체 종류", "")
        for k, v in MODALITY_LABELS.items():
            self.f_mod.addItem(v, k)
        self.f_mod.currentIndexChanged.connect(self._fill_thumbs)
        filt.addWidget(QLabel("검사일"))
        filt.addWidget(self.f_date, 1)
        filt.addWidget(QLabel("눈"))
        filt.addWidget(self.f_eye)
        filt.addWidget(self.f_mod)
        filt.addStretch(2)
        hint = QLabel("Ctrl+클릭: 비교 대상 선택")
        hint.setStyleSheet("color:#889")
        filt.addWidget(hint)
        cl.addLayout(filt)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setFlow(QListWidget.Flow.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(150, 150))
        self.thumbs.setGridSize(QSize(172, 196))
        self.thumbs.setFixedHeight(214)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thumbs.itemClicked.connect(self._on_thumb_clicked)
        self.thumbs.currentItemChanged.connect(lambda cur, _: cur and self._show_image(cur.data(Qt.ItemDataRole.UserRole)))
        self.thumbs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        cl.addWidget(self.thumbs)
        self.tabs = QTabWidget()
        self.view2d = ImageView()
        self.view2d.discPicked.connect(self._on_disc_picked)
        self.tabs.addTab(self.view2d, "2D 보기")
        self.eye3d = EyeView()
        self.eye3d.glError.connect(lambda m: QMessageBox.warning(
            self, "3D", m + "\n\n설정 > 일반 > 3D 렌더링을 '소프트웨어 렌더링'으로 바꾸고 다시 시작해 보세요."))
        self.tabs.addTab(self.eye3d, "3D 안구")
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
        cmp_l.addWidget(self.cmp_sync)
        a, b = self.cmp_views
        for src, dst in ((a, b), (b, a)):
            src.horizontalScrollBar().valueChanged.connect(
                lambda val, d=dst: self.cmp_sync.isChecked() and d.horizontalScrollBar().setValue(val))
            src.verticalScrollBar().valueChanged.connect(
                lambda val, d=dst: self.cmp_sync.isChecked() and d.verticalScrollBar().setValue(val))
            src.zoomChanged.connect(lambda f, s=src, d=dst: self.cmp_sync.isChecked()
                                    and abs(d.transform().m11() - f) > 1e-6 and d.setTransform(s.transform()))
        self.tabs.addTab(cmp_w, "비교")
        self.tabs.currentChanged.connect(self._on_tab)
        cl.addWidget(self.tabs, 1)

        # -- right: info + controls --------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 6, 6, 6)
        g_info = QGroupBox("영상 정보")
        self.info = QFormLayout(g_info)
        self.info_labels: dict[str, QLabel] = {}
        for key in ("patient", "exam", "laterality", "modality", "device", "fov", "file"):
            lab = QLabel("-")
            lab.setWordWrap(True)
            # long file names must wrap, not widen the panel
            lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.info_labels[key] = lab
            self.info.addRow({"patient": "환자", "exam": "검사일시", "laterality": "눈", "modality": "촬영 종류",
                              "device": "장비", "fov": "화각", "file": "파일"}[key], lab)
        btn_row = QHBoxLayout()
        b_assign = QPushButton("환자 지정/수정…")
        b_assign.clicked.connect(self._edit_image)
        b_open = QPushButton("원본 폴더")
        b_open.clicked.connect(self._open_folder)
        btn_row.addWidget(b_assign)
        btn_row.addWidget(b_open)
        self.info.addRow(btn_row)
        rl.addWidget(g_info)

        g_adj = QGroupBox("보기 조정")
        fa = QFormLayout(g_adj)
        self.s_bright = self._slider(-100, 100, 0)
        self.s_contrast = self._slider(10, 300, 100)
        self.s_gamma = self._slider(20, 400, 100)
        fa.addRow("밝기", self.s_bright)
        fa.addRow("대비", self.s_contrast)
        fa.addRow("감마", self.s_gamma)
        self.c_channel = QComboBox()
        for k in imaging.CHANNELS:
            self.c_channel.addItem(imaging.CHANNEL_LABELS[k], k)
        self.c_channel.currentIndexChanged.connect(self._schedule_adjust)
        fa.addRow("채널", self.c_channel)
        chk = QHBoxLayout()
        self.c_auto = QCheckBox("자동 대비")
        self.c_invert = QCheckBox("반전")
        self.c_overlay = QCheckBox("원·시신경 표시")
        for c in (self.c_auto, self.c_invert):
            c.toggled.connect(self._schedule_adjust)
        self.c_overlay.toggled.connect(self.view2d.toggle_overlays)
        chk.addWidget(self.c_auto)
        chk.addWidget(self.c_invert)
        fa.addRow(chk)
        b_reset = QPushButton("조정 초기화")
        b_reset.clicked.connect(self._reset_adjust)
        fa.addRow(self.c_overlay, b_reset)
        rl.addWidget(g_adj)

        g3 = QGroupBox("3D 안구")
        f3 = QFormLayout(g3)
        mode_row = QHBoxLayout()
        self.r_out = QRadioButton("외부 (안구 모형)")
        self.r_in = QRadioButton("내부 (망막 시점)")
        self.r_out.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_out)
        grp.addButton(self.r_in)
        self.r_out.toggled.connect(self._on_3d_mode)
        mode_row.addWidget(self.r_out)
        mode_row.addWidget(self.r_in)
        f3.addRow(mode_row)
        self.s_cut = self._slider(-30, 100, 25, self._on_cut)
        f3.addRow("앞쪽 절개", self.s_cut)
        fov_row = QHBoxLayout()
        self.sp_fov = QDoubleSpinBox()
        self.sp_fov.setRange(10, 240)
        self.sp_fov.setDecimals(1)
        self.sp_fov.setSuffix("°")
        self.sp_fov.valueChanged.connect(self._on_mapping)
        self.c_fovtype = QComboBox()
        self.c_fovtype.addItem("안구 중심각", "internal")
        self.c_fovtype.addItem("외부각(동공)", "external")
        self.c_fovtype.currentIndexChanged.connect(self._on_mapping)
        fov_row.addWidget(self.sp_fov)
        fov_row.addWidget(self.c_fovtype)
        f3.addRow("화각", fov_row)
        self.c_proj = QComboBox()
        for k in proj.PROJECTIONS:
            self.c_proj.addItem(proj.PROJECTION_LABELS[k], k)
        self.c_proj.currentIndexChanged.connect(self._on_mapping)
        f3.addRow("투영", self.c_proj)
        self.sp_roll = QDoubleSpinBox()
        self.sp_roll.setRange(-180, 180)
        self.sp_roll.setSuffix("°")
        self.sp_roll.valueChanged.connect(self._on_mapping)
        f3.addRow("회전", self.sp_roll)
        chk3 = QHBoxLayout()
        self.c_nerve = QCheckBox("시신경")
        self.c_nerve.setChecked(True)
        self.c_nerve.toggled.connect(lambda on: (setattr(self.eye3d, "show_nerve", on), self.eye3d.update()))
        self.c_grid = QCheckBox("각도 격자(10°)")
        self.c_grid.toggled.connect(lambda on: (setattr(self.eye3d, "show_grid", on), self.eye3d.update()))
        self.c_adj3d = QCheckBox("보기 조정 적용")
        self.c_adj3d.setChecked(True)
        self.c_adj3d.toggled.connect(lambda _: self._mark_3d_dirty())
        for c in (self.c_nerve, self.c_grid):
            chk3.addWidget(c)
        f3.addRow(chk3)
        f3.addRow(self.c_adj3d)
        for pair in ((("정면 보기", self.eye3d.front_view), ("시점 초기화", self.eye3d.reset_view)),
                     (("화각·투영 저장", self._save_mapping), ("화면 저장…", self._save_3d))):
            row3 = QHBoxLayout()
            for label, fn in pair:
                b = QPushButton(label)
                b.clicked.connect(fn)
                row3.addWidget(b)
            f3.addRow(row3)
        self.lbl_3d = QLabel("드래그: 회전 · 휠: 확대 · 더블클릭: 초기화")
        self.lbl_3d.setStyleSheet("color:#889; font-size:11px")
        self.lbl_3d.setWordWrap(True)
        self.lbl_3d.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        f3.addRow(self.lbl_3d)
        rl.addWidget(g3)
        rl.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(right)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(390)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(centre)
        split.addWidget(scroll)
        split.setSizes([470, 740, 390])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

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
        act_log.toggled.connect(dock.setVisible)
        dock.visibilityChanged.connect(lambda v: (act_log.setChecked(v), v and self._fill_log()))

        sb = QStatusBar()
        self.lbl_watch = QLabel("감시 꺼짐")
        self.lbl_status = QLabel("")
        sb.addWidget(self.lbl_watch)
        sb.addWidget(self.lbl_status, 1)
        self.setStatusBar(sb)

        for i, key in enumerate(("Ctrl+1", "Ctrl+2", "Ctrl+3")):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, i=i: self.tabs.setCurrentIndex(i))
            self.addAction(a)

        self._adjust_timer = QTimer(self, singleShot=True, timeout=self._apply_adjust)
        self._results: list[ImportResult] = []
        self._result_timer = QTimer(self, singleShot=True, timeout=self._flush_results)

    def _slider(self, lo, hi, val, slot=None) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.valueChanged.connect(slot or self._schedule_adjust)
        return s

    # =====================================================================
    # startup / watching
    # =====================================================================
    def _startup(self) -> None:
        if self.settings.watch_folders and self.settings.watch_on_startup:
            self.act_watch.setChecked(True)
        elif not self.settings.watch_folders:
            self.lbl_status.setText("설정에서 감시 폴더를 등록하세요 (또는 사진 파일을 창에 끌어다 놓기)")
        if self.settings.last_patient:
            self._select_patient_id(self.settings.last_patient)

    def _toggle_watch(self, on: bool) -> None:
        if on:
            errors = self.service.start_watching()
            self.act_watch.setText("■ 폴더 감시 중지")
            n = sum(1 for f in self.settings.watch_folders if f.enabled)
            self.lbl_watch.setText(f"● 감시 중 ({n}개 폴더)")
            self.lbl_watch.setStyleSheet("color:#1d7a46; font-weight:600")
            if errors:
                QMessageBox.warning(self, "폴더 감시", "\n".join(errors))
        else:
            self.service.stop_watching()
            self.act_watch.setText("▶ 폴더 감시 시작")
            self.lbl_watch.setText("감시 꺼짐")
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
            dlg.apply()
            self.settings.save()
            if str(self.settings.library) != old_lib:
                QMessageBox.information(self, "설정", "라이브러리 폴더 변경은 프로그램을 다시 시작하면 적용됩니다.")
            if self.act_watch.isChecked():
                self._toggle_watch(True)

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
        self._patient_ref = ref
        if ref == UNASSIGNED:
            self.banner.setText("미분류 영상 — 사진을 선택하고 [환자 지정/수정…]으로 환자를 지정하세요")
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

    def _on_thumb_clicked(self, item: QListWidgetItem) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier and self.current:
            self._set_compare(item.data(Qt.ItemDataRole.UserRole))

    def _thumb_menu(self, pos) -> None:
        item = self.thumbs.itemAt(pos)
        if not item:
            return
        iid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("환자 지정/정보 수정…", lambda: (self._show_image(iid), self._edit_image()))
        menu.addAction("비교 대상으로 (오른쪽)", lambda: self._set_compare(iid))
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
        self.current = row
        if row is None:
            self.view2d.set_rgb(None)
            self.eye3d.set_image(None)
            for lab in self.info_labels.values():
                lab.setText("-")
            return
        rgb = self._load(row)
        if rgb is None:
            self.view2d.set_rgb(None)
            self.info_labels["file"].setText("<span style='color:#b33'>파일을 찾을 수 없음</span>")
            return
        self.view2d.set_rgb(self._adjusted(rgb))
        circle = (row["circle_cx"], row["circle_cy"], row["circle_r"]) if row["circle_r"] else None
        disc = (row["disc_x"], row["disc_y"]) if row["disc_x"] is not None else None
        self.view2d.set_overlays(circle, disc)
        self._fill_info(row)
        self._load_mapping(row)
        self._mark_3d_dirty()

    def _fill_info(self, row) -> None:
        meta = json.loads(row["meta_json"] or "{}")
        src = meta.get("sources", {})

        def with_src(text, *fields):
            s = next((source_label(src.get(f)) for f in fields if src.get(f)), "")
            return f"{text}  <span style='color:#99a'>({s})</span>" if s and text and text != "-" else (text or "-")

        p = self.db.get_patient(row["patient_ref"]) if row["patient_ref"] else None
        if p:
            self.info_labels["patient"].setText(with_src(f"{p['patient_id']} {p['name'] or ''}", "patient_id"))
        else:
            guess = " ".join(x for x in (meta.get("patient_id"), meta.get("name")) if x)
            self.info_labels["patient"].setText(
                "<span style='color:#b33'>미분류</span>" + (f" — 추출값: {guess}" if guess else ""))
        self.info_labels["exam"].setText(with_src(f"{row['exam_date'] or '-'} {row['exam_time'] or ''}", "exam_date"))
        eye = {"OD": "OD (우안)", "OS": "OS (좌안)", "OU": "OU"}.get(row["laterality"] or "", "-")
        self.info_labels["laterality"].setText(with_src(eye, "laterality"))
        self.info_labels["modality"].setText(
            with_src(MODALITY_LABELS.get(row["modality"] or "", row["modality"] or "-"), "modality"))
        self.info_labels["device"].setText(with_src(row["device"] or get_profile(row["profile"]).name, "device"))
        ftype = "안구 중심각" if row["fov_type"] == "internal" else "외부각"
        self.info_labels["fov"].setText(with_src(f"{row['fov_deg']:g}° ({ftype})" if row["fov_deg"] else "-",
                                                 "fov_deg"))
        name = Path(row["original_path"] or row["file_path"]).name
        name = name.replace("_", "_​").replace(".", ".​")  # wrap points
        self.info_labels["file"].setText(f"{name}<br><span style='color:#99a'>{row['width']}×{row['height']}</span>")

    # -- adjustments -----------------------------------------------------------
    def _adjust_params(self) -> dict:
        return dict(brightness=self.s_bright.value() / 200.0, contrast=self.s_contrast.value() / 100.0,
                    gamma=self.s_gamma.value() / 100.0, channel=self.c_channel.currentData(),
                    invert=self.c_invert.isChecked(), auto=self.c_auto.isChecked())

    def _adjusted(self, rgb: np.ndarray) -> np.ndarray:
        return imaging.adjust(rgb, **self._adjust_params())

    def _schedule_adjust(self, *_):
        self._adjust_timer.start(60)

    def _apply_adjust(self) -> None:
        if self.current is None:
            return
        rgb = self._load(self.current)
        if rgb is not None:
            self.view2d.set_rgb(self._adjusted(rgb), keep_view=True)
            if self.c_adj3d.isChecked():
                self._mark_3d_dirty()
        if self.tabs.currentIndex() == 2:
            self._fill_compare()

    def _reset_adjust(self) -> None:
        for s, v in ((self.s_bright, 0), (self.s_contrast, 100), (self.s_gamma, 100)):
            s.setValue(v)
        self.c_channel.setCurrentIndex(0)
        self.c_auto.setChecked(False)
        self.c_invert.setChecked(False)

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
        tmax = math.degrees(self.eye3d.theta_max)
        self.lbl_3d.setText(f"망막 범위: 후극에서 {tmax:.0f}° (안구 중심각 {2 * tmax:.0f}°)\n"
                            "드래그: 회전 · 휠: 확대 · 더블클릭: 초기화")

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

    def _on_3d_mode(self, outside: bool) -> None:
        self.eye3d.mode = "outside" if outside else "inside"
        self.s_cut.setEnabled(outside)
        self.eye3d.update()

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
        tex = self._adjusted(rgb) if self.c_adj3d.isChecked() else rgb
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
        self.db.update_image(self.current["id"], disc_x=x, disc_y=y)
        self.current = self.db.get_image(self.current["id"])
        self.view2d.set_overlays((self.current["circle_cx"], self.current["circle_cy"], self.current["circle_r"]),
                                 (x, y))
        self._push_mapping()
        self.lbl_status.setText("시신경 유두 위치를 저장했습니다 (3D 시신경에 반영)")

    def _on_tab(self, i: int) -> None:
        if i == 1 and self._3d_dirty:
            self._update_3d()
        if i == 2:
            self._fill_compare()

    # -- compare -------------------------------------------------------------------
    def _set_compare(self, image_id: int) -> None:
        self.compare = self.db.get_image(image_id)
        self.tabs.setCurrentIndex(2)
        self._fill_compare()

    def _fill_compare(self) -> None:
        for view, lab, row in zip(self.cmp_views, self.cmp_labels, (self.current, self.compare)):
            if row is None:
                view.set_rgb(None)
                lab.setText("Ctrl+클릭으로 비교할 사진을 고르세요" if row is self.compare else "")
                continue
            rgb = self._load(row)
            view.set_rgb(self._adjusted(rgb) if rgb is not None else None)
            mod = MODALITY_LABELS.get(row["modality"] or "", "")
            lab.setText(f"<b>{row['exam_date'] or ''}</b> {row['laterality'] or ''} {mod}")

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
