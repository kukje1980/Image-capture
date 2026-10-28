"""캡처 오케스트레이션: 기본 저장 + 썸네일 + export 폴더 + DB 한 곳에서 처리.

요구사항 핵심: 사진/동영상 저장 시 ① 환자별 폴더에 기본 저장,
② 지정 export 폴더에도 복사, ③ DB(captures)에 레코드 삽입.
export 실패는 기본 저장/DB를 막지 않으며 export_path=NULL로 기록한다.

이미 있는 파일은 절대 덮어쓰지 않는다 (같은 밀리초 촬영·이름이 같아지는 두 환자 → 뒤에 _2, _3 …).
파일은 OpenCV 의 파일 입출력을 쓰지 않고 파이썬으로 쓴다 (윈도우 OpenCV 는 한글 경로에 쓰지 못함).
"""
from __future__ import annotations

import logging
import os
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
        if ext not in ("png", "jpg", "jpeg"):
            ext = "png"
        primary_dir = self._patient_dir(self.config.media_root, patient, ts)
        paths.ensure_dir(primary_dir)
        data = _encode(frame, ext)
        primary_path = _write_new(primary_dir / self._filename(ts, eye, ext), data, durable=True)

        thumb_path = self._write_thumbnail(primary_dir, primary_path.stem, frame)
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
        log.info("photo saved id=%s path=%s export=%s", cap.id, primary_path, export_path)
        return cap

    # ---- 동영상 ----
    def begin_video(self, patient: Patient, eye: str = "NA") -> Tuple[Path, datetime]:
        """녹화기가 직접 쓸 대상 경로를 만들어 반환한다."""
        ts = datetime.now()
        primary_dir = self._patient_dir(self.config.media_root, patient, ts)
        paths.ensure_dir(primary_dir)
        path = primary_dir / self._filename(ts, eye, "mp4")
        for cand in _candidates(path):           # 녹화기가 덮어쓰므로 아직 없는 이름을 고른다
            if not cand.exists() and not (cand.parent / ".thumbs" / f"{cand.stem}.jpg").exists():
                return cand, ts
        raise RuntimeError(f"저장할 파일 이름을 만들 수 없습니다: {path}")

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
        e = paths.sanitize(eye or "NA", 8)
        return f"{ts:%H%M%S}_{ts.microsecond // 1000:03d}_{e}.{ext}"

    def _write_thumbnail(self, parent_dir: Path, stem: str, frame) -> Optional[Path]:
        try:
            thumb_dir = paths.ensure_dir(Path(parent_dir) / ".thumbs")
            thumb_path = thumb_dir / f"{stem}.jpg"
            thumb_path.write_bytes(_encode(make_thumbnail(frame, self.config.thumbnail_max_side), "jpg"))
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
            return _copy_new(primary_path, export_dir / fname)
        except Exception:  # noqa: BLE001
            log.warning("export 복사 실패 (export_path=NULL로 기록)", exc_info=True)
            return None



def _candidates(path: Path):
    yield path
    for n in range(2, 10000):
        yield path.with_name(f"{path.stem}_{n}{path.suffix}")


def _open_new(path: Path):
    """아직 없는 이름으로만 새 파일을 연다 (원자적 — 여러 스레드가 같은 이름을 골라도 겹치지 않음)."""
    for cand in _candidates(path):
        try:
            return cand, open(cand, "xb")
        except FileExistsError:
            continue
    raise RuntimeError(f"저장할 파일 이름을 만들 수 없습니다: {path}")


def _write_new(path: Path, data: bytes, durable: bool = False) -> Path:
    """data 를 새 파일로 기록. 실패하면 반쯤 쓴 파일을 남기지 않는다.
    durable: DB 에 기록하기 전에 디스크에 확정 (정전 시 DB 는 있는데 파일이 비어 있는 일 방지)."""
    path, f = _open_new(path)
    try:
        with f:
            f.write(data)
            if durable:
                f.flush()
                os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _copy_new(src: Path, dest: Path) -> Path:
    dest, out = _open_new(dest)
    try:
        with out, open(src, "rb") as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    try:
        shutil.copystat(src, dest)               # 촬영 시각 보존 — 일부 NAS 는 거부하지만 사본 자체는 유효
    except OSError:
        pass
    return dest


def _encode(frame, ext: str) -> bytes:
    """프레임 → 이미지 파일 내용 (png/jpg)."""
    ext = (ext or "png").lower()
    if cv2 is not None:
        params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in ("jpg", "jpeg") else []
        ok, buf = cv2.imencode("." + ext, frame, params)
        if not ok:
            raise RuntimeError(f"이미지 변환 실패 ({ext})")
        return buf.tobytes()
    import io

    import imageio
    rgb = frame
    if frame.ndim == 3 and frame.shape[2] >= 3:      # BGR(A) → RGB(A)
        rgb = frame[..., [2, 1, 0, *range(3, frame.shape[2])]]
    bio = io.BytesIO()
    imageio.imwrite(bio, np.ascontiguousarray(rgb), format="jpeg" if ext in ("jpg", "jpeg") else ext)
    return bio.getvalue()
