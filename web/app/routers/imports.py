"""폴더 가져오기 API (/api/v1/import) — 안저 카메라 폴더 → 환자 DB.

GET  ''         설정·상태 (최근 가져온 사진, 확인 필요 수, seq — 화면이 새로 고칠 때 씀)
PUT  ''         설정 저장 — 서버 PC 에서만 (다른 PC 가 서버의 아무 폴더나 지우게 하지 않음)
POST /run       지금 가져오기
POST /preview   파일 이름 → 읽은 결과 (설정 창 확인용)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import config
from app.folder_import import ImportSettings
from app.fundus_filename import parse_filename, template_regex

router = APIRouter(prefix="/api/v1/import", tags=["import"])
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ImportSettingsIn(BaseModel):
    enabled: bool = False
    dir: str = ""
    template: str = ""
    delete: bool = True
    recursive: bool = True
    switch_patient: bool = True
    interval_sec: int = 3


class PreviewIn(BaseModel):
    filename: str
    template: str = ""


def _imp(request: Request):
    return request.app.state.importer


def _can_edit(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return config.IMPORT_REMOTE_EDIT or host in _LOCAL_HOSTS


@router.get("")
def get_import(request: Request):
    return {**_imp(request).status(), "can_edit": _can_edit(request) and config.IMPORT_AVAILABLE}


@router.put("")
def put_import(request: Request, body: ImportSettingsIn):
    if not config.IMPORT_AVAILABLE:
        raise HTTPException(400, "이 서버에서는 폴더 가져오기를 쓸 수 없습니다 (인터넷 호스팅 · 'PC에만 저장').")
    if not _can_edit(request):
        raise HTTPException(403, "폴더 가져오기 설정은 서버를 실행한 PC 에서만 바꿀 수 있습니다.")
    s = ImportSettings(**body.model_dump())
    s.dir = s.dir.strip()
    s.template = s.template.strip()
    s.interval_sec = max(2, min(60, int(s.interval_sec or 3)))
    if s.template:
        try:
            template_regex(s.template)
        except ValueError as e:
            raise HTTPException(400, f"파일 이름 형식: {e}") from e
    if s.enabled:
        from pathlib import Path
        if not s.dir or not Path(s.dir).is_dir():
            raise HTTPException(400, f"폴더가 없습니다: {s.dir or '(비어 있음)'}")
    imp = _imp(request)
    imp.update(s)
    imp.start()
    return {**imp.status(), "can_edit": True}


@router.post("/run")
def run_import(request: Request):
    if not config.IMPORT_AVAILABLE:
        raise HTTPException(400, "이 서버에서는 폴더 가져오기를 쓸 수 없습니다.")
    imp = _imp(request)
    items = imp.scan(force=True)
    return {"items": items, **imp.status(), "can_edit": _can_edit(request)}


@router.post("/preview")
def preview(body: PreviewIn):
    r = parse_filename(body.filename, body.template)
    return {"ok": r.ok, "id": r.id, "name": r.name, "date": r.date, "time": r.time, "eye": r.eye,
            "error": r.error, "summary": r.summary()}
