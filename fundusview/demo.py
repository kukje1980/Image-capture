"""Synthetic, de-identified fundus photographs for demos and tests.

A retina is drawn once on an azimuthal-equidistant *retinal map* (degrees
from the fovea: disc 21.5° nasal and slightly superior, four vessel
arcades, macula, choroidal texture) and then projected into a camera image
with the same geometry the 3D view uses (``projection.py``) — so a demo
image maps back onto the sphere exactly.

``write_demo_folder`` produces files in the real devices' formats (all
patients fictional):

* SYSEYE RetiCam 3100 Plus: ``<이름>-od-color-YYYYMMDD-HHMMSS-mmm.jpg`` with the
  APP15 JSON patient record (176°, plus a 220° montage and the device's
  anonymous default patient)
* Microclear APOLLO: ``PatientCapture/<ID>_<이름>/<YYYY_MM_DD>/COLOR/...MCOLOR.jpg``
  with the ``Description: {json}`` JPEG comment (WA 135° / UWA 165°)
* Kowa Export Tool: ``ID_YYYYMMDD_HHMMSS_R_FUNDUS (COLOR)_1.jpg`` and JOIA
  style + ``.xml`` sidecar (45°)
* DICOM Ophthalmic Photography 8-bit with a Korean name (ISO 2022 IR 149)
* a photo without any patient data (-> 미분류)
"""
from __future__ import annotations

import io
import json
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import projection as proj

MAP_PX_PER_DEG = 6.0
MAP_HALF_DEG = 115.0


def _retina_map(eye: str = "OD", seed: int = 1, tint=(0.80, 0.40, 0.22)) -> Image.Image:
    rng = np.random.default_rng(seed)
    n = int(2 * MAP_HALF_DEG * MAP_PX_PER_DEG)
    c = n / 2.0

    def px(xd, yd):  # degrees (x right, y up) -> map pixel
        return (c + xd * MAP_PX_PER_DEG, c - yd * MAP_PX_PER_DEG)

    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    rdeg = np.hypot(xx - c, yy - c) / MAP_PX_PER_DEG
    noise = rng.normal(0, 1, (n // 8 + 1, n // 8 + 1)).astype(np.float32)
    noise = np.asarray(Image.fromarray(((noise * 20) + 128).clip(0, 255).astype(np.uint8))
                       .resize((n, n), Image.Resampling.BICUBIC), dtype=np.float32) / 255.0 - 0.5
    shade = 1.0 - 0.0035 * np.clip(rdeg - 10, 0, None) + noise * 0.18
    base = np.stack([np.clip(shade * t * 255, 0, 255) for t in tint], axis=-1)
    # macula: darker, with a small foveal reflex
    mac = np.exp(-(rdeg / 6.5) ** 2)[..., None]
    base = base * (1 - 0.35 * mac) + 0.0
    fov_reflex = np.exp(-(rdeg / 0.5) ** 2)[..., None]
    base = base + fov_reflex * 120
    img = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    side = 1.0 if eye != "OS" else -1.0
    disc = (side * 21.0, 1.5)
    # vessels: 4 arcades + branches, random walks bending around the macula
    def vessel(start, ang, width, length, color, depth=0):
        x, y = start
        pts = [px(x, y)]
        w = width
        steps = int(length / 1.2)
        for i in range(steps):
            # temporal arcades curve around the fovea toward the periphery
            ang += rng.normal(0, 0.06)
            x += math.cos(ang) * 1.2
            y += math.sin(ang) * 1.2
            if math.hypot(x, y) < 7.5:  # keep out of the fovea
                ang += 0.25 * (1 if y > 0 else -1) * side
            pts.append(px(x, y))
            if depth < 3 and i > 6 and rng.random() < 0.05:
                vessel((x, y), ang + rng.choice([-1, 1]) * rng.uniform(0.4, 0.9),
                       w * 0.7, length * rng.uniform(0.35, 0.6), color, depth + 1)
            w = max(1.0, w * 0.992)
        for a, b in zip(pts, pts[1:]):
            d.line([a, b], fill=color, width=max(1, int(w)))

    for k, (ang, col) in enumerate((
            (math.radians(150 if side > 0 else 30), (120, 30, 25)),   # supero-temporal vein
            (math.radians(-150 if side > 0 else -30), (120, 30, 25)),
            (math.radians(160 if side > 0 else 20), (175, 55, 40)),   # arteries
            (math.radians(-160 if side > 0 else -20), (175, 55, 40)),
            (math.radians(40 if side > 0 else 140), (130, 35, 28)),   # nasal
            (math.radians(-40 if side > 0 else -140), (175, 55, 40)),
            (math.radians(90), (130, 35, 28)), (math.radians(-90), (175, 55, 40)))):
        vessel(disc, ang, 7.0 if k < 4 else 5.0, rng.uniform(70, 95), col)
    # optic disc with cup
    dx, dy = px(*disc)
    r = 3.6 * MAP_PX_PER_DEG
    d.ellipse([dx - r, dy - r * 1.08, dx + r, dy + r * 1.08], fill=(238, 205, 150))
    rc = r * 0.45
    d.ellipse([dx - rc, dy - rc, dx + rc, dy + rc], fill=(252, 238, 210))
    return img.filter(ImageFilter.GaussianBlur(0.8))


def synth_fundus(*, eye: str = "OD", fov_deg: float = 135.0, fov_type: str = "internal",
                 projection: str = "equidistant", size=(1088, 1148), seed: int = 1,
                 tint=(0.80, 0.40, 0.22), circle: tuple[float, float, float] | None = None,
                 radial_c: float = proj.DEFAULT_RADIAL_C) -> np.ndarray:
    """RGB image of a synthetic retina seen through the given camera geometry.

    By default the image circle fills the frame width (APOLLO-like 2176×2296
    aspect, the extra rows at the bottom stay black like the device's text
    strip); ``circle`` = (cx, cy, r) places it explicitly.
    """
    w, h = size
    rmap = np.asarray(_retina_map(eye, seed, tint), dtype=np.uint8)
    n = rmap.shape[0]
    cx, cy, R = circle or (w / 2.0, w / 2.0, w / 2.0 * 0.94)
    tmax = proj.theta_max(fov_deg, fov_type)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy = (xx - cx) / R, (cy - yy) / R
    rho = np.hypot(dx, dy)
    phi = np.arctan2(dy, dx)
    inside = rho <= 1.0
    # vectorised inverse of rho(theta)
    if projection == "equidistant":
        theta = rho * tmax
    elif projection == "stereographic":
        theta = 2 * np.arctan(rho * math.tan(tmax / 2))
    elif projection == "orthographic":
        theta = np.arcsin(np.clip(rho * math.sin(tmax), -1, 1))
    elif projection == "radial":
        theta = tmax * ((1 - radial_c) * rho + radial_c * rho ** 3)
    else:
        a_max = math.atan(proj.g(tmax, "perspective"))
        a = np.arctan(rho * math.tan(a_max))
        theta = a + np.arcsin(np.clip(proj.DEFAULT_VIEWPOINT * np.sin(a), -1, 1))
    tdeg = np.degrees(theta)
    mx = np.clip(n / 2 + tdeg * np.cos(phi) * MAP_PX_PER_DEG, 0, n - 1).astype(np.int32)
    my = np.clip(n / 2 - tdeg * np.sin(phi) * MAP_PX_PER_DEG, 0, n - 1).astype(np.int32)
    out = rmap[my, mx].astype(np.float32)
    vignette = np.clip(1.15 - 0.55 * rho ** 3, 0, 1)[..., None]
    out = out * vignette
    out[~inside] = 0
    return out.clip(0, 255).astype(np.uint8)


def _apollo_comment(when: str, eye: str, field_angle: int, dev_model: int, pid: str, name: str) -> str:
    day = when[:10].replace("-", "_")
    stamp = when.replace("-", "_").replace(" ", "_").replace(":", "_")
    base = f"PatientCapture/{pid}_{name}/{day}"
    d = {
        "ArchivedDT": when, "DescVer": "1.0.0", "DevModel": dev_model,
        "ExtraInfo": {"MColorRedPath": f"{base}/IR/{stamp}.000_IR_R.jpg",
                      "MColorGreenPath": f"{base}/RF/{stamp}.000_RF_G.jpg",
                      "MColorBluePath": f"{base}/RF/{stamp}.000_RF_B.jpg",
                      "SWVersion": "2.0.004.3," + ("110D" if field_angle >= 110 else "90D"),
                      "Note": "DEMO - synthetic image"},
        "Eye": 1 if eye == "OD" else 0, "FieldAngle": field_angle, "ImgType": 2, "TxtEncode": "UTF-8",
    }
    return "Description: " + json.dumps(d, ensure_ascii=False)


def with_app15(jpeg: bytes, payload: bytes) -> bytes:
    """Insert an APP15 (0xFFEF) segment after SOI / APP0, as RetiCam does."""
    if jpeg[:2] != b"\xff\xd8" or len(payload) > 65533:
        raise ValueError("not a JPEG / payload too large")
    i = 2
    if jpeg[2:4] == b"\xff\xe0":
        i = 4 + struct.unpack(">H", jpeg[4:6])[0]
    return jpeg[:i] + b"\xff\xef" + struct.pack(">H", len(payload) + 2) + payload + jpeg[i:]


def reticam_record(*, pid: str, name: str, born: str, sex: str, eye: str, when: str,
                   stitched: bool = False) -> dict:
    """RetiCam 2025-software style APP15 JSON (``when`` = 'YYYY/MM/DD hh:mm:ss.mmm')."""
    ext = ({"isStitchIm": True, "orgImHeight": 4304, "orgImWidth": 5736} if stitched else
           {"flashBaseLv": 40, "pupilEstmSize": 4.6, "smallPupilOn": False})
    return {
        "dateTime": when, "elapsedCntr": "0", "extData": ext, "eyeLaterality": eye,
        "fixatInnerCenter": [-1, -1] if stitched else [64, 48], "fixatInnerCoord": [-1, -1] if stitched else [64, 48],
        "focusValue": -1 if stitched else 11000, "irisMaskEllipseLMaxis": -1, "irisMaskEllipseSMaxis": -1,
        "irisMaskOffsetX": 0, "irisMaskOffsetY": 0, "irisMaskRadius": 0 if stitched else 0.97, "modeID": 1,
        "multiSpectralData": "", "patientBornDate": born, "patientContact": "", "patientID": pid,
        "patientMemo": "DEMO - synthetic image", "patientName": name, "patientRefPerson": "",
        "patientSex": sex, "patientSrcCode": 0, "picFormat": "JPG", "typeCode": 0, "version": 256,
    }


def _burn_text(rgb: np.ndarray, lines: list[str]) -> np.ndarray:
    img = Image.fromarray(rgb)
    d = ImageDraw.Draw(img)
    y = 6
    for line in lines:
        d.text((8, y), line, fill=(240, 150, 40))
        y += 14
    return np.asarray(img)


def write_demo_folder(root: Path | str, *, small: bool = False) -> list[Path]:
    """Write the demo drop folder; returns the image paths written."""
    root = Path(root)
    size = (544, 574) if small else (1088, 1148)
    out: list[Path] = []

    def save_jpeg(path: Path, rgb: np.ndarray, comment: str | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        kw = {"quality": 90}
        if comment:
            kw["comment"] = comment.encode("utf-8")
        Image.fromarray(rgb).save(path, **kw)
        out.append(path)

    # -- SYSEYE RetiCam 3100 Plus (frames 5736×4304, here 1/4 or 1/8 scale) ------------
    rw, rh = (717, 538) if small else (1434, 1076)
    circ = (rw / 2.0, rh / 2.0, rh / 2.0 * 0.97)
    rc_dir = root / "RetiCam"
    for name, pid, born, sex, eye, stamp, json_when, fov, stitched, seed in (
            ("정하늘", "PID20260310-0A1B2C3D", "1975/05/05", "F", "OD", "20260310-101530-123",
             "2026/03/10 17:15:30.123", 176.0, False, 21),   # JSON hour off, like the device
            ("정하늘", "PID20260310-0A1B2C3D", "1975/05/05", "F", "OS", "20260310-101702-456",
             "2026/03/10 17:17:02.456", 176.0, False, 22),
            ("정하늘", "PID20260310-0A1B2C3D", "1975/05/05", "F", "OD", "20260310-102010-789",
             "2026/03/10 17:20:10.789", 220.0, True, 23),
            ("Anonymous", "#AnonymousID#", "1980/01/01", "O", "OS", "20260311-090000-001",
             "2026/03/11 16:00:00.001", 176.0, False, 24)):
        rgb = synth_fundus(eye=eye, fov_deg=fov, fov_type="internal", projection="radial",
                           size=(rw, rh), seed=seed, circle=circ, tint=(0.82, 0.45, 0.24))
        rgb = _burn_text(rgb, [f"{eye} ( Color )", pid, "DEMO", born.replace("/", "-"),
                               f"Date: {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"])
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, "JPEG", quality=90)
        rec = reticam_record(pid=pid, name=name, born=born, sex=sex, eye=eye, when=json_when, stitched=stitched)
        p = rc_dir / f"{name}-{eye.lower()}-color-{stamp}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(with_app15(buf.getvalue(), json.dumps(rec, ensure_ascii=False).encode("utf-8")))
        out.append(p)

    # -- Microclear APOLLO -------------------------------------------------------
    for pid, name, when, eye, fa, model, seed in (
            ("20260115001", "김민수", "2026-01-15 10:20:31", "OD", 90, 3007, 3),
            ("20260115001", "김민수", "2026-01-15 10:22:05", "OS", 90, 3007, 4),
            ("20260212003", "이서연", "2026-02-12 14:05:40", "OD", 112, 3006, 5)):
        fov = 165.0 if fa >= 110 else 135.0
        rgb = synth_fundus(eye=eye, fov_deg=fov, fov_type="internal", projection="equidistant",
                           size=size, seed=seed, tint=(0.78, 0.47, 0.30))
        stamp = when.replace("-", "_").replace(" ", "_").replace(":", "_")
        p = root / "PatientCapture" / f"{pid}_{name}" / when[:10].replace("-", "_") / "COLOR" / f"{stamp}.120_MCOLOR.jpg"
        save_jpeg(p, rgb, _apollo_comment(when, eye, fa, model, pid, name))

    # -- Kowa VK-2 Export Tool (45° camera) ----------------------------------------
    vk = root / "VK2_Export"

    def camera_45(eye: str, seed: int) -> np.ndarray:
        """45° camera frame: square render cropped to 4:3, circle clipped top/bottom."""
        full = synth_fundus(eye=eye, fov_deg=45, fov_type="external", projection="perspective",
                            size=(size[0], size[0]), seed=seed)
        h = size[0] * 3 // 4
        top = (size[0] - h) // 2
        return np.ascontiguousarray(full[top:top + h])

    save_jpeg(vk / "D0001234_20260110_093015_R_FUNDUS (COLOR)_1.jpg", camera_45("OD", 7))
    rgb = camera_45("OS", 8)
    p = vk / "D0001235_20260110_094500_KOWA_COLOR_L.jpg"
    save_jpeg(p, rgb)
    p.with_suffix(".xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Data xmlns:nsCommon="http://www.joia.or.jp/standardized/namespaces/Common" '
        'xmlns:nsFUNDUS="http://www.joia.or.jp/standardized/namespaces/FUNDUS">\n'
        '  <nsCommon:Company>KOWA</nsCommon:Company>\n'
        '  <nsCommon:Patient>\n    <nsCommon:ID>D0001235</nsCommon:ID>\n'
        '    <nsCommon:LastName>박</nsCommon:LastName>\n    <nsCommon:FirstName>지호</nsCommon:FirstName>\n'
        '    <nsCommon:Sex>F</nsCommon:Sex>\n    <nsCommon:DOB>1968-04-21</nsCommon:DOB>\n  </nsCommon:Patient>\n'
        '  <nsFUNDUS:ImageLaterality>L</nsFUNDUS:ImageLaterality>\n'
        '  <nsCommon:AcquisitionDate>2026-01-10</nsCommon:AcquisitionDate>\n'
        '  <nsCommon:AcquisitionTime>09:45:00</nsCommon:AcquisitionTime>\n</Data>\n', encoding="utf-8")

    # -- DICOM (VK-2 DICOM export style, OP 8-bit) -------------------------------------
    try:
        out.append(write_demo_dicom(root / "DICOM" / "OP_demo_0001.dcm", small=small))
    except Exception:  # pydicom missing: skip
        pass

    # -- no patient data at all -----------------------------------------------------
    rgb = synth_fundus(eye="OD", fov_deg=50, fov_type="external", projection="perspective",
                       size=(size[0], size[0]), seed=9)
    save_jpeg(root / "기타" / "IMG_0001.jpg", rgb)
    return out


def write_demo_dicom(path: Path, *, small: bool = False) -> Path:
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    rgb = synth_fundus(eye="OS", fov_deg=45, fov_type="external", projection="perspective",
                       size=(512, 512) if small else (1024, 1024), seed=11)
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.77.1.5.1"  # Ophthalmic Photography 8 Bit
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SpecificCharacterSet = ["", "ISO 2022 IR 149"]
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = "OP"
    ds.Manufacturer = "KOWA"
    ds.ManufacturerModelName = "VK-2 (DEMO)"
    ds.PatientID = "D0009876"
    ds.PatientName = "CHOI^YUNA=崔^有娜=최^유나"
    ds.PatientBirthDate = "19790312"
    ds.PatientSex = "F"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyDate = ds.ContentDate = "20260120"
    ds.StudyTime = ds.ContentTime = "111502"
    ds.ImageLaterality = "L"
    ds.HorizontalFieldOfView = 45
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.Rows, ds.Columns = rgb.shape[:2]
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = rgb.tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=True)
    return path
