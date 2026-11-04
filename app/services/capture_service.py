"""캡처 오케스트레이션: 기본 저장 + 썸네일 + export 폴더 + DB 한 곳에서 처리.

요구사항 핵심: 사진/동영상 저장 시 ① 환자별 폴더에 기본 저장,
② 지정 export 폴더에도 복사, ③ DB(captures)에 레코드 삽입.
export 실패는 기본 저장/DB를 막지 않으며 export_path=NULL로 기록한다.
안저판은 import_photo() 로 카메라가 저장한 사진 파일을 원본 그대로(재압축 없이) 같은 규칙으로 등록한다.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from app import paths
from app.capture.frame_utils import make_thumbnail
from app.models.capture import Capture
from app.models.patient import Patient

try:
    import cv2
except ImportError:
    cv2 = None

log = logging.getLogger(__name__)

_EXT_ALIAS = {"jpeg": "jpg", "tiff": "tif"}
_EYE_STEM = re.compile(r"^(?P<head>.*_)(?P<eye>OD|OS|OU|NA)(?P<tail>_\d+)?$")


class ImageNotReady(ValueError):
    """이미지로 읽을 수 없음 (아직 쓰는 중이거나 손상·지원하지 않는 형식)."""


def read_image(path) -> np.ndarray:
    """사진 파일 → BGR 배열. 한글 경로도 되도록 바이트로 읽어 디코드한다."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if (cv2 is not None and data.size) else None
    if img is None:
        raise ImageNotReady(f"이미지를 읽을 수 없습니다: {Path(path).name}")
    return img


def capture_time(path) -> datetime:
    """촬영 시각: 사진 EXIF(DateTimeOriginal → DateTime) → 파일 수정 시각 순."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if raw:
            return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:  # noqa: BLE001 — EXIF 가 없거나 형식이 달라도 수정 시각으로 대신
        pass
    return datetime.fromtimestamp(os.path.getmtime(path))


class CaptureService:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    # ---- 사진 ----
    def save_photo(self, frame: np.ndarray, patient: Patient,
                   eye: str = "NA", note: str = "") -> Capture:
        if frame is None:
            raise ValueError("저장할 프레임이 없습니다.")
        ts = datetime.now()
        ext = (self.config.photo_format or "png").lower()
        primary_dir = self._patient_dir(self.config.media_root, patient, ts)
        paths.ensure_dir(primary_dir)
        fname = self._filename(ts, eye, ext)
        primary_path = primary_dir / fname
        self._imwrite(primary_path, frame, ext)

        thumb_path = self._write_thumbnail(primary_dir, primary_path.stem, frame)
        export_path = self._export(primary_path, patient, ts, fname)

        cap = Capture(
            patient_id=patient.id, media_type="photo",
            file_path=str(primary_path),
            export_path=(str(export_path) if export_path else None),
            thumbnail_path=(str(thumb_path) if thumb_path else None),
            captured_at=ts.strftime("%Y-%m-%d %H:%M:%S"),
            eye=eye, duration_ms=None, note=note,
        )
        cap.id = self.db.captures.insert(cap)
        log.info("photo saved id=%s path=%s export=%s", cap.id, primary_path, export_path)
        return cap

    # ---- 사진 파일 가져오기 (안저판) ----
    def import_photo(self, src, patient: Patient, eye: str = "NA", note: str = "") -> Capture:
        """카메라가 저장한 사진 파일을 환자 폴더로 복사(원본 화질 그대로) + 썸네일 + export + DB."""
        src = Path(src)
        img = read_image(src)                        # 다 써지지 않은 파일이면 ImageNotReady
        ts = capture_time(src)
        ext = src.suffix.lower().lstrip(".") or "jpg"
        ext = _EXT_ALIAS.get(ext, ext)
        primary_dir = self._patient_dir(self.config.media_root, patient, ts)
        paths.ensure_dir(primary_dir)
        primary_path = self._unique(primary_dir / self._filename(ts, eye, ext))
        shutil.copy2(src, primary_path)

        thumb_path = self._write_thumbnail(primary_dir, primary_path.stem, img)
        export_path = self._export(primary_path, patient, ts, primary_path.name)
        cap = Capture(
            patient_id=patient.id, media_type="photo",
            file_path=str(primary_path),
            export_path=(str(export_path) if export_path else None),
            thumbnail_path=(str(thumb_path) if thumb_path else None),
            captured_at=ts.strftime("%Y-%m-%d %H:%M:%S"),
            eye=eye, duration_ms=None, note=note,
        )
        cap.id = self.db.captures.insert(cap)
        log.info("photo imported id=%s src=%s → %s export=%s", cap.id, src, primary_path, export_path)
        return cap

    def change_eye(self, cap: Capture, eye: str) -> Capture:
        """저장된 영상의 안구를 바꾼다. 파일 이름의 _OD/_OS 도 함께 바꿔 폴더에서도 맞게 보이도록."""
        if eye not in ("OD", "OS", "OU", "NA") or cap.id is None or eye == (cap.eye or "NA"):
            return cap

        def renamed(p: Optional[str]) -> Optional[str]:
            if not p:
                return p
            old = Path(p)
            m = _EYE_STEM.match(old.stem)
            if not m or not old.exists():
                return p
            new = old.with_name(f"{m['head']}{eye}{m['tail'] or ''}{old.suffix}")
            if new.exists():
                return p
            try:
                os.replace(old, new)
            except OSError:
                log.warning("rename failed %s", old, exc_info=True)
                return p
            return str(new)

        cap.file_path = renamed(cap.file_path)
        cap.export_path = renamed(cap.export_path)
        cap.thumbnail_path = renamed(cap.thumbnail_path)
        cap.eye = eye
        self.db.captures.update_eye(cap.id, eye, cap.file_path, cap.export_path, cap.thumbnail_path)
        log.info("eye changed id=%s → %s", cap.id, eye)
        return cap

    # ---- 동영상 ----
    def begin_video(self, patient: Patient, eye: str = "NA") -> Tuple[Path, datetime]:
        """녹화기가 직접 쓸 대상 경로를 만들어 반환한다."""
        ts = datetime.now()
        primary_dir = self._patient_dir(self.config.media_root, patient, ts)
        paths.ensure_dir(primary_dir)
        fname = self._filename(ts, eye, "mp4")
        return primary_dir / fname, ts

    def finish_video(self, video_path, patient: Patient, eye: str, ts: datetime,
                     duration_ms: int, thumb_frame: Optional[np.ndarray] = None,
                     note: str = "") -> Capture:
        video_path = Path(video_path)
        thumb_path = None
        if thumb_frame is not None:
            thumb_path = self._write_thumbnail(video_path.parent, video_path.stem, thumb_frame)
        export_path = self._export(video_path, patient, ts, video_path.name)

        cap = Capture(
            patient_id=patient.id, media_type="video",
            file_path=str(video_path),
            export_path=(str(export_path) if export_path else None),
            thumbnail_path=(str(thumb_path) if thumb_path else None),
            captured_at=ts.strftime("%Y-%m-%d %H:%M:%S"),
            eye=eye, duration_ms=duration_ms, note=note,
        )
        cap.id = self.db.captures.insert(cap)
        log.info("video saved id=%s path=%s export=%s", cap.id, video_path, export_path)
        return cap

    # ---- 내부 헬퍼 ----
    def _patient_dir(self, root, patient, ts) -> Path:
        return paths.patient_subdir(Path(root), patient, self.config.subfolder_template, ts)

    @staticmethod
    def _filename(ts: datetime, eye: str, ext: str) -> str:
        e = eye or "NA"
        return f"{ts:%H%M%S}_{ts.microsecond // 1000:03d}_{e}.{ext}"

    @staticmethod
    def _unique(path: Path) -> Path:
        """같은 초에 찍은 사진(연속 촬영)이 서로 덮어쓰지 않게 _2, _3 … 을 붙인다."""
        if not path.exists():
            return path
        for i in range(2, 1000):
            cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
            if not cand.exists():
                return cand
        raise RuntimeError(f"저장할 파일 이름을 만들 수 없습니다: {path}")

    def _write_thumbnail(self, parent_dir: Path, stem: str, frame) -> Optional[Path]:
        try:
            thumb_dir = paths.ensure_dir(Path(parent_dir) / ".thumbs")
            thumb_path = thumb_dir / f"{stem}.jpg"
            self._imwrite(thumb_path, make_thumbnail(frame, self.config.thumbnail_max_side), "jpg")
            return thumb_path
        except Exception:  # noqa: BLE001
            log.warning("thumbnail 생성 실패", exc_info=True)
            return None

    def _export(self, primary_path: Path, patient, ts, fname) -> Optional[Path]:
        if not self.config.export_root:
            return None
        try:
            export_dir = self._patient_dir(self.config.export_root, patient, ts)
            paths.ensure_dir(export_dir)
            export_path = export_dir / fname
            shutil.copy2(primary_path, export_path)
            return export_path
        except Exception:  # noqa: BLE001
            log.warning("export 복사 실패 (export_path=NULL로 기록)", exc_info=True)
            return None

    def _imwrite(self, path: Path, frame, ext: str) -> None:
        ext = ext.lower()
        if cv2 is not None:
            params = []
            if ext in ("jpg", "jpeg"):
                params = [cv2.IMWRITE_JPEG_QUALITY, 95]
            ok = cv2.imwrite(str(path), frame, params)
            if not ok:
                raise RuntimeError(f"이미지 저장 실패: {path}")
        else:
            import imageio
            imageio.imwrite(str(path), np.ascontiguousarray(frame[..., ::-1]))
