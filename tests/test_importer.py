import shutil
import time
from pathlib import Path

import pytest

from fundusview.config import ACTION_MOVE, ACTION_REFERENCE, Settings, WatchFolder
from fundusview.db import Database
from fundusview.importer import Importer
from fundusview.watcher import ImportService


@pytest.fixture()
def env(tmp_path, demo_dir):
    drop = tmp_path / "drop"
    shutil.copytree(demo_dir, drop)
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(drop))])
    db = Database(tmp_path / "lib" / "fundus.db")
    yield s, db, drop
    db.close()


def _all_files(drop: Path):
    return sorted(p for p in drop.rglob("*") if p.suffix.lower() in (".jpg", ".dcm"))


def test_import_demo_folder(env):
    s, db, drop = env
    imp = Importer(db, s)
    results = [imp.import_file(p, s.watch_folders[0]) for p in _all_files(drop)]
    assert [r.status for r in results].count("imported") == 11
    pats = {r["patient_id"]: r for r in db.list_patients()}
    assert set(pats) == {"PID20260310-0A1B2C3D", "20260115001", "20260212003", "D0001234", "D0001235", "D0009876"}
    assert pats["20260115001"]["n_images"] == 2 and pats["20260115001"]["name"] == "김민수"
    assert db.count_unassigned() == 2  # IMG_0001 + RetiCam anonymous
    imgs = db.images_for_patient(pats["20260212003"]["id"])
    row = imgs[0]
    assert (row["fov_deg"], row["fov_type"], row["projection"], row["laterality"]) == (165.0, "internal",
                                                                                       "equidistant", "OD")
    assert Path(row["file_path"]).exists() and Path(row["thumb_path"]).exists()
    assert Path(row["file_path"]).parts[-3:-1] == ("20260212003", "2026-02-12")
    assert row["circle_r"] > 200
    rc = db.images_for_patient(pats["PID20260310-0A1B2C3D"]["id"])
    assert len(rc) == 3 and {r["projection"] for r in rc} == {"radial"}
    assert sorted(r["fov_deg"] for r in rc) == [176.0, 176.0, 220.0]
    assert pats["PID20260310-0A1B2C3D"]["name"] == "정하늘"
    dcm = db.images_for_patient(pats["D0009876"]["id"])[0]
    assert dcm["display_path"] and Path(dcm["display_path"]).exists()   # decoded PNG for DICOM
    # second pass: everything already seen
    again = [imp.import_file(p, s.watch_folders[0]) for p in _all_files(drop)]
    assert {r.status for r in again} == {"skipped"}


def test_duplicate_content_and_fill_blanks(env):
    s, db, drop = env
    imp = Importer(db, s)
    src = drop / "VK2_Export" / "D0001234_20260110_093015_R_FUNDUS (COLOR)_1.jpg"
    assert imp.import_file(src).status == "imported"
    copy = drop / "copy.jpg"
    shutil.copy(src, copy)
    assert imp.import_file(copy).status == "duplicate"


def test_existing_names_are_not_overwritten(env):
    s, db, drop = env
    from fundusview.models import ExtractedMeta
    ref = db.upsert_patient(ExtractedMeta(patient_id="20260115001", name="김민수(수정)"))
    imp = Importer(db, s)
    for p in (drop / "PatientCapture").rglob("*.jpg"):
        imp.import_file(p, s.watch_folders[0])
    assert db.get_patient(ref)["name"] == "김민수(수정)"


@pytest.mark.parametrize("action", [ACTION_MOVE, ACTION_REFERENCE])
def test_actions(env, action):
    s, db, drop = env
    f = WatchFolder(path=str(drop), action=action)
    src = drop / "VK2_Export" / "D0001234_20260110_093015_R_FUNDUS (COLOR)_1.jpg"
    res = Importer(db, s).import_file(src, f)
    row = db.get_image(res.image_id)
    if action == ACTION_MOVE:
        assert not src.exists() and Path(row["file_path"]).exists()
    else:
        assert src.exists() and row["file_path"] == str(src)


def test_unstable_file_is_pending(env, monkeypatch):
    s, db, drop = env
    import fundusview.importer as imp_mod
    monkeypatch.setattr(imp_mod, "wait_until_stable", lambda p, sec: False)
    res = Importer(db, s).import_file(drop / "기타" / "IMG_0001.jpg")
    assert res.status == "pending"


def test_watcher_picks_up_new_files(tmp_path, demo_dir):
    drop = tmp_path / "watched"
    drop.mkdir()
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.2, rescan_seconds=1,
                 watch_folders=[WatchFolder(path=str(drop))])
    db = Database(tmp_path / "lib" / "fundus.db")
    results = []
    svc = ImportService(db, s, on_result=results.append)
    try:
        assert svc.start_watching() == []
        time.sleep(0.5)
        # Export Tool style: written as .tmp, then renamed
        src = demo_dir / "VK2_Export" / "D0001234_20260110_093015_R_FUNDUS (COLOR)_1.jpg"
        tmp = drop / "D0001234_20260110_093015_R_FUNDUS (COLOR)_1.tmp"
        shutil.copy(src, tmp)
        tmp.rename(tmp.with_suffix(".jpg"))
        sub = drop / "PatientCapture" / "20260115001_김민수" / "2026_01_15" / "COLOR"
        sub.mkdir(parents=True)
        for p in (demo_dir / "PatientCapture").rglob("*10_20_31*.jpg"):
            shutil.copy(p, sub / p.name)
        deadline = time.time() + 20
        while len([r for r in results if r.status == "imported"]) < 2 and time.time() < deadline:
            time.sleep(0.1)
        assert sorted(r.message for r in results if r.status == "imported") == ["20260115001 김민수", "D0001234"]
    finally:
        svc.shutdown()
        db.close()


def test_same_id_different_name_is_logged(env):
    s, db, drop = env
    from fundusview.models import ExtractedMeta
    db.upsert_patient(ExtractedMeta(patient_id="20260115001", name="다른사람"))
    Importer(db, s).import_file(next((drop / "PatientCapture").rglob("*10_20_31*.jpg")), s.watch_folders[0])
    warns = [r["message"] for r in db.recent_logs() if r["level"] == "warn"]
    assert warns and "김민수" in warns[0] and "다른사람" in warns[0]


def test_polling_folder_and_unchanged_dirs(tmp_path, demo_dir):
    drop = tmp_path / "share"
    shutil.copytree(demo_dir / "VK2_Export", drop / "a")
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(drop), polling=True)])
    db = Database(tmp_path / "lib" / "fundus.db")
    svc = ImportService(db, s)
    try:
        assert svc.scan_folder(s.watch_folders[0], full=True) == 2
        deadline = time.time() + 10
        while svc.queued and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        assert svc.scan_folder(s.watch_folders[0]) == 0      # nothing new
        (drop / "b").mkdir()
        shutil.copy(demo_dir / "기타" / "IMG_0001.jpg", drop / "b" / "new.jpg")
        assert svc.scan_folder(s.watch_folders[0]) == 1      # new dir found
    finally:
        svc.shutdown()
        db.close()
