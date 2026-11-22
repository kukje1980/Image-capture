"""DICOM 전송 · 워크리스트 (dicomnet.py) against a PACS and a worklist server of this test's own
(pynetdicom, on this computer): what is asked, what arrives, and in which form."""
import io
import socket

import numpy as np
import pytest
from PIL import Image

from fundusview import dicomnet
from fundusview.config import Settings
from fundusview.db import Database
from fundusview.demo import synth_fundus, write_demo_dicom
from fundusview.dicomnet import (EXPLICIT_LE, IMPLICIT_LE, JPEG_BASELINE, OP_8BIT, SECONDARY_CAPTURE,
                                 DicomError, Item, Order)

pytest.importorskip("pynetdicom")


class Pacs:
    """A PACS and worklist server that keeps what it was sent and asked."""

    def __init__(self, contexts, orders=()):
        from pynetdicom import AE, evt
        from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification

        self.stored, self.queries, self.callers = [], [], []
        self.orders = list(orders)
        ae = AE(ae_title="TESTPACS")
        ae.add_supported_context(Verification)
        ae.add_supported_context(ModalityWorklistInformationFind)
        for sop, syntaxes in contexts:
            ae.add_supported_context(sop, syntaxes)
        self.server = ae.start_server(("127.0.0.1", 0), block=False, evt_handlers=[
            (evt.EVT_C_STORE, self._store), (evt.EVT_C_FIND, self._find)])
        self.port = self.server.server_address[1]

    def _store(self, event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        self.stored.append(ds)
        self.callers.append(event.assoc.requestor.ae_title)
        return 0x0000

    def _find(self, event):
        self.queries.append(event.identifier)
        for ds in self.orders:
            yield 0xFF00, ds
        yield 0x0000, None

    def settings(self, **more) -> Settings:
        return Settings(pacs_host="127.0.0.1", pacs_port=self.port, pacs_ae="TESTPACS",
                        mwl_host="127.0.0.1", mwl_port=self.port, mwl_ae="TESTPACS", dicom_ae="EYEROOM1", **more)

    def close(self):
        self.server.shutdown()


@pytest.fixture
def pacs():
    servers = []

    def make(contexts=None, orders=()):
        if contexts is None:
            contexts = [(OP_8BIT, [JPEG_BASELINE, EXPLICIT_LE, IMPLICIT_LE]),
                        (SECONDARY_CAPTURE, [JPEG_BASELINE, EXPLICIT_LE, IMPLICIT_LE])]
        servers.append(Pacs(contexts, orders))
        return servers[-1]

    yield make
    for s in servers:
        s.close()


@pytest.fixture
def jpeg(tmp_path):
    rgb = synth_fundus(eye="OD", fov_deg=45, fov_type="external", projection="perspective", size=(240, 200),
                       seed=5)
    path = tmp_path / "IMG_0001.jpg"
    Image.fromarray(rgb).save(path, "JPEG", quality=92)
    return path


def photo(path, **more) -> Item:
    values = dict(image_id=7, path=str(path), sha256="ab" * 32, patient_id="12345", name="홍길동",
                  birth_date="1960-03-05", sex="M", exam_date="2026-11-21", exam_time="10:15:30",
                  laterality="OD", kind="color", device="RetiCam 3100", fov_deg=45.0)
    values.update(more)
    return Item(**values)


def worklist_answer(pid, name, *, charset=("", "ISO 2022 IR 149"), accession="A2026112101", raw_name=None):
    from pydicom.dataset import Dataset

    ds = Dataset()
    if charset is not None:
        ds.SpecificCharacterSet = list(charset)
    ds.PatientID = pid
    if raw_name is None:
        ds.PatientName = name
    else:                                            # bytes as an older server sends them: no character set
        from pydicom.dataelem import DataElement
        ds["PatientName"] = DataElement(0x00100010, "PN", raw_name)
    ds.PatientBirthDate, ds.PatientSex = "19600305", "M"
    ds.AccessionNumber = accession
    ds.StudyInstanceUID = "1.2.410.200001.1.2026." + accession[-4:]
    ds.RequestedProcedureID = "RP" + accession[-4:]
    ds.RequestedProcedureDescription = "Fundus photography"
    step = Dataset()
    step.Modality = "OP"
    step.ScheduledStationAETitle = "EYEROOM1"
    step.ScheduledProcedureStepStartDate, step.ScheduledProcedureStepStartTime = "20261121", "093000"
    step.ScheduledProcedureStepID = "SPS" + accession[-4:]
    step.ScheduledProcedureStepDescription = "안저 촬영" if charset is not None else "Fundus"
    ds.ScheduledProcedureStepSequence = [step]
    return ds


# -- 연결 시험 --------------------------------------------------------------------------------------
def test_echo_answers_and_a_closed_port_says_why(pacs):
    p = pacs()
    s = p.settings()
    dicomnet.echo(s, dicomnet.pacs_node(s))
    with socket.socket() as sock:                    # a port nobody listens on
        sock.bind(("127.0.0.1", 0))
        free = sock.getsockname()[1]
    s.pacs_port = free
    with pytest.raises(DicomError, match="연결하지 못했습니다"):
        dicomnet.echo(s, dicomnet.pacs_node(s), timeout=2)
    with pytest.raises(DicomError, match="설정"):
        dicomnet.echo(Settings(), dicomnet.pacs_node(Settings()))


# -- 워크리스트 -------------------------------------------------------------------------------------
def test_worklist_orders_with_hangul_names(pacs):
    p = pacs(orders=[
        worklist_answer("12345", "Hong^Gildong=홍^길동"),
        worklist_answer("00777", None, charset=None, accession="A2026112102", raw_name="김영희".encode("cp949")),
    ])
    s = p.settings(mwl_own_station=True)
    orders = dicomnet.find_worklist(s, "2026-11-21")
    assert [(o.patient_id, o.name) for o in orders] == [("00777", "김영희"), ("12345", "홍길동")]   # by time, id
    o = orders[1]
    assert (o.pn, o.birth_date, o.sex) == ("Hong^Gildong=홍^길동", "1960-03-05", "M")
    assert (o.date, o.time, o.modality) == ("2026-11-21", "09:30:00", "OP")
    assert (o.accession, o.procedure_id, o.step_id) == ("A2026112101", "RP2101", "SPS2101")
    assert o.study_uid.endswith(".2101") and o.description == "안저 촬영"
    # what was asked: that day, this kind of exam, this station
    step = p.queries[0].ScheduledProcedureStepSequence[0]
    assert step.ScheduledProcedureStepStartDate == "20261121"
    assert step.Modality == "OP" and step.ScheduledStationAETitle == "EYEROOM1"


def test_worklist_asks_for_a_range_and_a_hangul_name(pacs):
    p = pacs()
    s = p.settings(mwl_modality="")
    assert dicomnet.find_worklist(s, "2026-11-20", "2026-11-21", name="홍길", patient_id="123") == []
    q = p.queries[0]
    step = q.ScheduledProcedureStepSequence[0]
    assert step.ScheduledProcedureStepStartDate == "20261120-20261121"
    assert step.Modality == "" and step.ScheduledStationAETitle == ""
    assert str(q.PatientName) == "*홍길*" and q.PatientID == "123"


def test_worklist_without_a_server_says_so():
    with pytest.raises(DicomError, match="설정"):
        dicomnet.find_worklist(Settings(), "2026-11-21")


def test_order_is_kept_for_the_patient_and_day(tmp_path):
    db = Database(tmp_path / "fundus.db")
    order = Order(patient_id="12345", name="홍길동", pn="Hong^Gildong=홍^길동", date="2026-11-21",
                  accession="A1", study_uid="1.2.3")
    db.save_order(order.as_dict())
    db.save_order(order.as_dict())                   # opened twice: one order
    assert db._one("SELECT COUNT(*) FROM orders")[0] == 1
    assert dicomnet.order_of(db.order_for("12345", "2026-11-21")) == order
    assert db.order_for("12345", "2026-11-22") is None
    assert dicomnet.order_of(None) is None
    db.close()


# -- 전송 -----------------------------------------------------------------------------------------
def test_jpeg_goes_as_it_is_under_the_order(pacs, jpeg):
    p = pacs()
    s = p.settings(dicom_institution="국제안과")
    order = Order(patient_id="12345", name="홍길동", pn="Hong^Gildong=홍^길동", date="2026-11-21",
                  accession="A2026112101", study_uid="1.2.410.200001.1.2026.2101", procedure_id="RP2101",
                  step_id="SPS2101", description="안저 촬영")
    seen = []
    results = dicomnet.send(s, [photo(jpeg, order=order)], progress=lambda i, n, r: seen.append((i, n, r)))
    assert [(r.image_id, r.ok, r.message) for r in results] == [(7, True, "")]
    assert seen[0] == (0, 1, None) and seen[-1][:2] == (1, 1) and seen[-1][2].ok
    ds = p.stored[0]
    assert p.callers == ["EYEROOM1"]
    assert ds.SOPClassUID == OP_8BIT and ds.file_meta.TransferSyntaxUID == JPEG_BASELINE
    assert (ds.PatientID, str(ds.PatientName)) == ("12345", "Hong^Gildong=홍^길동")
    assert (ds.PatientBirthDate, ds.PatientSex) == ("19600305", "M")
    assert (ds.AccessionNumber, ds.StudyInstanceUID) == ("A2026112101", "1.2.410.200001.1.2026.2101")
    assert ds.RequestAttributesSequence[0].ScheduledProcedureStepID == "SPS2101"
    assert (ds.StudyDate, ds.ContentTime, ds.ImageLaterality, ds.Modality) == ("20261121", "101530", "R", "OP")
    assert ds.InstitutionName == "국제안과" and ds.HorizontalFieldOfView == 45
    assert ds.PhotometricInterpretation == "YBR_FULL_422" and (ds.Rows, ds.Columns) == (200, 240)
    from pydicom.encaps import generate_frames
    assert next(generate_frames(ds.PixelData)) .rstrip(b"\x00") == jpeg.read_bytes().rstrip(b"\x00")
    # sent again: the same instance, not a second one
    again = dicomnet.send(s, [photo(jpeg, order=order)])
    assert again[0].sop_uid == results[0].sop_uid == p.stored[1].SOPInstanceUID


def test_pacs_without_ophthalmic_photography_or_jpeg_gets_a_plain_secondary_capture(pacs, jpeg):
    p = pacs(contexts=[(SECONDARY_CAPTURE, [IMPLICIT_LE])])
    s = p.settings()
    results = dicomnet.send(s, [photo(jpeg, laterality="OS", name="김영희")])
    assert results[0].ok, results[0].message
    ds = p.stored[0]
    assert ds.SOPClassUID == SECONDARY_CAPTURE and ds.file_meta.TransferSyntaxUID == IMPLICIT_LE
    assert ds.PhotometricInterpretation == "RGB" and ds.Laterality == "L"
    assert str(ds.PatientName) == "김영희" and ds.AccessionNumber == ""
    from fundusview import imaging
    got = np.frombuffer(ds.PixelData, np.uint8)[:200 * 240 * 3].reshape(200, 240, 3)
    assert np.array_equal(got, imaging.load_rgb(jpeg))
    # without an order the study is the patient's exam day: the same for both eyes
    other = dicomnet.wrap_photo(photo(jpeg, laterality="OD", sha256="cd" * 32), s)
    assert other.StudyInstanceUID == ds.StudyInstanceUID and other.SeriesInstanceUID != ds.SeriesInstanceUID
    assert other.SOPInstanceUID != ds.SOPInstanceUID


def test_png_and_composed_pictures(pacs, tmp_path):
    p = pacs()
    s = p.settings(dicom_charset="ISO_IR 192")
    rgb = synth_fundus(eye="OD", fov_deg=45, fov_type="external", projection="perspective", size=(120, 100),
                       seed=2)
    png = tmp_path / "montage.png"
    Image.fromarray(rgb).save(png)
    results = dicomnet.send(s, [photo(png, kind="montage", derived=True), photo(png, image_id=8, sha256="ef" * 32)])
    assert all(r.ok for r in results), [r.message for r in results]
    montage, plain = p.stored
    assert montage.SOPClassUID == SECONDARY_CAPTURE and list(montage.ImageType) == ["DERIVED", "SECONDARY"]
    assert plain.SOPClassUID == OP_8BIT and plain.file_meta.TransferSyntaxUID in (EXPLICIT_LE, IMPLICIT_LE)
    assert plain.SpecificCharacterSet == "ISO_IR 192" and str(plain.PatientName) == "홍길동"
    assert np.array_equal(np.frombuffer(plain.PixelData, np.uint8)[:rgb.size].reshape(rgb.shape), rgb)


def test_setting_secondary_capture_and_no_jpeg(jpeg):
    s = Settings(dicom_sop="sc", dicom_jpeg=False)
    ds = dicomnet.dataset_of(photo(jpeg), s)
    assert ds.SOPClassUID == SECONDARY_CAPTURE and ds.file_meta.TransferSyntaxUID == EXPLICIT_LE
    assert ds.LossyImageCompression == "01"          # it was a JPEG, whatever is sent


def test_turned_or_progressive_jpeg_is_not_sent_as_it_is(tmp_path):
    rgb = synth_fundus(eye="OD", fov_deg=45, fov_type="external", projection="perspective", size=(120, 100),
                       seed=2)
    turned = tmp_path / "turned.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.fromarray(rgb).save(turned, "JPEG", exif=exif)
    ds = dicomnet.dataset_of(photo(turned), Settings())
    assert ds.file_meta.TransferSyntaxUID == EXPLICIT_LE and (ds.Rows, ds.Columns) == (120, 100)   # as shown
    progressive = tmp_path / "progressive.jpg"
    Image.fromarray(rgb).save(progressive, "JPEG", progressive=True)
    assert dicomnet.dataset_of(photo(progressive), Settings()).file_meta.TransferSyntaxUID == EXPLICIT_LE


def test_dicom_file_goes_unchanged_unless_the_viewer_knows_better(pacs, tmp_path):
    import pydicom

    path = write_demo_dicom(tmp_path / "OP_demo.dcm", small=True)
    original = pydicom.dcmread(path)
    p = pacs()
    s = p.settings()
    # These cases change only the name/order; use the source's actual eye and acquisition
    # timestamp rather than photo()'s unrelated defaults, which are real corrections now.
    same_info = dict(patient_id="D0009876", birth_date="1979-03-12", sex="F", laterality="OS",
                     exam_date="2026-01-20", exam_time="11:15:02")
    same = photo(path, name="최유나", **same_info)
    fixed = photo(path, image_id=8, name="최윤아", **same_info)
    ordered = photo(path, image_id=9, name="최유나", **same_info,
                    order=Order(patient_id="D0009876", name="최유나", accession="ACC9", study_uid="1.2.3.9"))
    results = dicomnet.send(s, [same, fixed, ordered])
    assert all(r.ok for r in results), [r.message for r in results]
    a, b, c = p.stored
    assert str(a.PatientName) == str(original.PatientName) and a.SOPInstanceUID == original.SOPInstanceUID
    assert a.StudyInstanceUID == original.StudyInstanceUID and a.PixelData == original.PixelData
    assert str(b.PatientName) == "최윤아" and b.PatientID == "D0009876"
    assert b.SOPInstanceUID == original.SOPInstanceUID
    assert (c.AccessionNumber, c.StudyInstanceUID) == ("ACC9", "1.2.3.9")
    assert str(c.PatientName) == str(original.PatientName)


def test_dicom_file_with_undeclared_korean_text_is_declared(pacs, tmp_path):
    """VK-2 and older stations write CP949 bytes without a character set: sent with one."""
    import pydicom

    path = write_demo_dicom(tmp_path / "old.dcm", small=True)
    ds = pydicom.dcmread(path)
    del ds.SpecificCharacterSet
    ds.PatientName = "x"
    ds.InstitutionName = "y"
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    data = buf.getvalue()

    def swap(data, tag, old, new):                   # the value bytes of an explicit VR element
        i = data.index(tag)
        assert data[i + 8:i + 8 + len(old)] == old
        return data[:i + 6] + len(new).to_bytes(2, "little") + new + data[i + 8 + len(old):]

    data = swap(data, b"\x10\x00\x10\x00PN", b"x ", "최유나".encode("cp949"))
    data = swap(data, b"\x08\x00\x80\x00LO", b"y ", "국제안과".encode("cp949"))
    path.write_bytes(data)
    p = pacs()
    results = dicomnet.send(p.settings(), [photo(path, patient_id="D0009876", name="최유나", birth_date="",
                                                 sex="")])
    assert results[0].ok, results[0].message
    got = p.stored[0]
    assert list(got.SpecificCharacterSet) == ["", "ISO 2022 IR 149"]
    assert str(got.PatientName) == "최유나" and got.InstitutionName == "국제안과"


def test_one_bad_photo_does_not_stop_the_others(pacs, jpeg, tmp_path):
    p = pacs()
    results = dicomnet.send(p.settings(), [photo(tmp_path / "gone.jpg", image_id=1), photo(jpeg, image_id=2)])
    assert [(r.image_id, r.ok) for r in results] == [(1, False), (2, True)]
    assert "찾을 수 없습니다" in results[0].message and len(p.stored) == 1


def test_no_pacs_is_an_error_not_a_silent_nothing(jpeg):
    with pytest.raises(DicomError, match="설정"):
        dicomnet.send(Settings(), [photo(jpeg)])


def test_saved_dicom_file_reads_back(jpeg, tmp_path):
    import pydicom

    dest = dicomnet.save_dicom(photo(jpeg), Settings(), tmp_path / "out.dcm")
    ds = pydicom.dcmread(dest)
    assert ds.SOPClassUID == OP_8BIT and str(ds.PatientName) == "홍길동"
    from fundusview import imaging
    assert imaging.load_rgb(dest).shape == (200, 240, 3)
