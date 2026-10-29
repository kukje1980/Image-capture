"""Camera profiles: how to read a device's files and how to map its images
onto the 3D eye.

* ``reticam`` — SYSEYE RetiCam 3100 Plus, the company's ultra-wide-field
  camera (176° single shot, 220° two-image montage, eye-centre angles):
  APP15 JSON patient record + ``<이름>-<od|os>-color-YYYYMMDD-HHMMSS-mmm`` names;
  ``radial`` projection (centre magnified, see ``projection.py``).
* ``apollo``  — Microclear APOLLO (CSLO / CRO) wide-field SLO, the company's
  wide-angle model (WA 135° / UWA 165° eye-centre angle). Scan angle is
  proportional to image radius, so the projection is *equidistant* in the
  eye-centre angle.
* ``kowa_vk2`` — Kowa VK-2 / VK-2s capture software (nonmyd 7/8/8s/WX/AF,
  VX-10i/VX-20): Kowa Export Tool file names (VK EXPORT / MDR / JOIA style,
  JOIA ``.xml`` sidecar), DICOM export, and the native ``vk_3x`` store
  (serial-numbered files without patient data -> 미분류).
* ``kowa_vk2_id`` — a VK-2 "Copy Selected Images to Folder" target, where
  files are named by patient id only.
* ``generic`` — any other camera (DICOM / EXIF / sidecar / generic names).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .projection import DEFAULT_RADIAL_C, DEFAULT_VIEWPOINT

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".dcm", ".dicom")
# Written-then-renamed temporaries and VK-2's proprietary lossless format.
IGNORED_EXTS = (".tmp", ".part", ".crdownload", ".dlt", ".db", ".ini", ".xml", ".json", ".txt", ".csv")


@dataclass(frozen=True)
class CameraProfile:
    key: str
    name: str
    fov_deg: float                 # default field of view when the file does not say
    fov_type: str                  # "external" (at the pupil) or "internal" (eye centre)
    projection: str                # see projection.PROJECTIONS
    viewpoint: float = DEFAULT_VIEWPOINT
    radial_c: float = DEFAULT_RADIAL_C   # only for the "radial" projection
    filename_patterns: tuple[str, ...] = ()
    id_only_filenames: bool = False
    vendor: str = ""               # vendor-specific extractor ("apollo")
    # Fraction of the image-circle radius searched for the optic disc.
    disc_search: float = 0.7
    notes: str = ""
    match_devices: tuple[str, ...] = field(default=())


KOWA_PATTERNS = (
    # VK EXPORT style: ID_YYYYMMDD_HHMMSS_R_FUNDUS (COLOR)_1
    r"^(?P<pid>.+?)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<eye>[RL])_(?P<mode>.+?)_(?P<seq>\d+)$",
    # MDR style: ID_YYYYMMDD_HHMMSS_FUNDUS(COLOR)_R_01
    r"^(?P<pid>.+?)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<mode>.+?)_(?P<eye>[RL])_(?P<seq>\d{2})$",
    # JOIA style: ID_YYYYMMDD_HHMMSS_KOWA_COLOR_R (+ same-stem .xml)
    r"^(?P<pid>.+?)_(?P<date>\d{8})_(?P<time>\d{6})_KOWA_(?P<mode>[A-Z]+)_(?P<eye>[RL])$",
    # Native store vk_3x\-000512\vk000005 — serial only, no patient data.
    r"^vk(?P<seq>\d{6})$",
)

APOLLO_PATTERNS = (
    # 2024_10_08_10_46_27.573_RF_B / ..._ART(21)_FFA / ..._Mosaic_COLOR_OD_135°
    r"^(?P<date>\d{4}_\d{2}_\d{2})_(?P<time>\d{2}_\d{2}_\d{2})(?:\.\d{1,3})?(?:_ART\([\d\-]+\))?"
    r"(?:_(?:Mosaic_)?(?P<mode>[A-Za-z]+(?:-[A-Za-z]+)?))?(?:_(?:R|G|B|IR))?(?:_(?P<eye>OD|OS))?(?:_\d+°?)?",
)

RETICAM_PATTERNS = (
    # 홍길동-od-color-20260310-101530-123 (time = local wall clock)
    r"^(?P<name>.+)-(?P<eye>od|os|na)-(?P<mode>[a-z]+)-(?P<date>\d{8})-(?P<time>\d{6})-\d{3}(?:\s*\(\d+\))?$",
)

PROFILES: dict[str, CameraProfile] = {
    "reticam": CameraProfile(
        key="reticam",
        name="SYSEYE RetiCam 3100 Plus 초광각 (176°)",
        fov_deg=176.0, fov_type="internal", projection="radial",
        filename_patterns=RETICAM_PATTERNS, vendor="reticam", disc_search=0.5,
        notes="JPEG 안의 APP15 JSON(patientID·이름·생년월일·성별·눈·촬영 시각)과 파일 이름 "
              "<이름>-od-color-YYYYMMDD-HHMMSS-mmm 을 읽습니다. 기본 환자(#AnonymousID#)는 미분류. "
              "화각 176°(안구 중심각), 2장 몽타주 220°. 투영은 '광각 보정(중심 확대)'.",
        match_devices=("SYSEYE", "RETICAM", "BIO NEWVISION"),
    ),
    "apollo": CameraProfile(
        key="apollo",
        name="Microclear APOLLO 광각 (WA 135° / UWA 165°)",
        fov_deg=135.0, fov_type="internal", projection="equidistant",
        filename_patterns=APOLLO_PATTERNS, vendor="apollo", disc_search=0.5,
        notes="PatientCapture/<ID>_<이름>/<날짜>/<모드>/ 폴더 구조와 JPEG 주석(Description JSON)에서 "
              "검사 시각·눈·화각·장비를 읽습니다. 화각은 안구 중심각(외부각 × 1.5).",
        match_devices=("MICROCLEAR", "APOLLO", "RTSCAN"),
    ),
    "kowa_vk2": CameraProfile(
        key="kowa_vk2",
        name="Kowa VK-2 / VK-2s (Export Tool · DICOM)",
        fov_deg=45.0, fov_type="external", projection="perspective",
        filename_patterns=KOWA_PATTERNS,
        notes="Kowa Export Tool 파일명(VK EXPORT / MDR / JOIA + XML)과 VK-2 DICOM을 읽습니다. "
              "vk_3x 원본 저장소의 vk000123.jpg 파일은 환자 정보가 없어 미분류로 들어옵니다.",
        match_devices=("KOWA", "VK-2", "VK2", "NONMYD", "VX-10", "VX-20"),
    ),
    "kowa_vk2_id": CameraProfile(
        key="kowa_vk2_id",
        name="Kowa VK-2 폴더 복사 (파일명 = 환자 ID)",
        fov_deg=45.0, fov_type="external", projection="perspective",
        filename_patterns=KOWA_PATTERNS, id_only_filenames=True,
        notes="VK-2 'Copy Selected Images to Folder'처럼 파일 이름이 환자 ID인 폴더 전용.",
    ),
    "generic": CameraProfile(
        key="generic",
        name="일반 안저카메라 (45°)",
        fov_deg=45.0, fov_type="external", projection="perspective",
        notes="DICOM 태그, EXIF/주석, 같은 이름의 .txt/.xml/.json 파일, 일반적인 파일명 규칙을 사용합니다.",
    ),
}
AUTO = "auto"


def get_profile(key: str | None) -> CameraProfile:
    return PROFILES.get(key or "", PROFILES["generic"])


def profile_for_device(device: str | None) -> CameraProfile | None:
    if not device:
        return None
    u = device.upper()
    for p in PROFILES.values():
        if any(tok in u for tok in p.match_devices):
            return p
    return None
