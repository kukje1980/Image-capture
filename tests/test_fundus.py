"""안저 불러오기 · 안저 검토 화면 테스트."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication

from app.db.database import Database
from app.models.capture import Capture
from app.models.patient import Patient
from app.services import fundus_import
from app.services.capture_service import CaptureService
from app.services.fundus_import import FundusImportError, ImportedImage, guess_eye_from_name


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fundus(seed=0, h=120, w=160, disc_left=False):
    """안저 비슷한 합성 영상 (주황빛 원반 + 밝은 시신경 유두)."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.circle(img, (w // 2, h // 2), min(h, w) // 2 - 4, (30, 70 + seed * 10, 200), -1)
    x = w // 2 + (-1 if disc_left else 1) * w // 5
    cv2.circle(img, (x, h // 2), 9, (170, 230, 255), -1)
    return img


def _patient(db, chart="F1"):
    p = Patient(chart_no=chart, name="안저환자", sex="F")
    p.id = db.patients.insert(p)
    return p


# ---------------- 파일 이름 → 안구 ----------------
@pytest.mark.parametrize("name,eye", [
    ("kim_OD_2024.jpg", "OD"),
    ("kim_os_2024.jpg", "OS"),
    ("001-R.jpg", "OD"),
    ("001-L.png", "OS"),
    ("patient RE 01.tif", "OD"),
    ("patient.LE.01.tif", "OS"),
    ("홍길동_우안.jpg", "OD"),
    ("홍길동 좌안 2.png", "OS"),
    ("scan_right_eye.png", "OD"),
    ("C:\\data\\fundus\\0001_OS.dcm", "OS"),
    ("color.jpg", None),                 # 단어 안의 글자는 보지 않는다
    ("model_scan.png", None),
    ("ODESSA.png", None),
    ("IMG_0001.jpg", None),
    ("fundus_OD_OS.jpg", None),          # 양쪽 다 → 판단하지 않음
    ("OD_L.jpg", "OD"),                  # 분명한 표기(OD)가 한 글자 표기보다 우선
    ("L.jpg", "OS"),
])
def test_guess_eye_from_name(name, eye):
    assert guess_eye_from_name(name) == eye


# ---------------- 일반 이미지 ----------------
def test_read_png_korean_path_uses_mtime_and_name(tmp_path):
    p = tmp_path / "한글 폴더" / "홍길동_OS.png"
    p.parent.mkdir()
    ok, enc = cv2.imencode(".png", _fundus())
    enc.tofile(str(p))
    ts = datetime(2023, 4, 5, 6, 7, 8).timestamp()
    os.utime(p, (ts, ts))
    item = fundus_import.read_image(p)
    assert item.image.shape == (120, 160, 3) and item.image.dtype == np.uint8
    assert item.eye == "OS" and item.source_name == "홍길동_OS.png"
    assert item.captured_at == datetime(2023, 4, 5, 6, 7, 8)
    assert item.lossy is False


def test_read_jpeg_exif_datetime(tmp_path):
    from PIL import Image
    p = tmp_path / "exif-R.jpg"
    im = Image.fromarray(_fundus()[..., ::-1])
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = "2022:11:30 14:15:16"       # DateTimeOriginal
    im.save(p, exif=exif)
    item = fundus_import.read_image(p)
    assert item.captured_at == datetime(2022, 11, 30, 14, 15, 16)
    assert item.eye == "OD" and item.lossy is True


def test_read_errors(tmp_path):
    with pytest.raises(FundusImportError):
        fundus_import.read_image(tmp_path / "없는파일.jpg")
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(FundusImportError):
        fundus_import.read_image(bad)
    txt = tmp_path / "note.txt"
    txt.write_text("x")
    with pytest.raises(FundusImportError):
        fundus_import.read_image(txt)


# ---------------- DICOM ----------------
def _dicom_base(ts_uid, rows, cols, samples):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import generate_uid
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ts_uid
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.77.1.5.1"   # Ophthalmic Photography 8 Bit
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "OP"
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = samples
    ds.PixelRepresentation = 0
    if samples == 3:
        ds.PlanarConfiguration = 0
    return ds


def test_read_dicom_uncompressed_rgb(tmp_path):
    from pydicom.uid import ExplicitVRLittleEndian
    bgr = _fundus()
    ds = _dicom_base(ExplicitVRLittleEndian, 120, 160, 3)
    ds.PhotometricInterpretation = "RGB"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.ImageLaterality = "L"
    ds.Laterality = "R"                       # ImageLaterality 가 우선
    ds.StudyDate, ds.StudyTime = "20200101", "010101"
    ds.ContentDate, ds.ContentTime = "20240315", "093012.250000"
    ds.PixelData = bgr[..., ::-1].tobytes()
    p = tmp_path / "scan_0001"                # 확장자 없음 → 'DICM' 머리말로 인식
    ds.save_as(p, enforce_file_format=True)

    assert fundus_import.is_dicom(p)
    item = fundus_import.read_image(p)
    assert np.array_equal(item.image, bgr)
    assert item.eye == "OS"
    assert item.captured_at == datetime(2024, 3, 15, 9, 30, 12)
    assert item.lossy is False


def test_read_dicom_mono16_inverted_multiframe_and_fallback_dates(tmp_path):
    from pydicom.uid import ExplicitVRLittleEndian
    frame = np.linspace(0, 4095, 30 * 40, dtype=np.uint16).reshape(30, 40)
    ds = _dicom_base(ExplicitVRLittleEndian, 30, 40, 1)
    ds.PhotometricInterpretation = "MONOCHROME1"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 12, 11
    ds.NumberOfFrames = 2
    ds.Laterality = "R"
    ds.AcquisitionDateTime = "20230607112233.000000"
    ds.PixelData = frame.tobytes() + np.zeros_like(frame).tobytes()
    p = tmp_path / "mono.dcm"
    ds.save_as(p, enforce_file_format=True)

    item = fundus_import.read_image(p)
    assert item.image.shape == (30, 40, 3) and item.image.dtype == np.uint8
    assert int(item.image[0, 0, 0]) == 255 and int(item.image[-1, -1, 0]) == 0     # MONOCHROME1 반전
    assert item.eye == "OD"
    assert item.captured_at == datetime(2023, 6, 7, 11, 22, 33)


def test_read_dicom_jpeg_and_unsupported_compression(tmp_path, monkeypatch):
    from pydicom.encaps import encapsulate
    from pydicom.uid import JPEGBaseline8Bit, JPEGLSLossless
    bgr = _fundus()
    ok, enc = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    ds = _dicom_base(JPEGBaseline8Bit, 120, 160, 3)
    ds.PhotometricInterpretation = "YBR_FULL_422"
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.StudyDate = "20210203"
    ds.PixelData = encapsulate([enc.tobytes()])
    p = tmp_path / "jpeg_OD.dcm"
    ds.save_as(p, enforce_file_format=True)

    item = fundus_import.read_image(p)
    assert item.lossy is True and item.eye == "OD"           # 태그가 없으면 파일 이름에서
    assert item.captured_at == datetime(2021, 2, 3)
    assert np.abs(item.image.astype(int) - bgr.astype(int)).mean() < 6

    # pydicom 디코더가 실패하면 프레임 바이트를 직접 디코딩한다
    def boom(ds):
        raise RuntimeError("no decoder")
    monkeypatch.setattr(fundus_import, "_dicom_pixels", boom)
    item2 = fundus_import.read_image(p)
    assert np.abs(item2.image.astype(int) - bgr.astype(int)).mean() < 6

    # 직접 디코딩도 안 되는 압축 → 한국어 오류
    ds.file_meta.TransferSyntaxUID = JPEGLSLossless
    ds.PixelData = encapsulate([b"\x00" * 64])
    q = tmp_path / "jpegls.dcm"
    ds.save_as(q, enforce_file_format=True)
    with pytest.raises(FundusImportError, match="지원하지 않는 DICOM 압축"):
        fundus_import.read_image(q)


# ---------------- DB 마이그레이션 ----------------
def test_old_captures_table_gets_modality(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE patients (id INTEGER PRIMARY KEY AUTOINCREMENT, chart_no TEXT UNIQUE,
            patient_id TEXT, name TEXT NOT NULL, birth_date TEXT, sex TEXT, phone TEXT,
            memo TEXT, symptoms TEXT, diagnosis TEXT, doctor TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
        CREATE TABLE captures (id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL, file_path TEXT NOT NULL, export_path TEXT,
            thumbnail_path TEXT, captured_at TEXT NOT NULL, eye TEXT, duration_ms INTEGER, note TEXT);
        INSERT INTO patients (chart_no, name) VALUES ('OLD1', '기존환자');
        INSERT INTO captures (patient_id, media_type, file_path, captured_at, eye, note)
            VALUES (1, 'photo', '/tmp/a.png', '2025-01-02 03:04:05', 'OD', '기존'),
                   (1, 'video', '/tmp/b.mp4', '2025-01-02 03:05:00', 'OS', NULL);
    """)
    con.commit()
    con.close()

    for _ in range(2):                                  # 두 번 열어도 문제없다
        db = Database(str(path)).init()
        try:
            rows = db.captures.list_by_patient(1, order="asc")
            assert [(r.file_path, r.eye, r.note, r.modality) for r in rows] == [
                ("/tmp/a.png", "OD", "기존", "slit"), ("/tmp/b.mp4", "OS", None, "slit")]
            assert db.captures.list_by_patient(1, modality="fundus") == []
        finally:
            db.close()

    db = Database(str(path)).init()
    try:
        cid = db.captures.insert(Capture(patient_id=1, media_type="photo", file_path="/tmp/f.png",
                                         captured_at="2024-01-01 00:00:00", eye="OD", modality="fundus"))
        assert db.captures.get(cid).modality == "fundus"
        assert [c.id for c in db.captures.list_by_patient(1, modality="fundus")] == [cid]
        assert len(db.captures.list_by_patient(1)) == 3
    finally:
        db.close()


# ---------------- 저장 ----------------
def test_import_stores_fundus_capture(app_env, tmp_path):
    config, db = app_env
    svc = CaptureService(db, config)
    patient = _patient(db)
    when = datetime(2021, 7, 8, 9, 10, 11)
    item = ImportedImage(_fundus(), when, "OS", "원본_OS.png")
    cap = fundus_import.import_image(svc, patient, item)

    row = db.captures.get(cap.id)
    assert (row.media_type, row.modality, row.eye) == ("photo", "fundus", "OS")
    assert row.captured_at == "2021-07-08 09:10:11"
    assert row.note == "안저 · 원본_OS.png"
    assert row.file_path.endswith(".png") and "2021-07-08" in row.file_path     # 촬영일 폴더
    assert Path(row.file_path).exists() and Path(row.thumbnail_path).exists()
    assert row.export_path and Path(row.export_path).exists()
    assert np.array_equal(cv2.imread(row.file_path), item.image)

    # 같은 촬영 시각 · 같은 안구의 두 번째 사진이 첫 번째를 덮어쓰지 않는다
    cap2 = fundus_import.import_image(svc, patient, ImportedImage(_fundus(3), when, "OS", "b.jpg", True))
    assert cap2.file_path != cap.file_path and cap2.file_path.endswith(".jpg")
    # 안구를 직접 지정 · 알 수 없으면 NA
    cap3 = fundus_import.import_image(svc, patient, ImportedImage(_fundus(), when, None, "c.png"))
    cap4 = fundus_import.import_image(svc, patient, ImportedImage(_fundus(), when, "OS", "d.png"), eye="OD")
    assert (cap3.eye, cap4.eye) == ("NA", "OD")

    # 일반 촬영은 그대로 slit
    assert svc.save_photo(_fundus(), patient, eye="OD").modality == "slit"
    assert len(db.captures.list_by_patient(patient.id, modality="fundus")) == 4


def test_import_dialog_lists_and_imports(qapp, app_env, tmp_path):
    from app.ui.fundus_import_dialog import FundusImportDialog
    config, db = app_env
    svc = CaptureService(db, config)
    patient = _patient(db)
    files = []
    for name in ("a_OD.png", "b_OS.png", "c.png"):
        p = tmp_path / name
        cv2.imwrite(str(p), _fundus())
        files.append(str(p))
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"xx")
    dlg = FundusImportDialog(svc, patient, files=files + [str(bad)])
    rows = dlg.rows()
    assert [r["eye"] for r in rows] == ["OD", "OS", "NA", None]
    assert rows[3]["error"] and dlg.table.rowCount() == 4
    dlg.add_files(files[:1])                                  # 같은 파일은 다시 넣지 않는다
    assert dlg.table.rowCount() == 4
    dlg.set_all_eyes("OS")
    assert [r["eye"] for r in dlg.rows()[:3]] == ["OS", "OS", "OS"]
    dlg.rows()                                                 # no-op
    dlg._rows[0].combo.setCurrentIndex(0)                      # 첫 장만 OD 로
    caps = dlg.import_all()
    assert [c.eye for c in caps] == ["OD", "OS", "OS"]
    assert [n for n, _ in dlg.failed] == ["bad.jpg"]
    assert all(c.modality == "fundus" for c in db.captures.list_by_patient(patient.id))


# ---------------- 안저 검토 화면 ----------------
def _review(app_env, plan):
    """plan: [(eye, 'YYYY-MM-DD HH:MM:SS'), ...] 로 안저 사진을 넣고 화면을 만든다."""
    from app.ui.fundus.fundus_review import FundusReview
    config, db = app_env
    svc = CaptureService(db, config)
    patient = _patient(db)
    caps = {}
    for k, (eye, at) in enumerate(plan):
        item = ImportedImage(_fundus(k, disc_left=(eye == "OS")), datetime.fromisoformat(at), eye, f"{k}.png")
        caps[(eye, at)] = fundus_import.import_image(svc, patient, item)
    svc.save_photo(_fundus(), patient, eye="OD")              # 세극등 사진은 목록에 나오지 않는다
    w = FundusReview(db, config)
    w.resize(1200, 760)
    w.set_patient(patient)
    return w, caps, svc, patient


_PLAN = [("OD", "2023-01-10 09:00:00"), ("OS", "2023-01-10 09:01:00"),
         ("OD", "2024-03-01 10:00:00"), ("OD", "2024-03-01 10:05:00"), ("OS", "2024-03-01 10:06:00")]


def test_review_stages(qapp, app_env):
    w, caps, _, _ = _review(app_env, _PLAN)
    assert len(w.captures()) == 5 and w.sessions() == ["2024-03-01", "2023-01-10"]
    assert w.stack.currentIndex() == 1

    # 양안: 왼쪽 = OD(우안), 오른쪽 = OS(좌안), 가장 최근 검사의 가장 늦은 사진
    assert w.stage() == "ou"
    assert w.left.capture().id == caps[("OD", "2024-03-01 10:05:00")].id
    assert w.right.capture().id == caps[("OS", "2024-03-01 10:06:00")].id
    assert w.left.tag() == "" and w.right.tag() == ""
    assert w.left.has_image() and w.right.has_image()
    assert not w.left.b_older.isVisibleTo(w.left)

    # 비교: 왼쪽 = 이전 검사, 오른쪽 = 현재 검사
    assert w.stage_enabled("od") and w.stage_enabled("os")
    w.step_stage(1)
    assert w.stage() == "od"
    assert w.left.capture().id == caps[("OD", "2023-01-10 09:00:00")].id and w.left.tag() == "이전"
    assert w.right.capture().id == caps[("OD", "2024-03-01 10:05:00")].id and w.right.tag() == "현재"
    w.step_stage(1)
    assert w.stage() == "os"
    assert w.left.capture().id == caps[("OS", "2023-01-10 09:01:00")].id
    assert w.right.capture().id == caps[("OS", "2024-03-01 10:06:00")].id
    w.step_stage(1)                                            # 끝에서 멈춤
    assert w.stage() == "os"
    w.step_stage(-1)
    w.step_stage(-1)
    assert w.stage() == "ou" and w.c_stage.currentIndex() == 0
    assert not w.b_prev.isEnabled() and w.b_next.isEnabled()


def test_review_compare_disabled_without_prior(qapp, app_env):
    w, caps, _, _ = _review(app_env, [("OD", "2023-01-10 09:00:00"), ("OD", "2024-03-01 10:00:00"),
                                      ("OS", "2024-03-01 10:06:00")])
    assert w.stage_enabled("od") and not w.stage_enabled("os")
    assert w.c_stage.model().item(1).isEnabled() and not w.c_stage.model().item(2).isEnabled()
    assert w.set_stage("os") is False and w.stage() == "ou"
    w.step_stage(1)
    assert w.stage() == "od"
    w.step_stage(1)                                            # OS 비교는 건너뛸 곳이 없어 그대로
    assert w.stage() == "od"


def test_review_prior_scroll_and_timeline(qapp, app_env):
    plan = [("OD", "2022-05-05 08:00:00"), ("OD", "2023-01-10 09:00:00"), ("OD", "2024-03-01 10:00:00"),
            ("OS", "2024-03-01 10:06:00"), (None, "2024-03-01 10:07:00")]
    w, caps, _, _ = _review(app_env, plan)
    assert w.timeline.days() == ["2024-03-01", "2023-01-10", "2022-05-05"]
    assert len(w.timeline.thumbs()) == 5

    w.set_stage("od")
    assert w.prior_count() == 2 and w.left.tag() == "이전 1/2"
    assert w.left.b_older.isEnabled() and not w.left.b_newer.isEnabled()
    w.scroll_prior(1)                                          # [ : 더 이전
    assert w.left.capture().id == caps[("OD", "2022-05-05 08:00:00")].id and w.left.tag() == "이전 2/2"
    w.scroll_prior(1)
    assert w.prior_index() == 1
    w.left.b_newer.click()                                     # ] : 더 최근
    assert w.left.capture().id == caps[("OD", "2023-01-10 09:00:00")].id
    assert w.right.capture().id == caps[("OD", "2024-03-01 10:00:00")].id

    # 비교 단계에서 타임라인 클릭 → 활성 뷰포트
    w.set_active(w.right)
    w.show_capture(caps[("OD", "2022-05-05 08:00:00")])
    assert w.right.capture().id == caps[("OD", "2022-05-05 08:00:00")].id and w.right.tag() == "이전"

    # 양안 단계: 안구에 맞는 뷰포트, 미지정은 활성 뷰포트
    w.set_stage("ou")
    w.show_capture(caps[("OD", "2023-01-10 09:00:00")])
    assert w.left.capture().id == caps[("OD", "2023-01-10 09:00:00")].id and w.left.tag() == "이전"
    w.set_active(w.right)
    w.show_capture(caps[(None, "2024-03-01 10:07:00")])
    assert w.right.capture().id == caps[(None, "2024-03-01 10:07:00")].id
    # 끌어다 놓기는 놓은 뷰포트로
    w._on_dropped(w.left, caps[("OS", "2024-03-01 10:06:00")].id)
    assert w.left.capture().id == caps[("OS", "2024-03-01 10:06:00")].id


def test_review_link_view_modes_and_magnifier(qapp, app_env):
    w, caps, _, _ = _review(app_env, _PLAN)
    w.show()
    qapp.processEvents()
    left, right = w.viewports()
    assert w.linked() and left.is_fit() and right.is_fit()

    left.zoom_by(2.0, QPointF(100, 100))                       # 연동: 오른쪽도 같은 상대 배율·위치
    assert not left.is_fit()
    assert right.view_state() == pytest.approx(left.view_state())
    w.set_linked(False)
    before = right.view_state()
    left.zoom_by(1.5)
    assert right.view_state() == pytest.approx(before)
    w.set_linked(True)
    assert right.view_state() == pytest.approx(left.view_state())
    w.fit()
    assert left.is_fit() and right.is_fit()

    # 보기: 감각망막 = 녹색 채널, 맥락막 = 적색 채널
    src = cv2.imread(left.capture().file_path)
    w.set_view_mode("redfree")
    assert np.array_equal(left.display_array(), src[..., 1]) and right.view_mode() == "redfree"
    w.set_view_mode("choroid")
    assert np.array_equal(left.display_array(), src[..., 2])
    w.set_view_mode("color")
    assert np.array_equal(left.display_array(), src[..., ::-1])

    # 확대창: 가운데 클릭으로 켜고 끄기, 휠 배율 범위, 반대쪽 영상
    mag = w.magnifier
    assert not mag.is_shown()
    w._on_magnifier_requested(left, QPoint(120, 150))
    assert mag.is_shown() and w.b_mag.isChecked() and mag.host() is left
    vp, center, scale = mag.source()
    assert vp is left and scale == pytest.approx(left.zoom() * 2.5)
    assert center.x() == pytest.approx(left.image_at(QPoint(120, 150)).x(), abs=1.0)
    mag.set_other_mode(True)
    vp2, center2, _ = mag.source()
    assert vp2 is right and center2.x() == pytest.approx(center.x())
    mag.set_factor(99)
    assert mag.factor() == 6.0
    mag.set_factor(0)
    assert mag.factor() == 1.5
    assert not mag.grab().isNull()
    w._on_magnifier_requested(left, QPoint(120, 150))
    assert not mag.is_shown() and not w.b_mag.isChecked()
    w.close()


def test_review_empty_state(qapp, app_env):
    from app.ui.fundus.fundus_review import EMPTY_TEXT, FundusReview
    config, db = app_env
    w = FundusReview(db, config)
    assert w.stack.currentIndex() == 0 and w.lbl_empty.text() == EMPTY_TEXT
    assert not w.b_empty_import.isEnabled()                    # 환자 미선택
    patient = _patient(db)
    CaptureService(db, config).save_photo(_fundus(), patient, eye="OD")   # 세극등 사진만 있음
    w.set_patient(patient)
    assert w.stack.currentIndex() == 0 and w.b_empty_import.isEnabled()
    assert not w.stage_enabled("od") and w.captures() == []
    fired = []
    w.importRequested.connect(lambda: fired.append(1))
    w.b_empty_import.click()
    assert fired == [1]


def test_main_window_fundus_screen(qapp, app_env, tmp_path, monkeypatch):
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.ui import main_window as mw
    config, db = app_env
    config.source_mode = "synthetic"
    config.save = lambda: None
    _patient(db, "MW1")
    win = mw.MainWindow(config, db)
    win.show()
    end = time.time() + 5
    while time.time() < end and win._last_frame is None:
        qapp.processEvents()
        time.sleep(0.02)
    try:
        assert win._current_patient is not None and win.btn_import_fundus.isEnabled()
        assert win.mode_stack.currentIndex() == 3              # 환자 목록에서 시작
        win._set_screen(0)
        files = []
        for name, day in (("x_OD.png", 1), ("x_OS.png", 1), ("y_OD.png", 400)):
            p = tmp_path / name
            cv2.imwrite(str(p), _fundus())
            ts = datetime(2024, 6, 1, 12, 0, 0).timestamp() - day * 86400
            os.utime(p, (ts, ts))
            files.append(str(p))
        monkeypatch.setattr(mw, "pick_files", lambda parent=None: files)
        monkeypatch.setattr(mw.FundusImportDialog, "exec", lambda self: bool(self.import_all()))
        n0 = win.thumbnail_panel.count()
        win._import_fundus()
        assert win.thumbnail_panel.count() == n0 + 3
        assert "3장" in win.statusBar().currentMessage()

        QTest.keyClick(win, Qt.Key.Key_F3)                     # 안저 검토 화면으로
        assert win.mode_stack.currentIndex() == 2 and win.btn_mode_fundus.isChecked()
        assert not win._shortcut_objs["capture"].isEnabled()
        assert len(win.fundus.captures()) == 3 and win.fundus.stage_enabled("od")
        assert win.fundus.left.capture().eye == "OD" and win.fundus.right.capture().eye == "OS"
        QTest.keyClick(win.fundus, Qt.Key.Key_Right)           # → 다음 배치
        assert win.fundus.stage() == "od"
        QTest.keyClick(win.fundus, Qt.Key.Key_Left)
        assert win.fundus.stage() == "ou"

        win.fundus.set_active(win.fundus.right)
        target = win.fundus.right.capture()
        win.fundus.b_pro.click()                               # Pro 1화면에서 열기
        assert win.mode_stack.currentIndex() == 1 and win.pro.mode() == "single"
        assert win.pro.captures()[win.pro.current_index()].id == target.id
        QTest.keyClick(win, Qt.Key.Key_F2)                     # 기존 전환 키는 그대로
        assert win.mode_stack.currentIndex() == 0 and win.btn_mode_capture.isChecked()
        win.btn_mode_fundus.click()
        assert win.mode_stack.currentIndex() == 2
        QTest.keyClick(win, Qt.Key.Key_F3)
        assert win.mode_stack.currentIndex() == 0
    finally:
        win.close()
