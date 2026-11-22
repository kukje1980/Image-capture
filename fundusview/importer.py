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

Photos picked by hand (사진 가져오기, drag & drop) are first *previewed*
(:meth:`Importer.preview`: the same extraction, no image analysis) so the user
sees which patient each one goes to and can name the patient of those that do
not say (:class:`~fundusview.models.PatientAssign`).
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import imaging, placement
from .config import ACTION_MOVE, ACTION_REFERENCE, Settings, WatchFolder
from .db import Database
from .extract import extract_metadata, is_dicom
from .models import FIELD_LABELS, ExtractedMeta, PatientAssign
from .profiles import IGNORED_EXTS, IMAGE_EXTS, get_profile
from .projection import theta_max


@dataclass
class ImportResult:
    status: str            # imported / duplicate / assigned (an unassigned duplicate got its patient)
                           # / skipped / pending / error
    path: str
    message: str = ""
    image_id: int | None = None
    patient_ref: int | None = None


# Folder names read for a photo picked by hand (no watched root): …/12345_홍길동/2026-03-01/IMG_1.jpg
MANUAL_PARENT_LEVELS = 2


@dataclass
class PreviewItem:
    """What importing ``path`` would do — shown before the import (사진 가져오기 → 확인 창)."""
    path: str
    status: str                       # new / duplicate (already in the library) / error
    meta: ExtractedMeta = field(default_factory=ExtractedMeta)
    profile_name: str = ""
    message: str = ""
    image_id: int | None = None       # duplicate: the photo it already is
    patient_ref: int | None = None    # duplicate: that photo's patient (None = 미분류)
    folder: WatchFolder | None = None  # the folder settings it was read with (and is imported with)


def apply_assign(meta: ExtractedMeta, assign: PatientAssign | None) -> ExtractedMeta:
    """The patient the user named wins over what the file says (which is kept in ``raw``)."""
    if assign is None or not (assign.patient_id or "").strip():
        return meta
    other = meta.patient_id not in (None, "", assign.patient_id.strip())
    for name in ("patient_id", "name", "birth_date", "sex"):
        value = getattr(assign, name)
        value = value.strip() if isinstance(value, str) else value
        have = getattr(meta, name)
        if value and value != have:
            if have:
                meta.raw[f"파일의 {FIELD_LABELS[name]}"] = str(have)
            setattr(meta, name, value)
            meta.sources[name] = "user"
        elif other and not value and have:      # another patient: the file's name / birth date are not theirs
            meta.raw[f"파일의 {FIELD_LABELS[name]}"] = str(have)
            setattr(meta, name, None)
            meta.sources.pop(name, None)
    return meta


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE)


def safe_component(s: str, fallback: str = "_") -> str:
    """``s`` as a file / folder name every file system takes: no separators or control
    characters, no name Windows reserves (a patient id ``CON`` or ``NUL``), at most 80
    characters — cut in the stem, so a long file name keeps its extension."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s or "").strip(" .")
    if len(s) > 80:
        stem, dot, ext = s.rpartition(".")
        s = stem[:80 - len(ext) - 1].rstrip(" .") + "." + ext if dot and 0 < len(ext) <= 8 and stem else s[:80]
        s = s.strip(" .")
    if _WINDOWS_RESERVED.match(s):
        s = "_" + s
    return s or fallback


def describe_error(exc: BaseException) -> str:
    """An import failure in the user's words, the technical message after it."""
    kind, text = type(exc).__name__, str(exc)
    if kind == "DecompressionBombError":
        said = "사진이 너무 큽니다 (4억 화소 초과)"
    elif kind == "UnidentifiedImageError":
        said = "사진 파일이 아니거나 손상된 파일입니다"
    elif "truncated" in text.lower() or "Truncated" in text:
        said = "끝까지 저장되지 않은 사진입니다 (파일 손상)"
    elif "pixel data" in text.lower() or "Pixel Data" in text or kind == "InvalidDicomError":
        said = "DICOM 영상을 읽을 수 없습니다"
    elif isinstance(exc, PermissionError):
        said = "파일을 열 권한이 없거나 다른 프로그램이 쓰고 있습니다"
    elif isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        said = "디스크에 남은 공간이 없습니다"
    elif isinstance(exc, MemoryError):
        said = "메모리가 부족합니다"
    else:
        return f"{kind}: {text}"
    return f"{said} — {kind}: {text}"


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
    """True once the file stopped changing and can be opened.

    A file that stays empty is given up soon (False: tried again when it changes) — a failed
    copy leaves such files behind, and waiting the whole ``timeout`` for each of them would hold
    up every photo queued after it."""
    deadline = time.monotonic() + timeout
    empty_deadline = time.monotonic() + min(max(2 * seconds, 0.3), 3.0)
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
        elif st.st_size == 0:
            if now >= empty_deadline:
                return False
        elif now - stable_since >= seconds:
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

    def _extract(self, path: Path, folder: WatchFolder | None, assign: PatientAssign | None = None):
        """``(meta, profile)`` of a file: a watched folder gives its profile and root, a photo
        picked by hand is read with its nearest folder names."""
        meta, profile = extract_metadata(
            path, folder.profile if folder else "auto", watch_root=Path(folder.path) if folder else None,
            custom_patterns=self.settings.custom_filename_patterns,
            parent_levels=None if folder else MANUAL_PARENT_LEVELS)
        return apply_assign(meta, assign), profile

    def preview(self, path: Path | str, folder: WatchFolder | None = None) -> PreviewItem:
        """What :meth:`import_file` would read from ``path`` — nothing is stored."""
        path = Path(path)
        spath = str(path)
        try:
            if not path.is_file() or not is_candidate(path) or self._in_library(path):
                return PreviewItem(spath, "error", message="지원하지 않는 파일")
            st = path.stat()
            if st.st_size == 0:
                return PreviewItem(spath, "error", message="빈 파일")
            image_id = self.db.seen_image(spath, st.st_size, st.st_mtime)
            dup = self.db.get_image(image_id) if image_id is not None else None
            if dup is None:
                dup = self.db.image_by_sha(sha256_of(path))
            if dup is None and not is_dicom(path):
                with Image.open(path) as img:        # the header only: is it a picture at all?
                    img.size
            meta, profile = self._extract(path, folder)
            if dup is not None:
                return PreviewItem(spath, "duplicate", meta, profile.name, "이미 가져온 사진",
                                   dup["id"], dup["patient_ref"], folder)
            return PreviewItem(spath, "new", meta, profile.name, folder=folder)
        except Exception as exc:
            return PreviewItem(spath, "error", message=describe_error(exc)[:200])

    def import_file(self, path: Path | str, folder: WatchFolder | None = None, *,
                    force: bool = False, wait: bool = True,
                    assign: PatientAssign | None = None) -> ImportResult:
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
            return self._import(path, folder, st, assign)
        except Exception as exc:  # keep the watcher alive on any bad file
            msg = describe_error(exc)
            self.db.mark_seen(spath, st.st_size, st.st_mtime, "error", None, msg[:500])
            self.db.log("error", f"가져오기 실패 — {msg}", spath)
            return ImportResult("error", spath, msg)

    def _import(self, path: Path, folder: WatchFolder | None, st: os.stat_result,
                assign: PatientAssign | None = None) -> ImportResult:
        spath = str(path)
        digest = sha256_of(path)
        dup = self.db.image_by_sha(digest)
        if dup is not None:
            return self._duplicate(path, folder, st, dup, assign)

        meta, profile = self._extract(path, folder, assign)

        # The photo as the analysis needs it: a large JPEG is decoded reduced (its full size is
        # ``w`` × ``h``); what is found is scaled back to the photo's own pixels below.
        needs_display = is_dicom(path) or path.suffix.lower() in (".tif", ".tiff", "")
        if needs_display:
            rgb = imaging.load_rgb(path)
            h, w = rgb.shape[:2]
        else:
            rgb, w, h = imaging.load_for_import(path)
        fx, fy = w / rgb.shape[1], h / rgb.shape[0]
        circle = imaging.detect_circle(rgb)
        tmax_deg = math.degrees(theta_max(meta.fov_deg or profile.fov_deg,
                                          meta.fov_type or profile.fov_type, profile.viewpoint))
        disc = None
        if meta.modality not in ("montage", "anterior"):
            disc = imaging.detect_disc(rgb, circle, disc_frac=min(0.25, 3.8 / max(tmax_deg, 5.0)),
                                       search=profile.disc_search)
        guessed = not meta.laterality and meta.modality not in ("montage", "anterior")
        if guessed:
            meta.set("laterality", imaging.laterality_from_disc(disc, circle), "disc-estimate")
        fovea = None                    # with the disc it says where the photo lies on the eye (3D)
        if disc is not None:
            cam = placement.Camera(*circle, meta.fov_deg or profile.fov_deg, meta.fov_type or profile.fov_type,
                                   meta.projection or profile.projection, profile.viewpoint,
                                   get_profile(profile.key).radial_c)   # (the measured lens curve)
            # an eye the file does not name: the macula is looked for on both sides of the disc, and the
            # side it is on (temporal of the disc) tells the eye better than where the disc lies
            found = imaging.detect_fovea(rgb, cam, disc[:2], None if guessed else meta.laterality, with_side=True)
            if found is not None:
                fovea = found[:3]
                if guessed and found[3] != meta.laterality:
                    meta.laterality = found[3]
                    meta.sources["laterality"] = "fovea-estimate"
        if (fx, fy) != (1.0, 1.0):      # back to the photo's own pixels
            circle = (circle[0] * fx, circle[1] * fy, circle[2] * (fx + fy) / 2)
            disc = (disc[0] * fx, disc[1] * fy, *disc[2:]) if disc is not None else None
            fovea = (fovea[0] * fx, fovea[1] * fy, *fovea[2:]) if fovea is not None else None

        # -- store the file -------------------------------------------------
        pid_dir = safe_component(meta.patient_id or "", "_미분류")
        date_dir = meta.exam_date or "날짜없음"
        dest_dir = self.library / "images" / pid_dir / date_dir
        action = folder.action if folder else "copy"
        made: list[Path] = []           # files written here: removed again if the import fails
        try:
            if action == ACTION_REFERENCE:
                stored = path
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                stored = dest_dir / safe_component(path.name, "image")
                if stored.exists():
                    stored = dest_dir / f"{stored.stem}_{digest[:8]}{stored.suffix}"
                made.append(stored)
                shutil.copy2(spath, stored)     # a moved file leaves its folder only once it is registered
            display = None
            if needs_display:
                display = self.library / "display" / f"{digest[:24]}.png"
                display.parent.mkdir(parents=True, exist_ok=True)
                made.append(display)
                Image.fromarray(rgb).save(display, compress_level=1)
            thumb = self.library / "thumbs" / f"{digest[:24]}.jpg"
            thumb.parent.mkdir(parents=True, exist_ok=True)
            made.append(thumb)
            imaging.thumbnail(rgb).save(thumb, quality=88)

            # -- database (one commit) ---------------------------------------------
            with self.db.batch():
                patient_ref = self._patient_of(meta, spath)
                meta_dict = meta.as_dict()
                meta_dict["profile_name"] = profile.name
                meta_dict["source_file"] = spath
                image_id = self._insert(meta, profile, meta_dict, patient_ref, stored, display, thumb, spath,
                                        digest, w, h, circle, disc, fovea)
                # A moved file no longer exists at its source path; index the source
                # path anyway so a rescan of a "reference" folder does not re-import.
                self.db.mark_seen(spath, st.st_size, st.st_mtime, "imported", image_id)
                who = f"{meta.patient_id} {meta.name or ''}".strip() if meta.patient_id else "미분류"
                self.db.log("info", f"가져옴 — {who} · {meta.exam_date or '-'} · {meta.laterality or '-'} "
                                    f"· {profile.name}", spath)
        except BaseException:
            for f in made:                      # nothing half-imported stays in the library
                try:
                    f.unlink()
                except OSError:
                    pass
            raise
        if action == ACTION_MOVE:
            try:
                os.remove(spath)
            except OSError as exc:              # still open in the capture software: it stays, already imported
                self.db.log("warn", f"가져온 뒤 원본을 지우지 못함 — {exc}", spath)
        return ImportResult("imported", spath, who, image_id, patient_ref)

    def _patient_of(self, meta: ExtractedMeta, spath: str) -> int | None:
        """The patient row of ``meta`` (made or completed), ``None`` = 미분류."""
        if not meta.patient_id:
            return None
        if meta.name:
            existing = self.db.find_patient(meta.patient_id)
            if existing is not None and existing["name"] and \
                    existing["name"].replace(" ", "").lower() != meta.name.replace(" ", "").lower():
                # Same id, different name: two devices numbering patients
                # differently, or a typo at capture — make it visible.
                meta.raw["이름 불일치"] = f"파일: {meta.name} / 등록: {existing['name']}"
                self.db.log("warn", f"환자 ID {meta.patient_id}: 파일의 이름 '{meta.name}' ≠ 등록된 이름 "
                                    f"'{existing['name']}' — 확인 필요", spath)
        return self.db.upsert_patient(meta)

    def _duplicate(self, path: Path, folder: WatchFolder | None, st: os.stat_result, dup,
                   assign: PatientAssign | None) -> ImportResult:
        """The same photo again. One that lies in 미분류 gets the patient this copy names (the
        user picked it once more and said whose it is, or it came again with its data)."""
        spath = str(path)
        if dup["patient_ref"] is None:
            try:
                meta, _profile = self._extract(path, folder, assign)
            except Exception:
                meta = apply_assign(ExtractedMeta(), assign)
            if meta.patient_id:
                with self.db.batch():
                    ref = self._patient_of(meta, spath)
                    self.db.update_image(dup["id"], patient_ref=ref)
                    self.db.mark_seen(spath, st.st_size, st.st_mtime, "duplicate", dup["id"])
                    who = f"{meta.patient_id} {meta.name or ''}".strip()
                    self.db.log("info", f"미분류였던 영상 #{dup['id']} → 환자 {who}", spath)
                return ImportResult("assigned", spath, who, dup["id"], ref)
        with self.db.batch():
            self.db.mark_seen(spath, st.st_size, st.st_mtime, "duplicate", dup["id"])
            self.db.log("info", f"중복 파일 — 이미 등록된 영상 #{dup['id']}", spath)
        return ImportResult("duplicate", spath, "중복", dup["id"], dup["patient_ref"])

    def _insert(self, meta, profile, meta_dict, patient_ref, stored, display, thumb, spath, digest, w, h,
                circle, disc, fovea) -> int:
        return self.db.insert_image(
            patient_ref=patient_ref, exam_date=meta.exam_date, exam_time=meta.exam_time,
            laterality=meta.laterality, modality=meta.modality, device=meta.device,
            profile=profile.key, fov_deg=meta.fov_deg, fov_type=meta.fov_type,
            projection=meta.projection or profile.projection, file_path=str(stored),
            display_path=str(display) if display else None, thumb_path=str(thumb),
            original_path=spath, sha256=digest, width=w, height=h,
            circle_cx=circle[0], circle_cy=circle[1], circle_r=circle[2],
            disc_x=disc[0] if disc else None, disc_y=disc[1] if disc else None,
            fovea_x=fovea[0] if fovea else None, fovea_y=fovea[1] if fovea else None,
            meta_json=meta_dict,
        )

    def add_derived(self, row, rgb, note: str = "편집 영상", *, suffix: str = "편집", derived_from=None,
                    **fields) -> int:
        """Store an edited copy (VK-2 "Save Edited Image") next to ``row`` in the
        same patient record; the original photo is untouched. ``fields`` override
        the image row's values (e.g. ``modality`` of a composed sheet)."""
        import io
        import json

        # Encode and analyse before creating any files, so failures leave no partial record.
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, "PNG", compress_level=3)
        data = buf.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        thumb_buf = io.BytesIO()
        imaging.thumbnail(rgb).save(thumb_buf, "JPEG", quality=88)
        circle = imaging.detect_circle(rgb)
        meta = json.loads(row["meta_json"] or "{}")
        meta["derived_from"] = row["id"] if derived_from is None else derived_from
        h, w = rgb.shape[:2]
        values = dict(
            patient_ref=row["patient_ref"], exam_date=row["exam_date"], exam_time=row["exam_time"],
            laterality=row["laterality"], modality=row["modality"], device=row["device"], profile=row["profile"],
            fov_deg=row["fov_deg"], fov_type=row["fov_type"], projection=row["projection"],
            width=w, height=h, circle_cx=circle[0], circle_cy=circle[1], circle_r=circle[2],
            meta_json=meta, note=note,
        )
        values.update(fields)
        # Existing sha256 values and their unique index stay intact. New derived records use
        # a unique record identity there and retain the actual file hash in content_sha256. Physical
        # equality alone must never return a record belonging to another patient/eye/exam.
        storage_fields = {"file_path", "display_path", "thumb_path", "original_path", "sha256", "content_sha256"}
        identity_values = {k: v for k, v in values.items() if k not in storage_fields}
        identity = hashlib.sha256(("derived-v1:" + digest + ":" + uuid.uuid4().hex).encode("ascii")).hexdigest()

        def existing_record():
            # Compare the current values too: a previous derived record may have been moved
            # to another patient or had its eye/exam corrected since it was first saved.
            for candidate in self.db.derived_with_content(digest):
                current = dict(candidate)
                try:
                    current["meta_json"] = json.loads(current["meta_json"] or "{}")
                except (ValueError, TypeError):
                    continue
                if all(current.get(key) == value for key, value in identity_values.items()):
                    return candidate
            return None

        patient = self.db.get_patient(values["patient_ref"]) if values["patient_ref"] else None
        pid_dir = safe_component(patient["patient_id"] if patient else "", "_미분류")
        dest_dir = self.library / "images" / pid_dir / (values["exam_date"] or "날짜없음")
        stem = Path(row["original_path"] or row["file_path"]).stem
        made: list[Path] = []
        kept = False
        try:
            dup = existing_record()
            if dup is not None:
                return dup["id"]
            stored = _write_new_file(dest_dir, safe_component(f"{stem}_{suffix}")[:48], ".png", data)
            made.append(stored)
            thumb = _write_new_file(self.library / "thumbs", identity[:24], ".jpg", thumb_buf.getvalue())
            made.append(thumb)
            values.update(file_path=str(stored), display_path=None, thumb_path=str(thumb),
                          original_path=str(stored), sha256=identity, content_sha256=digest)
            # Recheck under the write lock after I/O: another sharing thread may have saved
            # the same scoped record while these files were being prepared.
            with self.db.batch():
                dup = existing_record()
                if dup is not None:
                    return dup["id"]
                image_id = self.db.insert_image(**values)
                self.db.log("info", f"편집 영상 저장 — 원본 #{row['id']} → #{image_id}", str(stored))
            kept = True
            return image_id
        finally:
            if not kept:
                for path in made:
                    try:
                        path.unlink()
                    except OSError:
                        pass


def _write_new_file(directory: Path, prefix: str, suffix: str, data: bytes) -> Path:
    """Publish a complete file under an exclusively reserved name; clean up on failure."""
    directory.mkdir(parents=True, exist_ok=True)
    final_fd, final_name = tempfile.mkstemp(prefix=prefix + "_", suffix=suffix, dir=directory)
    os.close(final_fd)
    final = Path(final_name)
    pending: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix="." + final.name + ".", suffix=".part", dir=directory)
        pending = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, final)  # only our own exclusive reservation is replaced
        return final
    except BaseException:
        for path in (pending, final):
            if path is not None:
                try:
                    path.unlink()
                except OSError:
                    pass
        raise
