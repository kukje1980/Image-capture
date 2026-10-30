"""캡처 오케스트레이션: 기본 저장 + 썸네일 + export 폴더 + DB 한 곳에서 처리.

요구사항 핵심: 사진/동영상 저장 시 ① 환자별 폴더에 기본 저장,
② 지정 export(전송) 폴더에도 복사(export_on_capture 가 켜진 경우), ③ DB(captures)에 레코드 삽입.
export 실패는 기본 저장/DB를 막지 않으며 export_path=NULL로 기록한다.

촬영 후 썸네일 목록에서 고른 영상은 send_to_export() 로 전송 폴더에 (다시) 보낼 수 있고,
delete_capture() 로 원본·썸네일·DB 레코드를 지운다 (전송 폴더의 복사본은 남긴다).
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple

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

    # ---- 목록에서 보내기 / 삭제 ----
    def send_to_export(self, capture: Capture, patient: Patient) -> Path:
        """영상 하나를 전송(export) 폴더에 복사하고 export_path 를 기록한다.

        이미 전송된 복사본이 그대로 있으면 다시 복사하지 않는다. 전송 폴더가 비어 있거나
        복사에 실패하면 예외를 던진다 (호출자가 사용자에게 알린다).
        """
        if not self.config.export_root:
            raise RuntimeError("전송 폴더가 설정되지 않았습니다. 설정에서 전송 폴더를 지정하세요.")
        src = Path(capture.file_path)
        if not src.exists():
            raise FileNotFoundError(f"원본 파일이 없습니다: {src}")
        if capture.export_path and Path(capture.export_path).exists():
            return Path(capture.export_path)
        ts = self._parse_ts(capture.captured_at)
        export_dir = self._patient_dir(self.config.export_root, patient, ts)
        paths.ensure_dir(export_dir)
        dst = export_dir / src.name
        shutil.copy2(src, dst)
        capture.export_path = str(dst)
        if capture.id is not None:
            self.db.captures.update_export_path(capture.id, capture.export_path)
        log.info("capture sent id=%s -> %s", capture.id, dst)
        return dst

    def delete_capture(self, capture: Capture) -> None:
        """원본 파일·썸네일·DB 레코드를 지운다. 전송 폴더의 복사본은 남긴다."""
        row = self.db.captures.delete(capture.id) if capture.id is not None else None
        targets: Iterable[Optional[str]] = (
            (row or {}).get("file_path", capture.file_path),
            (row or {}).get("thumbnail_path", capture.thumbnail_path),
        )
        for t in targets:
            if not t:
                continue
            try:
                os.remove(t)
            except FileNotFoundError:
                pass
            except OSError:
                log.warning("파일 삭제 실패: %s", t, exc_info=True)
        log.info("capture deleted id=%s path=%s", capture.id, capture.file_path)

    @staticmethod
    def _parse_ts(text: Optional[str]) -> datetime:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text or "", fmt)
            except ValueError:
                continue
        return datetime.now()

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
        if not self.config.export_root or not getattr(self.config, "export_on_capture", True):
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
