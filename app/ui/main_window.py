"""메인 윈도우: 레이아웃 조립 + 카메라/녹화 스레드 소유 + 신호 배선."""
from __future__ import annotations

import logging
import time
from collections import deque

from PySide6.QtCore import QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.capture.camera_worker import CameraWorker
from app.capture.sources import DeviceSource, FileSource, SyntheticSource
from app.capture.video_recorder import VideoRecorder
from app.services.capture_service import CaptureService
from app.ui.control_bar import ControlBar
from app.ui.image_viewer import ImageViewerDialog
from app.ui.patient_panel import PatientPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.thumbnail_panel import ThumbnailPanel
from app.ui.video_view import VideoView

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config, db):
        super().__init__()
        self.config = config
        self.db = db
        self.service = CaptureService(db, config)
        self.setWindowTitle("슬릿램프 디지털 영상 시스템")
        self.resize(1280, 800)

        self._last_frame = None
        self._paused = False
        self._current_patient = None
        self._frame_times = deque(maxlen=60)
        self._frame_size = (config.capture_width, config.capture_height)
        self._recording = False
        self._video_path = None
        self._video_ts = None
        self._video_eye = "NA"
        self._first_video_frame = None
        self.cam_thread = None
        self.worker = None

        self.recorder = VideoRecorder(fallback_fourcc=config.video_fallback_fourcc)
        self.recorder.error.connect(self._on_recorder_error)

        self._build_ui()
        self._start_camera()

    # ---- UI 구성 ----
    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        left = QVBoxLayout()
        self.patient_panel = PatientPanel(self.db)
        self.video_view = VideoView()
        self.control_bar = ControlBar()
        left.addWidget(self.patient_panel)
        left.addWidget(self.video_view, 1)
        left.addWidget(self.control_bar)

        self.thumbnail_panel = ThumbnailPanel(self.db, newest_on_top=self.config.newest_on_top)

        root.addLayout(left, 1)
        root.addWidget(self.thumbnail_panel)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        tb = QToolBar()
        self.addToolBar(tb)
        act_settings = QAction("설정", self)
        act_settings.triggered.connect(self._open_settings)
        act_reconnect = QAction("카메라 재연결", self)
        act_reconnect.triggered.connect(self._restart_camera)
        tb.addAction(act_settings)
        tb.addAction(act_reconnect)

        self.patient_panel.patientChanged.connect(self._on_patient_changed)
        self.control_bar.pauseToggled.connect(self._on_pause)
        self.control_bar.captureClicked.connect(self._on_capture)
        self.control_bar.recordToggled.connect(self._on_record_toggle)
        self.thumbnail_panel.thumbnailClicked.connect(self._on_thumbnail_clicked)

        self._on_patient_changed(self.patient_panel.current_patient())

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
        if self.cam_thread is not None:
            self.cam_thread.quit()
            if not self.cam_thread.wait(3000):
                log.warning("camera thread did not stop within timeout")
        self.worker = None
        self.cam_thread = None

    def _restart_camera(self) -> None:
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
        if not self._paused:
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
        self.thumbnail_panel.set_patient(patient.id if patient else None)

    # ---- 컨트롤 ----
    def _on_pause(self, checked: bool) -> None:
        self._paused = checked

    def _on_capture(self) -> None:
        if self._current_patient is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            return
        if self._last_frame is None:
            QMessageBox.information(self, "확인", "표시할 영상이 없습니다.")
            return
        eye = self.control_bar.current_eye()
        try:
            cap = self.service.save_photo(self._last_frame, self._current_patient, eye=eye)
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
        self._first_video_frame = None
        self.control_bar.set_status("녹화 중...")

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        _, _, duration = self.recorder.stop()
        try:
            cap = self.service.finish_video(
                self._video_path, self._current_patient, self._video_eye,
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
        self.statusBar().showMessage(f"녹화 오류: {msg}", 8000)

    def _on_thumbnail_clicked(self, capture) -> None:
        ImageViewerDialog(capture, self).exec()

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
