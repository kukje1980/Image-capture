"""폴더 가져오기: 안저 사진 파일 이름 → 환자 DB 등록 → 원본 삭제."""
from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.models.patient import Patient
from app.services.capture_service import CaptureService
from app.services.folder_import import DONE_DIR, REVIEW_DIR, FolderImporter
from app.services.fundus_filename import captured_at, parse_filename

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name, template, want", [
    ("12345_홍길동_20261109_R.jpg", "", ("12345", "홍길동", "2026-11-09", None, "OD")),
    ("12345_홍길동_20261109_143015_L.jpg", "", ("12345", "홍길동", "2026-11-09", "14:30:15", "OS")),
    ("20261109143015_12345_OD.jpg", "", ("12345", None, "2026-11-09", "14:30:15", "OD")),
    ("A0123-L-2026.11.09.jpg", "", ("A0123", None, "2026-11-09", None, "OS")),
    ("HONG_GILDONG_12345_20261109_RE_001.jpg", "", ("12345", "HONG GILDONG", "2026-11-09", None, "OD")),
    ("12345 김철수 2026-11-09 좌안.png", "", ("12345", "김철수", "2026-11-09", None, "OS")),
    ("20261109_123456_R.jpg", "", ("123456", None, "2026-11-09", None, "OD")),     # 6자리 아이디 ≠ 시각
    ("12345_홍길동_20261109_R_001.jpg", "{id}_{name}_{date}_{eye}", ("12345", "홍길동", "2026-11-09", None, "OD")),
    ("20261109143015_12345_OD.jpg", "{date}{time}_{id}_{eye}", ("12345", None, "2026-11-09", "14:30:15", "OD")),
    ("12345_HONG^GILDONG_261109_LEFT.jpg", "{id}_{name}_{date}_{eye}", ("12345", "HONG GILDONG", "2026-11-09", None, "OS")),
])
def test_parse_filename(name, template, want):
    r = parse_filename(name, template)
    assert r.ok, r.error
    assert (r.id, r.name, r.date, r.time, r.eye) == want


@pytest.mark.parametrize("name, template", [
    ("IMG_0042.JPG", ""),                          # 카메라 기본 이름 — 아이디로 착각하지 않음
    ("홍길동.jpg", ""),                             # 아이디 없음
    ("12345_홍길동_R.jpg", "{id}_{name}_{date}_{eye}"),
    ("12345_20261340_R.jpg", "{id}_{date}_{eye}"),  # 없는 날짜
    ("x.jpg", "{name}_{eye}"),                     # 형식에 {id} 없음
])
def test_parse_filename_rejects(name, template):
    assert not parse_filename(name, template).ok


def test_captured_at_fallbacks():
    from datetime import datetime
    fb = datetime(2026, 11, 9, 10, 20, 30)
    assert captured_at(parse_filename("12345_20261109_143015_R.jpg"), fb) == "2026-11-09 14:30:15"
    assert captured_at(parse_filename("12345_20261109_R.jpg"), fb) == "2026-11-09 10:20:30"   # 같은 날 → 파일 시각
    assert captured_at(parse_filename("12345_20250101_R.jpg"), fb) == "2025-01-01 00:00:00"
    assert captured_at(parse_filename("12345_홍길동_R.jpg"), fb) == "2026-11-09 10:20:30"


def test_field_from_filename():
    assert parse_filename("12345_홍길동_20261109_R_MAC.jpg").field == "황반 중심"
    assert parse_filename("12345_홍길동_20261109_L_disc.jpg").field == "시신경유두 중심"
    assert parse_filename("12345_홍길동_20261109_L.jpg").field is None
    r = parse_filename("12345_황반_홍길동_20261109_R.jpg")              # 부위 단어를 이름으로 읽지 않음
    assert r.name == "홍길동" and r.field == "황반 중심"
    assert parse_filename("12345_홍길동_20261109_R_황반.jpg", "{id}_{name}_{date}_{eye}").field == "황반 중심"


def test_parser_same_in_web_and_desktop():
    a = (ROOT / "app" / "services" / "fundus_filename.py").read_text(encoding="utf-8")
    b = (ROOT / "web" / "app" / "fundus_filename.py").read_text(encoding="utf-8")
    assert a == b, "app/services/fundus_filename.py 와 web/app/fundus_filename.py 를 똑같이 맞추세요"


# ---- 가져오기 ----
def _jpg(path: Path, color=(30, 60, 160), old=True) -> bytes:
    img = np.full((120, 160, 3), color, np.uint8)
    cv2.circle(img, (80, 60), 40, (40, 140, 230), -1)
    data = cv2.imencode(".jpg", img)[1].tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if old:
        t = time.time() - 10
        os.utime(path, (t, t))
    return data


@pytest.fixture()
def env(app_env, tmp_path):
    config, db = app_env
    watch = tmp_path / "camera_out"
    watch.mkdir()
    config.import_dir = str(watch)
    config.import_template = ""
    config.import_delete = True
    config.import_recursive = True
    svc = CaptureService(db, config)
    return config, db, svc, FolderImporter(db, svc, config), watch


def test_import_creates_patient_saves_original_and_deletes(env):
    config, db, svc, imp, watch = env
    data = _jpg(watch / "12345_홍길동_20261109_143015_R.jpg")
    _jpg(watch / "sub" / "12345_홍길동_20261109_143020_L.jpg")          # 하위 폴더
    items = imp.scan(force=True)
    assert [i.ok for i in items] == [True, True]
    p = db.patients.find_by_code("12345")
    assert p is not None and p.name == "홍길동" and items[0].new_patient
    caps = db.captures.list_by_patient(p.id, order="asc")
    assert [(c.eye, c.captured_at) for c in caps] == [("OD", "2026-11-09 14:30:15"), ("OS", "2026-11-09 14:30:20")]
    assert Path(caps[0].file_path).read_bytes() == data                   # 다시 인코딩하지 않은 원본
    assert caps[0].thumbnail_path and Path(caps[0].thumbnail_path).exists()
    assert not list(watch.rglob("*.jpg"))                                 # 원본은 지워짐
    # 같은 아이디는 기존 환자로
    _jpg(watch / "12345_홍길동_20261110_R.jpg")
    (item,) = imp.scan(force=True)
    assert item.ok and not item.new_patient and item.patient.id == p.id


def test_import_waits_until_file_is_stable(env):
    config, db, svc, imp, watch = env
    _jpg(watch / "777_김철수_20261109_L.jpg")
    assert imp.scan() == []                         # 처음 본 파일은 다음 번에 (카메라가 쓰는 중일 수 있음)
    (item,) = imp.scan()
    assert item.ok and item.patient.chart_no == "777"


def test_unreadable_and_conflicting_names_go_to_review(env):
    config, db, svc, imp, watch = env
    db.patients.insert(Patient(chart_no="555", name="이영희"))
    _jpg(watch / "IMG_0042.jpg")
    _jpg(watch / "555_박민수_20261109_R.jpg")      # 아이디는 이영희인데 이름이 다름 → 잘못 들어가지 않게
    _jpg(watch / "555_YOUNGHEE_20261109_L.jpg")    # 한글 ↔ 영문은 비교 불가 → 등록
    items = {Path(i.source).name: i for i in imp.scan(force=True)}
    assert not items["IMG_0042.jpg"].ok and not items["555_박민수_20261109_R.jpg"].ok
    assert items["555_YOUNGHEE_20261109_L.jpg"].ok
    review = sorted(f.name for f in (watch / REVIEW_DIR).iterdir())
    assert review == ["555_박민수_20261109_R.jpg", "IMG_0042.jpg"]
    assert imp.scan(force=True) == []               # '_확인필요' 폴더는 다시 보지 않음
    assert len(db.captures.list_by_patient(db.patients.find_by_code("555").id)) == 1


def test_keep_originals_moves_to_done_folder(env):
    config, db, svc, imp, watch = env
    config.import_delete = False
    _jpg(watch / "999_최수진_20261109_OD.png")
    (item,) = imp.scan(force=True)
    assert item.ok
    assert (watch / DONE_DIR / "999_최수진_20261109_OD.png").exists()
    assert imp.scan(force=True) == []


def test_template_and_no_folder(env):
    config, db, svc, imp, watch = env
    config.import_template = "{date}{time}_{id}_{eye}"
    _jpg(watch / "20261109090807_4321_LE.jpg")
    (item,) = imp.scan(force=True)
    assert item.ok and item.capture.captured_at == "2026-11-09 09:08:07" and item.capture.eye == "OS"
    assert item.patient.name == "4321"             # 이름이 없으면 아이디로 만들고 나중에 고침
    config.import_dir = str(watch / "nope")
    assert imp.scan(force=True) == [] and imp.last_error


# ---- 메인 창: 자동 가져오기 → 그 환자로 바뀌고 사진 목록에 보임 ----
def test_main_window_imports_and_switches_patient(app_env, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    config, db = app_env
    config.source_mode = "synthetic"
    config.capture_width, config.capture_height = 320, 180
    config.save = lambda: None
    db.patients.insert(Patient(chart_no="1", name="먼저"))
    watch = tmp_path / "fundus_in"
    watch.mkdir()
    config.import_enabled, config.import_dir = True, str(watch)
    from app.ui.main_window import MainWindow
    w = MainWindow(config, db)
    try:
        assert w._import_timer.isActive() and "켜짐" in w.btn_import.text()
        _jpg(watch / "24680_정하늘_20261109_101500_L.jpg")
        w._import_tick(force=True)
        end = time.time() + 10
        while time.time() < end and (w._current_patient is None or w._current_patient.chart_no != "24680"):
            app.processEvents()
            time.sleep(0.02)
        assert w._current_patient.chart_no == "24680" and w._current_patient.name == "정하늘"
        assert w.thumbnail_panel.count() == 1 and w.thumbnail_panel._items[0].eye == "OS"
        assert not list(watch.glob("*.jpg"))
        config.import_enabled = False
        w._sync_import()
        assert not w._import_timer.isActive()
    finally:
        w.close()
