"""참조 샘플 라이브러리 API (/api/v1/refs) — 부위별 · 정상/비정상(질환명) 대표 영상.

환자와 무관한 비교용 영상이다. Pro '참조' 탭에서 현재 영상과 나란히 비교한다.
'이 PC에만 저장' 모드에서는 같은 요청을 localstore.js 가 브라우저 저장소에서 처리한다.
분류 이름(질환명)은 사용자가 붙이는 라벨이며 프로그램이 판정하지 않는다.
"""
from __future__ import annotations

import secrets
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from app import config
from app.models.schemas import RefOut

router = APIRouter(prefix="/api/v1/refs", tags=["refs"])
REGIONS = ("eyelid", "conjunctiva", "cornea", "ac", "iris", "lens", "meibo", "other")
CONDITIONS = ("normal", "abnormal")
_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_REF_MB = 30


def _db(request: Request):
    return request.app.state.db


@router.get("", response_model=List[RefOut])
def list_refs(request: Request, region: Optional[str] = None, condition: Optional[str] = None):
    return _db(request).list_refs(region or None, condition or None)


@router.post("", response_model=RefOut, status_code=201)
async def create_ref(
    request: Request,
    region: str = Form(...),
    condition: str = Form(...),
    disease: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    ext: Optional[str] = Form("png"),
    file: UploadFile = Form(...),
):
    if region not in REGIONS:
        raise HTTPException(status_code=400, detail=f"알 수 없는 부위입니다: {region}")
    if condition not in CONDITIONS:
        raise HTTPException(status_code=400, detail="구분은 normal 또는 abnormal 이어야 합니다.")
    e = (ext or "png").strip().lower().lstrip(".")
    if e not in _EXT:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 파일 형식입니다: {e}")
    data = await file.read(MAX_REF_MB * 1024 * 1024 + 1)
    if len(data) > MAX_REF_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다 (최대 {MAX_REF_MB}MB).")
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    ts = config.now()
    rel = f"_reference/{region}/{ts:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}.{e}"
    path = config.MEDIA_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        rid = _db(request).create_ref({
            "region": region, "condition": condition,
            "disease": (disease or "").strip()[:80] or None, "note": (note or "").strip()[:300] or None,
            "file_path": rel, "url": "/media/" + rel, "created_at": ts.strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _db(request).get_ref(rid)


@router.delete("/{rid}", status_code=204)
def delete_ref(request: Request, rid: int):
    db = _db(request)
    r = db.get_ref(rid)
    if not r:
        raise HTTPException(status_code=404, detail="참조 샘플을 찾을 수 없습니다.")
    db.delete_ref(rid)
    try:
        (config.MEDIA_DIR / r["file_path"]).unlink(missing_ok=True)
    except Exception:
        pass
