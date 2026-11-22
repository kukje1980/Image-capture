"""DICOM network: sending photos to a PACS (C-STORE) and the modality worklist (MWL C-FIND).

설정 → DICOM says where the PACS and the worklist server are (host, port, AE title) and what this
program calls itself (its own AE title — the PACS must know it).

**전송.** A photo that came as a DICOM file keeps its pixels and original metadata except for the
patient, eye and acquisition information corrected in the viewer, or a selected worklist order.
Reassigned patients and converted pixel representations use deterministic identifiers, so retries
remain the same instance. A JPEG / PNG photo is wrapped into an
*Ophthalmic Photography 8 Bit Image* (a composed picture — 몽타주, 디스크 2장, 녹내장 분석, an edited
copy — into a *Secondary Capture Image*). A JPEG goes as it is (JPEG Baseline, no second
compression) when the PACS takes that, otherwise uncompressed; a PACS that does not take
Ophthalmic Photography gets a Secondary Capture. The UIDs are made from the photo itself, so
a photo sent twice arrives as the same instance, not as a second one.

**워크리스트.** The orders of a day are asked from the worklist server. The order a patient was
opened with is kept in the database (``Database.save_order``); a photo of that patient and day
is then sent with the order's Accession Number and Study Instance UID, which is what lets the
PACS put it under the order.

Nothing here touches Qt; ``pynetdicom`` is imported only when something is sent or asked.
"""
from __future__ import annotations

import hashlib
import json
import re
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from . import __version__
from .config import Settings
from .extract.dicom_meta import is_dicom, pn_text
from .extract.normalize import clean_name, has_hangul, norm_date, norm_sex, norm_time

OP_8BIT = "1.2.840.10008.5.1.4.1.1.77.1.5.1"      # Ophthalmic Photography 8 Bit Image Storage
SECONDARY_CAPTURE = "1.2.840.10008.5.1.4.1.1.7"
JPEG_BASELINE = "1.2.840.10008.1.2.4.50"
EXPLICIT_LE = "1.2.840.10008.1.2.1"
IMPLICIT_LE = "1.2.840.10008.1.2"
UNCOMPRESSED = (EXPLICIT_LE, IMPLICIT_LE)

CHARSET_KOREAN = "ISO 2022 IR 149"                 # KS X 1001 — what Korean PACS expect
CHARSET_UTF8 = "ISO_IR 192"
CHARSETS = ((CHARSET_KOREAN, "한글 (ISO 2022 IR 149) — 국내 PACS"), (CHARSET_UTF8, "UTF-8 (ISO_IR 192)"))

# photos the viewer made itself: sent as Secondary Capture, "DERIVED"
COMPOSED = ("montage", "disc", "glaucoma")
SERIES_TEXT = {"color": "Color fundus", "redfree": "Red-free", "af": "Fundus autofluorescence",
               "fa": "Fluorescein angiography", "icg": "ICG angiography", "ir": "Infrared",
               "anterior": "Anterior segment", "montage": "Montage", "disc": "Optic disc pair",
               "glaucoma": "Glaucoma analysis"}
EYES = {"OD": "R", "OS": "L", "OU": "B"}


class DicomError(Exception):
    """What went wrong, in words for the user."""


# ---------------------------------------------------------------------------------------------
# where to
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Node:
    host: str
    port: int
    ae_title: str

    @property
    def ok(self) -> bool:
        return bool(self.host.strip()) and 0 < int(self.port) < 65536

    @property
    def label(self) -> str:
        return f"{self.ae_title or 'ANY-SCP'}@{self.host}:{self.port}"


def pacs_node(s: Settings) -> Node:
    return Node(s.pacs_host.strip(), int(s.pacs_port or 0), s.pacs_ae.strip())


def worklist_node(s: Settings) -> Node:
    return Node(s.mwl_host.strip(), int(s.mwl_port or 0), s.mwl_ae.strip())


def own_ae(s: Settings) -> str:
    return (s.dicom_ae or "").strip()[:16] or "FUNDUSVIEWER"


def _charset(s: Settings) -> str:
    return s.dicom_charset if s.dicom_charset in (CHARSET_KOREAN, CHARSET_UTF8) else CHARSET_KOREAN


def _charset_value(charset: str):
    """The Specific Character Set to write: Korean is declared as ``\\ISO 2022 IR 149`` (ASCII,
    switching to KS X 1001 by escape sequence)."""
    return ["", CHARSET_KOREAN] if charset == CHARSET_KOREAN else charset


def _ascii(text: str) -> bool:
    return all(ord(c) < 128 for c in text or "")


def _associate(s: Settings, node: Node, contexts: Iterable[tuple[str, list[str]]], timeout: float):
    """An association with ``node`` asking for ``contexts`` — or a :class:`DicomError` saying why not."""
    if not node.ok:
        raise DicomError("서버 주소와 포트가 설정되지 않았습니다 — 설정 → DICOM")
    from pynetdicom import AE

    ae = AE(ae_title=own_ae(s))
    ae.acse_timeout = ae.connection_timeout = timeout
    ae.dimse_timeout = ae.network_timeout = max(timeout, 30.0)
    for abstract, syntaxes in contexts:
        ae.add_requested_context(abstract, syntaxes)
    try:
        assoc = ae.associate(node.host, node.port, ae_title=node.ae_title or "ANY-SCP")
    except Exception as exc:                         # a host name that does not resolve, …
        raise DicomError(f"{node.host}:{node.port}에 연결하지 못했습니다 — {exc}") from exc
    if assoc.is_established:
        return assoc
    if assoc.is_rejected:
        raise DicomError(f"서버({node.label})가 연결을 거부했습니다 — AE Title을 확인하세요 "
                         f"(이 프로그램: {own_ae(s)} — 서버에 등록되어 있어야 합니다)")
    raise DicomError(f"{node.host}:{node.port}에 연결하지 못했습니다 — 주소 · 포트 · 방화벽을 확인하세요")


def _close(assoc) -> None:
    try:
        if assoc.is_established:
            assoc.release()
        else:
            assoc.abort()
    except Exception:
        pass


def echo(s: Settings, node: Node, timeout: float = 8.0) -> None:
    """연결 시험 (C-ECHO): returns when the server answered, raises :class:`DicomError` otherwise."""
    from pynetdicom.sop_class import Verification

    assoc = _associate(s, node, [(Verification, [EXPLICIT_LE, IMPLICIT_LE])], timeout)
    try:
        status = assoc.send_c_echo()
        if not status or status.Status != 0x0000:
            raise DicomError("서버가 연결 시험(C-ECHO)에 답하지 않았습니다")
    finally:
        _close(assoc)


# ---------------------------------------------------------------------------------------------
# 워크리스트
# ---------------------------------------------------------------------------------------------
@dataclass
class Order:
    """One scheduled exam of the worklist."""
    patient_id: str = ""
    name: str = ""                # as the viewer shows it (the Hangul group of the name)
    pn: str = ""                  # Patient's Name as the server wrote it — sent back unchanged
    birth_date: str = ""          # YYYY-MM-DD
    sex: str = ""                 # M / F / O
    date: str = ""                # scheduled: YYYY-MM-DD
    time: str = ""                # HH:MM:SS
    modality: str = ""
    accession: str = ""
    study_uid: str = ""
    description: str = ""         # what is to be done
    procedure_id: str = ""        # Requested Procedure ID
    step_id: str = ""             # Scheduled Procedure Step ID
    station: str = ""             # Scheduled Station AE Title
    physician: str = ""           # Referring Physician
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Order | None":
        if not data:
            return None
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__ and v is not None})


def order_of(row) -> Order | None:
    """The :class:`Order` kept in a row of ``Database.order_for``."""
    if row is None:
        return None
    try:
        return Order.from_dict(json.loads(row["data_json"] or "{}"))
    except (ValueError, TypeError, KeyError):
        return None


def _text(ds, keyword: str) -> str:
    v = ds.get(keyword)
    return "" if v is None else str(v).strip()


def _display_name(pn: str) -> str:
    groups = [g for g in pn.split("=") if g.strip()]
    for g in groups:
        if has_hangul(g):
            return clean_name(g) or ""
    return (clean_name(groups[0]) or "") if groups else ""


def order_from_dataset(ds) -> Order:
    """A worklist answer as an :class:`Order` (also for names sent without a declared character set)."""
    steps = ds.get("ScheduledProcedureStepSequence")
    step = steps[0] if steps else None
    get = (lambda kw: _text(step, kw)) if step is not None else (lambda kw: "")
    pn = pn_text(ds, "PatientName")
    description = (get("ScheduledProcedureStepDescription") or _text(ds, "RequestedProcedureDescription"))
    if not description and step is not None:
        codes = step.get("ScheduledProtocolCodeSequence")
        description = _text(codes[0], "CodeMeaning") if codes else ""
    return Order(
        patient_id=_text(ds, "PatientID").replace(" ", ""),
        name=_display_name(pn), pn=pn,
        birth_date=norm_date(_text(ds, "PatientBirthDate")) or "",
        sex=norm_sex(_text(ds, "PatientSex")) or "",
        date=norm_date(get("ScheduledProcedureStepStartDate")[:8], min_year=1990) or "",
        time=norm_time(get("ScheduledProcedureStepStartTime")) or "",
        modality=get("Modality"),
        accession=_text(ds, "AccessionNumber"),
        study_uid=_text(ds, "StudyInstanceUID"),
        description=description,
        procedure_id=_text(ds, "RequestedProcedureID"),
        step_id=get("ScheduledProcedureStepID"),
        station=get("ScheduledStationAETitle"),
        physician=_display_name(pn_text(ds, "ReferringPhysicianName")),
    )


def worklist_query(s: Settings, start: str, end: str | None = None, *, patient_id: str = "",
                   name: str = ""):
    """The C-FIND identifier asking for the orders of ``start`` … ``end`` (YYYY-MM-DD)."""
    from pydicom.dataset import Dataset

    def day(text: str | None) -> str:
        return (text or "").replace("-", "")

    ds = Dataset()
    charset = _charset(s)
    if not _ascii(name):                             # a Hangul name can only be asked for with its character set
        ds.SpecificCharacterSet = _charset_value(charset)
    else:
        ds.SpecificCharacterSet = ""
    ds.AccessionNumber = ""
    ds.ReferringPhysicianName = ""
    ds.PatientName = f"*{name.strip()}*" if name.strip() else ""
    ds.PatientID = patient_id.strip()
    ds.PatientBirthDate = ""
    ds.PatientSex = ""
    ds.StudyInstanceUID = ""
    ds.RequestedProcedureDescription = ""
    ds.RequestedProcedureID = ""
    step = Dataset()
    step.Modality = (s.mwl_modality or "").strip().upper()
    step.ScheduledStationAETitle = own_ae(s) if s.mwl_own_station else ""
    a, b = day(start), day(end or start)
    step.ScheduledProcedureStepStartDate = a if a == b else f"{a}-{b}"
    step.ScheduledProcedureStepStartTime = ""
    step.ScheduledPerformingPhysicianName = ""
    step.ScheduledProcedureStepDescription = ""
    step.ScheduledProcedureStepID = ""
    step.ScheduledProtocolCodeSequence = []
    ds.ScheduledProcedureStepSequence = [step]
    return ds


def find_worklist(s: Settings, start: str, end: str | None = None, *, patient_id: str = "", name: str = "",
                  timeout: float = 10.0) -> list[Order]:
    """The orders of ``start`` … ``end`` on the worklist server, by time."""
    from pynetdicom.sop_class import ModalityWorklistInformationFind as MWL

    query = worklist_query(s, start, end, patient_id=patient_id, name=name)
    assoc = _associate(s, worklist_node(s), [(MWL, [EXPLICIT_LE, IMPLICIT_LE])], timeout)
    orders: list[Order] = []
    try:
        with warnings.catch_warnings():              # undeclared character sets are expected
            warnings.simplefilter("ignore")
            for status, identifier in assoc.send_c_find(query, MWL):
                if status is None:
                    raise DicomError("워크리스트 서버가 답하지 않았습니다 (시간 초과)")
                code = status.Status
                if code in (0xFF00, 0xFF01) and identifier is not None:
                    orders.append(order_from_dataset(identifier))
                elif code not in (0x0000, 0xFF00, 0xFF01):
                    if code == 0xFE00:
                        break
                    raise DicomError(f"워크리스트 서버가 조회를 받지 않았습니다 (상태 0x{code:04X})")
    except DicomError:
        raise
    except Exception as exc:
        raise DicomError(f"워크리스트를 읽지 못했습니다 — {exc}") from exc
    finally:
        _close(assoc)
    orders.sort(key=lambda o: (o.date, o.time, o.patient_id))
    return orders


# ---------------------------------------------------------------------------------------------
# what is sent
# ---------------------------------------------------------------------------------------------
def make_uid(*parts) -> str:
    """A UID that is the same whenever it is made from the same ``parts`` (2.25.<128 bit number>)."""
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
    return "2.25." + str(int.from_bytes(digest[:16], "big"))


@dataclass
class Item:
    """A photo to send: the file and what the viewer knows about it."""
    image_id: int
    path: str                     # the stored file (a DICOM file, a JPEG, a PNG …)
    sha256: str
    patient_id: str
    name: str = ""
    birth_date: str = ""
    sex: str = ""
    exam_date: str = ""
    exam_time: str = ""
    laterality: str = ""
    kind: str = ""                # key of models.MODALITY_LABELS
    device: str = ""
    fov_deg: float | None = None
    note: str = ""
    derived: bool = False         # made by the viewer (an edited copy, a montage …)
    order: Order | None = None
    label: str = ""               # for messages: "OD 2026-11-21 컬러"
    metadata_authoritative: bool = False  # DB values include explicit user-cleared fields


def item_of(row, patient, order: Order | None = None, label: str = "", path: str | None = None) -> Item:
    """The :class:`Item` of an ``images`` row and its ``patients`` row (``path``: the file, when the
    caller looks it up itself)."""
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    kind = row["modality"] or ""
    return Item(
        image_id=row["id"], path=(row["file_path"] or "") if path is None else path, sha256=row["sha256"] or "",
        patient_id=patient["patient_id"] or "", name=patient["name"] or "",
        birth_date=patient["birth_date"] or "", sex=patient["sex"] or "",
        exam_date=row["exam_date"] or "", exam_time=row["exam_time"] or "",
        laterality=row["laterality"] or "", kind=kind, device=row["device"] or "",
        fov_deg=row["fov_deg"], note=row["note"] or "",
        derived=kind in COMPOSED or meta.get("derived_from") is not None,
        order=order, label=label, metadata_authoritative=True,
    )


def _da(text: str) -> str:
    return (text or "").replace("-", "")[:8]


def _tm(text: str) -> str:
    return (text or "").replace(":", "")[:6]


def _patient_name(item: Item) -> str:
    """The name to write: the worklist's own spelling while the viewer still shows that patient
    under that name, else the viewer's."""
    o = item.order
    if o is not None and o.pn and (not item.name or item.name == o.name):
        return o.pn
    return item.name


def _study_uid(item: Item, own: str = "") -> str:
    if item.order is not None and item.order.study_uid:
        return item.order.study_uid
    return own or make_uid("study", item.patient_id, item.exam_date or "undated")


def _set_text(ds, s: Settings, **values) -> None:
    """Write text values; text beyond ASCII declares the character set of the settings."""
    if not all(_ascii(v) for v in values.values()):
        ds.SpecificCharacterSet = _charset_value(_charset(s))
    for keyword, value in values.items():
        setattr(ds, keyword, value)


def _code(value: str, scheme: str, meaning: str):
    from pydicom.dataset import Dataset

    c = Dataset()
    c.CodeValue, c.CodingSchemeDesignator, c.CodeMeaning = value, scheme, meaning
    return c


def _jpeg_as_is(path: Path) -> tuple[bytes, int, int, int] | None:
    """The bytes of a baseline JPEG that can travel unchanged, with its width, height and samples —
    ``None`` for anything else (progressive, turned by EXIF, CMYK …)."""
    from PIL import Image

    try:
        with Image.open(path) as img:
            if img.format != "JPEG" or img.mode not in ("RGB", "L"):
                return None
            if img.info.get("progressive") or img.info.get("progression"):
                return None
            if img.info.get("adobe_transform") == 0:           # RGB stored without the YCbCr transform
                return None
            if img.getexif().get(0x0112, 1) not in (1, None):  # the viewer shows it turned
                return None
            w, h, samples = img.width, img.height, len(img.getbands())
    except Exception:
        return None
    data = path.read_bytes()
    return (data, w, h, samples) if data[:2] == b"\xff\xd8" else None


def _put_pixels(ds, rgb) -> None:
    """Uncompressed 8-bit RGB pixels (Explicit VR Little Endian)."""
    import numpy as np

    rgb = np.ascontiguousarray(rgb[..., :3], dtype=np.uint8)
    ds.Rows, ds.Columns = int(rgb.shape[0]), int(rgb.shape[1])
    ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PlanarConfiguration = 3, "RGB", 0
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
    data = rgb.tobytes()
    ds.PixelData = data + (b"\x00" if len(data) % 2 else b"")
    ds["PixelData"].VR = "OB"
    ds["PixelData"].is_undefined_length = False
    ds.LossyImageCompression = "00"
    for kw in ("LossyImageCompressionMethod", "LossyImageCompressionRatio"):
        if kw in ds:
            delattr(ds, kw)
    ds.file_meta.TransferSyntaxUID = EXPLICIT_LE


def _put_jpeg(ds, data: bytes, w: int, h: int, samples: int) -> None:
    from pydicom.encaps import encapsulate

    ds.Rows, ds.Columns = h, w
    ds.SamplesPerPixel = samples
    if samples == 3:
        ds.PhotometricInterpretation, ds.PlanarConfiguration = "YBR_FULL_422", 0
    else:
        ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
    ds.PixelData = encapsulate([data])
    ds["PixelData"].VR = "OB"
    ds["PixelData"].is_undefined_length = True
    ds.LossyImageCompression = "01"
    ds.LossyImageCompressionMethod = "ISO_10918_1"
    ds.file_meta.TransferSyntaxUID = JPEG_BASELINE


def wrap_photo(item: Item, s: Settings, *, jpeg: bool = True, sop_class: str | None = None):
    """A JPEG / PNG photo of the library as a DICOM dataset (``sop_class``: as the settings say;
    a picture the viewer composed is always a Secondary Capture)."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import PYDICOM_IMPLEMENTATION_UID

    path = Path(item.path)
    if sop_class is None:
        sop_class = SECONDARY_CAPTURE if (item.derived or s.dicom_sop == "sc") else OP_8BIT
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = sop_class
    ds.file_meta.MediaStorageSOPInstanceUID = make_uid("sop", item.sha256 or item.path)
    ds.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    ds.file_meta.ImplementationVersionName = f"FUNDUSVIEW{__version__.replace('.', '')}"[:16]
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID

    order = item.order
    now = datetime.now()
    date = _da(item.exam_date) or now.strftime("%Y%m%d")
    time = _tm(item.exam_time)
    description = (order.description if order else "") or "Fundus photography"
    # -- patient · study · series -------------------------------------------------------------
    _set_text(ds, s, PatientName=_patient_name(item), PatientID=item.patient_id,
              StudyDescription=description,
              ReferringPhysicianName=(order.physician if order else ""),
              InstitutionName=(s.dicom_institution or "").strip(),
              ImageComments=(item.note or "")[:1024])
    ds.PatientBirthDate = _da(item.birth_date)
    ds.PatientSex = item.sex if item.sex in ("M", "F", "O") else ""
    ds.StudyInstanceUID = _study_uid(item)
    ds.StudyDate = _da(order.date) if order is not None and order.date else date
    ds.StudyTime = _tm(order.time) if order is not None and order.time else time
    ds.AccessionNumber = order.accession if order else ""
    ds.StudyID = (order.procedure_id if order else "")[:16]
    if order is not None and (order.procedure_id or order.step_id):
        ref = Dataset()
        ref.AccessionNumber = order.accession
        ref.StudyInstanceUID = ds.StudyInstanceUID
        ref.RequestedProcedureID = order.procedure_id
        ref.ScheduledProcedureStepID = order.step_id
        ref.RequestedProcedureDescription = order.description if _ascii(order.description) else ""
        ds.RequestAttributesSequence = [ref]
    eye = EYES.get(item.laterality, "")
    ds.Modality = (s.mwl_modality or "").strip().upper() or "OP"
    ds.SeriesInstanceUID = make_uid("series", ds.StudyInstanceUID, eye, item.kind, item.derived)
    ds.SeriesNumber = {"R": 1, "L": 2}.get(eye, 3) + (10 if item.derived else 0)
    ds.SeriesDate, ds.SeriesTime = date, time
    ds.SeriesDescription = " ".join(filter(None, (SERIES_TEXT.get(item.kind, "Fundus"), item.laterality)))
    ds.InstanceNumber = int(item.image_id)
    ds.ContentDate, ds.ContentTime = date, time
    if time:
        ds.AcquisitionDateTime = date + time
    # -- equipment ----------------------------------------------------------------------------
    device = item.device if _ascii(item.device) else ""
    ds.Manufacturer = device.split(" ")[0] if device else "Unknown"
    ds.ManufacturerModelName = device or "Fundus camera"
    ds.DeviceSerialNumber = "0"
    ds.SoftwareVersions = f"FundusViewer {__version__}"
    ds.StationName = own_ae(s)
    # -- image --------------------------------------------------------------------------------
    ds.ImageType = ["DERIVED", "SECONDARY"] if item.derived else ["ORIGINAL", "PRIMARY"]
    ds.BurnedInAnnotation = "YES" if item.kind in ("disc", "glaucoma") else "NO"
    if eye:
        ds.ImageLaterality = eye
    if sop_class == SECONDARY_CAPTURE:
        ds.ConversionType = "WSD"
        ds.DateOfSecondaryCapture, ds.TimeOfSecondaryCapture = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
        if eye:
            ds.Laterality = eye if eye in ("R", "L") else ""
    else:
        if not eye:
            ds.ImageLaterality = "U"                 # type 1: unknown is different from bilateral
        ds.NumberOfFrames = 1
        ds.PixelSpacing = None
        ds.AnatomicRegionSequence = [_code("5665001", "SCT", "Retina") if item.kind != "anterior"
                                     else _code("28726007", "SCT", "Cornea")]
        ds.AcquisitionContextSequence = []
        ds.PatientEyeMovementCommanded = ""
        ds.EmmetropicMagnification = None
        ds.IntraOcularPressure = None
        ds.HorizontalFieldOfView = float(item.fov_deg) if item.fov_deg else None
        ds.PupilDilated = ""
        ds.RefractiveStateSequence = []
        ds.AcquisitionDeviceTypeCodeSequence = [_code("409898007", "SCT", "Fundus Camera")]
        ds.IlluminationTypeCodeSequence = []
        ds.LightPathFilterTypeStackCodeSequence = []
        ds.ImagePathFilterTypeStackCodeSequence = []
        ds.LensesCodeSequence = []
        ds.DetectorType = ""
    # -- pixels -------------------------------------------------------------------------------
    as_is = _jpeg_as_is(path) if jpeg else None
    if as_is is not None:
        _put_jpeg(ds, *as_is)
    else:
        from . import imaging
        _put_pixels(ds, imaging.load_rgb(path))
        if path.suffix.lower() in (".jpg", ".jpeg"):   # it was compressed once, whatever is sent
            ds.LossyImageCompression = "01"
            ds.LossyImageCompressionMethod = "ISO_10918_1"
    return ds


def _image_datetime(ds) -> tuple[str, str]:
    """The acquisition date/time displayed by the importer (not necessarily the study's)."""
    for day_kw, time_kw in (("AcquisitionDateTime", None), ("ContentDate", "ContentTime"),
                           ("AcquisitionDate", "AcquisitionTime"), ("SeriesDate", "SeriesTime"),
                           ("StudyDate", "StudyTime")):
        value = _text(ds, day_kw)
        day = norm_date(value[:8], min_year=1990)
        if day:
            time = value[8:14] if time_kw is None else _text(ds, time_kw)
            return day, norm_time(time) or ""
    return "", ""


def _correct_image_datetime(ds, item: Item) -> bool:
    """Correct acquisition fields; the existing study retains its own date and time."""
    old_day, old_time = _image_datetime(ds)
    day_changed = (item.metadata_authoritative or bool(item.exam_date)) and item.exam_date != old_day
    time_changed = (item.metadata_authoritative or bool(item.exam_time)) and item.exam_time != old_time
    if day_changed:
        for keyword in ("SeriesDate", "ContentDate", "AcquisitionDate"):
            if keyword == "ContentDate" or keyword in ds:
                setattr(ds, keyword, _da(item.exam_date))
    if time_changed:
        for keyword in ("SeriesTime", "ContentTime", "AcquisitionTime"):
            if keyword == "ContentTime" or keyword in ds:
                setattr(ds, keyword, _tm(item.exam_time))
    acquired = _text(ds, "AcquisitionDateTime")
    if acquired and (day_changed or time_changed):
        if day_changed and not item.exam_date:
            ds.AcquisitionDateTime = ""
            return True
        day = _da(item.exam_date) if day_changed else acquired[:8]
        time = acquired[8:]
        if time_changed:
            zone = re.search(r"[+-]\d{4}$", time)
            time = (_tm(item.exam_time) + (zone.group() if zone else "")) if item.exam_time else ""
        ds.AcquisitionDateTime = day + time
    return day_changed or time_changed


def load_dicom(item: Item, s: Settings):
    """An imported DICOM with the viewer's patient, eye and acquisition corrections.

    Unchanged images retain their original identifiers and tags. A reassigned patient gets a
    deterministic new study/instance; a corrected image or worklist study gets a separate series
    and instance so the original SOP identity never moves to a different DICOM hierarchy.
    """
    import pydicom
    from pydicom.dataset import FileMetaDataset

    from .extract.dicom_meta import _person_name

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = pydicom.dcmread(item.path, force=True)
        if not getattr(ds, "file_meta", None):
            ds.file_meta = FileMetaDataset()
        if "TransferSyntaxUID" not in ds.file_meta:
            ds.file_meta.TransferSyntaxUID = IMPLICIT_LE
        if "SOPClassUID" not in ds or "SOPInstanceUID" not in ds:
            raise DicomError("DICOM 파일에 SOP Class / Instance UID가 없습니다")
        source_sop = str(ds.SOPInstanceUID)
        source_series = _text(ds, "SeriesInstanceUID") or source_sop
        source_study = _text(ds, "StudyInstanceUID")
        changes: dict[str, str] = {}
        reassigned = bool(item.patient_id) and _text(ds, "PatientID").replace(" ", "") != item.patient_id
        if reassigned:
            # A previous patient's optional history, identifiers and characteristics must not
            # survive reassignment. Clear the whole patient group, including nested metadata,
            # then rebuild the required fields from the target patient (unknown values blank).
            def clear_patient_group(dataset, element):
                if element.tag.group == 0x0010:
                    del dataset[element.tag]

            ds.walk(clear_patient_group)
            changes["PatientID"] = item.patient_id
            # Blanks belong to the new patient too: never inherit the previous patient's values.
            changes["PatientName"] = _patient_name(item)
            ds.PatientBirthDate = _da(item.birth_date)
            ds.PatientSex = item.sex if item.sex in ("M", "F", "O") else ""
            for keyword in ("AccessionNumber", "StudyID", "RequestAttributesSequence"):
                if keyword in ds:
                    delattr(ds, keyword)
            ds.StudyInstanceUID = make_uid("study", item.patient_id, item.exam_date or "undated")
            ds.SOPInstanceUID = make_uid("reassigned", source_sop, item.patient_id)
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        name = _patient_name(item)
        if (name or item.metadata_authoritative) and (_person_name(ds) or "") != (_display_name(name) or name):
            changes["PatientName"] = name
        if (name and "PatientName" not in changes and "SpecificCharacterSet" not in ds
                and not _ascii(pn_text(ds))):
            changes["PatientName"] = name            # a Hangul name without its character set: declared here
        if not reassigned and (item.birth_date or item.metadata_authoritative) and \
                (norm_date(_text(ds, "PatientBirthDate")) or "") != item.birth_date:
            ds.PatientBirthDate = _da(item.birth_date)
        if not reassigned and (item.sex or item.metadata_authoritative) and \
                (norm_sex(_text(ds, "PatientSex")) or "") != item.sex:
            ds.PatientSex = item.sex if item.sex in ("M", "F", "O") else ""
        eye = EYES.get(item.laterality, "U" if item.metadata_authoritative else None)
        series_eye_value = eye if eye in ("R", "L") else ""
        image_eye, series_eye = _text(ds, "ImageLaterality"), _text(ds, "Laterality")
        eye_changed = bool(eye) and (eye != (image_eye or series_eye)
                                   or bool(series_eye and series_eye != series_eye_value))
        if eye_changed:
            ds.ImageLaterality = eye
            if "Laterality" in ds:
                ds.Laterality = series_eye_value
        timestamp_changed = _correct_image_datetime(ds, item)
        order = item.order
        if order is not None:
            if order.accession:
                ds.AccessionNumber = order.accession
            if order.study_uid:
                ds.StudyInstanceUID = order.study_uid
            if order.procedure_id and not _text(ds, "StudyID"):
                ds.StudyID = order.procedure_id[:16]
        if reassigned or _text(ds, "StudyInstanceUID") != source_study:
            # New study metadata belongs to the target; an explicit worklist schedule is
            # authoritative for the study while Series/Content/Acquisition retain capture time.
            ds.StudyDate = _da(order.date) if order is not None and order.date else _da(item.exam_date)
            ds.StudyTime = _tm(order.time) if order is not None and order.time else _tm(item.exam_time)
        if reassigned or eye_changed or timestamp_changed or _text(ds, "StudyInstanceUID") != source_study:
            if not _text(ds, "StudyInstanceUID"):
                ds.StudyInstanceUID = _study_uid(item)
            ds.SeriesInstanceUID = make_uid("corrected-series", source_series, ds.StudyInstanceUID,
                                             item.patient_id, item.laterality, item.exam_date, item.exam_time)
            ds.SOPInstanceUID = make_uid("corrected-instance", source_sop, ds.SeriesInstanceUID)
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        if changes:
            if not all(_ascii(v) for v in changes.values()):
                _redeclare(ds, _charset(s))
            for keyword, value in changes.items():
                setattr(ds, keyword, value)
    return ds


def _redeclare(ds, charset: str) -> None:
    """Give a dataset the character set of the settings. Text it holds without a declared character
    set (CP949 bytes of older capture stations) is read first, so it is written correctly."""
    from pydicom.dataelem import DataElement

    from .extract.dicom_meta import _decode_bytes

    declared = "SpecificCharacterSet" in ds
    if not declared:
        for elem in list(ds):
            if elem.VR not in ("LO", "SH", "PN", "ST", "LT", "UT"):
                continue
            original = getattr(elem.value, "original_string", None)
            raw = original if isinstance(original, (bytes, bytearray)) else None
            if raw is None:
                try:
                    value = elem.value
                    text = str(value) if isinstance(value, str) or elem.VM <= 1 else "\\".join(map(str, value))
                    raw = text.encode("latin-1")
                except (UnicodeEncodeError, AttributeError):
                    continue
            if any(b > 0x7F for b in raw):
                ds[elem.tag] = DataElement(elem.tag, elem.VR, _decode_bytes(bytes(raw)).rstrip("\x00 "))
    ds.SpecificCharacterSet = _charset_value(charset)


def dataset_of(item: Item, s: Settings, *, jpeg: bool | None = None):
    """The dataset to send for ``item``."""
    path = Path(item.path)
    if not item.path or not path.is_file():
        raise DicomError("사진 파일을 찾을 수 없습니다")
    if is_dicom(path):
        return load_dicom(item, s)
    return wrap_photo(item, s, jpeg=bool(s.dicom_jpeg) if jpeg is None else jpeg)


def save_dicom(item: Item, s: Settings, dest: Path | str) -> Path:
    """Write what would be sent for ``item`` as a DICOM file (Part 10)."""
    ds = dataset_of(item, s)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds.save_as(str(dest), enforce_file_format=True)
    return Path(dest)


# ---------------------------------------------------------------------------------------------
# 전송
# ---------------------------------------------------------------------------------------------
@dataclass
class SendResult:
    image_id: int
    ok: bool
    message: str = ""
    sop_uid: str = ""


def _peek(item: Item) -> tuple[str, str] | None:
    """SOP class and transfer syntax of a DICOM file, without its pixels."""
    import pydicom

    path = Path(item.path)
    if not item.path or not path.is_file() or not is_dicom(path):
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None) or IMPLICIT_LE
        return str(ds.SOPClassUID), str(ts)
    except Exception:
        return None


def _contexts(items: list[Item]) -> list[tuple[str, list[str]]]:
    """What to ask the PACS for: each kind of picture uncompressed, and compressed as it is stored —
    one presentation context per form, so the PACS can take one and refuse the other."""
    wanted: dict[tuple[str, tuple[str, ...]], None] = {}
    for sop in (OP_8BIT, SECONDARY_CAPTURE):
        wanted[(sop, (JPEG_BASELINE,))] = None
        wanted[(sop, UNCOMPRESSED)] = None
    for item in items:
        peek = _peek(item)
        if peek is not None:
            sop, ts = peek
            if ts not in UNCOMPRESSED:
                wanted[(sop, (ts,))] = None
            wanted[(sop, UNCOMPRESSED)] = None
    return [(sop, list(ts)) for sop, ts in wanted][:120]


def _accepted(assoc) -> set[tuple[str, str]]:
    return {(str(cx.abstract_syntax), str(cx.transfer_syntax[0])) for cx in assoc.accepted_contexts}


def _fit(ds, item: Item, s: Settings, accepted: set[tuple[str, str]]):
    """``ds`` in a form the PACS said it takes — or a :class:`DicomError`."""
    sop, ts = str(ds.SOPClassUID), str(ds.file_meta.TransferSyntaxUID)
    made_here = not is_dicom(Path(item.path))
    takes = {t for a, t in accepted if a == sop}
    if not takes and made_here and sop != SECONDARY_CAPTURE:
        # no Ophthalmic Photography there: a Secondary Capture is taken by every PACS
        ds = wrap_photo(item, s, jpeg=bool(s.dicom_jpeg), sop_class=SECONDARY_CAPTURE)
        sop, ts = SECONDARY_CAPTURE, str(ds.file_meta.TransferSyntaxUID)
        takes = {t for a, t in accepted if a == sop}
    if not takes:
        raise DicomError("PACS가 이 종류의 영상을 받지 않습니다 (SOP Class 거부)")
    if ts in takes or (ts in UNCOMPRESSED and takes & set(UNCOMPRESSED)):
        return ds
    if not takes & set(UNCOMPRESSED):
        raise DicomError("PACS가 이 영상의 압축 형식을 받지 않습니다")
    if made_here:
        return wrap_photo(item, s, jpeg=False, sop_class=sop)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            source_uid = str(ds.SOPInstanceUID)
            old_color = _text(ds, "PhotometricInterpretation")
            ds.decompress(generate_instance_uid=False)
            if _text(ds, "PhotometricInterpretation") != old_color:
                # YBR -> RGB changes the pixel representation. Give that conversion its own stable
                # identity rather than pydicom's randomly generated instance on every retry.
                ds.SOPInstanceUID = make_uid("decompressed-rgb-v1", source_uid)
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    except Exception as exc:
        raise DicomError(f"PACS가 받는 형식으로 압축을 풀지 못했습니다 — {exc}") from exc
    return ds


def send(s: Settings, items: list[Item], progress: Callable[[int, int, SendResult | None], None] | None = None,
         cancelled: Callable[[], bool] | None = None, timeout: float = 15.0) -> list[SendResult]:
    """Send ``items`` to the PACS over one association. A photo that fails does not stop the others;
    a connection that cannot be made raises :class:`DicomError`."""
    if not items:
        return []
    assoc = _associate(s, pacs_node(s), _contexts(items), timeout)
    results: list[SendResult] = []
    try:
        accepted = _accepted(assoc)
        for i, item in enumerate(items):
            if cancelled is not None and cancelled():
                break
            if progress is not None:
                progress(i, len(items), None)
            res = SendResult(item.image_id, False)
            try:
                if not assoc.is_established:
                    raise DicomError("PACS와의 연결이 끊어졌습니다")
                ds = _fit(dataset_of(item, s), item, s, accepted)
                res.sop_uid = str(ds.SOPInstanceUID)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    status = assoc.send_c_store(ds)
                code = status.Status if status and "Status" in status else None
                if code is None:
                    raise DicomError("PACS가 답하지 않았습니다 (시간 초과)")
                if code == 0x0000 or code in (0xB000, 0xB006, 0xB007):
                    res.ok = True
                    res.message = "" if code == 0 else f"경고 0x{code:04X}"
                else:
                    raise DicomError(f"PACS가 저장하지 못했습니다 (상태 0x{code:04X})")
            except DicomError as exc:
                res.message = str(exc)
            except Exception as exc:                 # an unreadable file, a codec that is not there …
                res.message = f"{type(exc).__name__}: {exc}"[:200]
            results.append(res)
            if progress is not None:
                progress(i + 1, len(items), res)
    finally:
        _close(assoc)
    return results
