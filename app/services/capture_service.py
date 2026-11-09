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


def read_image(path) -> Optional[np.ndarray]:
    """한글 경로에서도 읽히게 (cv2.imread 는 윈도우에서 한글 경로를 못 읽음)."""
    if cv2 is None:
        return None
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    except Exception:  # noqa: BLE001
        log.warning("image read failed: %s", path, exc_info=True)
        return None


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

    # ---- 폴더 가져오기 (안저 카메라 사진 원본 그대로) ----
    def import_photo(self, src, patient: Patient, eye: str = "NA", captured_at: str = "",
                     note: str = "") -> Capture:
        """다른 프로그램이 만든 사진 파일을 다시 인코딩하지 않고 그대로 복사해 등록한다.

        저장 위치·이름 규칙은 촬영 사진과 같다 (<root>/<환자>/<날짜>/<시각>_<안구>.<확장자>).
        복사한 크기가 원본과 다르면 실패로 보고 등록하지 않는다 (원본은 호출한 쪽이 지운다).
        """
        src = Path(src)
        ts = datetime.strptime(captured_at, "%Y-%m-%d %H:%M:%S") if captured_at else datetime.now()
        ext = src.suffix.lower().lstrip(".") or "jpg"
        primary_dir = self._patient_dir(self.config.media_root, patient, ts)
        paths.ensure_dir(primary_dir)
        dest = primary_dir / self._filename(ts, eye, ext)
        n = 2
        while dest.exists():                                   # 같은 초에 찍힌 사진
            dest = primary_dir / f"{Path(self._filename(ts, eye, ext)).stem}_{n}.{ext}"
            n += 1
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            tmp.unlink(missing_ok=True)
            raise OSError(f"복사한 크기가 원본과 다릅니다: {src.name}")
        tmp.replace(dest)

        frame = read_image(dest)
        thumb_path = self._write_thumbnail(primary_dir, dest.stem, frame) if frame is not None else None
        export_path = self._export(dest, patient, ts, dest.name)
        cap = Capture(
            patient_id=patient.id, media_type="photo",
            file_path=str(dest),
            export_path=(str(export_path) if export_path else None),
            thumbnail_path=(str(thumb_path) if thumb_path else None),
            captured_at=ts.strftime("%Y-%m-%d %H:%M:%S"),
            eye=eye or "NA", duration_ms=None, note=note or None,
        )
        cap.id = self.db.captures.insert(cap)
        log.info("photo imported id=%s src=%s path=%s", cap.id, src, dest)
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
