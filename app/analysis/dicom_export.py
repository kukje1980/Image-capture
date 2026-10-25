"""DICOM 내보내기 — Ophthalmic Photography 8 Bit Image (슬릿램프 영상 포함, PACS 연동용).

SOP Class 1.2.840.10008.5.1.4.1.1.77.1.5.1, Modality OP, RGB 8bit 비압축(Explicit VR Little Endian).
같은 환자·같은 날 영상은 하나의 Study 로 묶이도록 Study UID 를 환자·날짜로부터 결정적으로 만든다.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app import __version__

OP_8BIT = "1.2.840.10008.5.1.4.1.1.77.1.5.1"
_UID_ROOT = "1.2.826.0.1.3680043.10.1371."      # 이 프로그램 전용 접두어 (UUID 파생 2.25 형식과 겹치지 않게)
_LATERALITY = {"OD": "R", "OS": "L", "OU": "B"}


def _uid(*parts: str) -> str:
    """입력 문자열에서 결정적으로 만든 UID (64자 이내)."""
    digest = int(hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24], 16)
    return (_UID_ROOT + str(digest))[:64]


def _dt(captured_at: Optional[str]) -> datetime:
    try:
        return datetime.strptime(captured_at or "", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now()


def build_dataset(img_bgr: np.ndarray, patient, capture=None, institution: str = "", derived: bool = False):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    when = _dt(getattr(capture, "captured_at", None))
    pid = (patient.chart_no or patient.patient_id or str(patient.id or "")).strip() or "UNKNOWN"
    study_uid = _uid("study", pid, when.strftime("%Y%m%d"))
    eye = (getattr(capture, "eye", None) or "NA").upper()
    series_uid = _uid("series", pid, when.strftime("%Y%m%d"), eye)
    sop_uid = generate_uid() if capture is None or derived else _uid("sop", pid, str(capture.id), capture.file_path)

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = OP_8BIT
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = (_UID_ROOT + "1")
    meta.ImplementationVersionName = f"SLITLAMP_{__version__}"[:16]

    ds = Dataset()
    ds.file_meta = meta
    ds.SpecificCharacterSet = "ISO_IR 192"                    # UTF-8 (한글 이름)
    ds.SOPClassUID = OP_8BIT
    ds.SOPInstanceUID = sop_uid
    ds.ImageType = ["DERIVED" if derived else "ORIGINAL", "SECONDARY" if derived else "PRIMARY"]
    # 환자
    ds.PatientName = patient.name or ""
    ds.PatientID = pid
    ds.PatientBirthDate = (patient.birth_date or "").replace("-", "")[:8]
    ds.PatientSex = {"M": "M", "F": "F", "O": "O"}.get(patient.sex or "", "")
    # 검사
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.StudyDate = ds.SeriesDate = ds.ContentDate = when.strftime("%Y%m%d")
    ds.AcquisitionDateTime = when.strftime("%Y%m%d%H%M%S")
    ds.StudyTime = ds.SeriesTime = ds.ContentTime = when.strftime("%H%M%S")
    ds.StudyID = when.strftime("%Y%m%d")
    ds.AccessionNumber = ""
    ds.ReferringPhysicianName = patient.doctor or ""
    ds.StudyDescription = "Slit lamp photography"
    ds.SeriesDescription = f"Slit lamp {eye}" if eye in _LATERALITY else "Slit lamp"
    ds.Modality = "OP"
    ds.SeriesNumber = 1
    ds.InstanceNumber = int(getattr(capture, "id", 1) or 1)
    ds.Manufacturer = "SlitLampImaging"
    ds.InstitutionName = institution or ""
    ds.SoftwareVersions = __version__
    ds.ImageLaterality = _LATERALITY.get(eye, "U")
    ds.Laterality = ds.ImageLaterality if eye in ("OD", "OS") else ""
    ds.PatientEyeMovementCommanded = "NO"
    ds.BurnedInAnnotation = "YES" if derived else "NO"
    ds.LossyImageCompression = "00"
    if getattr(capture, "note", None):
        ds.ImageComments = capture.note
    # 영상 (RGB 8bit, interleaved)
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB) if img_bgr.ndim == 3 else cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2RGB)
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.Rows, ds.Columns = int(rgb.shape[0]), int(rgb.shape[1])
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = rgb.tobytes()
    return ds


def export(img_bgr: np.ndarray, patient, path, capture=None, institution: str = "", derived: bool = False) -> Path:
    ds = build_dataset(img_bgr, patient, capture, institution, derived)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=True)
    return path


def default_name(patient, capture=None) -> str:
    when = _dt(getattr(capture, "captured_at", None))
    chart = (patient.chart_no or "patient").replace("/", "_")
    eye = (getattr(capture, "eye", None) or "NA")
    cid = getattr(capture, "id", None)
    return f"{chart}_{when:%Y%m%d_%H%M%S}_{eye}" + (f"_{cid}" if cid else "") + ".dcm"
