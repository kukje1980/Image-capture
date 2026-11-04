"""안저판: 제품·데이터 폴더 분리, 폴더 감시, 사진 가져오기, 안구 추정·수정, 안저 화면."""
from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app import brand, paths, shortcuts
from app.capture.folder_watch import IMPORTED_DIR, FolderScanner, FolderUnavailable, guess_eye
from app.config import AppConfig
from app.db.database import Database
from app.models.patient import Patient
from app.services.capture_service import CaptureService, ImageNotReady

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def fundus_env(tmp_path, monkeypatch):
    """안저 제품 + 임시 APPDATA (설정·DB·사진 격리)."""
    monkeypatch.setenv(brand.ENV_KEY, "fundus")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    config = AppConfig.load()
    config.export_root = str(tmp_path / "export")
    config.watch_folder = str(tmp_path / "camera")
    os.makedirs(config.watch_folder)
    db = Database(config.db_path).init()
    yield config, db, tmp_path
    db.close()


def _jpg(path, color=(40, 90, 200), exif_time: str | None = None) -> Path:
    img = np.zeros((300, 400, 3), np.uint8)
    cv2.circle(img, (200, 150), 130, color, -1)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exif_time:
        from PIL import Image

        im = Image.fromarray(img[..., ::-1])
        exif = Image.Exif()
        exif[306] = exif_time                       # DateTime
        im.save(path, "JPEG", exif=exif.tobytes())
    else:
        cv2.imwrite(str(path), img)
    return path


# ---------------- 제품 · 브랜드 ----------------
def test_fundus_product_has_own_data_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv(brand.ENV_KEY, "fundus")
    assert brand.is_fundus() and brand.current()["window_title"] == "안저 디지털 영상 시스템"
    assert paths.get_appdata_dir() == tmp_path / "FundusImaging"
    cfg = AppConfig.load()
    assert Path(cfg.db_path).name == "fundus.db" and "FundusImaging" in cfg.media_root
    monkeypatch.setenv(brand.ENV_KEY, "keeler")
    assert not brand.is_fundus() and paths.get_appdata_dir() == tmp_path / "SlitLampImaging"


def test_brand_choose_keeps_product(monkeypatch):
    monkeypatch.delenv(brand.ENV_KEY, raising=False)
    assert brand.choose([], "keeler") == "keeler"                      # 같은 제품 안에서는 설정 파일로 변경
    assert brand.choose([], "fundus") == "default"                     # 설정 파일로 제품은 못 바꿈
    assert brand.choose(["app", "--brand", "fundus"], "keeler") == "fundus"
    monkeypatch.setenv(brand.ENV_KEY, "fundus")                        # 안저 설치본
    assert brand.choose([], "keeler") == "fundus"
    assert brand.choose([], "") == "fundus"


def test_fundus_shortcuts(monkeypatch):
    monkeypatch.setenv(brand.ENV_KEY, "fundus")
    ids = [a[0] for a in shortcuts.actions()]
    assert "import" in ids and "watch" in ids and "record" not in ids and "capture" not in ids
    assert shortcuts.defaults()["import"] == "I"
    monkeypatch.setenv(brand.ENV_KEY, "default")
    assert "record" in [a[0] for a in shortcuts.actions()]


# ---------------- 안구 추정 ----------------
@pytest.mark.parametrize("name,eye", [
    ("20261104_103012_R.jpg", "OD"), ("IMG_0001_L.JPG", "OS"), ("P123-OD-1.tif", "OD"),
    ("p123 OS.png", "OS"), ("Right_eye.jpg", "OD"), ("scan_LEFT02.jpg", "OS"),
    ("홍길동_우안.jpg", "OD"), ("홍길동_좌.jpg", "OS"), ("both_OU.jpg", "OU"),
    ("IMG_0001.jpg", None), ("R_and_L.jpg", None), ("ROAD.jpg", None), ("12345.jpg", None),
])
def test_guess_eye(name, eye):
    assert guess_eye(name) == eye


# ---------------- 폴더 감시 ----------------
def test_scanner_ignores_existing_and_waits_until_written(tmp_path):
    _jpg(tmp_path / "old.jpg")
    sc = FolderScanner(tmp_path, settle=2)
    assert sc.prime() == 1
    assert sc.poll() == []                                             # 시작 전부터 있던 사진은 가져오지 않음
    new = tmp_path / "new.jpg"
    new.write_bytes(b"\xff\xd8partial")                                # 카메라가 쓰는 중
    assert sc.poll() == []
    _jpg(new)                                                          # 다 씀 (크기 바뀜)
    os.utime(new, ns=(time.time_ns(), time.time_ns()))
    assert sc.poll() == []                                             # 한 번 더 같은지 확인
    assert sc.poll() == [new]
    assert sc.poll() == []                                             # 한 번만
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "empty.jpg").write_bytes(b"")
    (tmp_path / "~tmp.jpg").write_bytes(b"x")
    assert sc.poll() == [] and sc.poll() == []                         # 이미지 아님·빈 파일·임시 파일


def test_scanner_subfolders_skip_imported_and_overwrite(tmp_path):
    sc = FolderScanner(tmp_path, recursive=True, settle=1)
    sc.prime()
    a = _jpg(tmp_path / "2026-11-04" / "a.jpg")
    _jpg(tmp_path / IMPORTED_DIR / "moved.jpg")
    assert sc.poll() == [a]
    _jpg(a, color=(10, 200, 10))                                       # 같은 이름으로 덮어쓰기 → 새 사진
    os.utime(a, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    assert sc.poll() == [a]
    flat = FolderScanner(tmp_path, recursive=False, settle=1)
    flat.prime()
    _jpg(tmp_path / "2026-11-04" / "b.jpg")
    assert flat.poll() == []


def test_scanner_unavailable_folder_keeps_memory(tmp_path):
    cam = tmp_path / "cam"
    cam.mkdir()
    _jpg(cam / "x.jpg")
    sc = FolderScanner(cam, settle=1)
    sc.prime()
    os.rename(cam, tmp_path / "gone")                                  # 네트워크 끊김 흉내
    with pytest.raises(FolderUnavailable):
        sc.poll()
    os.rename(tmp_path / "gone", cam)
    assert sc.poll() == []                                             # 돌아와도 예전 사진을 다시 가져오지 않음


# ---------------- 사진 가져오기 · 안구 수정 ----------------
def test_import_photo_copies_original(fundus_env):
    config, db, tmp = fundus_env
    p = Patient(chart_no="F1", name="안저")
    p.id = db.patients.insert(p)
    svc = CaptureService(db, config)
    src = _jpg(tmp / "camera" / "IMG_7_R.jpg", exif_time="2026:10:30 09:15:42")
    cap = svc.import_photo(src, p, eye="OD")
    assert Path(cap.file_path).read_bytes() == src.read_bytes()        # 재압축 없이 원본 그대로
    assert cap.captured_at == "2026-10-30 09:15:42"                    # EXIF 촬영 시각
    assert "2026-10-30" in cap.file_path and cap.file_path.endswith("_OD.jpg")
    assert Path(cap.export_path).exists() and Path(cap.thumbnail_path).exists()
    assert db.captures.list_by_patient(p.id)[0].eye == "OD"
    cap2 = svc.import_photo(src, p, eye="OD")                          # 같은 초 → 덮어쓰지 않음
    assert cap2.file_path != cap.file_path and Path(cap.file_path).exists()
    bad = tmp / "camera" / "broken.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(ImageNotReady):
        svc.import_photo(bad, p)


def test_change_eye_renames_files(fundus_env):
    config, db, tmp = fundus_env
    p = Patient(chart_no="F2", name="수정")
    p.id = db.patients.insert(p)
    svc = CaptureService(db, config)
    cap = svc.import_photo(_jpg(tmp / "camera" / "a.jpg"), p, eye="NA")
    old = cap.file_path
    svc.change_eye(cap, "OS")
    assert cap.eye == "OS" and cap.file_path.endswith("_OS.jpg") and not Path(old).exists()
    for f in (cap.file_path, cap.export_path, cap.thumbnail_path):
        assert Path(f).exists() and "_OS" in Path(f).name
    row = db.captures.get(cap.id)
    assert row.eye == "OS" and row.file_path == cap.file_path


# ---------------- 안저 화면 ----------------
def _window(config, db):
    from app.ui.fundus_window import FundusWindow

    return FundusWindow(config, db)


def test_window_pending_until_patient_confirmed(qapp, fundus_env, monkeypatch):
    config, db, tmp = fundus_env
    config.watch_enabled = False                                       # 스레드 없이 신호 흉내
    a = Patient(chart_no="A1", name="가환자")
    a.id = db.patients.insert(a)
    w = _window(config, db)
    try:
        assert not w.pro.b_live.isVisibleTo(w.pro) and w.pro.b_single.isVisibleTo(w.pro)
        assert not w.thumbnail_panel.filter_buttons["video"].isVisibleTo(w.thumbnail_panel)
        asked = []
        monkeypatch.setattr(w, "_ask_pending", lambda p, n: asked.append((p.name, n)) or "yes")
        # 시작 때 자동 선택된 환자 → 바로 등록하지 않고 묻는다
        f1 = _jpg(tmp / "camera" / "s1_L.jpg")
        w._on_new_file(str(f1))
        assert w._pending == [str(f1)] and w.thumbnail_panel.count() == 0
        qapp.processEvents()
        assert asked == [("가환자", 1)] and w._pending == []
        caps = w.thumbnail_panel.all_captures()
        assert len(caps) == 1 and caps[0].eye == "OS"                  # 파일 이름 L → OS
        assert w._shown is not None and w._shown.id == caps[0].id
        # 확인된 환자 → 바로 등록 (이름에 안구 없음 → 도크에서 고른 안구)
        w.fundus_bar.set_eye("OD")
        w._on_new_file(str(_jpg(tmp / "camera" / "s2.jpg")))
        assert w.thumbnail_panel.count() == 2 and w._shown.eye == "OD"
        w._on_new_file(str(f1))                                        # 같은 파일 다시 → 무시
        assert w.thumbnail_panel.count() == 2
        # 안구 수정
        w._on_fix_eye("OS")
        assert w._shown.eye == "OS" and db.captures.get(w._shown.id).eye == "OS"
        # '등록 안 함'
        monkeypatch.setattr(w, "_patient_confirmed", False)
        monkeypatch.setattr(w, "_ask_pending", lambda p, n: "drop")
        w._on_new_file(str(_jpg(tmp / "camera" / "s3.jpg")))
        qapp.processEvents()
        assert w._pending == [] and w.thumbnail_panel.count() == 2
    finally:
        w.close()


def test_window_watches_folder(qapp, qtbot, fundus_env):
    config, db, tmp = fundus_env
    config.watch_interval_ms = 300
    config.watch_move_imported = True
    p = Patient(chart_no="W1", name="감시")
    p.id = db.patients.insert(p)
    w = _window(config, db)
    qtbot.addWidget(w)
    try:
        w.patient_panel.combo.setCurrentIndex(0)
        w._on_patient_changed(w.patient_panel.current_patient())       # 사용자가 고른 것처럼
        assert w._patient_confirmed
        qtbot.waitUntil(lambda: w._watch_ok is True, timeout=10000)
        src = _jpg(tmp / "camera" / "20261104" / "x_R.jpg")
        qtbot.waitUntil(lambda: w.thumbnail_panel.count() == 1, timeout=15000)
        cap = w.thumbnail_panel.all_captures()[0]
        assert cap.eye == "OD" and Path(cap.file_path).exists()
        qtbot.waitUntil(lambda: not src.exists(), timeout=5000)        # 원본은 '_가져옴' 으로 정리
        assert list((tmp / "camera" / IMPORTED_DIR).rglob("x_R.jpg"))
    finally:
        w.close()
    assert w._watch_thread is None


def test_fundus_build_files():
    iss = (ROOT / "installer" / "fundus.iss").read_text(encoding="utf-8-sig")
    assert "FundusImaging.exe" in iss and "brand\\fundus\\app.ico" in iss
    ids = {}
    for name in ("slitlamp", "keeler", "fundus"):
        text = (ROOT / "installer" / f"{name}.iss").read_text(encoding="utf-8-sig")
        ids[name] = next(line for line in text.splitlines() if line.startswith("AppId="))
    assert len(set(ids.values())) == 3                                 # 셋 다 나란히 설치 가능
    for spec in ("build.spec", "build_mac.spec"):
        text = (ROOT / spec).read_text(encoding="utf-8")
        assert "FundusImaging" in text and "brand_fundus.py" in text, spec
    assert (ROOT / "tools" / "rthooks" / "brand_fundus.py").is_file()
    for f in ("app.ico", "app.icns", "app.png"):
        assert (ROOT / "assets" / "brand" / "fundus" / f).is_file(), f
    for wf in ("build-windows.yml", "build-mac.yml"):
        assert "FundusImaging" in (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
