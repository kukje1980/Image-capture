"""캡처 오케스트레이션: 기본 저장 + 썸네일 + export 폴더 + DB 한 곳에서 처리.

요구사항 핵심: 사진/동영상 저장 시 ① 환자별 폴더에 기본 저장,
② 지정 export 폴더에도 복사, ③ DB(captures)에 레코드 삽입.
export 실패는 기본 저장/DB를 막지 않으며 export_path=NULL로 기록한다.
"""
from __future__ import annotations

import logging
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
