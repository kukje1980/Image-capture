"""캡처(사진/동영상) 업로드·조회 API (/api/v1/captures).

브라우저가 캡처한 blob을 multipart로 업로드하면 서버는
환자별 폴더에 파일 저장 + DB 레코드 삽입을 한다.
(브라우저는 이와 동시에 File System Access API로 사용자가 지정한
로컬 폴더에도 직접 쓴다 — 그 부분은 프런트엔드가 담당.)
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from app import config
from app.models.schemas import CaptureNoteIn, CaptureOut

router = APIRouter(prefix="/api/v1/captures", tags=["captures"])

_UNSAFE = re.compile(r"[^0-9A-Za-z._가-힣-]+")
_EXT = {"photo": "png", "video": "mp4"}
# 저장 파일은 /media 로 같은 출처에서 그대로 제공되므로, 영상 형식만 허용한다
# (html·svg 등이 올라가면 같은 출처에서 스크립트가 실행될 수 있음)
_ALLOWED_EXT = {"photo": {"png", "jpg", "jpeg", "webp"}, "video": {"mp4", "webm", "mov", "mkv"}}


def _db(request: Request):
    return request.app.state.db


def _sanitize(s: str) -> str:
    s = (s or "").strip()
    s = _UNSAFE.sub("_", s)
    return s or "_"


def _target_paths(patient: dict, media_type: str, ts: datetime, ext: str):
    chart = _sanitize(patient.get("chart_no") or "noChart")
    pid = _sanitize(patient.get("patient_id") or str(patient["id"]))
    date = ts.strftime("%Y-%m-%d")
    rel_dir = Path(f"{chart}_{pid}") / date
    fname = f"{ts:%H%M%S}_{ts.microsecond // 1000:03d}_{media_type}.{ext}"
    rel_path = rel_dir / fname
    abs_path = config.MEDIA_DIR / rel_path
    return rel_path, abs_path


@router.get("", response_model=List[CaptureOut])
def list_captures(request: Request, patient_id: int, order: str = "desc"):
    return _db(request).list_captures(patient_id, order=order)


@router.post("", response_model=CaptureOut, status_code=201)
async def create_capture(
    request: Request,
    patient_id: int = Form(...),
    media_type: str = Form(...),
    eye: str = Form("NA"),
    duration_ms: Optional[int] = Form(None),
    ext: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    file: UploadFile = Form(...),
):
    db = _db(request)
    patient = db.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="환자를 찾을 수 없습니다.")
    if media_type not in ("photo", "video"):
        raise HTTPException(status_code=400, detail="media_type은 photo 또는 video 여야 합니다.")

    ts = config.now()
    file_ext = (ext or _EXT[media_type]).strip().lower().lstrip(".")
    if file_ext not in _ALLOWED_EXT[media_type]:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 파일 형식입니다: {file_ext}")
    rel_path, abs_path = _target_paths(patient, media_type, ts, file_ext)
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    # 같은 밀리초에 두 장이 올라와도 덮어쓰지 않게 새 파일로만 연다 ('x'), 겹치면 짧은 꼬리표를 붙인다
    try:
        out = open(abs_path, "xb")
    except FileExistsError:
        abs_path = abs_path.with_name(f"{abs_path.stem}_{secrets.token_hex(3)}{abs_path.suffix}")
        rel_path = rel_path.with_name(abs_path.name)
        out = open(abs_path, "xb")
    # 통째로 메모리에 올리지 않고 나눠서 기록 + 크기 제한
    limit, size = config.MAX_UPLOAD_MB * 1024 * 1024, 0
    try:
        with out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다 (최대 {config.MAX_UPLOAD_MB}MB).")
                out.write(chunk)
    except BaseException:
        abs_path.unlink(missing_ok=True)
        raise

    url = "/media/" + str(rel_path).replace("\\", "/")
    try:
        cid = db.create_capture({
        "patient_id": patient_id,
        "media_type": media_type,
        "file_path": str(rel_path).replace("\\", "/"),
        "url": url,
        "captured_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "eye": eye if eye in ("OD", "OS", "OU", "NA") else "NA",
        "duration_ms": duration_ms,
        "note": note,
        })
    except Exception:                                   # 기록 실패(그 사이 환자 삭제 등) → 파일만 남지 않게
        abs_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="저장하지 못했습니다 (환자가 삭제되었을 수 있습니다).")
    return db.get_capture(cid)


@router.patch("/{cid}", response_model=CaptureOut)
def update_capture(request: Request, cid: int, body: CaptureNoteIn):
    """영상별 코멘트 수정 (Pro 모드)."""
    db = _db(request)
    if not db.get_capture(cid):
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    note = (body.note or "").strip() or None
    db.update_capture_note(cid, note)
    return db.get_capture(cid)


@router.delete("/{cid}", status_code=204)
def delete_capture(request: Request, cid: int):
    row = _db(request).delete_capture(cid)
    if row and row.get("file_path"):
        try:
            (config.MEDIA_DIR / row["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
