"""안저 사진 불러오기 — 일반 영상(JPG·PNG·BMP·TIFF)과 DICOM 을 읽어 환자 기록으로 저장.

Qt 에 의존하지 않는 순수 로직이다 (다이얼로그는 app/ui/fundus_import_dialog.py).
  read_image(path)        파일 → ImportedImage (BGR 영상 · 촬영 일시 · 안구 방향)
  guess_eye_from_name()   파일 이름에서 OD/OS 추정
  import_image()          ImportedImage 를 CaptureService 로 저장 (modality='fundus')
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

log = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
DICOM_EXTS = (".dcm", ".dicom")
FILE_FILTER = ("안저 영상 (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.dcm *.dicom);;"
               "이미지 (*.jpg *.jpeg *.png *.bmp *.tif *.tiff);;DICOM (*.dcm *.dicom);;모든 파일 (*)")
NOTE_PREFIX = "안저"

# 손실 압축 전송 구문 (JPEG Baseline / Extended / JPEG 2000 손실) — 다시 저장할 때 JPEG 로 둔다
_LOSSY_TS = {"1.2.840.10008.1.2.4.50", "1.2.840.10008.1.2.4.51", "1.2.840.10008.1.2.4.91"}


class FundusImportError(Exception):
    """불러오기 실패 (사용자에게 그대로 보여 줄 한국어 메시지)."""


@dataclass
class ImportedImage:
    image: np.ndarray                    # BGR uint8
    captured_at: Optional[datetime]      # 촬영 일시 (DICOM · EXIF · 파일 수정 시각 순)
    eye: Optional[str]                   # 'OD' | 'OS' | None(알 수 없음)
    source_name: str                     # 원본 파일 이름
    lossy: bool = False                  # 원본이 JPEG 계열 손실 압축 → JPEG 로 저장


# ---------------- 안구 방향 추정 ----------------
_STRONG = {"OD": "OD", "RE": "OD", "RIGHT": "OD", "OS": "OS", "LE": "OS", "LEFT": "OS"}
_WEAK = {"R": "OD", "L": "OS"}
_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z]+")


def guess_eye_from_name(name: str) -> Optional[str]:
    """파일 이름에서 안구 방향을 추정한다. 확실하지 않으면 None.

    영숫자가 아닌 문자로 구분된 토큰 OD/OS/RE/LE/RIGHT/LEFT (없으면 R/L), 또는 '우안'/'좌안'.
    'color', 'model' 처럼 단어 안에 들어 있는 글자는 보지 않는다. 양쪽이 다 나오면 None.
    """
    stem = Path(str(name).replace("\\", "/")).name
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    found = set()
    if "우안" in stem:
        found.add("OD")
    if "좌안" in stem:
        found.add("OS")
    tokens = [t.upper() for t in _TOKEN_SPLIT.split(stem) if t]
    found |= {_STRONG[t] for t in tokens if t in _STRONG}
    if not found:
        found = {_WEAK[t] for t in tokens if t in _WEAK}
    return found.pop() if len(found) == 1 else None


def _eye_from_laterality(value) -> Optional[str]:
    v = str(value or "").strip().upper()
    return {"R": "OD", "L": "OS"}.get(v)


# ---------------- 읽기 ----------------
def is_dicom(path) -> bool:
    p = Path(path)
    if p.suffix.lower() in DICOM_EXTS:
        return True
    try:
        with open(p, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def read_image(path) -> ImportedImage:
    """파일을 읽어 ImportedImage 로. 읽을 수 없으면 FundusImportError."""
    p = Path(path)
    if not p.is_file():
        raise FundusImportError("파일을 찾을 수 없습니다.")
    if is_dicom(p):
        return _read_dicom(p)
    if p.suffix.lower() not in IMAGE_EXTS:
        raise FundusImportError(f"지원하지 않는 파일 형식입니다 ({p.suffix or '확장자 없음'}).")
    return _read_plain(p)


def _mtime(p: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(p)).replace(microsecond=0)
    except OSError:
        return None


def _read_plain(p: Path) -> ImportedImage:
    if cv2 is None:  # pragma: no cover
        raise FundusImportError("영상 처리 모듈(OpenCV)을 불러올 수 없습니다.")
    try:
        data = np.fromfile(str(p), dtype=np.uint8)          # 한글 경로 대응
    except OSError as e:
        raise FundusImportError(f"파일을 읽을 수 없습니다: {e}") from e
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if img is None:
        raise FundusImportError("이미지를 해석할 수 없습니다 (손상되었거나 지원하지 않는 형식).")
    lossy = p.suffix.lower() in (".jpg", ".jpeg")
    when = (_exif_datetime(p) if lossy else None) or _mtime(p)
    return ImportedImage(img, when, guess_eye_from_name(p.name), p.name, lossy)


def _exif_datetime(p: Path) -> Optional[datetime]:
    """JPEG EXIF 의 촬영 일시 (DateTimeOriginal → DateTimeDigitized)."""
    try:
        from PIL import Image
        with Image.open(p) as im:
            exif = im.getexif()
            sub = exif.get_ifd(0x8769)                       # Exif IFD
        for tag in (36867, 36868):
            dt = _parse_dt(str(sub.get(tag) or "").strip(), ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"))
            if dt:
                return dt
    except Exception:  # noqa: BLE001
        log.debug("EXIF 읽기 실패: %s", p, exc_info=True)
    return None


def _parse_dt(text: str, formats) -> Optional[datetime]:
    for fmt in formats:
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


# ---------------- DICOM ----------------
def _dicom_datetime(date_val, time_val="") -> Optional[datetime]:
    """DICOM DA('YYYYMMDD') + TM('HHMMSS.ffffff', 뒤쪽 생략 가능) → datetime."""
    d = re.sub(r"[^0-9]", "", str(date_val or ""))[:8]
    if len(d) != 8:
        return None
    t = re.sub(r"[^0-9.]", "", str(time_val or "")).split(".")[0]
    t = (t + "000000")[:6]
    try:
        return datetime.strptime(d + t, "%Y%m%d%H%M%S")
    except ValueError:
        try:
            return datetime.strptime(d, "%Y%m%d")
        except ValueError:
            return None


def _dicom_captured_at(ds) -> Optional[datetime]:
    dt = _dicom_datetime(ds.get("ContentDate"), ds.get("ContentTime"))
    if dt is None:
        adt = str(ds.get("AcquisitionDateTime") or "")
        dt = _dicom_datetime(adt[:8], adt[8:])
    if dt is None:
        dt = _dicom_datetime(ds.get("StudyDate"), ds.get("StudyTime"))
    return dt


def _to_uint8(arr: np.ndarray, bits_stored: int, color: bool) -> np.ndarray:
    if arr.dtype == np.uint8:
        return arr
    if color:                                   # 컬러 >8비트: 저장 비트 수 기준으로 8비트로
        shift = max(0, int(bits_stored or arr.dtype.itemsize * 8) - 8)
        return np.clip(arr.astype(np.int64) >> shift, 0, 255).astype(np.uint8)
    a = arr.astype(np.float32)                  # 흑백 >8비트: 실제 값 범위를 0~255 로
    lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return np.zeros(a.shape, dtype=np.uint8)
    return np.clip((a - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)


def _dicom_pixels(ds) -> np.ndarray:
    """pydicom 디코더로 첫 프레임을 BGR uint8 로."""
    frames = int(ds.get("NumberOfFrames", 1) or 1)
    if frames > 1:
        ds.pixel_array_options(index=0)         # 다중 프레임 → 첫 프레임만 디코딩
    arr = ds.pixel_array
    samples = int(ds.get("SamplesPerPixel", 1) or 1)
    photometric = str(ds.get("PhotometricInterpretation", "")).upper()
    if samples == 1 and arr.ndim == 3:          # (프레임, 행, 열) 로 온 경우
        arr = arr[0]
    elif samples > 1 and arr.ndim == 4:
        arr = arr[0]
    if photometric == "PALETTE COLOR":
        from pydicom.pixels import apply_color_lut
        arr = apply_color_lut(arr, ds)
        samples = 3
    bits = int(ds.get("BitsStored", 8) or 8)
    if samples == 1:
        gray = _to_uint8(arr, bits, color=False)
        if photometric == "MONOCHROME1":        # 0 = 흰색 → 반전
            gray = 255 - gray
        return np.ascontiguousarray(np.stack([gray, gray, gray], axis=-1))
    rgb = _to_uint8(arr, 16 if photometric == "PALETTE COLOR" and arr.dtype != np.uint8 else bits,
                    color=True)
    # pydicom 은 YBR 계열을 RGB 로 바꿔 돌려준다 → BGR 로 뒤집기만 하면 된다
    return np.ascontiguousarray(rgb[..., :3][..., ::-1])


def _dicom_first_frame_bytes(ds) -> Optional[bytes]:
    try:
        from pydicom.encaps import generate_frames
        frames = int(ds.get("NumberOfFrames", 1) or 1)
        return next(generate_frames(ds.PixelData, number_of_frames=frames))
    except Exception:  # noqa: BLE001
        log.debug("DICOM 프레임 추출 실패", exc_info=True)
        return None


def _read_dicom(p: Path) -> ImportedImage:
    try:
        import pydicom
    except ImportError as e:  # pragma: no cover
        raise FundusImportError("DICOM 모듈(pydicom)이 설치되어 있지 않습니다.") from e
    try:
        ds = pydicom.dcmread(str(p), force=True)
    except Exception as e:  # noqa: BLE001
        raise FundusImportError(f"DICOM 파일을 읽을 수 없습니다: {e}") from e
    if "PixelData" not in ds:
        raise FundusImportError("영상이 들어 있지 않은 DICOM 파일입니다.")
    meta = getattr(ds, "file_meta", None)
    ts = meta.get("TransferSyntaxUID") if meta is not None else None
    if ts is None:                               # 머리말 없는 파일 → 기본 전송 구문으로 가정
        from pydicom.dataset import FileMetaDataset
        from pydicom.uid import ImplicitVRLittleEndian
        if meta is None:
            ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ts = ImplicitVRLittleEndian
    compressed = bool(getattr(ts, "is_compressed", False))

    img = None
    try:
        img = _dicom_pixels(ds)
    except Exception as e:  # noqa: BLE001
        log.info("pydicom 픽셀 디코딩 실패 (%s) — 프레임 직접 디코딩 시도: %s", p.name, e)
        if compressed and cv2 is not None:       # 캡슐화된 JPEG 등은 프레임 바이트를 직접 디코딩
            raw = _dicom_first_frame_bytes(ds)
            if raw:
                img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            if compressed:
                name = getattr(ts, "name", "") or str(ts)
                raise FundusImportError(
                    f"지원하지 않는 DICOM 압축 형식입니다 ({name}). "
                    "장비에서 비압축 또는 JPEG 로 내보내 주세요.") from e
            raise FundusImportError(f"DICOM 영상을 해석할 수 없습니다: {e}") from e
    if img is None or img.size == 0:
        raise FundusImportError("DICOM 영상을 해석할 수 없습니다.")

    eye = (_eye_from_laterality(ds.get("ImageLaterality"))
           or _eye_from_laterality(ds.get("Laterality"))
           or guess_eye_from_name(p.name))
    when = _dicom_captured_at(ds) or _mtime(p)
    lossy = str(ts) in _LOSSY_TS or str(ds.get("LossyImageCompression", "")) == "01"
    return ImportedImage(img, when, eye, p.name, lossy)


# ---------------- 저장 ----------------
def import_image(service, patient, item: ImportedImage, eye: Optional[str] = None):
    """ImportedImage 를 환자 기록으로 저장하고 Capture 를 돌려준다.

    eye 를 주면 그 값('OD' | 'OS' | 'NA')을, 아니면 추정값을 쓴다. 저장 경로·export 복사·썸네일은
    일반 촬영과 같다 (media_type='photo', modality='fundus', 코멘트 '안저 · <원본파일명>').
    """
    e = eye or item.eye or "NA"
    if e not in ("OD", "OS"):
        e = "NA"
    return service.save_photo(
        item.image, patient, eye=e, note=f"{NOTE_PREFIX} · {item.source_name}",
        captured_at=item.captured_at or datetime.now(), modality="fundus",
        ext="jpg" if item.lossy else "png",
    )


def import_file(service, patient, path, eye: Optional[str] = None):
    """read_image + import_image."""
    return import_image(service, patient, read_image(path), eye)
