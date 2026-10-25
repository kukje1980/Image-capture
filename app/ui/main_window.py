"""메인 윈도우: 레이아웃 조립 + 카메라/녹화 스레드 소유 + 신호 배선."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
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

from app import brand as app_brand
from app import shortcuts
from app.capture.camera_worker import CameraWorker
from app.capture.frame_utils import device_names, find_sony_index
from app.capture.sources import DeviceSource, FileSource, SyntheticSource
from app.capture.video_recorder import VideoRecorder
from app.services.capture_service import CaptureService
from app.ui import icons
from app.ui.control_bar import ControlBar
from app.ui.image_viewer import ImageViewerDialog
from app.ui.patient_panel import PatientPanel
from app.ui.pro.pro_workspace import ProWorkspace
from app.ui.quad_view import QuadView
from app.ui.settings_dialog import SettingsDialog
from app.ui.shortcuts_dialog import ShortcutsDialog
from app.ui.theme import ICON, ICON_ACCENT, build_qss, make_app_icon
from app.ui.thumbnail_panel import ThumbnailPanel
from app.ui.video_view import VideoView

log = logging.getLogger(__name__)
MIN_FREE_MB = 500          # 녹화 시작에 필요한 최소 여유 공간


def _free_space_mb(path) -> float | None:
    try:
        import shutil
        return shutil.disk_usage(str(path)).free / (1024 * 1024)
    except OSError:
        return None


class _DeviceProbe(QThread):
    """연결된 카메라 이름 목록을 별도 스레드에서 조회 (ffmpeg 실행 — 수 초 걸릴 수 있음)."""

    found = Signal(list)

    def run(self) -> None:
        try:
            names = device_names()
        except Exception:  # noqa: BLE001
            log.exception("device probe failed")
            names = []
        self.found.emit(list(names))


class MainWindow(QMainWindow):
    def __init__(self, config, db):
        super().__init__()
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
        self._finishing = None               # 멈춘 녹화를 백그라운드에서 마무리(인코더 종료) 하는 동안의 정보
        self._reconnect_attempts = 0
        self.cam_thread = None
        self.worker = None
        self._probe = None

        self.recorder = VideoRecorder(fallback_fourcc=config.video_fallback_fourcc)
        self.recorder.error.connect(self._on_recorder_error)
        self.recorder.finished.connect(self._on_recorder_finished)

        self._build_ui()
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        # 카메라는 창이 먼저 뜬 뒤에 연다 — 장치 검색(수 초)과 장치 열기가 첫 화면을 막지 않게
        QTimer.singleShot(0, self._boot_camera)

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
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(simple)            # 0 = 기본
        self.mode_stack.addWidget(self.pro)          # 1 = Pro
        body_lay.addWidget(self.mode_stack, 1)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.pro.savedCapture.connect(self._on_pro_saved)
        self.pro.patientUpdated.connect(self._on_pro_patient_updated)

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

    def _build_topbar(self) -> QFrame:
        """브랜드 + 촬영/Pro 검토 전환 스위치 + 설정·재연결·테마."""
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 9, 12, 9)
        lay.setSpacing(12)
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
        lay.addSpacing(12)

        # 촬영 / Pro 검토 전환 (act_pro 는 체크형 액션으로 유지)
        self.act_pro = QAction("Pro 검토", self)
        self.act_pro.setCheckable(True)
        self.act_pro.setToolTip("전문가용 영상 검토 화면 (MULTI·비교·보정·편집·인쇄)")
        self.act_pro.toggled.connect(self._on_pro_toggled)
        self.addAction(self.act_pro)
        sw = QFrame()
        sw.setObjectName("ModeSwitch")
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.btn_mode_capture = QPushButton(icons.gap("촬영"))
        self.btn_mode_pro = QPushButton(icons.gap("Pro 검토"))
        grp = QButtonGroup(self)
        for b, name in ((self.btn_mode_capture, "camera"), (self.btn_mode_pro, "review")):
            b.setObjectName("ModeBtn")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            ic = icons.icon(name, ICON, 16)
            ic.addPixmap(icons.pixmap(name, ICON_ACCENT, 16), ic.Mode.Normal, ic.State.On)
            b.setIcon(ic)
            b.setIconSize(QSize(15, 15))
            grp.addButton(b)
            sl.addWidget(b)
        self.btn_mode_capture.setChecked(True)
        self.btn_mode_pro.setToolTip(self.act_pro.toolTip())
        self.btn_mode_capture.clicked.connect(lambda: self.act_pro.setChecked(False))
        self.btn_mode_pro.clicked.connect(lambda: self.act_pro.setChecked(True))
        lay.addWidget(sw)
        lay.addStretch(1)

        def tool(text, icon_name, tip, slot):
            b = QPushButton(icons.gap(text))
            b.setObjectName("IconBtn")
            b.setIcon(icons.icon(icon_name, ICON, 16))
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        tool("카메라 재연결", "videocam", "캡처 장비 다시 연결", self._restart_camera)
        tool("", "keyboard", "단축키 설정 (캡처·녹화·안구 등)", self._open_shortcuts)
        tool("설정", "sliders", "카메라·저장 위치·형식 설정", self._open_settings)
        self.act_theme = QAction(self)
        self.act_theme.triggered.connect(self._toggle_theme)
        self.btn_theme = tool("", "sun", "밝은/어두운 테마 전환", self._toggle_theme)
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
        self.btn_theme.setIcon(icons.icon("sun" if dark else "moon", ICON, 16))
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
        capture = self.mode_stack.currentIndex() == 0
        for aid, sc in self._shortcut_objs.items():
            sc.setEnabled(capture or shortcuts.scope(aid) == "all")
        self._esc_fullscreen.setEnabled(self._fullscreen)

    def _apply_key_hints(self) -> None:
        cb = self.control_bar
        hints = {"capture": cb.btn_capture, "record": cb.btn_record, "pause": cb.btn_pause,
                 "freeze": cb.btn_freeze, "quad": cb.btn_quad, "mode": self.btn_mode_pro}
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
            self.patient_panel._new_patient()

    def _set_fullscreen(self, on: bool) -> None:
        """영상 전체 화면: 창을 화면 가득 채우고 상단바·환자 배너·썸네일·상태바를 숨김 (Esc 로 해제)."""
        if on == self._fullscreen:
            return
        self._fullscreen = on
        for w in (self.topbar, self.patient_panel, self.thumbnail_panel, self.statusBar()):
            w.setVisible(not on)
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

    def _boot_camera(self) -> None:
        """시작 시 카메라 열기. 장치 이름 검색(ffmpeg 실행, 최대 수 초)은 별도 스레드에서 한다."""
        if self.config.source_mode != "device":
            self._start_camera()
            return
        self.control_bar.set_status("카메라 찾는 중…")
        self.video_view.set_placeholder("연결된 캡처 장비를 찾고 있습니다…")
        self._probe = _DeviceProbe(self)
        self._probe.found.connect(self._on_devices_found)
        self._probe.start()

    def _on_devices_found(self, names: list) -> None:
        self._probe = None
        try:
            self._pick_camera(names)
        except Exception:  # noqa: BLE001
            log.exception("camera pick failed")
        self._start_camera()

    def _pick_camera(self, names: list | None = None) -> None:
        """카메라 자동 선택: 저장된 이름으로 다시 찾고, 처음이면 소니(USB 스트리밍) 카메라를 우선."""
        cfg = self.config
        if cfg.source_mode != "device":
            return
        if names is None:
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
        if self.cam_thread is not None:      # 이미 열려 있으면(재연결 타이머와 사용자 조작이 겹침) 먼저 닫는다
            self._stop_camera()
        self.video_view.set_placeholder("카메라 연결 중…")
        self.cam_thread = QThread(self)
        # 녹화기는 캡처 스레드에서 모든 프레임을 직접 받는다 (GUI 가 바빠 화면 프레임을 건너뛰어도 녹화는 온전히)
        self.worker = CameraWorker(self._source_factory(), sink=self._record_sink)
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
        """사용자가 '카메라 재연결'·설정 변경을 했을 때. 자동 재연결 대기도 취소한다."""
        self._reconnect_timer.stop()
        self._reconnect_attempts = 0
        if self._probe is not None:          # 아직 장치 검색 중이면 그 결과로 어차피 열리므로 그대로 둔다
            return
        if self._recording:                  # 카메라·해상도가 바뀌기 전에 지금 녹화를 마무리해 저장
            self._stop_recording()
        self._stop_camera()
        self.video_view.clear()
        self._start_camera()

    # ---- 카메라 신호 처리 ----
    def _on_camera_opened(self, w: int, h: int, fps: float) -> None:
        self._frame_size = (w, h)
        if self._reconnect_attempts:
            self.statusBar().showMessage("카메라가 다시 연결되었습니다", 5000)
        self._reconnect_attempts = 0
        self._reconnect_timer.stop()
        self.control_bar.set_status(f"카메라 {w}x{h} @ {fps:.0f}fps")

    def _record_sink(self, frame) -> None:
        """캡처 스레드에서 매 프레임 호출 — 위젯을 건드리지 않는다."""
        if self._recording:
            self.recorder.feed(frame)
            if self._first_video_frame is None:
                self._first_video_frame = frame

    def _on_frame_ready(self, frame) -> None:
        worker = self.worker
        try:
            self._last_frame = frame
            self._frame_times.append(time.time())
            if self.mode_stack.currentIndex() == 1:
                self.pro.set_live_frame(frame)
            if self._quad:
                self.quad_view.set_live_frame(frame)
            elif not self._paused and not self._single_frozen:
                self.video_view.set_frame(frame)
        finally:
            if worker is not None:
                worker.frame_done()          # 다음 프레임 허용 (한 장만 대기 — 큐가 쌓이지 않게)

    def _on_camera_error(self, msg: str) -> None:
        self.control_bar.set_status(f"오류: {msg}")
        self.statusBar().showMessage(f"카메라 오류: {msg}", 8000)
        if self._recording:
            self._stop_recording()
        self._schedule_reconnect()

    # ---- 자동 재연결 (USB 캡처 장비가 잠시 끊겨도 프로그램을 다시 켤 필요 없게) ----
    def _schedule_reconnect(self) -> None:
        if self.config.source_mode != "device" or self._reconnect_timer.isActive():
            return
        self._reconnect_attempts += 1
        delay = 3000 if self._reconnect_attempts <= 5 else 10000
        self.video_view.clear()
        self.video_view.set_placeholder(f"카메라 연결이 끊겼습니다 — {delay // 1000}초 뒤 자동 재연결 "
                                        f"({self._reconnect_attempts}회)")
        self._reconnect_timer.start(delay)

    def _try_reconnect(self) -> None:
        if self.cam_thread is not None and self.worker is not None and self.worker.frames and \
                self._frame_times and time.time() - self._frame_times[-1] < 2.0:
            return                           # 그 사이 정상 복구됨
        log.info("camera auto-reconnect attempt %s", self._reconnect_attempts)
        self.control_bar.set_status(f"카메라 재연결 시도 중 ({self._reconnect_attempts}회)…")
        self._stop_camera()
        self._start_camera()

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
        if self._recording:                  # 녹화 중에는 언제든 멈출 수 있어야 한다
            self.control_bar.btn_record.setEnabled(True)
        self.video_view.set_hud(patient=(f"{patient.name}  ·  {patient.chart_no}" if patient and patient.chart_no
                                         else (patient.name if patient else "환자 미선택")))
        self.thumbnail_panel.set_patient(patient.id if patient else None)
        self.pro.set_patient(patient)

    # ---- Pro 모드 ----
    def _on_pro_toggled(self, on: bool) -> None:
        self.mode_stack.setCurrentIndex(1 if on else 0)
        (self.btn_mode_pro if on else self.btn_mode_capture).setChecked(True)
        if hasattr(self, "_shortcut_objs"):
            self._sync_shortcut_scope()
        if on:
            self.pro.reload(select_last=False)
            if self._last_frame is not None:
                self.pro.set_live_frame(self._last_frame)
            self.pro.setFocus()
        else:
            p = self._current_patient
            self.thumbnail_panel.set_patient(p.id if p else None)
        self.statusBar().showMessage("Pro 모드" if on else "기본 모드", 3000)

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
        if self._finishing is not None:      # 직전 녹화의 인코더가 아직 파일을 닫는 중
            self.statusBar().showMessage("이전 녹화를 저장하는 중입니다. 잠시 후 다시 누르세요.", 4000)
            self.control_bar.reset_record_button()
            return
        if self._last_frame is None:
            QMessageBox.information(self, "확인", "카메라 영상이 없어 녹화할 수 없습니다.")
            self.control_bar.reset_record_button()
            return
        free_mb = _free_space_mb(self.config.media_root)
        if free_mb is not None and free_mb < MIN_FREE_MB:
            QMessageBox.warning(self, "디스크 공간 부족",
                                f"저장 폴더의 여유 공간이 {free_mb:,.0f}MB 뿐이라 녹화를 시작하지 않습니다.\n"
                                f"(최소 {MIN_FREE_MB}MB 필요) 오래된 파일을 정리한 뒤 다시 시도하세요.\n{self.config.media_root}")
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

    def _stop_recording(self, wait: bool = False) -> None:
        """녹화 중지. 인코더가 남은 프레임을 쓰고 파일을 닫는 데 수 초가 걸릴 수 있어
        기본은 백그라운드에서 마무리하고(화면이 멈추지 않음) 끝나면 _on_recorder_finished 가 DB 에 기록한다.
        wait=True 는 프로그램 종료 때처럼 끝날 때까지 기다려야 할 때."""
        if not self._recording:
            return
        self._recording = False
        self._rec_timer.stop()
        self._refresh_hud_state()
        ctx = {"path": self._video_path, "patient": self._video_patient, "eye": self._video_eye,
               "ts": self._video_ts, "thumb": self._first_video_frame}
        self.control_bar.reset_record_button()
        if wait:
            self._finishing = None
            _, count, duration = self.recorder.stop()        # finished 신호는 _finishing 이 None 이라 무시됨
            self._finish_video(ctx, count, duration)
            return
        self._finishing = ctx
        self.control_bar.set_saving(True)
        self.control_bar.set_status("동영상 저장 중…")
        threading.Thread(target=self.recorder.stop, name="recorder-stop", daemon=True).start()

    def _on_recorder_finished(self, path: str, count: int, duration: int) -> None:
        ctx, self._finishing = self._finishing, None
        self.control_bar.set_saving(False)
        if ctx is None:
            return
        self._finish_video(ctx, count, duration)

    def _finish_video(self, ctx: dict, count: int, duration: int) -> None:
        if count == 0:
            # 프레임이 하나도 기록되지 않은 녹화(인코더 오류·카메라 끊김)는 DB 에 남기지 않는다
            try:
                os.remove(ctx["path"])
            except OSError:
                pass
            QMessageBox.warning(self, "녹화 실패", "녹화된 영상이 없습니다 (카메라 또는 인코더 오류).")
            self.control_bar.set_status("녹화 실패")
            return
        try:
            cap = self.service.finish_video(
                ctx["path"], ctx["patient"], ctx["eye"], ctx["ts"], duration, thumb_frame=ctx["thumb"],
            )
            self.thumbnail_panel.add_capture(cap)
            self.control_bar.set_status(f"동영상 저장됨 ({duration // 1000}초)")
        except Exception as e:  # noqa: BLE001
            log.exception("finish_video failed")
            QMessageBox.warning(self, "오류", f"동영상 저장 실패: {e}\n파일은 남아 있습니다: {ctx['path']}")

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
        self._reconnect_timer.stop()
        try:
            if self._recording:
                self._stop_recording(wait=True)
            elif self._finishing is not None:            # 백그라운드 마무리 중이면 끝날 때까지 잠시 기다린다
                t = self.recorder._thread
                if t is not None:
                    t.join(timeout=10)
        except Exception:  # noqa: BLE001
            log.warning("stop recording on close failed", exc_info=True)
        if self._probe is not None:
            self._probe.wait(2000)
        self._stop_camera()
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        event.accept()
