"""질환별 참고 사진 API (/api/v1/references).

상단 질환 아이콘 → 참고 사진 패널에 보이는, 병원이 직접 등록한 비교용 사진. 환자 정보와 연결되지 않으며
<media>/_references/<질환 id>/ 아래에 저장한다. 질환 목록(id)은 static/dx/library.json 과 같다.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from app import config
from app.models.schemas import ReferenceOut

router = APIRouter(prefix="/api/v1/references", tags=["references"])

LIBRARY_PATH = config.BASE_DIR / "static" / "dx" / "library.json"
_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_MAX_CAPTION = 200


def disease_ids() -> set[str]:
    try:
        lib = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
        return {d["id"] for d in lib.get("diseases", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _db(request: Request):
    return request.app.state.db


def _check_disease(disease: str) -> str:
    d = (disease or "").strip().lower()
    if not _ID.match(d) or d not in disease_ids():
        raise HTTPException(status_code=400, detail="알 수 없는 질환입니다.")
    return d


@router.get("", response_model=List[ReferenceOut])
def list_references(request: Request, disease: Optional[str] = None):
    return _db(request).list_references(_check_disease(disease) if disease else None)


@router.post("", response_model=ReferenceOut, status_code=201)
async def create_reference(
    request: Request,
    disease: str = Form(...),
    caption: Optional[str] = Form(None),
    file: UploadFile = Form(...),
):
    db = _db(request)
    d = _check_disease(disease)
    name = (file.filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext == "jpeg":
        ext = "jpg"
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="사진 파일(png·jpg·webp)만 등록할 수 있습니다.")
    ts = config.now()
    rel_dir = Path("_references") / d
    abs_dir = config.MEDIA_DIR / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    rel_path = rel_dir / f"{ts:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.{ext}"
    abs_path = config.MEDIA_DIR / rel_path
    limit, size = config.MAX_UPLOAD_MB * 1024 * 1024, 0
    try:
        with open(abs_path, "xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다 (최대 {config.MAX_UPLOAD_MB}MB).")
                out.write(chunk)
    except BaseException:
        abs_path.unlink(missing_ok=True)
        raise
    if size == 0:
        abs_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    cap = (caption or "").strip()[:_MAX_CAPTION] or None
    rid = db.create_reference({
        "disease": d,
        "file_path": str(rel_path).replace("\\", "/"),
        "url": "/media/" + str(rel_path).replace("\\", "/"),
        "caption": cap,
        "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return db.get_reference(rid)


@router.delete("/{rid}", status_code=204)
def delete_reference(request: Request, rid: int):
    row = _db(request).delete_reference(rid)
    if not row:
        raise HTTPException(status_code=404, detail="참고 사진을 찾을 수 없습니다.")
    if row.get("file_path"):
        try:
            (config.MEDIA_DIR / row["file_path"]).unlink(missing_ok=True)
        except OSError:
            pass
