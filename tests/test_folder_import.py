"""가져오기 폴더 — 새로 들어온 사진을 지금 환자에게 가져오고 원본은 '가져옴' 폴더로 옮긴다."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.services.folder_import import (
    DONE_DIR,
    LONG_SETTLE,
    FolderImporter,
    check_import_folder,
    looks_complete,
)


def _jpeg(w=640, h=480) -> bytes:
    img = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _patient(db, chart="F001", name="가져오기"):
    p = Patient(chart_no=chart, name=name)
    p.id = db.patients.insert(p)
    return p


@pytest.fixture()
def env(app_env, tmp_path):
    config, db = app_env
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return config, db, CaptureService(db, config), inbox


def test_new_photo_is_imported_after_it_settles(env):
    config, db, service, inbox = env
    p = _patient(db)
    imp = FolderImporter(service, inbox)
    assert imp.poll(p).imported == []                 # 빈 폴더 (첫 살피기)

    data = _jpeg()
    (inbox / "DSC00001.JPG").write_bytes(data)
    assert imp.poll(p, "OD").imported == []           # 막 들어옴 — 다 써졌는지 한 번 더 본다
    res = imp.poll(p, "OD")
    assert len(res.imported) == 1 and not res.failed and not res.warnings

    cap = res.imported[0]
    assert cap.patient_id == p.id and cap.eye == "OD" and cap.media_type == "photo"
    assert cap.note == "가져옴 · DSC00001.JPG"
    assert Path(cap.file_path).read_bytes() == data   # 원본 그대로 (재압축 없음)
    assert cap.file_path.endswith(".jpg")
    assert Path(cap.thumbnail_path).exists() and Path(cap.export_path).exists()
    assert [c.id for c in db.captures.list_by_patient(p.id)] == [cap.id]
    # 원본은 '가져옴' 폴더로 옮겨져 다시 가져오지 않는다
    assert not (inbox / "DSC00001.JPG").exists()
    assert (inbox / DONE_DIR / "DSC00001.JPG").read_bytes() == data
    assert imp.poll(p).imported == [] and imp.poll(p).imported == []


def test_photos_already_there_wait_for_confirmation(env):
    _, db, service, inbox = env
    p = _patient(db)
    (inbox / "old1.jpg").write_bytes(_jpeg())
    (inbox / "old2.jpg").write_bytes(_jpeg())
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    res = imp.poll(p)
    assert res.imported == [] and res.held == 2      # 다른 환자 사진일 수 있어 바로 넣지 않는다
    assert db.captures.list_by_patient(p.id) == []

    res = imp.import_held(p, "OS")
    assert [c.note for c in res.imported] == ["가져옴 · old1.jpg", "가져옴 · old2.jpg"]
    assert all(c.eye == "OS" for c in res.imported)
    assert sorted(x.name for x in (inbox / DONE_DIR).iterdir()) == ["old1.jpg", "old2.jpg"]
    assert imp.poll(p).held == 0


def test_skipped_photos_stay_in_folder_and_new_ones_still_import(env):
    _, db, service, inbox = env
    p = _patient(db)
    (inbox / "old.jpg").write_bytes(_jpeg())
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    assert imp.poll(p).held == 1
    assert imp.skip_held() == 1
    for _ in range(3):
        res = imp.poll(p)
        assert res.held == 0 and res.imported == []
    assert (inbox / "old.jpg").exists()

    (inbox / "new.jpg").write_bytes(_jpeg())
    imp.poll(p)
    assert [c.note for c in imp.poll(p).imported] == ["가져옴 · new.jpg"]
    assert (inbox / "old.jpg").exists()


def test_without_patient_photos_wait_then_ask(env):
    _, db, service, inbox = env
    imp = FolderImporter(service, inbox)
    imp.poll(None)
    (inbox / "a.jpg").write_bytes(_jpeg())
    imp.poll(None)
    res = imp.poll(None)
    assert res.waiting == 1 and res.imported == []
    p = _patient(db)
    res = imp.poll(p)
    assert res.held == 1 and res.imported == []      # 환자 없이 들어온 사진은 확인 후에


def test_partly_written_jpeg_waits_until_complete(env):
    _, db, service, inbox = env
    p = _patient(db)
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    data = _jpeg(1600, 1200)
    f = inbox / "slow.jpg"
    f.write_bytes(data[: len(data) // 2])              # 복사 중 (JPEG 끝 표시 없음)
    for _ in range(LONG_SETTLE):
        assert imp.poll(p).imported == []
    f.write_bytes(data)
    imp.poll(p)
    res = imp.poll(p)
    assert len(res.imported) == 1
    assert Path(res.imported[0].file_path).read_bytes() == data


def test_ignores_other_files_hidden_files_and_subfolders(env):
    _, db, service, inbox = env
    p = _patient(db)
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    (inbox / "memo.txt").write_text("x")
    (inbox / "DSC00002.ARW").write_bytes(b"raw")
    (inbox / "._DSC00003.JPG").write_bytes(_jpeg())    # macOS 숨김 파일
    (inbox / "~tmp.jpg").write_bytes(_jpeg())
    (inbox / "sub").mkdir()
    (inbox / "sub" / "x.jpg").write_bytes(_jpeg())
    for _ in range(3):
        res = imp.poll(p)
        assert res.imported == [] and res.held == 0 and res.failed == []


def test_bmp_and_tiff_are_saved_in_photo_format(env):
    config, db, service, inbox = env
    config.photo_format = "png"
    p = _patient(db)
    img = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    (inbox / "scan.bmp").write_bytes(cv2.imencode(".bmp", img)[1].tobytes())
    (inbox / "scan.tif").write_bytes(cv2.imencode(".tif", img)[1].tobytes())
    imp.poll(p)
    res = imp.poll(p)
    assert len(res.imported) == 2
    for cap in res.imported:
        assert cap.file_path.endswith(".png")
        back = cv2.imdecode(np.fromfile(cap.file_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert back.shape == img.shape and np.array_equal(back, img)   # 무손실


def test_unreadable_photo_is_reported_once_and_left_alone(env):
    _, db, service, inbox = env
    p = _patient(db)
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    (inbox / "broken.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 100 + b"\xff\xd9")
    failed = []
    for _ in range(LONG_SETTLE + 3):
        failed += imp.poll(p).failed
    assert [n for n, _ in failed] == ["broken.jpg"]
    assert (inbox / "broken.jpg").exists() and db.captures.list_by_patient(p.id) == []


def test_same_name_again_is_imported_and_kept_separately(env):
    _, db, service, inbox = env
    p = _patient(db)
    imp = FolderImporter(service, inbox)
    imp.poll(p)
    for _ in range(2):                                  # 카메라 파일 번호가 처음으로 돌아간 경우
        (inbox / "DSC00001.JPG").write_bytes(_jpeg())
        imp.poll(p)
        assert len(imp.poll(p).imported) == 1
    assert sorted(x.name for x in (inbox / DONE_DIR).iterdir()) == ["DSC00001.JPG", "DSC00001_1.JPG"]
    assert len(db.captures.list_by_patient(p.id)) == 2


def test_missing_folder_reports_error_and_recovers(env, tmp_path):
    _, db, service, _ = env
    p = _patient(db)
    later = tmp_path / "nas"
    imp = FolderImporter(service, later)
    assert imp.poll(p).error                            # 네트워크 폴더가 아직 연결되지 않음 등
    later.mkdir()
    (later / "a.jpg").write_bytes(_jpeg())
    imp.poll(p)
    assert imp.poll(p).held == 1                        # 연결됐을 때 이미 있던 사진은 확인 후에


def test_looks_complete():
    data = _jpeg()
    assert looks_complete(data, ".jpg") and not looks_complete(data[:-10], ".JPG")
    png = cv2.imencode(".png", np.zeros((4, 4, 3), np.uint8))[1].tobytes()
    assert looks_complete(png, ".png") and not looks_complete(png[:-12], ".png")
    bmp = cv2.imencode(".bmp", np.zeros((4, 4, 3), np.uint8))[1].tobytes()
    assert looks_complete(bmp, ".bmp") and not looks_complete(bmp[:-5], ".bmp")
    assert not looks_complete(b"", ".tif") and looks_complete(b"II*\x00", ".tif")


def test_check_import_folder(app_env, tmp_path):
    config, _ = app_env
    assert check_import_folder("", config.media_root, config.export_root) is None
    assert "찾을 수 없습니다" in check_import_folder(str(tmp_path / "nope"), config.media_root, config.export_root)
    assert "기본 저장 폴더" in check_import_folder(config.media_root, config.media_root, config.export_root)
    inside = Path(config.export_root) / "in"
    inside.mkdir(parents=True)
    assert "export" in check_import_folder(str(inside), config.media_root, config.export_root)
    ok = tmp_path / "camera"
    ok.mkdir()
    assert check_import_folder(str(ok), config.media_root, config.export_root) is None


def test_config_keeps_import_folder(app_env, tmp_path):
    from app.config import AppConfig
    config, _ = app_env
    config.import_folder = str(tmp_path / "camera")
    config.save()
    assert AppConfig.load().import_folder == str(tmp_path / "camera")


# ---- 메인 창 ----
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


@pytest.fixture()
def win_env(qapp, app_env, tmp_path, monkeypatch):
    config, db = app_env
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "before.jpg").write_bytes(_jpeg())        # 프로그램을 열기 전부터 있던 사진
    config.source_mode = "synthetic"
    config.import_folder = str(inbox)
    config.save = lambda: None
    _patient(db, "W1", "창환자")
    answers = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answers.pop(0)))
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    w._import_timer.stop()                              # 테스트에서는 직접 살핀다
    w.show()
    assert _wait(qapp, lambda: w._last_frame is not None)
    yield w, inbox, answers
    w.close()


def _poll(qapp, w):
    """한 번 살피고 작업 스레드(이어지는 '가져오기' 작업까지)가 끝날 때까지 기다린다."""
    w._poll_import()
    assert _wait(qapp, lambda: w._import_job is None)


def test_window_asks_for_old_photos_then_imports_new_ones(qapp, win_env):
    w, inbox, answers = win_env
    assert w._importer is not None and w.thumbnail_panel.count() == 0
    answers.append(QMessageBox.StandardButton.No)
    _poll(qapp, w)
    _poll(qapp, w)                                      # 전부터 있던 사진 → 묻고 '아니요'
    assert answers == [] and w.thumbnail_panel.count() == 0
    assert (inbox / "before.jpg").exists()

    w.control_bar.set_eye("OS")
    (inbox / "new.jpg").write_bytes(_jpeg())
    _poll(qapp, w)
    _poll(qapp, w)
    assert w.thumbnail_panel.count() == 1
    cap = w.thumbnail_panel.visible_captures()[0]
    assert cap.eye == "OS" and cap.note == "가져옴 · new.jpg"
    assert (inbox / DONE_DIR / "new.jpg").exists() and (inbox / "before.jpg").exists()


def test_window_imports_old_photos_when_confirmed(qapp, win_env):
    w, inbox, answers = win_env
    answers.append(QMessageBox.StandardButton.Yes)
    _poll(qapp, w)
    _poll(qapp, w)
    assert answers == [] and w.thumbnail_panel.count() == 1
    assert (inbox / DONE_DIR / "before.jpg").exists()


def test_window_turns_watch_off_and_on_from_settings(win_env, tmp_path):
    w, _, _ = win_env
    w.config.import_folder = ""
    w._setup_import()
    assert w._importer is None and not w._import_timer.isActive()
    other = tmp_path / "other"
    other.mkdir()
    w.config.import_folder = str(other)
    w._setup_import()
    assert w._importer is not None and w._importer.folder == other and w._import_timer.isActive()


def test_settings_dialog_checks_and_saves_import_folder(qapp, app_env, tmp_path, monkeypatch):
    from app.ui.settings_dialog import SettingsDialog
    config, _ = app_env
    config.source_mode = "synthetic"
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    dlg = SettingsDialog(config)
    dlg.import_folder.setText(config.media_root)        # 저장 폴더를 다시 가져오게 되는 설정은 막는다
    dlg.accept()
    assert warned and dlg.result() != SettingsDialog.DialogCode.Accepted
    cam = tmp_path / "camera"
    cam.mkdir()
    dlg.import_folder.setText(str(cam))
    dlg.accept()
    assert dlg.result() == SettingsDialog.DialogCode.Accepted and len(warned) == 1
    dlg.apply_to_config()
    assert config.import_folder == str(cam)


def test_window_pro_view_gets_new_photo_without_losing_place(qapp, win_env):
    w, inbox, answers = win_env
    answers.append(QMessageBox.StandardButton.No)
    _poll(qapp, w)
    _poll(qapp, w)
    w.act_pro.setChecked(True)                          # Pro 검토 화면에서 사진이 들어와도
    w.pro.set_mode("multi")
    (inbox / "pro.jpg").write_bytes(_jpeg())
    _poll(qapp, w)
    _poll(qapp, w)
    assert [c.note for c in w.pro.captures()] == ["가져옴 · pro.jpg"]
    assert w.pro.mode() == "multi"


def test_hung_folder_does_not_block_the_window(qapp, win_env, monkeypatch):
    import threading
    w, _, _ = win_env
    gate = threading.Event()
    monkeypatch.setattr(w._importer, "poll", lambda *a, **k: gate.wait(5) and None)
    w._poll_import()
    t = time.time()
    qapp.processEvents()                                # 폴더가 응답하지 않아도 화면은 바로 돌아온다
    w._poll_import()                                    # 앞 작업이 끝나기 전에는 겹쳐 시작하지 않는다
    assert time.time() - t < 1 and w._import_job is not None
    gate.set()
    assert _wait(qapp, lambda: w._import_job is None)
