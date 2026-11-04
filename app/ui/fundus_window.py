"""안저판 메인 창 — 안저카메라가 사진을 저장하는 폴더를 감시해 지금 환자에게 자동 등록한다.

슬릿램프판(MainWindow)의 상단바·환자 배너·썸네일·Pro 검토·단축키·테마는 그대로 쓰고,
왼쪽 '촬영' 부분만 [큰 사진 보기 + 안저 도크]로 바꾼다. 실시간 영상·녹화·4분할은 없다.

흐름
    카메라 촬영 → 카메라(프로그램)가 폴더에 JPG/TIFF 저장 → FolderWatchWorker 가 '다 써진' 새 파일 발견
    → 파일 이름으로 안구 추정(R/L·OD/OS) → CaptureService.import_photo (환자 폴더 복사·썸네일·export·DB)
    → 썸네일 맨 위 + 큰 화면에 표시
환자를 확실히 고르기 전(프로그램 시작 직후 자동 선택된 환자 포함)에 들어온 사진은 바로 등록하지 않고
'대기'로 모아 두었다가 환자 이름을 보여 주며 등록할지 묻는다 — 다른 환자에게 잘못 들어가는 일을 막기 위함.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.capture.folder_watch import IMAGE_EXTS, IMPORTED_DIR, FolderWatchWorker, guess_eye
from app.services.capture_service import ImageNotReady
from app.ui.fundus_bar import EYE_KO, FundusBar
from app.ui.fundus_settings import FundusSettingsDialog
from app.ui.image_viewer import ImageViewerDialog
from app.ui.main_window import MainWindow
from app.ui.pro.pro_workspace import load_bgr
from app.ui.video_view import VideoView

log = logging.getLogger(__name__)

_MAX_RETRY = 5
_BADGES = {
    "pending": ("#ffd08a", "#f5a524"),
    "watch": ("#c9f5ee", "#3ccf7a"),
    "off": ("#a3acba", None),
    "nofolder": ("#ffd08a", None),
    "error": ("#ff8a87", "#f0524f"),
}


def _sig(path: str):
    try:
        st = os.stat(path)
        return (path, st.st_size, st.st_mtime_ns)
    except OSError:
        return (path, None, None)


class FundusWindow(MainWindow):
    # ---- UI ----
    def _build_ui(self) -> None:
        self._watch_thread: QThread | None = None
        self._watch_worker: FolderWatchWorker | None = None
        self._watch_ok: bool | None = None
        self._pending: list[str] = []          # 환자 확인 전에 들어온 사진
        self._retries: dict[str, int] = {}
        self._imported: set = set()            # 이번 실행에서 가져온 원본 (경로·크기·시각 — 중복 방지)
        self._shown = None                     # 큰 화면의 Capture
        self._asking = False
        self._ui_ready = False
        self._patient_confirmed = False        # 사용자가 직접 고른 환자인가 (시작 때 자동 선택은 아님)
        super()._build_ui()
        self.pro.set_live_available(False)
        self.thumbnail_panel.filter_buttons["video"].setVisible(False)   # 동영상 없음
        self._ui_ready = True
        self._refresh_view()

    def _capture_mode_label(self) -> str:
        return "사진"

    def _add_source_tool(self, tool) -> None:
        tool("사진 폴더", "folder", "안저카메라 사진 폴더 열기", self._open_watch_folder)

    def _build_capture_area(self, left) -> None:
        self.video_view = VideoView()
        self.fundus_bar = FundusBar()
        self.control_bar = None                # 슬릿램프 촬영 도크 없음
        left.addWidget(self.video_view, 1)
        left.addWidget(self.fundus_bar)
        self.fundus_bar.set_watch_state(bool(self.config.watch_enabled))
        self.fundus_bar.importClicked.connect(self._on_import_files)
        self.fundus_bar.watchToggled.connect(self._on_watch_toggled)
        self.fundus_bar.fixEyeRequested.connect(self._on_fix_eye)
        self.fundus_bar.eyeChanged.connect(
            lambda e: self.statusBar().showMessage(f"새 사진 안구: {EYE_KO[e]}", 2500))

    # ---- 단축키 ----
    def _apply_key_hints(self) -> None:
        fb = self.fundus_bar
        hints = {"import": fb.btn_import, "watch": fb.btn_watch, "mode": self.btn_mode_pro}
        for code, b in fb.eye_buttons.items():
            hints[f"eye{code}"] = b
        for aid, w in hints.items():
            base = w.property("tipBase")
            if base is None:
                base = w.toolTip()
                w.setProperty("tipBase", base)
            key = self._keys.get(aid)
            w.setToolTip(f"{base} ({key})" if key else base)

    def _run_action(self, aid: str) -> None:
        if aid.startswith("eye"):
            self.fundus_bar.set_eye(aid[3:])
        elif aid == "import":
            if self.fundus_bar.btn_import.isEnabled():
                self._on_import_files()
        elif aid == "watch":
            self.fundus_bar.btn_watch.toggle()
        else:
            super()._run_action(aid)           # 전체 화면·Pro 전환·환자 검색·신규 환자

    # ---- 폴더 감시 (슬릿램프판의 카메라 자리) ----
    def _pick_camera(self) -> None:
        pass

    def _start_camera(self) -> None:
        cfg = self.config
        folder = (cfg.watch_folder or "").strip()
        self._watch_ok = None
        if not folder:
            self._set_status("설정(⚙)에서 안저카메라 사진 폴더를 지정하세요", "warn")
        elif not cfg.watch_enabled:
            self._set_status("자동 가져오기 꺼짐 — '사진 가져오기'로 직접 등록할 수 있습니다", "warn")
        else:
            self._watch_thread = QThread(self)
            self._watch_worker = FolderWatchWorker(folder, cfg.watch_subfolders, cfg.watch_interval_ms)
            self._watch_worker.moveToThread(self._watch_thread)
            self._watch_thread.started.connect(self._watch_worker.run)
            self._watch_worker.found.connect(self._on_new_file)
            self._watch_worker.status.connect(self._on_watch_status)
            self._watch_worker.stopped.connect(self._watch_thread.quit)
            self._watch_thread.start()
            self._set_status(f"폴더 확인 중 · {folder}")
        self._refresh_view()

    def _stop_camera(self) -> None:
        if self._watch_worker is not None:
            self._watch_worker.stop()
            for sig, slot in ((self._watch_worker.found, self._on_new_file),
                              (self._watch_worker.status, self._on_watch_status)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        if self._watch_thread is not None:
            self._watch_thread.quit()
            if not self._watch_thread.wait(5000):
                log.warning("watch thread did not stop within timeout")
        self._watch_worker = None
        self._watch_thread = None

    def _restart_camera(self) -> None:
        self._stop_camera()
        self._start_camera()

    def _on_watch_status(self, msg: str, ok: bool) -> None:
        self._watch_ok = ok
        self._set_status(msg, "ok" if ok else "error")
        self._refresh_view()

    def _on_watch_toggled(self, on: bool) -> None:
        self.config.watch_enabled = on
        try:
            self.config.save()
        except Exception:  # noqa: BLE001
            log.warning("watch toggle save failed", exc_info=True)
        self._restart_camera()

    # ---- 새 사진 ----
    def _on_new_file(self, path: str) -> None:
        if _sig(path) in self._imported or path in self._pending:
            return
        if self._current_patient is not None and self._patient_confirmed:
            self._import(path, self._current_patient, auto=True)
            return
        self._pending.append(path)
        self._set_status(f"새 사진 {len(self._pending)}장 대기 — 환자를 확인하면 등록합니다", "warn")
        self._refresh_view()
        if self._current_patient is not None:
            QTimer.singleShot(0, self._offer_pending)

    def _offer_pending(self) -> None:
        p = self._current_patient
        if self._asking or not self._pending or p is None:
            return
        self._asking = True
        try:
            answer = self._ask_pending(p, len(self._pending))
            if self._current_patient is not p:             # 묻는 사이 환자가 바뀌었으면 다시 묻는다
                return
            if answer == "yes":
                self._patient_confirmed = True
                files, self._pending = self._pending, []
                for f in files:
                    self._import(f, p, auto=True)
            elif answer == "drop":
                n = len(self._pending)
                self._pending = []
                self._set_status(f"새 사진 {n}장을 등록하지 않았습니다 (원본은 폴더에 그대로)", "warn")
        finally:
            self._asking = False
            self._refresh_view()
        if self._pending and self._current_patient is not None and self._patient_confirmed:
            QTimer.singleShot(0, self._offer_pending)

    def _ask_pending(self, patient, n: int) -> str:
        """대기 사진을 이 환자에게 등록할지 묻는다 → 'yes' | 'later' | 'drop'."""
        who = f"{patient.name} ({patient.chart_no})" if patient.chart_no else patient.name
        box = QMessageBox(QMessageBox.Icon.Question, "새 안저 사진",
                          f"안저카메라에서 새 사진 {n}장이 들어왔습니다.\n\n{who} 환자에게 등록할까요?",
                          parent=self)
        b_yes = box.addButton("등록", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("나중에 (다른 환자 선택)", QMessageBox.ButtonRole.RejectRole)
        b_drop = box.addButton("등록 안 함", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_yes)
        box.exec()
        clicked = box.clickedButton()
        return "yes" if clicked is b_yes else ("drop" if clicked is b_drop else "later")

    def _import(self, path: str, patient, auto: bool):
        cfg = self.config
        name = Path(path).name
        guessed = guess_eye(name) if cfg.watch_eye_from_name else None
        eye = guessed or self.fundus_bar.current_eye()
        try:
            cap = self.service.import_photo(path, patient, eye=eye)
        except ImageNotReady:
            n = self._retries.get(path, 0) + 1
            if n <= _MAX_RETRY and os.path.exists(path):      # 아직 쓰는 중일 수 있음 → 잠시 뒤 다시
                self._retries[path] = n
                QTimer.singleShot(1500, lambda: self._import(path, patient, auto))
                return None
            self._retries.pop(path, None)
            log.warning("unreadable image: %s", path)
            self._set_status(f"사진을 읽을 수 없습니다: {name}", "error")
            return None
        except Exception as e:  # noqa: BLE001
            log.exception("photo import failed: %s", path)
            self._retries.pop(path, None)
            self._set_status(f"가져오기 실패: {name} ({e})", "error")
            return None
        self._retries.pop(path, None)
        self._imported.add(_sig(path))           # 직접 가져온 파일을 감시가 또 가져오지 않게
        if patient is self._current_patient or (self._current_patient and patient.id == self._current_patient.id):
            self.thumbnail_panel.add_capture(cap)
            self._show_capture(cap)
            if self.mode_stack.currentIndex() == 1 and self.pro.mode() == "multi":
                self.pro.reload(select_last=False)
        how = " (파일 이름)" if guessed else ""
        self._set_status(f"등록됨 · {patient.name} · {EYE_KO.get(eye, eye)}{how} · {name}")
        self.statusBar().showMessage(f"새 안저 사진 등록: {patient.name} · {EYE_KO.get(eye, eye)}", 5000)
        if auto and cfg.watch_move_imported:
            self._move_original(path)
        return cap

    def _move_original(self, path: str) -> None:
        """가져온 원본을 감시 폴더의 '_가져옴/날짜' 폴더로 옮긴다 (감시 폴더 안의 파일만)."""
        try:
            root = Path(self.config.watch_folder)
            src = Path(path)
            src.resolve().relative_to(root.resolve())
            dest_dir = root / IMPORTED_DIR / date.today().isoformat()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            i = 2
            while dest.exists():
                dest = dest_dir / f"{src.stem}_{i}{src.suffix}"
                i += 1
            shutil.move(str(src), str(dest))
        except ValueError:
            return
        except OSError:
            log.warning("move imported original failed: %s", path, exc_info=True)

    def _on_import_files(self) -> None:
        p = self._current_patient
        if p is None:
            QMessageBox.information(self, "확인", "환자를 먼저 선택하세요.")
            return
        pattern = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, f"사진 가져오기 — {p.name}", self.config.watch_folder or "",
                                                f"이미지 ({pattern});;모든 파일 (*)")
        self._patient_confirmed = True if files else self._patient_confirmed
        for f in files:
            if f in self._pending:
                self._pending.remove(f)
            self._import(f, p, auto=False)
        self._refresh_view()

    # ---- 보기 ----
    def _latest_photo(self):
        photos = [c for c in self.thumbnail_panel.all_captures() if c.media_type == "photo"]
        return max(photos, key=lambda c: (c.captured_at or "", c.id or 0)) if photos else None

    def _show_capture(self, cap) -> None:
        img = load_bgr(cap.file_path) if cap is not None else None
        if img is None:
            self._shown = None
            self.video_view.clear()
            self.video_view.set_hud(eye="NA", caption="")
        else:
            self._shown = cap
            self.video_view.set_frame(img)
            bits = [f"촬영 {cap.captured_at}"] + ([cap.note] if cap.note else [])
            self.video_view.set_hud(eye=cap.eye or "NA", caption="  ·  ".join(bits))
        self.fundus_bar.set_fix_enabled(self._shown is not None)

    def _refresh_view(self) -> None:
        """오른쪽 위 상태 칩 + 사진이 없을 때 안내 문구."""
        if not getattr(self, "_ui_ready", False):
            return
        cfg = self.config
        if self._pending:
            kind, text = "pending", f"새 사진 {len(self._pending)}장 대기"
        elif not (cfg.watch_folder or "").strip():
            kind, text = "nofolder", "사진 폴더 미설정"
        elif not cfg.watch_enabled:
            kind, text = "off", "자동 꺼짐"
        elif self._watch_ok is False:
            kind, text = "error", "폴더 연결 안 됨"
        else:
            kind, text = "watch", "자동 가져오기"
        fg, dot = _BADGES[kind]
        self.video_view.set_hud(state="badge", badge=(text, fg, dot))
        if not (cfg.watch_folder or "").strip():
            title, sub = "사진 폴더를 지정하세요", "설정(⚙)에서 안저카메라가 사진을 저장하는 폴더를 고르면 자동으로 가져옵니다"
        elif self._current_patient is None:
            title, sub = "환자를 선택하세요", "선택한 환자에게 새 안저 사진이 자동으로 등록됩니다"
        else:
            title, sub = "안저 사진 대기 중", "안저카메라로 촬영하면 몇 초 안에 이 환자에게 등록됩니다"
        self.video_view.set_placeholder(title, sub, icon="image", hud=True)

    def _set_status(self, text: str, level: str = "ok") -> None:
        self.fundus_bar.set_status(text, level)

    # ---- 환자 ----
    def _on_patient_changed(self, patient) -> None:
        self._current_patient = patient
        if self._ui_ready:
            self._patient_confirmed = patient is not None
        self.fundus_bar.set_import_enabled(patient is not None)
        self.video_view.set_hud(patient=(f"{patient.name}  ·  {patient.chart_no}" if patient and patient.chart_no
                                         else (patient.name if patient else "환자 미선택")))
        self.thumbnail_panel.set_patient(patient.id if patient else None)
        self.pro.set_patient(patient)
        self._show_capture(self._latest_photo())
        self._refresh_view()
        if patient is not None and self._pending and self._patient_confirmed:
            QTimer.singleShot(0, self._offer_pending)

    def _on_pro_saved(self) -> None:
        super()._on_pro_saved()
        self._show_capture(self._latest_photo())

    def _on_thumbnail_clicked(self, capture) -> None:
        if capture.media_type == "photo":
            self._show_capture(capture)
        else:
            ImageViewerDialog(capture, self).exec()

    def _on_fix_eye(self, code: str) -> None:
        cap = self._shown
        if cap is None:
            return
        try:
            self.service.change_eye(cap, code)
        except Exception as e:  # noqa: BLE001
            log.exception("change eye failed")
            QMessageBox.warning(self, "오류", f"안구 수정 실패: {e}")
            return
        p = self._current_patient
        self.thumbnail_panel.set_patient(p.id if p else None)
        self._show_capture(cap)
        self._set_status(f"안구를 {EYE_KO.get(code, code)}(으)로 바꿨습니다")

    # ---- 설정 ----
    def _open_settings(self) -> None:
        dlg = FundusSettingsDialog(self.config, self)
        if dlg.exec():
            dlg.apply_to_config()
            self.thumbnail_panel.newest_on_top = self.config.newest_on_top
            self._restart_camera()

    def _open_watch_folder(self) -> None:
        folder = (self.config.watch_folder or "").strip()
        if folder and Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            self._open_settings()
