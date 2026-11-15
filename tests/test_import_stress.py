"""극한 테스트: the import under bad files, hostile names, many files at once and several
threads — it must never crash, never file a photo under a patient the files do not name, never
leave half an import behind, and stay quick."""
import io
import os
import random
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from fundusview.config import ACTION_MOVE, Settings, WatchFolder
from fundusview.db import Database
from fundusview.demo import synth_fundus, write_demo_dicom
from fundusview.extract import extract_metadata
from fundusview.extract.filename_meta import date_like, filename_meta, plausible_pid
from fundusview.extract.normalize import parse_key_values
from fundusview.importer import Importer
from fundusview.models import ExtractedMeta, PatientAssign
from fundusview.watcher import ImportService

_BASE = None


def fundus() -> Image.Image:
    global _BASE
    if _BASE is None:
        img = synth_fundus(eye="OD", fov_deg=45, fov_type="external", size=(240, 240), seed=3)
        _BASE = img if isinstance(img, Image.Image) else Image.fromarray(img)
    return _BASE.copy()


def jpeg_bytes(mark: int = 0) -> bytes:
    img = fundus()
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, 50, 14], fill=(mark % 251, (mark // 251) % 251, 90))
    d.text((4, 3), str(mark), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def encoded(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def png_header_only(width: int, height: int) -> bytes:
    """A PNG that only says how large it is — enough for the reader to refuse it."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0" * 64)) + chunk(b"IEND", b""))


@pytest.fixture()
def env(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.0, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(drop))])
    db = Database(tmp_path / "lib" / "fundus.db")
    yield s, db, drop
    db.close()


def library_files(s: Settings) -> set[str]:
    return {str(p) for p in s.library.rglob("*") if p.is_file() and "fundus.db" not in p.name}


def registered_files(db: Database) -> set[str]:
    rows = db._all("SELECT file_path, thumb_path, display_path FROM images")
    return {r[k] for r in rows for k in ("file_path", "thumb_path", "display_path") if r[k]}


# -- files that are not what they say ---------------------------------------------------
def test_broken_and_odd_files_never_crash_the_import(env):
    s, db, drop = env
    good = jpeg_bytes(1)
    dicom = write_demo_dicom(drop / "ok.dcm", small=True).read_bytes()
    broken = {                                   # none of these is a photo
        "zero.jpg": b"", "trunc_10.jpg": good[:10], "trunc_half.jpg": good[:len(good) // 2],
        "trunc_header.jpg": good[:400], "text.jpg": b"this is not an image\n" * 50,
        "random.jpg": os.urandom(5000), "random.png": os.urandom(5000), "random.tif": os.urandom(5000),
        "random.bmp": os.urandom(5000), "random.dcm": os.urandom(5000), "empty.dcm": b"",
        "dicm_only.dcm": b"\0" * 128 + b"DICM", "dicm_garbage.dcm": b"\0" * 128 + b"DICM" + os.urandom(3000),
        "noext_dicm": b"\0" * 128 + b"DICM" + os.urandom(500), "jpeg_named.dcm": good,
        "html.jpg": b"<html><body>404 Not Found</body></html>", "nul.jpg": b"\0" * 100000,
        "soi_only.jpg": b"\xff\xd8\xff\xe0" + b"\0" * 20, "trunc.dcm": dicom[:len(dicom) // 2],
        "trunc_header.dcm": dicom[:300],
        "bomb.png": png_header_only(30000, 30000),                           # says it is 900 megapixels
    }
    odd = {                                      # … and these are, whatever they look like
        "png_named.jpg": encoded(fundus(), "PNG"), "jpeg_named.png": jpeg_bytes(2),
        "gif_named.jpg": encoded(fundus(), "GIF"), "1x1.png": encoded(Image.new("RGB", (1, 1)), "PNG"),
        "thin.png": encoded(Image.new("RGB", (5000, 3)), "PNG"),
        "black.jpg": encoded(Image.new("RGB", (300, 300)), "JPEG"),
        "white.jpg": encoded(Image.new("RGB", (300, 300), (255, 255, 255)), "JPEG"),
        "cmyk.jpg": encoded(Image.new("CMYK", (300, 300)), "JPEG"),
        "palette.png": encoded(Image.new("P", (300, 300)), "PNG"),
        "transparent.png": encoded(Image.new("RGBA", (300, 300), (200, 80, 40, 0)), "PNG"),
        "sixteen_bit.tif": encoded(Image.new("I;16", (300, 300)), "TIFF"),
        "bilevel.tif": encoded(Image.new("1", (300, 300)), "TIFF"),
        "float.tif": encoded(Image.new("F", (300, 300)), "TIFF"),
        "pages.tif": encoded(fundus(), "TIFF", save_all=True, append_images=[fundus(), fundus()]),
    }
    for name, data in {**broken, **odd}.items():
        (drop / name).write_bytes(data)
    imp = Importer(db, s)
    status = {}
    for p in sorted(drop.iterdir()):
        preview = imp.preview(p, s.watch_folders[0])              # must not raise
        result = imp.import_file(p, s.watch_folders[0], wait=False)
        status[p.name] = result.status
        assert preview.status in ("new", "error") and preview.meta is not None
        if result.status == "error":
            assert result.message and db.seen(str(p))["status"] == "error"
    assert {n for n in broken if status[n] not in ("error", "skipped")} == set()
    assert {n for n in odd if status[n] != "imported"} == set()
    assert status["ok.dcm"] == "imported"
    # nothing half-imported: every file in the library belongs to a registered image
    assert library_files(s) == registered_files(db)
    assert db.count_patients() == 1                               # the DICOM's — no patient out of garbage
    said = [r["message"] for r in db.recent_logs(500) if r["level"] == "error"]
    assert any("사진 파일이 아니거나 손상" in m for m in said) and any("너무 큽니다" in m for m in said)
    assert any("끝까지 저장되지 않은" in m for m in said) and any("DICOM 영상을 읽을 수 없습니다" in m for m in said)


@pytest.mark.parametrize("name,pid", [
    (unicodedata.normalize("NFD", "홍길동_12345_OD.jpg"), "12345"),     # a name as macOS writes it
    ("가" * 70 + "_12345.jpg", None), ("a" * 200 + ".jpg", None),
    ("12345_홍길동_20240305_OD .jpg", "12345"), (" 12345_홍길동.jpg", "12345"), ("12345_홍길동..jpg", "12345"),
    ("CON_12345_홍길동.jpg", "12345"), ("12345_홍길동_20240305_OD.JPG", "12345"), ("12345_ㅎㄱㄷ.jpg", None),
    ("emoji😀_12345.jpg", None), ("semi;colon=1&x.jpg", None), ("quote'\"x.jpg", None),
    ("%20_12345_김철수.jpg", "12345"), ("12345_홍길동\t탭.jpg", "12345"), ("x....jpg", None),
    ("$(rm -rf)_`x`.jpg", None), ("-rf.jpg", None), ("12345_홍길동; DROP TABLE patients;--.jpg", "12345"),
])
def test_hostile_file_names(env, name, pid):
    s, db, drop = env
    p = drop / name
    try:
        p.write_bytes(jpeg_bytes(7))
    except OSError:
        pytest.skip("this file system does not take the name")
    r = Importer(db, s).import_file(p, s.watch_folders[0], wait=False)
    assert r.status == "imported"
    row = db.get_image(r.image_id)
    stored = Path(row["file_path"])
    assert stored.exists() and stored.suffix.lower() == ".jpg" and len(stored.name) <= 80
    patient = db.get_patient(row["patient_ref"]) if row["patient_ref"] else None
    assert (patient["patient_id"] if patient else None) == pid
    assert db.count_patients() == (1 if pid else 0)               # the table is still there


def test_a_patient_id_that_is_not_a_folder_name(env):
    """Ids from DICOM / device data are free text: slashes, dots, a name Windows reserves."""
    s, db, drop = env
    imp = Importer(db, s)
    for i, pid in enumerate(["../../etc", "A/B\\C", "NUL", "..", "12:34", "x" * 300, " 7 "]):
        p = drop / f"IMG_{i}.jpg"
        p.write_bytes(jpeg_bytes(100 + i))
        r = imp.import_file(p, wait=False, assign=PatientAssign(pid, "홍길동"))
        stored = Path(db.get_image(r.image_id)["file_path"]).resolve()
        assert r.status == "imported" and stored.is_relative_to((s.library / "images").resolve())
        assert stored.parent.parent.parent == (s.library / "images").resolve()    # images/<id>/<date>/file
    assert db.count_patients() == 7 and library_files(s) == registered_files(db)


# -- names made at random ----------------------------------------------------------------
WORDS = ["홍길동", "김철수", "이영희", "박", "사진", "안저", "우안", "좌안", "OD", "OS", "R", "L", "IMG", "DSC", "scan",
         "copy", "새", "파일", "COLOR", "FAF", "20240305", "2024-03-05", "240305", "101500", "1015", "19800101",
         "800101", "12345", "A777", "0001", "1", "23", "P-99", "D0001234", "20260115001", "1709600000000", "(2)",
         "final", "녹내장", "KakaoTalk", "Screenshot", "WIN", "", "😀", "ㅎㄱㄷ", "Hong Gildong", "vk000005"]
SEPS = ["_", "-", " ", ".", "(", ")", "", "__", " - ", ","]


def test_random_names_never_raise_and_never_take_a_date_for_a_patient():
    rng = random.Random(20260301)
    for _ in range(4000):
        n = rng.randint(1, 6)
        stem = "".join(rng.choice(WORDS) + rng.choice(SEPS) for _ in range(n))
        folder = "".join(rng.choice(WORDS) + rng.choice(SEPS) for _ in range(rng.randint(1, 3))) or "x"
        path = Path("/root") / folder / (stem + ".jpg")
        m = filename_meta(path, watch_root=Path("/root"))         # must not raise
        if m.patient_id is not None:
            pid = m.patient_id
            assert any(c.isdigit() for c in pid) and plausible_pid(pid), (stem, folder, pid)
            assert not (len(pid) == 8 and date_like(pid)), (stem, folder, pid)
            assert pid not in ("1709600000000", "1"), (stem, folder, pid)
        if m.name is not None:
            assert m.name not in ("사진", "안저", "우안", "좌안", "파일", "녹내장"), (stem, folder, m.name)
        for value in (m.exam_date, m.birth_date):
            assert value is None or len(value) == 10


def test_random_text_in_a_picture_never_raises_and_rarely_names_a_patient():
    rng = random.Random(7)
    keys = ["id", "name", "ID", "Name", "date", "type", "comment", "eye", "sex", "x", "url", "PatientID", "환자번호"]
    chars = "abc XYZ 012 가나다 :=;&/\\\n\t\"'<>{}[]|%@#"
    named = 0
    for i in range(3000):
        text = "".join(rng.choice([rng.choice(keys), rng.choice(chars) * rng.randint(1, 4)]) for _ in range(12))
        m = ExtractedMeta()
        parse_key_values(text, m, "t", strict=True)               # must not raise
        if m.patient_id:
            assert len(m.patient_id) <= 32 and not any(c in m.patient_id for c in " :=/\\<>{}"), text
            named += 1
        parse_key_values(os.urandom(64).decode("latin-1"), ExtractedMeta(), "t", strict=True)
    assert named < 900                                            # an id needs an unmistakable key or a record


def test_random_bytes_in_every_text_container(tmp_path):
    """EXIF, JPEG comment, PNG text and XMP filled with noise: read without an exception, no patient."""
    from PIL import PngImagePlugin
    rng = random.Random(11)
    for i in range(40):
        noise = bytes(rng.randrange(256) for _ in range(rng.randint(1, 400)))
        exif = Image.Exif()
        exif[270] = noise.decode("latin-1")
        exif[0x9C9C] = noise + (b"\0" if len(noise) % 2 else b"")
        p = tmp_path / f"n{i}.jpg"
        fundus().save(p, comment=noise, exif=exif, xmp=b"<?xpacket id='W5M0'?><x a:id=\"" + noise[:50] + b"\">")
        m, _ = extract_metadata(p)
        assert m.patient_id is None or len(m.patient_id) <= 32
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", noise.decode("latin-1"))
        info.add_text("Description", noise.hex())
        q = tmp_path / f"n{i}.png"
        fundus().save(q, pnginfo=info)
        extract_metadata(q)


# -- many files, several threads -----------------------------------------------------------
def test_bulk_import_while_the_window_reads_the_database(env):
    """300 files of 30 patients (a tenth of them the same photo twice) put in the queue from four
    threads while two more read the database as the window does: every photo once, with its
    patient; no error; no reader ever sees half an import."""
    s, db, drop = env
    patients, per, unique = 30, 9, 270
    for i in range(unique):
        pid = 10000 + i % patients
        folder = drop / f"{pid}_김환{i % patients:02d}"[:40]
        folder.mkdir(exist_ok=True)
        data = jpeg_bytes(i)
        (folder / f"IMG_{i:04d}.jpg").write_bytes(data)
        if i % 9 == 0:                                            # the same photo under another name
            (folder / f"copy_{i:04d}.jpg").write_bytes(data)
    files = sorted(str(p) for p in drop.rglob("*.jpg"))
    assert len(files) == 300
    results, statuses = [], []
    svc = ImportService(db, s, on_result=results.append, on_status=statuses.append)
    stop, seen_bad = threading.Event(), []

    def reader():
        while not stop.is_set():
            for row in db.list_patients():
                imgs = db.images_for_patient(row["id"])
                if len(imgs) != row["n_images"] and not stop.is_set():
                    again = db.list_patients(row["patient_id"])   # the count moved on between the two reads?
                    if again and len(db.images_for_patient(row["id"])) < again[0]["n_images"]:
                        seen_bad.append(row["patient_id"])
                for im in imgs[:3]:
                    if not (im["file_path"] and im["thumb_path"] and im["sha256"]):
                        seen_bad.append(im["id"])
            db.count_unassigned()
            db.recent_logs(50)

    readers = [threading.Thread(target=reader, daemon=True) for _ in range(2)]
    for t in readers:
        t.start()
    t0 = time.perf_counter()
    feeders = [threading.Thread(target=lambda part=files[k::4]: [svc.enqueue(f, s.watch_folders[0]) for f in part])
               for k in range(4)]
    for t in feeders:
        t.start()
    for t in feeders:
        t.join()
    for f in files[:50]:                                          # … and some of them once more
        svc.enqueue(f, s.watch_folders[0])
    deadline = time.time() + 180
    while (len(results) < len(files) or svc.queued) and time.time() < deadline:
        time.sleep(0.02)
    took = time.perf_counter() - t0
    stop.set()
    for t in readers:
        t.join(timeout=10)
    svc.shutdown()
    count = Counter(r.status for r in results)
    assert count == {"imported": unique, "duplicate": 30}, (count, [r.message for r in results if r.status == "error"][:3])
    assert not seen_bad
    assert db.count_patients() == patients and db.count_unassigned() == 0
    assert all(p["n_images"] == per for p in db.list_patients())
    assert db._one("SELECT COUNT(*), COUNT(DISTINCT sha256) FROM images")[:] == (unique, unique)
    assert library_files(s) == registered_files(db)
    assert statuses[-1] == "대기 중"
    assert took < 150, f"{took:.0f} s for {len(files)} files"
    # everything is remembered: a full rescan of the folder finds nothing to do, at once
    svc2 = ImportService(db, s)
    t0 = time.perf_counter()
    assert svc2.scan_all(full=True) == 0
    assert time.perf_counter() - t0 < 2.0
    svc2.shutdown()


def test_a_rescan_of_thousands_of_known_files_is_quick(env):
    s, db, drop = env
    with db.batch():
        for i in range(6000):
            sub = drop / f"d{i % 60:02d}"
            sub.mkdir(exist_ok=True)
            p = sub / f"IMG_{i:05d}.jpg"
            p.write_bytes(b"x")
            st = p.stat()
            db.mark_seen(os.path.normpath(str(p)), st.st_size, st.st_mtime, "imported", i)
    svc = ImportService(db, s)
    try:
        t0 = time.perf_counter()
        assert svc.scan_all(full=True) == 0
        full = time.perf_counter() - t0
        t0 = time.perf_counter()
        assert svc.scan_all() == 0
        quick = time.perf_counter() - t0
        assert full < 3.0 and quick < 1.0, (full, quick)
        (drop / "d07" / "new.jpg").write_bytes(jpeg_bytes(1))     # one new file among them is found
        assert svc.scan_all(full=True) == 1
    finally:
        svc.shutdown()


def test_a_large_patient_list_stays_quick(env):
    s, db, drop = env
    with db.batch():
        for i in range(5000):
            ref = db.upsert_patient(ExtractedMeta(patient_id=f"{100000 + i}", name=f"김{i:04d}", birth_date="1970-01-01"))
            for k in range(4):
                db.insert_image(patient_ref=ref, exam_date=f"2026-0{1 + k}-15", laterality="OD" if k % 2 else "OS",
                                file_path=f"/x/{i}_{k}.jpg", sha256=f"{i}-{k}")
    t0 = time.perf_counter()
    rows = db.list_patients()
    listed = time.perf_counter() - t0
    t0 = time.perf_counter()
    found = db.list_patients("김12")
    searched = time.perf_counter() - t0
    assert len(rows) == 5000 and rows[0]["n_images"] == 4 and len(found) == 100
    assert listed < 1.5 and searched < 1.0, (listed, searched)
    t0 = time.perf_counter()
    assert len(db.patients_named("김 0042")) == 1 and db.find_patient("104999") is not None
    assert time.perf_counter() - t0 < 0.5


def test_a_batch_is_one_transaction(env):
    s, db, drop = env
    with pytest.raises(RuntimeError):
        with db.batch():
            db.upsert_patient(ExtractedMeta(patient_id="1", name="가"))
            db.log("info", "inside")
            raise RuntimeError("stop")
    assert db.count_patients() == 0 and db.recent_logs() == []
    with db.batch():
        db.upsert_patient(ExtractedMeta(patient_id="1", name="가"))
        with db.batch():                                          # nested: still one commit, at the end
            db.upsert_patient(ExtractedMeta(patient_id="2", name="나"))
    assert db.count_patients() == 2
    other = Database(db.path)                                     # another connection sees it: committed
    assert other.count_patients() == 2
    other.close()


# -- files that change under the import ------------------------------------------------------
def test_a_file_still_being_written_waits(env):
    s, db, drop = env
    s.stable_seconds = 0.3
    data = jpeg_bytes(5)
    p = drop / "12345_홍길동_20240305_OD.jpg"
    results = []
    svc = ImportService(db, s, on_result=results.append)
    try:
        with open(p, "wb") as f:
            for k in range(0, len(data), max(1, len(data) // 6)):  # written in pieces, slower than the check
                f.write(data[k:k + max(1, len(data) // 6)])
                f.flush()
                svc.enqueue(p, s.watch_folders[0])                 # a change event for every piece
                time.sleep(0.12)
        deadline = time.time() + 30
        while not results and time.time() < deadline:
            time.sleep(0.02)
        assert [r.status for r in results] == ["imported"]
        assert Path(db.get_image(results[0].image_id)["file_path"]).read_bytes() == data   # the whole file
    finally:
        svc.shutdown()


def test_files_that_vanish_or_are_emptied_before_their_turn(env):
    s, db, drop = env
    results = []
    svc = ImportService(db, s, on_result=results.append)
    try:
        files = []
        for i in range(30):
            p = drop / f"1234{i % 3}_홍길동_20240305_OD_{i}.jpg"
            p.write_bytes(jpeg_bytes(200 + i))
            files.append(p)
        for p in files:
            svc.enqueue(p, s.watch_folders[0], force=True)
        for p in files[1::3]:
            try:
                p.unlink()                                         # taken away by the capture software
            except OSError:
                pass
        for p in files[2::3]:
            try:
                p.write_bytes(b"")                                 # … or rewritten from scratch
            except OSError:
                pass
        deadline = time.time() + 60
        while (svc.queued or len(results) < 30) and time.time() < deadline:
            time.sleep(0.02)
        assert len(results) == 30 and svc._worker.is_alive()
        assert {r.status for r in results} <= {"imported", "skipped", "pending", "error", "duplicate"}
        assert sum(r.status == "imported" for r in results) >= 10
        # an emptied file is left alone until it changes — it does not hold the queue up again
        assert svc.scan_folder(s.watch_folders[0], full=True) == 0
        assert library_files(s) == registered_files(db)
        extra = drop / "99999_김철수_20240305_OS.jpg"              # the worker still works
        extra.write_bytes(jpeg_bytes(999))
        svc.enqueue(extra, s.watch_folders[0])
        deadline = time.time() + 30
        while not any(r.path.endswith("OS.jpg") for r in results) and time.time() < deadline:
            time.sleep(0.02)
        assert db.find_patient("99999") is not None
    finally:
        svc.shutdown()


def test_moving_many_files_out_of_a_drop_folder(env):
    s, db, drop = env
    folder = WatchFolder(path=str(drop), action=ACTION_MOVE)
    s.watch_folders = [folder]
    for i in range(60):
        (drop / f"2000{i % 5}_이영희_20240305_OD_{i}.jpg").write_bytes(jpeg_bytes(300 + i))
    (drop / "broken.jpg").write_bytes(b"\xff\xd8 broken")
    results = []
    svc = ImportService(db, s, on_result=results.append)
    try:
        assert svc.scan_folder(folder, full=True) == 61
        deadline = time.time() + 120
        while (svc.queued or len(results) < 61) and time.time() < deadline:
            time.sleep(0.02)
        assert Counter(r.status for r in results) == {"imported": 60, "error": 1}
        assert sorted(p.name for p in drop.iterdir()) == ["broken.jpg"]      # only the bad file stays behind
        assert library_files(s) == registered_files(db) and db.count_patients() == 5
        assert svc.scan_folder(folder, full=True) == 0
    finally:
        svc.shutdown()


# -- the 확인 창 with a whole archive ----------------------------------------------------------
def test_review_dialog_with_thousands_of_files(env):
    from PySide6.QtWidgets import QApplication
    from fundusview.ui import import_dialog as d

    app = QApplication.instance() or QApplication([])
    s, db, drop = env
    data = jpeg_bytes(1)
    for i in range(2400):
        folder = drop / "archive" / (f"{30000 + i % 300}_박환{i % 300:03d}" if i % 300 < 280 else f"기타{i % 300}")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"IMG_{i:05d}.jpg").write_bytes(data + bytes(str(i), "ascii"))   # its own content
    svc = ImportService(db, s)
    t0 = time.perf_counter()
    dlg = d.ImportReviewDialog(svc, db, [str(drop / "archive")])
    try:
        deadline = time.time() + 120
        while not dlg.ready and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)
        took = time.perf_counter() - t0
        assert dlg.ready and took < 60, f"{took:.0f} s"
        assert len(dlg.groups) == 300 and dlg.table.rowCount() == 300
        assert sum(len(g.items) for g in dlg.groups) == 2400
        assert sum(1 for g in dlg.groups if g.patient_id) == 280
        assert "사진 2400장 — 환자 280명" in dlg.lbl_head.text() and "환자 정보 없음 160장" in dlg.lbl_head.text()
        t0 = time.perf_counter()
        for r, g in enumerate(dlg.groups):                         # naming every open row stays quick
            if not g.patient_id:
                dlg.set_patient(r, f"9{r:04d}")
        assert time.perf_counter() - t0 < 5.0 and "환자 300명" in dlg.lbl_head.text()
        assert len(dlg.result_items()) == 2400
    finally:
        dlg.reject()
        svc.shutdown()


def test_review_dialog_closed_while_reading(env):
    """Cancel while the files are still being read: the reading stops, nothing is imported."""
    from PySide6.QtWidgets import QApplication
    from fundusview.ui import import_dialog as d

    app = QApplication.instance() or QApplication([])
    s, db, drop = env
    data = jpeg_bytes(1)
    for i in range(1500):
        (drop / f"IMG_{i:05d}.jpg").write_bytes(data + bytes(str(i), "ascii"))
    svc = ImportService(db, s)
    try:
        dlg = d.ImportReviewDialog(svc, db, [str(drop)])
        app.processEvents()
        dlg.reject()
        assert not dlg._thread.is_alive()
        app.processEvents()
        assert db.count_patients() == 0 and db.count_unassigned() == 0 and svc.queued == 0
    finally:
        svc.shutdown()


def test_the_patient_lists_fill_quickly_with_thousands_of_patients(tmp_path):
    """The patient table sizes its columns to its contents; measured after every cell that took
    ten seconds for 300 patients. Now 3000 patients are listed (and sorted) in well under that."""
    from PySide6.QtWidgets import QApplication
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.0, rescan_seconds=0, watch_on_startup=False,
                 auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    with db.batch():
        for i in range(3000):
            ref = db.upsert_patient(ExtractedMeta(patient_id=f"{100000 + i}", name=f"김{i:04d}", sex="F"))
            db.insert_image(patient_ref=ref, exam_date="2026-03-01", file_path=f"/x/{i}.jpg", sha256=str(i))
    w = MainWindow(s, db)
    try:
        w.show()
        app.processEvents()
        t0 = time.perf_counter()
        w.refresh_patients()
        app.processEvents()
        took = time.perf_counter() - t0
        pl = w.patient_list
        assert pl.table.rowCount() == 3000 and len(pl.refs()) == 3000
        assert took < 5.0, f"{took:.1f} s"
        assert pl.table.columnWidth(0) > 40 and pl.table.columnWidth(1) > 40   # still sized to fit
        assert pl.table.item(0, 0).text() == "100000" and pl.table.item(2999, 0).text() == "102999"
        t0 = time.perf_counter()
        pl.sort_by(1, ascending=False)
        assert pl.table.item(0, 1).text() == "김2999" and time.perf_counter() - t0 < 5.0
        pl.f_name.setText("김12")
        t0 = time.perf_counter()
        pl.refresh()
        assert pl.table.rowCount() == 100 and time.perf_counter() - t0 < 2.0
    finally:
        w.service.shutdown()
        w.close()
