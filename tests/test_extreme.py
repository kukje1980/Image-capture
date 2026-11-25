"""극한 테스트 (0.13.13): what hostile or damaged input used to break — a settings file of the wrong
shape, a database that is not one, two imports of the same photo at once, an address that is not
the server's, dates that are not dates … Each case here failed before its fix."""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fundusview.config import Settings, WatchFolder
from fundusview.db import Database
from fundusview.models import ExtractedMeta


def _photo(path: Path, seed: int = 0, size: int = 96) -> Path:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:size, :size]
    disc = ((xx - size / 2) ** 2 + (yy - size / 2) ** 2) < (size * 0.45) ** 2
    rgb = np.zeros((size, size, 3), np.uint8)
    rgb[disc] = (150, 70, 40)
    rgb[disc] += rng.integers(0, 30, (int(disc.sum()), 3), dtype=np.uint8)
    Image.fromarray(rgb).save(path)
    return path


# -- settings ---------------------------------------------------------------------------------
def test_settings_saved_by_notepad_with_a_byte_order_mark_are_read(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"library_dir": "D:/병원자료", "pacs_host": "10.0.0.5"},
                                                  ensure_ascii=False).encode("utf-8"))
    s = Settings.load(path)
    assert s.library_dir == "D:/병원자료" and s.pacs_host == "10.0.0.5"
    s.save(path)                                             # … and the next save keeps them
    assert Settings.load(path).library_dir == "D:/병원자료"


@pytest.mark.parametrize("text", ["null", "[]", '"x"', "3", "{not json", ""])
def test_a_settings_file_that_is_not_settings_starts_with_defaults_and_is_kept_aside(tmp_path, text):
    path = tmp_path / "settings.json"
    path.write_text(text, encoding="utf-8")
    s = Settings.load(path)                                  # (was: AttributeError / TypeError at start-up)
    assert s == Settings()
    assert (tmp_path / "settings.json.bad").read_text(encoding="utf-8") == text and not path.exists()


def test_settings_values_of_the_wrong_kind_become_usable_ones(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "stable_seconds": "1.5", "rescan_seconds": "60", "share_port": "8765", "library_dir": 5,
        "watch_on_startup": "yes", "custom_filename_patterns": [5, None, r"(?P<pid>\d+)"],
        "pacs_port": "abc", "mwl_port": None, "unknown_key": 1,
        "watch_folders": [5, "C:/x", {"profile": "auto"}, {"path": ""},
                          {"path": "C:/cam", "recursive": "no", "polling": True, "extra": 1}],
    }), encoding="utf-8")
    s = Settings.load(path)
    d = Settings()
    assert s.stable_seconds == 1.5 and isinstance(s.stable_seconds, float)
    assert s.rescan_seconds == 60 and isinstance(s.rescan_seconds, int) and s.share_port == 8765
    assert s.library_dir == d.library_dir and s.watch_on_startup is d.watch_on_startup
    assert s.custom_filename_patterns == [r"(?P<pid>\d+)"]
    assert s.pacs_port == d.pacs_port and s.mwl_port == d.mwl_port
    assert [f.path for f in s.watch_folders] == ["C:/cam"]
    assert s.watch_folders[0].recursive is WatchFolder(path="x").recursive and s.watch_folders[0].polling is True
    path.write_text('{"stable_seconds": NaN, "rescan_seconds": Infinity}', encoding="utf-8")
    s = Settings.load(path)
    assert s.stable_seconds == d.stable_seconds and s.rescan_seconds == d.rescan_seconds
    s.library                                                # (was: TypeError for library_dir = 5)


def test_a_filename_pattern_that_is_not_text_is_skipped():
    from fundusview.extract.filename_meta import match_patterns

    assert match_patterns("12345_x.jpg", [5, None, "("], ExtractedMeta(), "test") is False


# -- database ---------------------------------------------------------------------------------
def test_a_file_that_is_not_a_database_is_refused_and_can_be_put_aside(tmp_path):
    path = tmp_path / "fundus.db"
    path.write_bytes(b"this is not sqlite " * 400)
    with pytest.raises(sqlite3.Error):
        Database(path)
    os.replace(path, tmp_path / "fundus.db.corrupt")         # not held open (Windows: could not be renamed)
    db = Database(path)
    assert db.count_patients() == 0
    db.close()


def test_startup_tells_of_a_damaged_library_and_starts_an_empty_one_beside_it(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from fundusview import app as app_mod

    QApplication.instance() or QApplication([])
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "fundus.db").write_bytes(b"\0" * 5000 + b"junk")
    s = Settings(library_dir=str(lib))
    assert app_mod._open_library(s, gui=False) is None       # the server without a window: said, not raised
    asked = []

    def answer(which):
        def run(box):
            asked.append(box.text())
            for b in box.buttons():
                if which in b.text():
                    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self, b=b: b)
            return 0
        return run

    monkeypatch.setattr(QMessageBox, "exec", answer("끝내기"))
    assert app_mod._open_library(s, gui=True) is None and (lib / "fundus.db").read_bytes().endswith(b"junk")
    monkeypatch.setattr(QMessageBox, "exec", answer("새로 시작"))
    db = app_mod._open_library(s, gui=True)
    try:
        assert db is not None and db.count_patients() == 0 and "열 수 없습니다" in asked[-1]
        kept = [p for p in lib.iterdir() if ".corrupt-" in p.name]
        assert len(kept) == 1 and kept[0].read_bytes().endswith(b"junk")   # kept, never deleted
    finally:
        db.close()


def test_merging_a_patient_into_itself_or_into_nobody_changes_nothing(tmp_path):
    db = Database(tmp_path / "f.db")
    a = db.upsert_patient(ExtractedMeta(patient_id="A", name="가"))
    b = db.upsert_patient(ExtractedMeta(patient_id="B", name="나"))
    ia = db.insert_image(patient_ref=a, file_path="a.jpg", sha256="1")
    ib = db.insert_image(patient_ref=b, file_path="b.jpg", sha256="2")
    db.merge_patients(a, a)                                  # (was: the patient deleted, the photo without one)
    db.merge_patients(a, 99999)                              # (was: the photos pointed at nobody)
    assert db.get_patient(a) is not None and db.get_image(ia)["patient_ref"] == a
    db.merge_patients(a, b)
    assert db.get_patient(a) is None and db.get_image(ia)["patient_ref"] == b == db.get_image(ib)["patient_ref"]
    db.close()


def test_the_patient_search_looks_for_percent_and_underscore_as_typed(tmp_path):
    db = Database(tmp_path / "f.db")
    for pid, name in (("100%", "가"), ("A_1", "나"), ("AB1", "다"), ("C", "라")):
        db.upsert_patient(ExtractedMeta(patient_id=pid, name=name))
    found = lambda text: sorted(r["patient_id"] for r in db.list_patients(text))   # noqa: E731
    assert found("%") == ["100%"] and found("_") == ["A_1"] and found("A") == ["AB1", "A_1"]
    assert found("\\") == [] and len(db.list_patients("")) == 4
    db.close()


# -- importing --------------------------------------------------------------------------------
def test_two_imports_of_the_same_photo_at_once_leave_its_files_in_the_library(tmp_path):
    """The one that lost at the database (UNIQUE sha256) removed "its" files — the thumbnail (named
    by the photo's digest) and, with the same file name, the stored photo of the one that won."""
    from fundusview.importer import Importer

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.0)
    db = Database(tmp_path / "lib" / "fundus.db")
    imp = Importer(db, s)
    for trial in range(6):
        folders = []
        for k in range(3):
            d = tmp_path / f"src{trial}_{k}"
            d.mkdir()
            folders.append(_photo(d / "photo.png", seed=trial))        # the same picture, the same name
        start = threading.Barrier(len(folders))
        results = []

        def run(p):
            start.wait()
            results.append(imp.import_file(p, wait=False))

        threads = [threading.Thread(target=run, args=(p,)) for p in folders]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(r.status for r in results) == ["duplicate", "duplicate", "imported"], results
        row = db.get_image(next(r.image_id for r in results if r.status == "imported"))
        assert Path(row["file_path"]).is_file() and Path(row["thumb_path"]).is_file()
    db.close()


def test_an_old_file_is_not_waited_for_as_if_it_were_still_being_written(tmp_path):
    from fundusview.importer import OLD_FILE_SECONDS, wait_until_stable

    old = _photo(tmp_path / "old.png")
    past = time.time() - OLD_FILE_SECONDS - 60
    os.utime(old, (past, past))
    t0 = time.monotonic()
    assert wait_until_stable(old, 1.5)
    assert time.monotonic() - t0 < 1.0                       # (was: the whole 1.5 s, for every photo)
    new = _photo(tmp_path / "new.png")                       # just written: the whole wait, as before
    t0 = time.monotonic()
    assert wait_until_stable(new, 0.6)
    assert time.monotonic() - t0 >= 0.6
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    os.utime(empty, (past, past))
    assert not wait_until_stable(empty, 0.1)                 # an empty file stays "not finished"


def test_a_sidecar_that_cannot_be_read_does_not_refuse_the_photo(tmp_path):
    from fundusview.extract.embedded_meta import sidecar_meta

    photo = _photo(tmp_path / "p.png")
    (tmp_path / "p.json").write_text("[" * 20000 + "]" * 20000, encoding="utf-8")   # (was: RecursionError)
    (tmp_path / "p.csv").write_text('a,b\n"' + "x" * 200_000 + '",1\n', encoding="utf-8")  # (was: csv.Error)
    assert sidecar_meta(photo).patient_id is None
    deep = {"PatientID": "12345"}
    for _ in range(200):
        deep = {"more": deep}
    (tmp_path / "p.json").write_text(json.dumps(deep), encoding="utf-8")
    sidecar_meta(photo)                                      # nested past any camera's file: no error


def test_a_picture_past_the_size_limit_is_refused_before_it_is_decoded(tmp_path):
    """Between one and two times the limit Pillow only warned: a 1 MB file became gigabytes."""
    from fundusview import imaging
    from fundusview.importer import describe_error

    big = tmp_path / "bomb.png"
    Image.new("1", (21000, 20000)).save(big)                 # 420 megapixels, a few kB on disk
    with pytest.raises(Exception) as err:
        imaging.load_rgb(big)
    assert "너무 큽니다" in describe_error(err.value)


def test_a_montage_of_photos_one_pixel_wide_does_not_fail_in_the_resize():
    from fundusview import montage

    class Thin:
        rgb = np.full((800, 1, 3), 90, np.uint8)

    out = montage._coarse_vessels(Thin, 0.25)
    assert out.shape[0] >= 1 and out.shape[1] >= 1


# -- sharing ----------------------------------------------------------------------------------
def test_a_mistyped_server_address_is_no_address_not_an_error():
    from fundusview.share import normalize_url

    for bad in ("host:notaport", "http://host:99999", "http://[::1", "http://", ""):
        assert normalize_url(bad) == "", bad                 # (was: ValueError out of urlsplit)
    assert normalize_url("192.168.0.7") == normalize_url("http://192.168.0.7/")
    assert normalize_url("pc:8123/") == "http://pc:8123"


@pytest.mark.parametrize("body", [b"<html>router</html>", b"", b"null", b"[]", b'"x"', b"3"])
def test_an_answer_that_is_not_the_servers_is_a_share_error(body):
    from fundusview.share import ShareError, _reply

    with pytest.raises(ShareError):                          # (was: JSONDecodeError / AttributeError)
        _reply(body)
    assert _reply(b'{"rev": 3}') == {"rev": 3}


def test_the_share_page_escapes_every_value_it_writes():
    from fundusview import share_page

    text = Path(share_page.__file__).read_text(encoding="utf-8")
    assert 'r.fov_deg + "°"' not in text and "esc(String(r.fov_deg))" in text


# -- samples · DICOM --------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["[]", "null", '"x"', '{"diseases": [5, null, "", "녹내장"]}'])
def test_a_sample_index_of_the_wrong_shape_is_read_as_far_as_it_goes(tmp_path, text):
    from fundusview.samples import FOLDER, INDEX, SampleLibrary

    root = tmp_path / FOLDER
    root.mkdir()
    (root / INDEX).write_text(text, encoding="utf-8")
    lib = SampleLibrary(tmp_path)
    names = lib.diseases()                                   # (was: AttributeError / TypeError)
    assert names and all(isinstance(n, str) and n for n in names)
    assert all(lib.count(n) == 0 for n in names)


def test_dicom_dates_and_times_are_written_only_when_they_are_dates_and_times():
    pytest.importorskip("pydicom")
    from fundusview.dicomnet import _da, _tm

    assert _da("2026-03-05") == "20260305" and _da("20260305") == "20260305"
    for bad in ("날짜없음", "2024-3-5", "0000-00-00", "2026-13-01", "2026-02-30", "1970년", "", None):
        assert _da(bad) == "", bad                           # (was: "202435", "00000000", or the file not saved)
    assert _tm("10:22:01") == "102201" and _tm("1022") == "1022" and _tm("10:22:01.250") == "102201"
    for bad in ("오전 10시", "25:61:61", "10시", "", None):
        assert _tm(bad) == "", bad


def test_an_ae_title_that_is_not_ascii_is_a_dicom_error():
    pytest.importorskip("pynetdicom")
    from fundusview import dicomnet

    s = Settings(dicom_ae="한글", pacs_host="127.0.0.1", pacs_port=1, pacs_ae="PACS")
    with pytest.raises(dicomnet.DicomError):                 # (was: a bare ValueError)
        dicomnet._associate(s, dicomnet.pacs_node(s), [], 0.2)


def test_a_field_of_view_no_camera_has_is_left_to_the_profile(tmp_path):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    from fundusview.extract.dicom_meta import dicom_meta

    def fov_of(value):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.77.1.5.1"
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(tmp_path / "x.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.PatientID, ds.Modality = "1", "OP"
        ds.HorizontalFieldOfView = value
        ds.save_as(tmp_path / "x.dcm")
        return dicom_meta(tmp_path / "x.dcm").fov_deg

    assert fov_of(45.0) == 45.0 and fov_of(200.0) == 200.0
    for bad in (-45.0, 0.0, 720.0, 1e-30, float("inf")):     # (was: taken as the photo's angle)
        assert fov_of(bad) is None, bad


# -- what the photo's own windows write ---------------------------------------------------------
def test_the_folders_button_looks_for_devices_also_with_automatic_search_off(tmp_path):
    """설정 → [지금 장비 폴더 다시 찾기] did nothing with 자동으로 찾기 switched off."""
    from fundusview import autosetup

    cam = tmp_path / "cam"
    cam.mkdir()
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"), auto_detect=False)
    found = [(str(cam), "auto")]
    autosetup.apply(s, found)                                # start-up: the inbox, no device folder
    assert str(cam) not in [f.path for f in s.watch_folders]
    added = autosetup.apply(s, found, force=True)            # the button
    assert [f.path for f in added] == [str(cam)]


def test_an_eye_stated_in_the_info_window_is_the_users_not_a_guess(tmp_path):
    """정보 수정 wrote the eye but left it marked as estimated: the next search for the macula
    could turn it round again."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from fundusview.ui.dialogs import ImageDialog

    QApplication.instance() or QApplication([])
    db = Database(tmp_path / "f.db")
    iid = db.insert_image(file_path="a.jpg", sha256="1", laterality="OD",
                          meta_json=json.dumps({"sources": {"laterality": "fovea-estimate"}, "keep": 1}))
    dlg = ImageDialog(db, db.get_image(iid))
    dlg.eye.setCurrentIndex(dlg.eye.findData("OS"))
    dlg.apply()
    row = db.get_image(iid)
    meta = json.loads(row["meta_json"])
    assert row["laterality"] == "OS" and meta["sources"]["laterality"] == "manual" and meta["keep"] == 1
    dlg.deleteLater()
    dlg = ImageDialog(db, row)                               # nothing changed: nothing re-marked
    dlg.note.setText("메모")
    dlg.apply()
    assert json.loads(db.get_image(iid)["meta_json"]) == meta
    dlg.deleteLater()
    db.close()
