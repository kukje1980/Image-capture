"""Clinical identity and failure recovery when saving derived images."""
import hashlib
import datetime
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import numpy as np
import pytest
from PIL import Image

from fundusview import imaging
from fundusview.config import Settings
from fundusview.db import Database, SCHEMA
from fundusview.importer import Importer
from fundusview.models import ExtractedMeta, PatientAssign
from fundusview.profiles import get_profile


@pytest.fixture
def storage(tmp_path):
    settings = Settings(library_dir=str(tmp_path / "library"))
    db = Database(tmp_path / "library.sqlite")
    ref = db.upsert_patient(ExtractedMeta(patient_id="PATIENT-A"))
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (40, 60, 80)).save(source)
    iid = db.insert_image(patient_ref=ref, exam_date="2026-11-22", laterality="OD", modality="color",
                          file_path=str(source), original_path=str(source),
                          sha256=hashlib.sha256(source.read_bytes()).hexdigest(), meta_json={})
    yield Importer(db, settings), db, db.get_image(iid)
    db.close()


def pixels(value):
    return np.full((32, 32, 3), value, dtype=np.uint8)


def library_files(imp):
    return {p for p in imp.library.rglob("*") if p.is_file()}


def test_fast_edits_keep_both_files_and_actual_content_hash(storage, monkeypatch):
    class FrozenDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 22, 12, 34, 56)

    monkeypatch.setattr(datetime, "datetime", FrozenDateTime)
    imp, db, source = storage
    first = db.get_image(imp.add_derived(source, pixels(30)))
    before = Path(first["file_path"]).read_bytes()
    second = db.get_image(imp.add_derived(source, pixels(70)))
    assert first["file_path"] != second["file_path"]
    assert Path(first["file_path"]).read_bytes() == before
    for row in (first, second):
        assert row["content_sha256"] == hashlib.sha256(Path(row["file_path"]).read_bytes()).hexdigest()
        assert row["sha256"] != row["content_sha256"]
    assert len(library_files(imp)) == 4


@pytest.mark.parametrize("changed", ["patient_ref", "laterality", "exam_date", "modality"])
def test_same_pixels_have_separate_clinical_records(storage, changed):
    imp, db, source = storage
    first = imp.add_derived(source, pixels(60))
    other_patient = db.upsert_patient(ExtractedMeta(patient_id="PATIENT-B"))
    value = {"patient_ref": other_patient, "laterality": "OS", "exam_date": "2026-11-23", "modality": "montage"}[changed]
    second = imp.add_derived(source, pixels(60), **{changed: value})
    assert first != second
    assert db.get_image(second)[changed] == value
    assert db.get_image(first)["content_sha256"] == db.get_image(second)["content_sha256"]
    assert imp.add_derived(source, pixels(60), **{changed: value}) == second
    assert len(library_files(imp)) == 4


def test_saving_again_after_previous_derived_record_was_reassigned(storage):
    imp, db, source = storage
    first = imp.add_derived(source, pixels(60))
    other_patient = db.upsert_patient(ExtractedMeta(patient_id="PATIENT-B"))
    db.update_image(first, patient_ref=other_patient)
    second = imp.add_derived(source, pixels(60))
    assert second != first
    assert db.get_image(first)["patient_ref"] == other_patient
    assert db.get_image(second)["patient_ref"] == source["patient_ref"]
    assert imp.add_derived(source, pixels(60)) == second


def test_external_raw_import_does_not_choose_another_patients_derived_record(storage, tmp_path):
    imp, db, source = storage
    derived_id = imp.add_derived(source, pixels(160))
    exported = tmp_path / "exported-edit.png"
    exported.write_bytes(Path(db.get_image(derived_id)["file_path"]).read_bytes())
    result = imp.import_file(exported, wait=False, assign=PatientAssign("PATIENT-B"))
    assert result.status == "imported" and result.image_id != derived_id
    assert db.get_patient(result.patient_ref)["patient_id"] == "PATIENT-B"
    assert db.get_image(result.image_id)["sha256"] == db.get_image(derived_id)["content_sha256"]


def test_legacy_derived_content_still_deduplicates_in_the_same_context(storage):
    imp, db, source = storage
    first = imp.add_derived(source, pixels(60))
    digest = db.get_image(first)["content_sha256"]
    db.update_image(first, sha256=digest, content_sha256=None)
    assert imp.add_derived(source, pixels(60)) == first
    assert db.get_image(first)["sha256"] == digest  # no legacy row rewrite/backfill


@pytest.mark.parametrize("stage", ["thumbnail", "fsync", "publish", "insert", "log", "commit"])
def test_failed_save_rolls_back_only_its_own_files_and_record(storage, monkeypatch, stage):
    imp, db, source = storage
    saved = db.get_image(imp.add_derived(source, pixels(30)))
    before = {p: p.read_bytes() for p in library_files(imp)}
    count = db._one("SELECT COUNT(*) FROM images")[0]
    import fundusview.importer as module

    def fail(*args, **kwargs):
        raise OSError("injected write failure")

    if stage == "thumbnail":
        real = module._write_new_file
        monkeypatch.setattr(module, "_write_new_file", lambda directory, prefix, suffix, data:
                            fail() if suffix == ".jpg" else real(directory, prefix, suffix, data))
    elif stage in ("fsync", "publish"):
        monkeypatch.setattr(module.os, "fsync" if stage == "fsync" else "replace", fail)
    elif stage == "insert":
        monkeypatch.setattr(db, "insert_image", fail)
    elif stage == "log":
        monkeypatch.setattr(db, "log", fail)
    else:
        # A deferred FK error occurs during COMMIT, after insert_image has returned.
        db._con.execute("PRAGMA defer_foreign_keys=ON")
    with pytest.raises((OSError, sqlite3.IntegrityError)):
        imp.add_derived(source, pixels(90), **({"patient_ref": 999999} if stage == "commit" else {}))
    assert not db._con.in_transaction
    assert db._one("SELECT COUNT(*) FROM images")[0] == count
    assert {p: p.read_bytes() for p in library_files(imp)} == before
    assert db.get_image(saved["id"])["file_path"] == saved["file_path"]


def test_concurrent_identical_saves_leave_one_record_and_no_unused_files(storage, monkeypatch):
    imp, db, source = storage
    import fundusview.importer as module
    real = module._write_new_file
    both_started = Barrier(2)

    def write(directory, prefix, suffix, data):
        result = real(directory, prefix, suffix, data)
        if suffix == ".png":
            both_started.wait(timeout=10)
        return result

    monkeypatch.setattr(module, "_write_new_file", write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: imp.add_derived(source, pixels(100)), range(2)))
    assert ids[0] == ids[1]
    assert db._one("SELECT COUNT(*) FROM images")[0] == 2
    assert len(library_files(imp)) == 2


def test_opening_legacy_database_preserves_rows_and_raw_dedup(tmp_path):
    path = tmp_path / "old.sqlite"
    legacy_schema = "\n".join(line for line in SCHEMA.splitlines() if "content_sha256 TEXT" not in line)
    with sqlite3.connect(path) as con:
        con.executescript(legacy_schema)
        con.execute("INSERT INTO images(file_path,sha256,imported_at) VALUES ('old.png','legacy-hash','2026')")
    db = Database(path)
    try:
        old = db.image_by_sha("legacy-hash")
        assert old["file_path"] == "old.png" and old["content_sha256"] is None
        imp = Importer(db, Settings(library_dir=str(tmp_path / "library")))
        first = tmp_path / "raw.png"
        second = tmp_path / "raw-copy.png"
        Image.new("RGB", (32, 32), (80, 90, 100)).save(first)
        second.write_bytes(first.read_bytes())
        result = imp.import_file(first, wait=False)
        duplicate = imp.import_file(second, wait=False)
        assert result.status == "imported" and duplicate.status == "duplicate"
        assert duplicate.image_id == result.image_id
        assert db.get_image(result.image_id)["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    finally:
        db.close()


@pytest.mark.parametrize("known_eye,expected,source_name", [(None, "OS", "fovea-estimate"),
                                                          ("OD", "OD", "dicom")])
def test_fovea_can_correct_only_automatic_eye_guess(storage, monkeypatch, known_eye, expected, source_name):
    imp, db, row = storage
    path = Path(row["file_path"]).with_name("unknown-eye.png")
    Image.new("RGB", (32, 32), (100, 110, 120)).save(path)
    meta = ExtractedMeta(laterality=known_eye, sources={"laterality": "dicom"} if known_eye else {})
    monkeypatch.setattr(imp, "_extract", lambda *args: (meta, get_profile("generic")))
    monkeypatch.setattr(imaging, "detect_circle", lambda rgb: (16., 16., 15.))
    monkeypatch.setattr(imaging, "detect_disc", lambda *args, **kwargs: (10., 16., .9))
    monkeypatch.setattr(imaging, "laterality_from_disc", lambda *args: "OD")
    monkeypatch.setattr(imaging, "detect_fovea", lambda *args, **kwargs: (22., 16., .9, "OS"))
    result = imp.import_file(path, wait=False)
    assert result.status == "imported"
    stored = db.get_image(result.image_id)
    assert stored["laterality"] == expected
    assert json.loads(stored["meta_json"])["sources"]["laterality"] == source_name
