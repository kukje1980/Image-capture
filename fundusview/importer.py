"""File -> database import.

For each candidate file:

1. wait until the capture software has finished writing it (size/mtime
   stable for ``stable_seconds`` and the file opens for reading),
2. skip it if it was already handled (seen-file index) or its SHA-256 is
   already in the library (the same photo exported twice),
3. extract patient / exam metadata (``extract``) and analyse the image
   (fundus circle, optic disc, eye from the disc side if nothing said),
4. copy / move it into the library ``images/<환자ID>/<검사일>/`` (or keep it in
   place), write a thumbnail and — for DICOM — a viewable PNG,
5. create / complete the patient and insert the image row.

Files without a patient id are kept as 미분류 (unassigned) for the user to
assign; nothing is guessed.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import imaging
from .config import ACTION_MOVE, ACTION_REFERENCE, Settings, WatchFolder
from .db import Database
from .extract import extract_metadata, is_dicom
from .profiles import IGNORED_EXTS, IMAGE_EXTS
from .projection import theta_max


@dataclass
class ImportResult:
    status: str            # imported / duplicate / skipped / pending / error
    path: str
    message: str = ""
    image_id: int | None = None
    patient_ref: int | None = None


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def safe_component(s: str, fallback: str = "_") -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "").strip(" .")
    return s[:80] or fallback


def is_candidate(path: Path) -> bool:
    name = path.name
    if name.startswith((".", "~$")) or name.lower() in ("thumbs.db", "desktop.ini"):
        return False
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return True
    if ext in IGNORED_EXTS:
        return False
    # DICOM from PACS / VK-2 exports often has no extension.
    return ext == "" and is_dicom(path)


def wait_until_stable(path: Path, seconds: float, timeout: float = 180.0) -> bool:
    """True once the file stopped changing and can be opened."""
    deadline = time.monotonic() + timeout
    last = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        try:
            st = path.stat()
            sig = (st.st_size, st.st_mtime_ns)
        except OSError:
            return False
        now = time.monotonic()
        if sig != last:
            last, stable_since = sig, now
        elif now - stable_since >= seconds and st.st_size > 0:
            try:
                with open(path, "rb") as f:  # still locked by the writer on Windows?
                    f.read(1)
                return True
            except OSError:
                stable_since = now
        time.sleep(min(0.25, max(seconds / 4, 0.05)))
    return False


class Importer:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    @property
    def library(self) -> Path:
        return self.settings.library

    def _in_library(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.library.resolve())
            return True
        except (ValueError, OSError):
            return False

    def import_file(self, path: Path | str, folder: WatchFolder | None = None, *,
                    force: bool = False, wait: bool = True) -> ImportResult:
        path = Path(path)
        spath = str(path)
        if not path.is_file() or not is_candidate(path) or self._in_library(path):
            return ImportResult("skipped", spath, "지원하지 않는 파일")
        if wait and not wait_until_stable(path, self.settings.stable_seconds):
            return ImportResult("pending", spath, "파일 쓰기가 끝나지 않음 (다음 검사에서 재시도)")
        st = path.stat()
        seen = self.db.seen(spath)
        if (not force and seen is not None and seen["size"] == st.st_size
                and abs((seen["mtime"] or 0) - st.st_mtime) < 1e-3 and seen["status"] != "error"):
            return ImportResult("skipped", spath, "이미 처리됨", seen["image_id"])
        try:
            return self._import(path, folder, st)
        except Exception as exc:  # keep the watcher alive on any bad file
            msg = f"{type(exc).__name__}: {exc}"
            self.db.mark_seen(spath, st.st_size, st.st_mtime, "error", None, msg[:500])
            self.db.log("error", f"가져오기 실패 — {msg}", spath)
            return ImportResult("error", spath, msg)

    def _import(self, path: Path, folder: WatchFolder | None, st: os.stat_result) -> ImportResult:
        spath = str(path)
        digest = sha256_of(path)
        dup = self.db.image_by_sha(digest)
        if dup is not None:
            self.db.mark_seen(spath, st.st_size, st.st_mtime, "duplicate", dup["id"])
            self.db.log("info", f"중복 파일 — 이미 등록된 영상 #{dup['id']}", spath)
            return ImportResult("duplicate", spath, "중복", dup["id"], dup["patient_ref"])

        root = Path(folder.path) if folder else None
        meta, profile = extract_metadata(
            path, folder.profile if folder else "auto", watch_root=root,
            custom_patterns=self.settings.custom_filename_patterns)

        rgb = imaging.load_rgb(path)
        h, w = rgb.shape[:2]
        circle = imaging.detect_circle(rgb)
        tmax_deg = math.degrees(theta_max(meta.fov_deg or profile.fov_deg,
                                          meta.fov_type or profile.fov_type, profile.viewpoint))
        disc = None
        if meta.modality not in ("montage", "anterior"):
            disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / max(tmax_deg, 5.0)),
                                       search=profile.disc_search)
        if not meta.laterality and meta.modality not in ("montage", "anterior"):
            meta.set("laterality", imaging.laterality_from_disc(disc, circle), "disc-estimate")

        # -- store the file -------------------------------------------------
        pid_dir = safe_component(meta.patient_id or "", "_미분류")
        date_dir = meta.exam_date or "날짜없음"
        dest_dir = self.library / "images" / pid_dir / date_dir
        action = folder.action if folder else "copy"
        if action == ACTION_REFERENCE:
            stored = path
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            stored = dest_dir / safe_component(path.name, "image")
            if stored.exists():
                stored = dest_dir / f"{stored.stem}_{digest[:8]}{stored.suffix}"
            if action == ACTION_MOVE:
                shutil.move(spath, stored)
            else:
                shutil.copy2(spath, stored)
        display = None
        if is_dicom(path) or stored.suffix.lower() in (".tif", ".tiff") or stored.suffix == "":
            display = self.library / "display" / f"{digest[:24]}.png"
            display.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb).save(display, compress_level=1)
        thumb = self.library / "thumbs" / f"{digest[:24]}.jpg"
        thumb.parent.mkdir(parents=True, exist_ok=True)
        imaging.thumbnail(rgb).save(thumb, quality=88)

        # -- database ---------------------------------------------------------
        if meta.patient_id and meta.name:
            existing = self.db.find_patient(meta.patient_id)
            if existing is not None and existing["name"] and \
                    existing["name"].replace(" ", "").lower() != meta.name.replace(" ", "").lower():
                # Same id, different name: two devices numbering patients
                # differently, or a typo at capture — make it visible.
                meta.raw["이름 불일치"] = f"파일: {meta.name} / 등록: {existing['name']}"
                self.db.log("warn", f"환자 ID {meta.patient_id}: 파일의 이름 '{meta.name}' ≠ 등록된 이름 "
                                    f"'{existing['name']}' — 확인 필요", spath)
        patient_ref = self.db.upsert_patient(meta) if meta.patient_id else None
        meta_dict = meta.as_dict()
        meta_dict["profile_name"] = profile.name
        meta_dict["source_file"] = spath
        image_id = self.db.insert_image(
            patient_ref=patient_ref, exam_date=meta.exam_date, exam_time=meta.exam_time,
            laterality=meta.laterality, modality=meta.modality, device=meta.device,
            profile=profile.key, fov_deg=meta.fov_deg, fov_type=meta.fov_type,
            projection=profile.projection, file_path=str(stored),
            display_path=str(display) if display else None, thumb_path=str(thumb),
            original_path=spath, sha256=digest, width=w, height=h,
            circle_cx=circle[0], circle_cy=circle[1], circle_r=circle[2],
            disc_x=disc[0] if disc else None, disc_y=disc[1] if disc else None,
            meta_json=meta_dict,
        )
        # A moved file no longer exists at its source path; index the source
        # path anyway so a rescan of a "reference" folder does not re-import.
        self.db.mark_seen(spath, st.st_size, st.st_mtime, "imported", image_id)
        who = f"{meta.patient_id} {meta.name or ''}".strip() if meta.patient_id else "미분류"
        self.db.log("info", f"가져옴 — {who} · {meta.exam_date or '-'} · {meta.laterality or '-'} "
                            f"· {profile.name}", spath)
        return ImportResult("imported", spath, who, image_id, patient_ref)
