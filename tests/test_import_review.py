"""사진 가져오기: the patient data read from photos picked by hand, the preview, the patient the
user names for photos that do not say, and the 확인 창 (ImportReviewDialog)."""
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, PngImagePlugin

from fundusview.config import ACTION_MOVE, Settings, WatchFolder
from fundusview.db import Database
from fundusview.demo import synth_fundus
from fundusview.extract import extract_metadata
from fundusview.extract.filename_meta import filename_meta, name_id_pair
from fundusview.extract.normalize import norm_date, parse_key_values
from fundusview.importer import Importer, apply_assign, safe_component
from fundusview.models import ExtractedMeta, PatientAssign
from fundusview.watcher import ImportService

_FUNDUS = None


def photo(path: Path, mark: int = 0, **save) -> Path:
    """A small fundus photo at ``path``; ``mark`` makes its content (and SHA) its own."""
    global _FUNDUS
    if _FUNDUS is None:
        img = synth_fundus(eye="OD", fov_deg=45, fov_type="external", size=(260, 260), seed=3)
        _FUNDUS = img if isinstance(img, Image.Image) else Image.fromarray(img)
    img = _FUNDUS.copy()
    for x in range(48):
        img.putpixel((x, 3), ((mark * 37) % 256, (mark // 7) % 256, 200))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, **({"quality": 95} if path.suffix.lower() in (".jpg", ".jpeg") else {}), **save)
    return path


@pytest.fixture()
def lib(tmp_path):
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.0, rescan_seconds=0)
    db = Database(tmp_path / "lib" / "fundus.db")
    yield s, db, tmp_path
    db.close()


# -- what is never a patient ---------------------------------------------------------
XMP = b'''<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
 xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmp:CreatorTool="Adobe Photoshop 25.9 (Windows)" xmpMM:InstanceID="xmp.iid:aa" xmpMM:DocumentID="xmp.did:bb">
 <xmpMM:History><rdf:Seq><rdf:li stEvt:action="created" stEvt:instanceID="xmp.iid:cc"/></rdf:Seq></xmpMM:History>
 <dc:title><rdf:Alt><rdf:li xml:lang="x-default">Sunset</rdf:li></rdf:Alt></dc:title>
 <dc:description><rdf:Alt><rdf:li xml:lang="x-default">%s</rdf:li></rdf:Alt></dc:description>
</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'''


def test_the_xmp_packet_id_is_not_a_patient(tmp_path):
    """Every file Photoshop, a phone or a camera writes carries ``<?xpacket … id="W5M0…"?>``."""
    p = photo(tmp_path / "IMG_0001.jpg", xmp=XMP % b"Note: taken at home; Type: landscape")
    m, _ = extract_metadata(p)
    assert (m.patient_id, m.name) == (None, None)


def test_a_patient_typed_into_the_xmp_description_is_read(tmp_path):
    p = photo(tmp_path / "IMG_0002.jpg", xmp=XMP % "PatientID=778899; Name: 홍길동; DOB: 1970-01-02".encode())
    m, _ = extract_metadata(p)
    assert (m.patient_id, m.name, m.birth_date, m.sources["patient_id"]) == ("778899", "홍길동", "1970-01-02", "xmp")


@pytest.mark.parametrize("comment", [
    "Created with GIMP", "File source: https://example.com/id=5&name=x, date: today", "LEAD Technologies Inc. V1.01",
    "ID: 7", "Name: Sunset", "id=abc def ghi jkl", "Screenshot ID: 99 Name: test",
])
def test_text_in_a_picture_that_is_not_about_a_patient(tmp_path, comment):
    m, _ = extract_metadata(photo(tmp_path / "a.jpg", comment=comment.encode()))
    assert (m.patient_id, m.name) == (None, None)


@pytest.mark.parametrize("comment,expected", [
    ("PatientID=12345; Name: 홍길동", ("12345", "홍길동")),       # an unmistakable key
    ("환자번호: 12345", ("12345", None)),
    ("ID: 12345\nName: 홍길동\nSex: M", ("12345", "홍길동")),     # common words, but a patient record
    ("id=12345; birth=1970-01-02", ("12345", None)),
])
def test_text_in_a_picture_that_is_a_patient_record(tmp_path, comment, expected):
    m, _ = extract_metadata(photo(tmp_path / "a.jpg", comment=comment.encode()))
    assert (m.patient_id, m.name) == expected


def test_png_text_of_a_screenshot(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "Adobe ImageReady")
    info.add_text("Comment", "Type: screenshot\nDate: 2024/05/01\nID: 7")
    m, _ = extract_metadata(photo(tmp_path / "shot.png", pnginfo=info))
    assert m.patient_id is None and m.exam_date == "2024-05-01"


@pytest.mark.parametrize("name", [
    "20240305_101500.jpg",                      # a phone: date_time — the time is not a patient
    "IMG_20240305_101500.jpg", "KakaoTalk_20240305_101500123.jpg", "KakaoTalk_Photo_2024-03-05-10-15-00.jpeg",
    "Screenshot_20240305-101500_Gallery.jpg", "WIN_20240305_10_15_00_Pro.jpg", "PXL_20240305_101500123.jpg",
    "IMG-20240305-WA0001.jpg", "Resized_20240305_101500.jpeg", "FB_IMG_1709600000000.jpg", "1709600000000.jpg",
    "DSC01234.JPG", "scan0001.jpg", "image (3).jpg", "1.jpg", "12345.jpg", "12345_OD.jpg", "temp_12345.jpg",
    "20240305.jpg", "2024-03-05.jpg", "새 파일.jpg", "20240305_안저.jpg", "20240305_사진.jpg", "사진_20240305.jpg",
    "홍길동_19800101.jpg",                       # a birth date, not a chart number
    "홍길동_800101_OD.jpg", "홍길동_20240305_1015.jpg", "홍길동-od-color-20260310-101530-123.jpg",
    "홍길동_12345_67890.jpg",                    # two numbers: which one is not guessed
    "홍길동_김철수_12345.jpg",                    # two names
])
def test_names_that_do_not_name_a_patient(name):
    assert filename_meta(Path(name)).patient_id is None


def test_a_word_is_not_a_name():
    for name in ("새 파일.jpg", "우안 사진.jpg", "녹내장_검사.jpg", "안저사진 OD.jpg"):
        assert filename_meta(Path(name)).name is None, name
    assert filename_meta(Path("김영상 OD.jpg")).name == "김영상"        # … but 영상 can be in a name
    assert filename_meta(Path("정상훈_OS.jpg")).name == "정상훈"


# -- what is read ----------------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("홍길동_12345.jpg", ("12345", "홍길동", None, None)),
    ("홍길동(12345).jpg", ("12345", "홍길동", None, None)),
    ("홍길동12345.jpg", ("12345", "홍길동", None, None)),
    ("홍길동 12345 OS.jpg", ("12345", "홍길동", None, "OS")),
    ("12345(홍길동).jpg", ("12345", "홍길동", None, None)),
    ("12345-홍길동-OD.jpg", ("12345", "홍길동", None, "OD")),
    ("OD_12345_홍길동.jpg", ("12345", "홍길동", None, "OD")),
    ("우안_홍길동_12345.jpg", ("12345", "홍길동", None, "OD")),
    ("12345_홍길동_우안.jpg", ("12345", "홍길동", None, "OD")),
    ("copy of 12345_홍길동.jpg", ("12345", "홍길동", None, None)),
    ("12345_홍길동 - 복사본.jpg", ("12345", "홍길동", None, None)),
    ("12345_홍길동 (2).jpg", ("12345", "홍길동", None, None)),
    ("2024-03-05 홍길동 12345.jpg", ("12345", "홍길동", "2024-03-05", None)),
    ("12345_홍길동_2024-03-05_OD.jpg", ("12345", "홍길동", "2024-03-05", "OD")),
    ("12345_홍길동_2024.03.05_OS.jpg", ("12345", "홍길동", "2024-03-05", "OS")),
    ("홍길동_A12345_20240305_OD.jpg", ("A12345", "홍길동", "2024-03-05", "OD")),
    ("20240305_101500_12345_홍길동_OD.jpg", ("12345", "홍길동", "2024-03-05", "OD")),
    ("12345_Hong Gildong_20240305_L.jpg", ("12345", "Hong Gildong", "2024-03-05", "OS")),
])
def test_names_that_name_a_patient(name, expected):
    m = filename_meta(Path(name))
    assert (m.patient_id, m.name, m.exam_date, m.laterality) == expected


def test_name_id_pair():
    assert name_id_pair("홍길동_12345") == ("12345", "홍길동")
    assert name_id_pair("12345 사진") is None and name_id_pair("홍길동") is None
    assert name_id_pair("홍길동_20240305_12345") == ("12345", "홍길동")
    assert name_id_pair("홍길동_20240305_101500") is None       # date and time


@pytest.mark.parametrize("folder,expected", [
    ("12345_홍길동", ("12345", "홍길동")), ("12345 홍길동", ("12345", "홍길동")), ("홍길동_12345", ("12345", "홍길동")),
    ("홍길동(12345)", ("12345", "홍길동")), ("홍길동 12345", ("12345", "홍길동")),
    ("12345_홍길동_녹내장", ("12345", "홍길동")), ("P-99 홍길동", ("P-99", "홍길동")),
    ("2026 사진", (None, None)), ("2026-03 안저", (None, None)), ("2026 Photos", (None, None)),
    ("D850_backup", (None, None)), ("PC1_data", (None, None)), ("Room2_사진", (None, None)),
    ("A7M3_사진", (None, None)), ("iPhone14 backup", (None, None)), ("새 폴더 (2)", (None, None)),
    ("12345", (None, None)), ("20260301", (None, None)), ("USB 2.0 Drive", (None, None)),
])
def test_folder_names(tmp_path, folder, expected):
    m = filename_meta(tmp_path / folder / "IMG_0001.jpg", watch_root=tmp_path)
    assert (m.patient_id, m.name) == expected


@pytest.mark.parametrize("text,expected", [
    ("2024년 3월 5일", "2024-03-05"), ("24.03.05", "2024-03-05"), ("80-01-01", "1980-01-01"),
    ("2024.3.5", "2024-03-05"), ("20240305101500", "2024-03-05"), ("2024-13-45", None), ("March 5", None),
])
def test_more_date_spellings(text, expected):
    assert norm_date(text) == expected


def test_strict_free_text_keeps_exam_fields():
    m = ExtractedMeta()
    parse_key_values("ID: 7\nEye: OS\nDate: 2024-03-05", m, "t", strict=True)
    assert (m.patient_id, m.laterality, m.exam_date) == (None, "OS", "2024-03-05")


# -- photos picked by hand: the folders above them --------------------------------------
def test_a_picked_file_is_read_with_its_folder_names(lib):
    s, db, tmp = lib
    p = photo(tmp / "usb" / "12345_홍길동" / "2026-03-01" / "IMG_0001.jpg", 1)
    r = Importer(db, s).import_file(p, wait=False)             # no watched folder: picked by hand
    pat = db.find_patient("12345")
    assert r.status == "imported" and pat["name"] == "홍길동"
    row = db.get_image(r.image_id)
    assert row["exam_date"] == "2026-03-01" and row["patient_ref"] == pat["id"]


def test_a_picked_folder_is_read_with_its_own_name(lib):
    s, db, tmp = lib
    folder = tmp / "usb" / "홍길동(12345)"
    for i in range(3):
        photo(folder / f"IMG_000{i}.jpg", 10 + i)
    svc = ImportService(db, s)
    try:
        items = svc.preview_paths([str(folder)])
        assert [(it.status, it.meta.patient_id, it.meta.name, it.meta.sources["patient_id"]) for it in items] == \
            [("new", "12345", "홍길동", "folder")] * 3
        assert db.count_patients() == 0 and not (tmp / "lib" / "images").exists()   # a preview stores nothing
    finally:
        svc.shutdown()


def test_folders_far_above_a_picked_file_are_not_read(lib):
    s, db, tmp = lib
    p = photo(tmp / "12345_홍길동" / "a" / "b" / "IMG_0001.jpg", 2)
    assert Importer(db, s).preview(p).meta.patient_id is None


# -- preview / the patient the user names ----------------------------------------------
def test_preview_says_what_the_import_reads(lib):
    s, db, tmp = lib
    imp = Importer(db, s)
    p = photo(tmp / "12345_홍길동_20240305_OD.jpg", 3)
    pv = imp.preview(p)
    assert (pv.status, pv.meta.patient_id, pv.meta.name, pv.meta.exam_date) == ("new", "12345", "홍길동", "2024-03-05")
    assert imp.import_file(p, wait=False).status == "imported"
    again = imp.preview(p)
    assert again.status == "duplicate" and again.patient_ref == db.find_patient("12345")["id"]
    bad = tmp / "bad.jpg"
    bad.write_bytes(b"not a picture")
    assert imp.preview(bad).status == "error" and "사진 파일이 아니" in imp.preview(bad).message
    empty = tmp / "empty.jpg"
    empty.write_bytes(b"")
    assert imp.preview(empty).status == "error"


def test_the_patient_the_user_names(lib):
    s, db, tmp = lib
    imp = Importer(db, s)
    r = imp.import_file(photo(tmp / "IMG_0001.jpg", 4), wait=False,
                        assign=PatientAssign("777", "이영희", "1970-01-02", "F"))
    pat = db.get_patient(r.patient_ref)
    assert (pat["patient_id"], pat["name"], pat["birth_date"], pat["sex"]) == ("777", "이영희", "1970-01-02", "F")
    row = db.get_image(r.image_id)
    assert '"patient_id": "user"' in row["meta_json"]
    assert Path(row["file_path"]).parts[-3] == "777"
    # … and it wins over what the file says, which is kept for reference
    r2 = imp.import_file(photo(tmp / "12345_홍길동_20240305_OD.jpg", 5), wait=False, assign=PatientAssign("777"))
    assert r2.patient_ref == r.patient_ref and db.find_patient("12345") is None
    assert "12345" in db.get_image(r2.image_id)["meta_json"]
    assert db.get_patient(r.patient_ref)["name"] == "이영희"       # not renamed by the other patient's file


def test_apply_assign():
    m = apply_assign(ExtractedMeta(patient_id="1", name="가나다", birth_date="1990-01-01"), PatientAssign("2"))
    assert (m.patient_id, m.name, m.birth_date) == ("2", None, None)         # another patient's name is not theirs
    m = apply_assign(ExtractedMeta(patient_id="1", name="가나다"), PatientAssign("1", "가나라"))
    assert (m.patient_id, m.name, m.sources["name"]) == ("1", "가나라", "user")
    m = apply_assign(ExtractedMeta(name="가나다"), None)
    assert m.name == "가나다"


def test_a_photo_in_unassigned_gets_its_patient_when_picked_again(lib):
    s, db, tmp = lib
    imp = Importer(db, s)
    p = photo(tmp / "IMG_0001.jpg", 6)
    first = imp.import_file(p, wait=False)
    assert first.patient_ref is None and db.count_unassigned() == 1
    r = imp.import_file(p, force=True, wait=False, assign=PatientAssign("555", "박지호"))
    assert (r.status, r.image_id) == ("assigned", first.image_id)
    assert db.count_unassigned() == 0 and db.get_image(first.image_id)["patient_ref"] == db.find_patient("555")["id"]
    # the same content under a name that says the patient does the same
    q = photo(tmp / "IMG_0002.jpg", 7)
    imp.import_file(q, wait=False)
    named = tmp / "888_최유나_20240305_OS.jpg"
    shutil.copy(q, named)
    assert imp.import_file(named, wait=False).status == "assigned" and db.find_patient("888")["name"] == "최유나"
    # a photo that has its patient stays a plain duplicate
    assert imp.import_file(named, force=True, wait=False, assign=PatientAssign("999")).status == "duplicate"
    assert db.find_patient("999") is None


def test_a_moved_photo_leaves_its_folder_only_when_it_is_registered(lib, monkeypatch):
    s, db, tmp = lib
    drop = tmp / "drop"
    folder = WatchFolder(path=str(drop), action=ACTION_MOVE)
    imp = Importer(db, s)
    p = photo(drop / "12345_홍길동_20240305_OD.jpg", 8)
    monkeypatch.setattr(db, "insert_image", lambda **kw: (_ for _ in ()).throw(RuntimeError("disk full")))
    r = imp.import_file(p, folder, wait=False)
    assert r.status == "error" and p.exists()                    # the original is still there
    left = [f for f in (tmp / "lib").rglob("*") if f.is_file() and "fundus.db" not in f.name]
    assert left == [] and db.find_patient("12345") is None       # nothing half-imported, nothing registered
    monkeypatch.undo()
    r = imp.import_file(p, folder, force=True, wait=False)
    assert r.status == "imported" and not p.exists() and Path(db.get_image(r.image_id)["file_path"]).exists()


def test_stored_names(lib):
    assert safe_component("a" * 200 + ".jpg").endswith(".jpg") and len(safe_component("a" * 200 + ".jpg")) == 80
    assert safe_component("CON") == "_CON" and safe_component("nul.jpg") == "_nul.jpg"
    assert safe_component("A/B:C*?.png") == "A_B_C__.png" and safe_component(" . ") == "_"
    s, db, tmp = lib
    r = Importer(db, s).import_file(photo(tmp / ("가" * 82 + ".jpg"), 9), wait=False, assign=PatientAssign("AUX"))
    stored = Path(db.get_image(r.image_id)["file_path"])
    assert stored.suffix == ".jpg" and stored.parts[-3] == "_AUX" and stored.exists()


def test_a_large_jpeg_is_analysed_reduced_and_found_in_its_own_pixels(lib):
    """The import decodes a big JPEG at a fraction of its size; the image circle, disc and fovea
    it stores are in the photo's own pixels, where the full-size analysis finds them."""
    from fundusview import imaging
    s, db, tmp = lib
    img = synth_fundus(eye="OS", fov_deg=45, fov_type="external", size=(700, 700), seed=5)
    img = (img if isinstance(img, Image.Image) else Image.fromarray(img)).resize((3000, 2400), Image.BICUBIC)
    p = tmp / "big.jpg"
    img.save(p, quality=90)
    small, w, h = imaging.load_for_import(p)
    assert (w, h) == (3000, 2400) and max(small.shape) < 2048
    r = Importer(db, s).import_file(p, wait=False)
    row = db.get_image(r.image_id)
    assert (row["width"], row["height"], row["laterality"]) == (3000, 2400, "OS")
    full = imaging.load_rgb(p)
    cx, cy, cr = imaging.detect_circle(full)
    assert row["circle_cx"] == pytest.approx(cx, abs=8) and row["circle_cy"] == pytest.approx(cy, abs=8)
    assert row["circle_r"] == pytest.approx(cr, abs=8)
    assert row["disc_x"] is not None and row["fovea_x"] is not None
    disc = imaging.detect_disc(full, (cx, cy, cr))
    assert (row["disc_x"], row["disc_y"]) == pytest.approx(disc[:2], abs=30)


def test_exif_orientation_is_kept_by_the_reduced_reader(tmp_path):
    from fundusview import imaging
    a = np.zeros((1200, 2400, 3), np.uint8)
    a[:, :1200] = (200, 60, 30)                                   # left half red
    exif = Image.Exif()
    exif[0x0112] = 6                                              # shown turned 90° clockwise
    p = tmp_path / "turned.jpg"
    Image.fromarray(a).save(p, quality=90, exif=exif)
    small, w, h = imaging.load_for_import(p)
    full = imaging.load_rgb(p)
    assert (w, h) == (1200, 2400) == (full.shape[1], full.shape[0])
    assert small.shape[0] > small.shape[1]                        # portrait, as the full reader gives it
    assert small[:small.shape[0] // 3].mean(axis=(0, 1))[0] > 150 > small[-small.shape[0] // 3:].mean()
    assert full[:800].mean(axis=(0, 1))[0] > 150 > full[-800:].mean()


# -- the 확인 창 ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture()
def picked(lib, app):
    """A USB stick as it comes: photos that say their patient in every way, and some that do not."""
    s, db, tmp = lib
    usb = tmp / "usb"
    photo(usb / "홍길동_12345" / "IMG_0001.jpg", 21)
    photo(usb / "홍길동_12345" / "IMG_0002.jpg", 22)
    photo(usb / "새 폴더" / "IMG_0003.jpg", 23)
    photo(usb / "새 폴더" / "IMG_0004.jpg", 24)
    photo(usb / "이영희 OD.jpg", 25)
    photo(usb / "D0001234_박철수_20260301_OS.jpg", 26)
    (usb / "notes.txt").write_text("not a photo")
    (usb / "broken.jpg").write_bytes(b"\xff\xd8 not really")
    db.upsert_patient(ExtractedMeta(patient_id="D0001234", name="박지호"))
    current = db.upsert_patient(ExtractedMeta(patient_id="77001", name="이영희", birth_date="1970-01-01", sex="F"))
    svc = ImportService(db, s)
    yield svc, db, usb, current
    svc.shutdown()


def _row(dlg, **want):
    from fundusview.ui import import_dialog as d
    for r, g in enumerate(dlg.groups):
        if all(getattr(g, k) == v for k, v in want.items()):
            return r, {c: dlg.table.item(r, c).text() for c in range(d.C_PICK)}
    raise AssertionError(f"no row {want}: {[(g.patient_id, g.name, g.where) for g in dlg.groups]}")


def _drain(app, svc, n, timeout=60.0):
    done = []
    svc.on_result = done.append
    _wait(app, lambda: len(done) >= n and svc.queued == 0, timeout)
    return done


def test_review_dialog_shows_what_was_read(picked, app):
    from fundusview.ui import import_dialog as d
    svc, db, usb, current = picked
    dlg = d.ImportReviewDialog(svc, db, [str(usb)], current_ref=current)
    try:
        _wait(app, lambda: dlg.ready)
        assert sum(len(g.items) for g in dlg.groups) == 6 and len(dlg.failed) == 1
        assert "사진 6장" in dlg.lbl_head.text() and "환자 정보 없음 3장" in dlg.lbl_head.text()
        assert "broken.jpg" in dlg.lbl_note.text()
        r, cells = _row(dlg, patient_id="12345")
        assert (cells[d.C_NAME], cells[d.C_COUNT]) == ("홍길동", "2장") and "새 환자" in cells[d.C_STATE]
        assert "폴더 이름" in cells[d.C_STATE]
        r, cells = _row(dlg, patient_id="D0001234")
        assert "이름이 다릅니다" in cells[d.C_STATE] and "박지호" in cells[d.C_STATE]
        r, cells = _row(dlg, patient_id="", name="이영희")
        assert "환자 정보 없음" in cells[d.C_STATE]
        # only a name was read: the one registered patient of that name is offered
        assert dlg.groups[r].suggestion[0] == "77001" and dlg.table.cellWidget(r, d.C_PICK) is not None
        r2, _ = _row(dlg, patient_id="", name="")
        assert dlg.groups[r2].suggestion[0] == "77001"             # the patient selected in the window
        assert dlg.btn_ok.isEnabled() and dlg.btn_ok.text() == "가져오기 (6장)"
    finally:
        dlg.reject()


def test_review_dialog_names_the_patient_and_imports(picked, app):
    from fundusview.ui import import_dialog as d
    svc, db, usb, current = picked
    dlg = d.ImportReviewDialog(svc, db, [str(usb)], current_ref=current)
    _wait(app, lambda: dlg.ready)
    r_named, _ = _row(dlg, patient_id="", name="이영희")
    dlg.table.cellWidget(r_named, d.C_PICK).click()               # ← 이영희 (77001)
    assert dlg.table.item(r_named, d.C_ID).text() == "77001"
    assert dlg.table.item(r_named, d.C_BIRTH).text() == "1970-01-01" and dlg.table.item(r_named, d.C_SEX).text() == "여"
    assert "등록된 환자" in dlg.table.item(r_named, d.C_STATE).text()
    r_none, _ = _row(dlg, patient_id="", name="")
    dlg.table.item(r_none, d.C_ID).setText(" 9 0 0 1 ")           # typed by hand: a new patient
    dlg.table.item(r_none, d.C_NAME).setText("김새롬")
    dlg.table.item(r_none, d.C_BIRTH).setText("1988.12.03")
    dlg.table.item(r_none, d.C_SEX).setText("남")
    assert dlg.table.item(r_none, d.C_ID).text() == "9001"
    assert "새 환자" in dlg.table.item(r_none, d.C_STATE).text()
    assert "환자 4명" in dlg.lbl_head.text() and "환자 정보 없음" not in dlg.lbl_head.text()
    dlg._accept()
    assert dlg.result() == d.ImportReviewDialog.DialogCode.Accepted
    items = dlg.result_items()
    assert len(items) == 6
    results = _drain(app, svc, svc.import_items(items))
    assert sorted(r.status for r in results) == ["imported"] * 6
    new = db.find_patient("9001")
    assert (new["name"], new["birth_date"], new["sex"]) == ("김새롬", "1988-12-03", "M")
    assert len(db.images_for_patient(new["id"])) == 2 and len(db.images_for_patient(current)) == 1
    assert db.find_patient("12345")["name"] == "홍길동" and db.count_unassigned() == 0
    assert db.find_patient("D0001234")["name"] == "박지호"        # the registered name stays
    # picked once more: nothing is new
    again = d.ImportReviewDialog(svc, db, [str(usb)], current_ref=current)
    try:
        _wait(app, lambda: again.ready)
        assert again.groups == [] and again.skipped == 6 and not again.btn_ok.isEnabled()
        assert "새로 가져올 사진이 없습니다" in again.lbl_head.text()
    finally:
        again.reject()


def test_review_dialog_left_empty_goes_to_unassigned_and_can_be_named_later(picked, app):
    from fundusview.ui import import_dialog as d
    svc, db, usb, current = picked
    folder = usb / "새 폴더"
    dlg = d.ImportReviewDialog(svc, db, [str(folder)])            # no patient selected: nothing offered
    _wait(app, lambda: dlg.ready)
    assert len(dlg.groups) == 1 and dlg.groups[0].suggestion is None
    dlg._accept()
    _drain(app, svc, svc.import_items(dlg.result_items()))
    assert db.count_unassigned() == 2
    again = d.ImportReviewDialog(svc, db, [str(folder)], current_ref=current)
    _wait(app, lambda: again.ready)
    assert len(again.groups) == 1 and "이미 미분류에 있는 사진" in again.table.item(0, d.C_STATE).text()
    assert again.result_items() == []                              # still nobody's: nothing to do
    again.set_patient(0, "77001")
    again._accept()
    results = _drain(app, svc, svc.import_items(again.result_items()))
    assert [r.status for r in results] == ["assigned", "assigned"]
    assert db.count_unassigned() == 0 and len(db.images_for_patient(current)) == 2


def test_review_dialog_checks_what_is_typed(picked, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from fundusview.ui import import_dialog as d
    svc, db, usb, current = picked
    said = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: said.append(a[2])))
    dlg = d.ImportReviewDialog(svc, db, [str(usb / "새 폴더")])
    try:
        _wait(app, lambda: dlg.ready)
        dlg.table.item(0, d.C_ID).setText("9002")
        dlg.table.item(0, d.C_BIRTH).setText("어제")
        dlg._accept()
        assert said and "생년월일" in said[0] and dlg.result() != d.ImportReviewDialog.DialogCode.Accepted
        dlg.table.item(0, d.C_BIRTH).setText("")
        dlg.table.item(0, d.C_SEX).setText("?")
        dlg._accept()
        assert len(said) == 2 and "성별" in said[1]
    finally:
        dlg.reject()


def test_review_dialog_with_nothing_to_import(lib, app):
    from fundusview.ui import import_dialog as d
    s, db, tmp = lib
    (tmp / "empty").mkdir()
    (tmp / "empty" / "readme.txt").write_text("x")
    svc = ImportService(db, s)
    dlg = d.ImportReviewDialog(svc, db, [str(tmp / "empty")])
    try:
        _wait(app, lambda: dlg.ready)
        assert "가져올 사진 파일이 없습니다" in dlg.lbl_head.text() and not dlg.btn_ok.isEnabled()
    finally:
        dlg.reject()
        svc.shutdown()


def test_the_window_imports_through_the_review_dialog(tmp_path, app, monkeypatch):
    """사진 가져오기 in the window: the dialog opens with the selected patient, and what it
    returns is imported."""
    from fundusview.ui import import_dialog as d
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.0, rescan_seconds=0, watch_on_startup=False,
                 auto_detect=False)
    w = MainWindow(s, Database(tmp_path / "lib" / "fundus.db"))
    try:
        ref = w.db.upsert_patient(ExtractedMeta(patient_id="77001", name="이영희"))
        w.refresh_patients()
        w._select_patient_ref(ref)
        files = [str(photo(tmp_path / "usb" / f"IMG_000{i}.jpg", 40 + i)) for i in range(2)]
        seen = {}

        def run(dlg):
            _wait(app, lambda: dlg.ready)
            seen["suggestion"] = dlg.groups[0].suggestion
            dlg.table.cellWidget(0, d.C_PICK).click()
            dlg._accept()
            return dlg.result()

        monkeypatch.setattr(d.ImportReviewDialog, "exec", run)
        assert w.review_import(files) == 2
        assert seen["suggestion"][0] == "77001"
        _wait(app, lambda: len(w.db.images_for_patient(ref)) == 2 and w.service.queued == 0, 60)
        _wait(app, lambda: not w._result_timer.isActive() and not w._results)
        assert w.db.count_unassigned() == 0
        monkeypatch.setattr(d.ImportReviewDialog, "exec", lambda dlg: (dlg.reject(), dlg.result())[1])
        assert w.review_import(files) == 0                          # cancelled: nothing queued
    finally:
        w.service.shutdown()
        w.close()
