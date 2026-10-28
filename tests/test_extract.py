import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fundusview.extract import extract_metadata
from fundusview.extract.apollo_meta import _png_header
from fundusview.extract.filename_meta import filename_meta
from fundusview.profiles import KOWA_PATTERNS


def _jpeg(path: Path, comment: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    kw = {"comment": comment.encode()} if comment else {}
    Image.fromarray(np.zeros((32, 32, 3), np.uint8)).save(path, **kw)
    return path


# -- Microclear APOLLO -----------------------------------------------------------
def test_apollo_demo_files(demo_dir):
    files = sorted((demo_dir / "PatientCapture").rglob("*.jpg"))
    assert len(files) == 3
    metas = [extract_metadata(p, watch_root=demo_dir) for p in files]
    m, prof = metas[0]
    assert prof.key == "apollo"
    assert (m.patient_id, m.name, m.exam_date, m.exam_time, m.laterality) == (
        "20260115001", "김민수", "2026-01-15", "10:20:31", "OD")
    assert (m.fov_deg, m.fov_type, m.device, m.modality) == (135.0, "internal", "Microclear APOLLO WA", "color")
    assert metas[1][0].laterality == "OS"              # Eye: 0
    assert metas[2][0].fov_deg == 165.0                # FieldAngle 112 -> UWA
    assert metas[2][0].device == "Microclear APOLLO UWA"


def test_apollo_comment_outside_its_folder(tmp_path):
    """A file copied out of PatientCapture still names its patient via the JSON paths."""
    comment = "Description: " + json.dumps({
        "ArchivedDT": "2024-10-08 10:46:27", "DevModel": 3007, "Eye": 0, "FieldAngle": 90, "ImgType": 5,
        "ExtraInfo": {"MColorRedPath": "PatientCapture/20241008001_TESTER/2024_10_08/IR/x_IR_R.jpg",
                      "SWVersion": "2.0.004.3,90D"}})
    p = _jpeg(tmp_path / "copied.jpg", comment)
    m, prof = extract_metadata(p)
    assert prof.key == "apollo"
    assert (m.patient_id, m.name, m.laterality, m.modality, m.fov_deg) == (
        "20241008001", "TESTER", "OS", "redfree", 135.0)
    assert m.description is None  # the JSON blob must not leak into the description


def test_apollo_filename_variants():
    from fundusview.extract.apollo_meta import FILENAME
    for stem, mode, eye in (("2025_07_29_16_38_42.443_ART(21)_FFA", "FFA", None),
                            ("2024_06_13_16_10_56.246_ART(8-8)_ICGA-FFA (1)", "ICGA-FFA", None),
                            ("2024_10_08_10_46_27.573_RF_B", "RF", None),
                            ("2025_01_02_09_00_00.000_Mosaic_COLOR_OD_135°", "Mosaic_COLOR", "OD")):
        m = FILENAME.match(stem)
        assert m and m.group("mode") == mode and m.group("eye") == eye, stem


def test_apollo_png_header():
    head = (b"\x00\x00\x00\x02" + b"\x00\x00\x00\x13" + b"2026-02-06 11:09:52" + b"\x00\x01\x00\x71"
            + b"\x00\x00\x00\x5a" + b"\x00" * 16)
    assert _png_header(head) == {"ArchivedDT": "2026-02-06 11:09:52", "Eye": 1, "FieldAngle": 90}
    assert _png_header(b"garbage") == {}


# -- Kowa VK-2 ---------------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("AB-12_20240305_101500_R_FUNDUS (COLOR)_1.jpg", ("AB-12", "2024-03-05", "10:15:00", "OD", "color")),
    ("108-1_20240305_101500_FUNDUS(COLOR)_L_01.jpg", ("108-1", "2024-03-05", "10:15:00", "OS", "color")),
    ("ID_7_20240305_101500_KOWA_FAF_R.jpg", ("ID_7", "2024-03-05", "10:15:00", "OD", "af")),
    ("P1_20240305_101500_L_RED FREE_2.jpg", ("P1", "2024-03-05", "10:15:00", "OS", "redfree")),
])
def test_kowa_export_tool_names(name, expected):
    m = filename_meta(Path(name), KOWA_PATTERNS)
    assert (m.patient_id, m.exam_date, m.exam_time, m.laterality, m.modality) == expected


def test_kowa_native_store_is_unassigned(tmp_path):
    p = _jpeg(tmp_path / "vk_3x" / "-000512" / "vk000005.jpg")
    m, prof = extract_metadata(p, "kowa_vk2", watch_root=tmp_path)
    assert m.patient_id is None and m.raw.get("일련번호") == "000005"


def test_joia_xml_sidecar(demo_dir):
    p = demo_dir / "VK2_Export" / "D0001235_20260110_094500_KOWA_COLOR_L.jpg"
    m, prof = extract_metadata(p)
    assert prof.key == "kowa_vk2"
    assert (m.patient_id, m.name, m.birth_date, m.sex, m.laterality) == ("D0001235", "박지호", "1968-04-21", "F", "OS")
    assert m.sources["name"] == "sidecar.xml"


def test_id_only_profile(tmp_path):
    p = _jpeg(tmp_path / "A12345_3.jpg")
    assert extract_metadata(p, "generic")[0].patient_id is None
    assert extract_metadata(p, "kowa_vk2_id")[0].patient_id == "A12345"


# -- DICOM ------------------------------------------------------------------------
def test_dicom_korean_name(demo_dir):
    m, prof = extract_metadata(demo_dir / "DICOM" / "OP_demo_0001.dcm")
    assert prof.key == "kowa_vk2"  # Manufacturer KOWA
    assert (m.patient_id, m.name, m.birth_date, m.sex, m.laterality) == ("D0009876", "최유나", "1979-03-12", "F", "OS")
    assert (m.fov_deg, m.fov_type, m.exam_date, m.exam_time) == (45.0, "external", "2026-01-20", "11:15:02")


@pytest.mark.filterwarnings("ignore:Found unknown escape sequence")  # writing the fixture
def test_dicom_undeclared_cp949(tmp_path):
    """VK-2 writes no Specific Character Set; Korean bytes are CP949 (with ISO 2022 escapes)."""
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = "1.2.3"
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(tmp_path / "x.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientID = "777"
    ds.PatientName = pydicom.valuerep.PersonName(b"HONG^GILDONG=\x1b$)C" + "홍^길동".encode("cp949"))
    ds.save_as(str(tmp_path / "x.dcm"), enforce_file_format=True)
    m, _ = extract_metadata(tmp_path / "x.dcm")
    assert (m.patient_id, m.name) == ("777", "홍길동")


# -- generic -----------------------------------------------------------------------
@pytest.mark.parametrize("rel,expected", [
    ("12345_홍길동_20240305_OD.jpg", ("12345", "홍길동", "2024-03-05", "OD")),
    ("20240305_101500_A777_이영희_OS.png", ("A777", "이영희", "2024-03-05", "OS")),
    ("12345678_김철수.jpg", ("12345678", "김철수", None, None)),
    ("P-99 홍길동/20240305/IMG_0001_RE.jpg", ("P-99", "홍길동", "2024-03-05", "OD")),
])
def test_generic_names_and_folders(tmp_path, rel, expected):
    p = _jpeg(tmp_path / rel)
    m = filename_meta(p, watch_root=tmp_path)
    assert (m.patient_id, m.name, m.exam_date, m.laterality) == expected


def test_photo_without_data_falls_back_to_file_time(demo_dir):
    m, prof = extract_metadata(demo_dir / "기타" / "IMG_0001.jpg")
    assert m.patient_id is None and m.sources["exam_date"] == "file-time"
    assert prof.key == "generic" and m.fov_deg == 45.0


@pytest.mark.parametrize("name", ["IMG_20240305_101500.jpg", "Capture_20240305_OD.jpg",
                                  "DSC_FUNDUS_20240305.jpg", "fundus_20240305.jpg"])
def test_camera_file_names_are_not_patient_ids(tmp_path, name):
    m, _ = extract_metadata(_jpeg(tmp_path / name))
    assert m.patient_id is None
    assert m.exam_date == "2024-03-05"  # the date is still used


# -- SYSEYE RetiCam ------------------------------------------------------------------
def test_reticam_demo_files(demo_dir):
    rc = demo_dir / "RetiCam"
    m, prof = extract_metadata(rc / "정하늘-od-color-20260310-101530-123.jpg")
    assert prof.key == "reticam"
    assert (m.patient_id, m.name, m.birth_date, m.sex, m.laterality) == (
        "PID20260310-0A1B2C3D", "정하늘", "1975-05-05", "F", "OD")
    # the file name's local time wins over the JSON's (hour-shifted) dateTime
    assert (m.exam_date, m.exam_time, m.sources["exam_time"]) == ("2026-03-10", "10:15:30", "filename")
    assert (m.fov_deg, m.fov_type, m.projection, m.device) == (176.0, "internal", "radial",
                                                               "SYSEYE RetiCam 3100 Plus")
    mont, _ = extract_metadata(rc / "정하늘-od-color-20260310-102010-789.jpg")
    assert (mont.modality, mont.fov_deg) == ("montage", 220.0)
    anon, _ = extract_metadata(rc / "Anonymous-os-color-20260311-090000-001.jpg")
    assert anon.patient_id is None and anon.name is None and anon.birth_date is None
    assert anon.laterality == "OS"


def test_reticam_json_without_filename_and_old_50deg(tmp_path):
    """A renamed copy is still recognised by its APP15 record; a 2023-era
    50°-class frame (no ellipse keys, ~2700 px) maps as an ordinary camera."""
    import io
    from fundusview.demo import with_app15
    buf = io.BytesIO()
    Image.fromarray(np.zeros((2048 // 8, 2730 // 8, 3), np.uint8)).save(buf, "JPEG")
    rec = {"dateTime": "2023/06/13 07:31:08.441", "eyeLaterality": "OS", "irisMaskRadius": 0.95,
           "modeID": 1, "patientBornDate": "1960/02/03", "patientFirstName": "길동", "patientLastName": "홍",
           "patientID": "A-77", "patientSex": "M", "version": 256}
    p = tmp_path / "copy.jpg"
    p.write_bytes(with_app15(buf.getvalue(), json.dumps(rec, ensure_ascii=False).encode()))
    m, prof = extract_metadata(p)
    assert prof.key == "reticam"
    assert (m.patient_id, m.name, m.sex, m.exam_time) == ("A-77", "홍길동", "M", "07:31:08")
    assert (m.fov_deg, m.fov_type, m.projection) == (50.0, "external", "perspective")


def test_reticam_tiff_with_jpg_extension(tmp_path):
    """Some exports are TIFF data named .jpg; the record is then in a TIFF tag."""
    rec = {"patientID": "T-1", "patientName": "김테스트", "eyeLaterality": "OD", "modeID": 1,
           "irisMaskEllipseLMaxis": -1}
    p = tmp_path / "김테스트-od-color-20240529-111213-000.jpg"
    Image.fromarray(np.zeros((64, 64, 3), np.uint8)).save(
        p, "TIFF", tiffinfo={270: json.dumps(rec, ensure_ascii=False).encode("utf-8")})
    m, prof = extract_metadata(p)
    assert prof.key == "reticam" and (m.patient_id, m.name, m.laterality) == ("T-1", "김테스트", "OD")
    assert m.fov_deg == 176.0
