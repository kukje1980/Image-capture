"""메인 윈도우: 레이아웃 조립 + 카메라/녹화 스레드 소유 + 신호 배선."""
from __future__ import annotations

import logging
import os
import time
from collections import deque

from PySide6.QtCore import QSize, Qt, QThread, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.capture.camera_worker import CameraWorker
from app.capture.frame_utils import device_names, find_sony_index
from app.capture.sources import DeviceSource, FileSource, SyntheticSource
from app.capture.video_recorder import VideoRecorder
from app.services.capture_service import CaptureService
from app.ui.control_bar import ControlBar, tool_button
from app.ui.exam_screen import ExamScreen
from app.ui.home_screen import HomeScreen
from app.ui.image_viewer import ImageViewerDialog
from app.ui.patient_panel import PatientPanel
from app.ui.pro.pro_workspace import ProWorkspace
from app.ui.quad_view import QuadView
from app.ui.settings_dialog import SettingsDialog
from app.ui.shortcuts_dialog import ShortcutsDialog
from app import brand as app_brand
from app import shortcuts
from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT, build_qss, make_app_icon
from app.ui.thumbnail_panel import ThumbnailPanel
from app.ui.video_view import VideoView

from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)


MODES = ["capture", "pro", "exam", "home"]       # mode_stack 순서


class MainWindow(QMainWindow):
    def __init__(self, config, db):
        super().__init__()
        self._mode = "capture"
        self.config = config
        self.db = db
        self.service = CaptureService(db, config)
        self.brand = app_brand.current()
        self.setWindowTitle(self.brand["window_title"])
        self.setWindowIcon(make_app_icon())
        self.resize(1280, 800)

        self._last_frame = None
        self._paused = False
        self._quad = False
        self._single_frozen = False
        self._freeze_frame = None
        self._current_patient = None
        self._frame_times = deque(maxlen=60)
        self._frame_size = (config.capture_width, config.capture_height)
        self._recording = False
        self._video_path = None
        self._video_ts = None
        self._video_eye = "NA"
        self._first_video_frame = None
        self._video_patient = None
        self._rec_started = 0.0
        self.cam_thread = None
        self.worker = None

        self.recorder = VideoRecorder(fallback_fourcc=config.video_fallback_fourcc)
        self.recorder.error.connect(self._on_recorder_error)

        self._build_ui()
        self._pick_camera()
        self._start_camera()

    # ---- UI 구성 ----
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.topbar = self._build_topbar()
        outer.addWidget(self.topbar)
        self.patient_panel = PatientPanel(self.db)
        outer.addWidget(self.patient_panel)          # 단일/Pro 공통 환자 배너

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(12, 12, 12, 10)
        simple = QWidget()                           # 기본(촬영) 화면
        root = QHBoxLayout(simple)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.video_view = VideoView()
        self.quad_view = QuadView()
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.video_view)   # index 0 = 단일
        self.view_stack.addWidget(self.quad_view)     # index 1 = 4분할
        self.control_bar = ControlBar()
        left.addWidget(self.view_stack, 1)
        left.addWidget(self.control_bar)

        self.thumbnail_panel = ThumbnailPanel(self.db, newest_on_top=self.config.newest_on_top)

        root.addLayout(left, 1)
        root.addWidget(self.thumbnail_panel)

        # Pro(전문가 검토) 화면
        self.pro = ProWorkspace(self.db, self.service, self.config, get_eye=None)
        self.exam_screen = ExamScreen(self.db, self.config)
        self.home = HomeScreen(self.config)
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(simple)            # 0 = 기본(촬영)
        self.mode_stack.addWidget(self.pro)          # 1 = Pro
        self.mode_stack.addWidget(self.exam_screen)  # 2 = 검사 기록
        self.mode_stack.addWidget(self.home)         # 3 = 홈
        body_lay.addWidget(self.mode_stack, 1)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.pro.savedCapture.connect(self._on_pro_saved)
        self.pro.patientUpdated.connect(self._on_pro_patient_updated)
        self.exam_screen.openCapture.connect(self._on_thumbnail_clicked)
        self.exam_screen.openInPro.connect(lambda: self.set_mode("pro"))
        self.exam_screen.editPatient.connect(lambda: self.patient_panel.edit_patient())
        self.home.action.connect(self._on_home_action)

        self.patient_panel.patientChanged.connect(self._on_patient_changed)
        self.control_bar.pauseToggled.connect(self._on_pause)
        self.control_bar.captureClicked.connect(self._on_capture)
        self.control_bar.recordToggled.connect(self._on_record_toggle)
        self.control_bar.quadToggled.connect(self._on_quad_toggled)
        self.control_bar.freezeClicked.connect(self._on_freeze)
        self.control_bar.saveQuadClicked.connect(self._on_save_quad)
        self.control_bar.clearQuadClicked.connect(self._on_clear_quad)
        self.quad_view.cellClicked.connect(self._on_quad_cell_clicked)
        self.thumbnail_panel.thumbnailClicked.connect(self._on_thumbnail_clicked)
        self.control_bar.eyeChanged.connect(lambda e: self.video_view.set_hud(eye=e))
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(500)
        self._rec_timer.timeout.connect(self._update_rec_hud)

        self._on_patient_changed(self.patient_panel.current_patient())
        self._fullscreen = False
        self._install_shortcuts()
        self.set_mode("capture" if getattr(self.config, "start_screen", "home") == "capture" else "home")

    def _build_topbar(self) -> QFrame:
        """브랜드 + 아이콘 메뉴: [촬영 | Pro 검토] [신규 환자 | 정보 수정] … [카메라 | 단축키 | 설정 | 테마]."""
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 12, 6)
        lay.setSpacing(10)
        b = self.brand
        self.brand_logo = None
        if app_brand.asset(b.get("logo")):
            # 브랜드 로고 (테마에 맞춰 밝은/어두운 배경용을 바꿔 그림)
            self.brand_logo = QLabel()
            self.brand_logo.setObjectName("BrandLogo")
            lay.addWidget(self.brand_logo)
            self._render_brand_logo()
        else:
            logo = QLabel()
            logo.setPixmap(make_app_icon().pixmap(34, 34))
            logo.setFixedSize(34, 34)
            lay.addWidget(logo)
        if not (self.brand_logo and b.get("logo_only")):
            brand = QVBoxLayout()
            brand.setSpacing(0)
            t1 = QLabel("슬릿램프 영상 시스템")
            t1.setObjectName("BrandTitle")
            t2 = QLabel("SLIT LAMP IMAGING")
            t2.setObjectName("BrandSub")
            brand.addWidget(t1)
            brand.addWidget(t2)
            lay.addLayout(brand)
        lay.addSpacing(10)

        def nav(text, icon_name, tip, color=ICON, checkable=False):
            btn = tool_button(text, icon_name, "NavBtn", checkable=checkable, color=color, tip=tip,
                              icon_size=20, min_width=58)
            return btn

        def seg():
            f = QFrame()
            f.setObjectName("NavSeg")
            sl = QHBoxLayout(f)
            sl.setContentsMargins(3, 3, 3, 3)
            sl.setSpacing(2)
            return f, sl

        # 촬영 / Pro 검토 전환 (act_pro 는 체크형 액션으로 유지)
        self.act_pro = QAction("Pro 검토", self)
        self.act_pro.setCheckable(True)
        self.act_pro.setToolTip("전문가용 영상 검토 화면 (MULTI·비교·보정·편집·인쇄)")
        self.act_pro.toggled.connect(self._on_pro_toggled)
        self.addAction(self.act_pro)
        sw, sl = seg()
        self.btn_mode_home = nav("홈", "home", "시작 화면 (아이콘 메뉴)", checkable=True)
        self.btn_mode_capture = nav("촬영", "camera", "실시간 촬영 화면", checkable=True)
        self.btn_mode_pro = nav("Pro 검토", "review", self.act_pro.toolTip(), checkable=True)
        self.btn_mode_exam = nav("검사 기록", "clipboard", "촬영일별 영상 모음과 검사 소견", checkable=True)
        self.mode_buttons = {"home": self.btn_mode_home, "capture": self.btn_mode_capture,
                             "pro": self.btn_mode_pro, "exam": self.btn_mode_exam}
        grp = QButtonGroup(self)
        for mode, name in (("home", "home"), ("capture", "camera"), ("pro", "review"), ("exam", "clipboard")):
            btn = self.mode_buttons[mode]
            ic = icons.icon(name, ICON, 20)
            ic.addPixmap(icons.pixmap(name, ICON_ACCENT, 20), ic.Mode.Normal, ic.State.On)
            btn.setIcon(ic)
            grp.addButton(btn)
            sl.addWidget(btn)
            btn.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
        self.btn_mode_capture.setChecked(True)
        lay.addWidget(sw)

        # 환자: 신규 등록 · 정보 수정 (Pro 검토 바로 옆)
        pw, pl = seg()
        self.btn_new_patient = nav("신규 환자", "user-plus", "신규 환자 등록", color=ICON_ACCENT)
        self.btn_edit_patient = nav("정보 수정", "user-edit", "선택한 환자 정보 수정")
        self.btn_new_patient.clicked.connect(lambda: self.patient_panel.new_patient())
        self.btn_edit_patient.clicked.connect(lambda: self.patient_panel.edit_patient())
        pl.addWidget(self.btn_new_patient)
        pl.addWidget(self.btn_edit_patient)
        lay.addWidget(pw)
        lay.addStretch(1)

        tw, tl = seg()
        self.btn_camera = nav("카메라", "videocam", "캡처 장비 다시 연결")
        self.btn_keys = nav("단축키", "keyboard", "단축키 설정 (캡처·녹화·안구 등)")
        self.btn_settings = nav("설정", "sliders", "카메라·저장 위치·형식 설정")
        self.btn_theme = nav("테마", "sun", "밝은/어두운 테마 전환")
        self.btn_camera.clicked.connect(self._restart_camera)
        self.btn_keys.clicked.connect(self._open_shortcuts)
        self.btn_settings.clicked.connect(self._open_settings)
        self.act_theme = QAction(self)
        self.act_theme.triggered.connect(self._toggle_theme)
        self.btn_theme.clicked.connect(self._toggle_theme)
        for btn in (self.btn_camera, self.btn_keys, self.btn_settings, self.btn_theme):
            tl.addWidget(btn)
        lay.addWidget(tw)
        self._sync_theme_button()
        return bar

    def _render_brand_logo(self) -> None:
        if self.brand_logo is None:
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        key = "logo_dark" if self.config.theme == "dark" else "logo"
        path = app_brand.asset(self.brand.get(key)) or app_brand.asset(self.brand.get("logo"))
        r = QSvgRenderer(path)
        size = r.defaultSize()
        h = 40
        w = max(1, round(size.width() * h / max(1, size.height())))
        ratio = 2
        pm = QPixmap(w * ratio, h * ratio)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r.render(p, QRectF(0, 0, w * ratio, h * ratio))
        p.end()
        pm.setDevicePixelRatio(ratio)
        self.brand_logo.setPixmap(pm)
        self.brand_logo.setFixedSize(w, h)

    def _sync_theme_button(self) -> None:
        dark = self.config.theme == "dark"
        self.btn_theme.setIcon(icons.icon("sun" if dark else "moon", ICON, 20))
        self.act_theme.setText("☀ 라이트 모드" if dark else "🌙 다크 모드")

    def _update_rec_hud(self) -> None:
        if self._recording and self._rec_started:
            s = int(time.time() - self._rec_started)
            self.video_view.set_hud(state="rec", rec_text=f"{s // 60:02d}:{s % 60:02d}")

    def _refresh_hud_state(self) -> None:
        if self._recording:
            self._update_rec_hud()
        elif self._single_frozen:
            self.video_view.set_hud(state="frozen")
        elif self._paused:
            self.video_view.set_hud(state="paused")
        else:
            self.video_view.set_hud(state="live")

    # ---- 단축키 (사용자 지정) ----
    def _install_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        for sc in getattr(self, "_shortcut_objs", {}).values():
            sc.setEnabled(False)
            sc.deleteLater()
        self._keys = shortcuts.load(self.config)
        self._shortcut_objs = {}
        for aid, key in self._keys.items():
            if not key:
                continue
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.setAutoRepeat(False)
            sc.activated.connect(lambda aid=aid: self._run_action(aid))
            self._shortcut_objs[aid] = sc
        if not hasattr(self, "_esc_fullscreen"):
            self._esc_fullscreen = QShortcut(QKeySequence("Esc"), self)
            self._esc_fullscreen.activated.connect(lambda: self._set_fullscreen(False))
        self._sync_shortcut_scope()
        self._apply_key_hints()

    def _sync_shortcut_scope(self) -> None:
        """촬영 화면 전용 단축키는 Pro 화면에서 끈다 (Pro 의 Space 등과 겹치지 않게)."""
        capture = self._mode == "capture"
        for aid, sc in self._shortcut_objs.items():
            sc.setEnabled(capture or shortcuts.scope(aid) == "all")
        self._esc_fullscreen.setEnabled(self._fullscreen)

    def _apply_key_hints(self) -> None:
        cb = self.control_bar
        hints = {"capture": cb.btn_capture, "record": cb.btn_record, "pause": cb.btn_pause,
                 "freeze": cb.btn_freeze, "quad": cb.btn_quad, "mode": self.btn_mode_pro,
                 "newPatient": self.btn_new_patient}
        for aid, w in hints.items():
            base = w.property("tipBase")
            if base is None:
                base = w.toolTip()
                w.setProperty("tipBase", base)
            key = self._keys.get(aid)
            w.setToolTip(f"{base} ({key})" if key else base)
        for code, b in cb.eye_buttons.items():
            hints[f"eye{code}"] = b
        for aid, w in hints.items():
            if aid.startswith("eye"):
                base = w.property("tipBase")
                if base is None:
                    base = w.toolTip()
                    w.setProperty("tipBase", base)
                key = self._keys.get(aid)
                w.setToolTip(f"{base} ({key})" if key else base)

    def _run_action(self, aid: str) -> None:
        cb = self.control_bar
        if aid.startswith("eye"):
            code = aid[3:]
            if self.mode_stack.currentIndex() == 1:
                self.pro.c_eye.setCurrentIndex(["NA", "OD", "OS", "OU"].index(code))
            else:
                cb.set_eye(code)
            self.statusBar().showMessage(f"안구: {'미지정' if code == 'NA' else code}", 2000)
        elif aid == "capture" and cb.btn_capture.isEnabled():
            self._on_capture()
        elif aid == "record" and cb.btn_record.isEnabled():
            cb.btn_record.toggle()
        elif aid == "pause" and cb.btn_pause.isVisible() and cb.btn_pause.isEnabled():
            cb.btn_pause.toggle()
        elif aid == "freeze" and cb.btn_freeze.isEnabled():
            self._on_freeze()
        elif aid == "quad":
            cb.btn_quad.toggle()
        elif aid == "fullscreen":
            self._set_fullscreen(not self._fullscreen)
        elif aid == "mode":
            self.act_pro.toggle()
        elif aid == "patients":
            self.patient_panel.search.setFocus()
            self.patient_panel.search.selectAll()
            self.patient_panel.combo.showPopup()
        elif aid == "newPatient":
            self.patient_panel.new_patient()

    def _set_fullscreen(self, on: bool) -> None:
        """영상 전체 화면: 창을 화면 가득 채우고 상단바·환자 배너·썸네일·상태바를 숨김 (Esc 로 해제)."""
        if on == self._fullscreen:
            return
        self._fullscreen = on
        for w in (self.topbar, self.thumbnail_panel, self.statusBar()):
            w.setVisible(not on)
        self.patient_panel.setVisible(not on and self._mode != "home")
        if on:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
            self.statusBar().showMessage("전체 화면 — Esc 로 나가기", 3000)
        else:
            self.showMaximized() if getattr(self, "_was_maximized", False) else self.showNormal()
        self._esc_fullscreen.setEnabled(on)

    def _open_shortcuts(self) -> None:
        dlg = ShortcutsDialog(self._keys, self)
        if dlg.exec():
            self.config.shortcuts = dlg.values()
            try:
                self.config.save()
            except Exception:  # noqa: BLE001
                log.warning("shortcut save failed", exc_info=True)
            self._install_shortcuts()
            self.statusBar().showMessage("단축키를 저장했습니다", 3000)

    # ---- 카메라 스레드 ----
    def _source_factory(self):
        cfg = self.config
        mode = cfg.source_mode

        def factory():
            if mode == "synthetic":
                return SyntheticSource(cfg.capture_width or 1280, cfg.capture_height or 720, 30.0)
            if mode == "file":
                return FileSource(cfg.test_file_path, loop=True)
            return DeviceSource(cfg.camera_index, cfg.camera_backend,
                                cfg.capture_width, cfg.capture_height)

        return factory

    def _pick_camera(self) -> None:
        """카메라 자동 선택: 저장된 이름으로 다시 찾고, 처음이면 소니(USB 스트리밍) 카메라를 우선."""
        cfg = self.config
        if cfg.source_mode != "device":
            return
        names = device_names()
        if not names:
            return
        idx = None
        if cfg.camera_name and cfg.camera_name in names:
            idx = names.index(cfg.camera_name)          # 장치 순서가 바뀌어도 같은 카메라
        elif cfg.camera_name:
            # 저장한 카메라가 안 보이면 같은 번호의 다른 장치(노트북 웹캠 등)로 몰래 바뀌지 않게 알린다
            cur = names[cfg.camera_index] if 0 <= cfg.camera_index < len(names) else "없음"
            msg = (f"설정한 카메라 '{cfg.camera_name}' 를 찾지 못했습니다.\n"
                   f"연결을 확인하세요. 지금은 '{cur}' 로 연결합니다 (설정에서 바꿀 수 있습니다).")
            log.warning(msg)
            self.statusBar().showMessage(msg.replace("\n", " "), 15000)
            box = QMessageBox(QMessageBox.Icon.Warning, "카메라", msg, QMessageBox.StandardButton.Ok, self)
            box.setModal(False)                 # 시작을 막지 않게 (창은 떠 있고 확인만 누르면 됨)
            box.show()
            return
        elif not cfg.camera_name:
            idx = find_sony_index(names)
            if idx is not None:
                self.statusBar().showMessage(f"소니 카메라를 찾아 연결합니다: {names[idx]}", 8000)
        if idx is None or idx >= len(names):
            return
        if idx != cfg.camera_index or cfg.camera_name != names[idx]:
            cfg.camera_index, cfg.camera_name = idx, names[idx]
            try:
                cfg.save()
            except Exception:  # noqa: BLE001
                log.warning("camera selection save failed", exc_info=True)

    def _start_camera(self) -> None:
        self.cam_thread = QThread(self)
        self.worker = CameraWorker(self._source_factory())
        self.worker.moveToThread(self.cam_thread)
        self.cam_thread.started.connect(self.worker.run)
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.opened.connect(self._on_camera_opened)
        self.worker.error.connect(self._on_camera_error)
        self.worker.stopped.connect(self.cam_thread.quit)
        self.cam_thread.start()

    def _stop_camera(self) -> None:
        # run() 루프가 워커 스레드의 이벤트 루프를 점유하므로 QueuedConnection은
        # 처리되지 않는다. _running(bool)을 직접 내려 루프가 즉시 빠져나오게 한다.
        if self.worker is not None:
            self.worker.stop()
            # 늦게 멈추는 이전 워커의 프레임·오류가 새 카메라 화면에 섞이지 않게 연결을 끊는다
            for sig, slot in ((self.worker.frame_ready, self._on_frame_ready),
                              (self.worker.opened, self._on_camera_opened),
                              (self.worker.error, self._on_camera_error)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        if self.cam_thread is not None:
            self.cam_thread.quit()
            if not self.cam_thread.wait(3000):
                log.warning("camera thread did not stop within timeout")
        self.worker = None
        self.cam_thread = None

    def _restart_camera(self) -> None:
        if self._recording:                  # 카메라·해상도가 바뀌기 전에 지금 녹화를 마무리해 저장
            self._stop_recording()
        self._stop_camera()
        self.video_view.clear()
        self._start_camera()

    # ---- 카메라 신호 처리 ----
    def _on_camera_opened(self, w: int, h: int, fps: float) -> None:
        self._frame_size = (w, h)
        self.control_bar.set_status(f"카메라 {w}x{h} @ {fps:.0f}fps")

    def _on_frame_ready(self, frame) -> None:
        self._last_frame = frame
        self._frame_times.append(time.time())
        if self._recording:
            self.recorder.feed(frame)
            if self._first_video_frame is None:
                self._first_video_frame = frame
        if self.mode_stack.currentIndex() == 1:
            self.pro.set_live_frame(frame)
        if self._quad:
            self.quad_view.set_live_frame(frame)
        elif not self._paused and not self._single_frozen:
            self.video_view.set_frame(frame)

    def _on_camera_error(self, msg: str) -> None:
        self.control_bar.set_status(f"오류: {msg}")
        self.statusBar().showMessage(f"카메라 오류: {msg}", 8000)
        if self._recording:
            self._stop_recording()

    def _estimate_fps(self) -> float:
        if len(self._frame_times) < 2:
            return 30.0
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return 30.0
        fps = (len(self._frame_times) - 1) / span
        return max(5.0, min(60.0, fps))

    # ---- 환자 ----
    def _on_patient_changed(self, patient) -> None:
        self._current_patient = patient
        self.control_bar.set_capture_enabled(patient is not None)
        self.btn_edit_patient.setEnabled(patient is not None)
        if self._recording:                  # 녹화 중에는 언제든 멈출 수 있어야 한다
            self.control_bar.btn_record.setEnabled(True)
        self.video_view.set_hud(patient=(f"{patient.name}  ·  {patient.chart_no}" if patient and patient.chart_no
                                         else (patient.name if patient else "환자 미선택")))
        self.thumbnail_panel.set_patient(patient.id if patient else None)
        self.pro.set_patient(patient)
        if self._mode == "exam":
            self.exam_screen.set_patient(patient)

    # ---- Pro 모드 ----
    def _on_pro_toggled(self, on: bool) -> None:
        self.set_mode("pro" if on else "capture")

    def set_mode(self, name: str) -> None:
        """화면 전환: home(아이콘 메뉴) · capture(촬영) · pro(Pro 검토) · exam(검사 기록)."""
        if name not in MODES:
            return
        if self._mode == "exam" and name != "exam":
            self.exam_screen.flush()             # 적던 소견 저장
        self._mode = name
        self.mode_stack.setCurrentIndex(MODES.index(name))
        self.patient_panel.setVisible(name != "home" and not self._fullscreen)
        self.mode_buttons[name].setChecked(True)
        self.act_pro.blockSignals(True)
        self.act_pro.setChecked(name == "pro")
        self.act_pro.blockSignals(False)
        if hasattr(self, "_shortcut_objs"):
            self._sync_shortcut_scope()
        p = self._current_patient
        if name == "pro":
            self.pro.reload(select_last=False)
            if self._last_frame is not None:
                self.pro.set_live_frame(self._last_frame)
            self.pro.setFocus()
        elif name == "capture":
            self.thumbnail_panel.set_patient(p.id if p else None)
        elif name == "exam":
            self.exam_screen.set_patient(p)
        self.statusBar().showMessage({"home": "홈", "capture": "촬영", "pro": "Pro 모드", "exam": "검사 기록"}[name], 3000)

    def mode(self) -> str:
        return self._mode

    def _on_home_action(self, aid: str) -> None:
        """홈 화면 아이콘 타일."""
        if aid == "newPatient":
            if self.patient_panel.new_patient():
                self.set_mode("capture")
        elif aid == "patients":
            self.set_mode("capture")
            self._run_action("patients")
        elif aid in ("capture", "pro", "exam"):
            self.set_mode(aid)
        elif aid == "settings":
            self._open_settings()
        elif aid == "shortcuts":
            self._open_shortcuts()

    def _on_pro_saved(self) -> None:
        p = self._current_patient
        self.thumbnail_panel.set_patient(p.id if p else None)

    def _on_pro_patient_updated(self, patient) -> None:
        self._current_patient = patient
        self.patient_panel.refresh_current(patient)
        self.video_view.set_hud(patient=f"{patient.name}  ·  {patient.chart_no}" if patient.chart_no else patient.name)

    # ---- 컨트롤 ----
    def _on_pause(self, checked: bool) -> None:
        self._paused = checked
        self._refresh_hud_state()

    def _on_quad_toggled(self, on: bool) -> None:
        self._quad = on
        self.view_stack.setCurrentIndex(1 if on else 0)
        # 모드 전환 시 단일-정지 상태/버튼 초기화
        self._single_frozen = False
        self._freeze_frame = None
        self.control_bar.set_freeze_state(False)
        self._refresh_hud_state()
        self.control_bar.set_status(
            "4분할 모드 · '정지영상'으로 각 칸을 채우세요" if on else "단일 모드")

    def _on_quad_cell_clicked(self, idx: int) -> None:
        if self._quad:
            self.quad_view.set_active(idx)

    def _on_freeze(self) -> None:
        if self._last_frame is None:
            return
        if self._quad:
            if self.quad_view.freeze_active(self.control_bar.current_eye()):
                if self.quad_view.is_full():
                    self.control_bar.set_status("4칸 모두 채움 · '4분할 저장' 또는 칸 클릭으로 교체")
                else:
                    self.control_bar.set_status("정지영상 추가됨 (다음 칸으로 이동)")
            else:
                self.control_bar.set_status("4칸이 가득 찼습니다 · 칸을 클릭해 교체하거나 '비우기'")
            return
        # 단일 모드: 현재 프레임을 정지영상으로 고정 / 재개 토글
        self._single_frozen = not self._single_frozen
        if self._single_frozen:
            self._freeze_frame = self._last_frame
            self.video_view.set_frame(self._freeze_frame)
            self.control_bar.set_freeze_state(True)
            self.control_bar.set_status("정지영상 (▶라이브로 복귀 · 사진 캡처로 저장)")
        else:
            self._freeze_frame = None
            self.control_bar.set_freeze_state(False)
            self.control_bar.set_status("라이브")
        self._refresh_hud_state()

    def _on_save_quad(self) -> None:
        if self._current_patient is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            return
        if not self.quad_view.has_any():
            QMessageBox.information(self, "확인", "저장할 정지영상이 없습니다.")
            return
        eye = self.control_bar.current_eye()
        saved = 0
        try:
            for frame, cell_eye in self.quad_view.images_for_save(eye):
                cap = self.service.save_photo(frame, self._current_patient, eye=cell_eye, note="4분할")
                self.thumbnail_panel.add_capture(cap)
                saved += 1
            comp = self.quad_view.composite()
            if comp is not None:
                cap = self.service.save_photo(comp, self._current_patient, eye="NA", note="4분할 합성")
                self.thumbnail_panel.add_capture(cap)
                saved += 1
        except Exception as e:  # noqa: BLE001
            log.exception("quad save failed")
            QMessageBox.warning(self, "오류", f"4분할 저장 실패: {e}")
            return
        self.control_bar.set_status(f"4분할 저장됨 (개별+합성 {saved}장)")

    def _on_clear_quad(self) -> None:
        self.quad_view.reset()
        self.control_bar.set_status("4분할 초기화")

    def _on_capture(self) -> None:
        if self._current_patient is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            return
        frame = self._freeze_frame if (self._single_frozen and self._freeze_frame is not None) else self._last_frame
        if frame is None:
            QMessageBox.information(self, "확인", "표시할 영상이 없습니다.")
            return
        eye = self.control_bar.current_eye()
        try:
            cap = self.service.save_photo(frame, self._current_patient, eye=eye)
        except Exception as e:  # noqa: BLE001
            log.exception("photo save failed")
            QMessageBox.warning(self, "오류", f"저장 실패: {e}")
            return
        self.thumbnail_panel.add_capture(cap)
        self.control_bar.set_status("사진 저장됨")

    def _on_record_toggle(self, checked: bool) -> None:
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self._current_patient is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            self.control_bar.reset_record_button()
            return
        eye = self.control_bar.current_eye()
        path, ts = self.service.begin_video(self._current_patient, eye=eye)
        size = self._frame_size
        if self._last_frame is not None:
            size = (self._last_frame.shape[1], self._last_frame.shape[0])
        try:
            self.recorder.start(path, self._estimate_fps(), size)
        except Exception as e:  # noqa: BLE001
            log.exception("recorder start failed")
            QMessageBox.warning(self, "오류", f"녹화 시작 실패: {e}")
            self.control_bar.reset_record_button()
            return
        self._recording = True
        self._video_path = path
        self._video_ts = ts
        self._video_eye = eye
        self._video_patient = self._current_patient   # 녹화 중 환자를 바꿔도 시작한 환자에게 저장
        self._first_video_frame = None
        self._rec_started = time.time()
        self._rec_timer.start()
        self._update_rec_hud()
        self.control_bar.set_status("녹화 중...")

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self._rec_timer.stop()
        self._refresh_hud_state()
        _, count, duration = self.recorder.stop()
        if count == 0:
            # 프레임이 하나도 기록되지 않은 녹화(인코더 오류·카메라 끊김)는 DB 에 남기지 않는다
            try:
                os.remove(self._video_path)
            except OSError:
                pass
            QMessageBox.warning(self, "녹화 실패", "녹화된 영상이 없습니다 (카메라 또는 인코더 오류).")
            self.control_bar.set_status("녹화 실패")
            self.control_bar.reset_record_button()
            return
        try:
            cap = self.service.finish_video(
                self._video_path, self._video_patient, self._video_eye,
                self._video_ts, duration, thumb_frame=self._first_video_frame,
            )
            self.thumbnail_panel.add_capture(cap)
            self.control_bar.set_status(f"동영상 저장됨 ({duration // 1000}초)")
        except Exception as e:  # noqa: BLE001
            log.exception("finish_video failed")
            QMessageBox.warning(self, "오류", f"동영상 저장 실패: {e}")
        self.control_bar.reset_record_button()

    def _on_recorder_error(self, msg: str) -> None:
        log.error("recorder error: %s", msg)
        if self._recording:                  # 녹화가 이어지는 것처럼 보이지 않게 멈추고 쓴 부분까지만 저장
            self._stop_recording()
        self.statusBar().showMessage(f"녹화 오류로 녹화를 멈췄습니다: {msg}", 10000)

    def _on_thumbnail_clicked(self, capture) -> None:
        ImageViewerDialog(capture, self).exec()

    def _toggle_theme(self) -> None:
        self.config.theme = "dark" if self.config.theme != "dark" else "light"
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(self.config.theme))
        self._sync_theme_button()
        self._render_brand_logo()
        try:
            self.config.save()
        except Exception:  # noqa: BLE001
            log.warning("theme save failed", exc_info=True)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            dlg.apply_to_config()
            self.thumbnail_panel.newest_on_top = self.config.newest_on_top
            self._restart_camera()

    # ---- 종료 ----
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._recording:
                self._stop_recording()
        except Exception:  # noqa: BLE001
            log.warning("stop recording on close failed", exc_info=True)
        self._stop_camera()
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        event.accept()
