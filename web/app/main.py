"""FastAPI 진입점.

실행: uvicorn app.main:app --host 127.0.0.1 --port 8000
(web/ 디렉토리에서 실행)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config
from app.db.database import Database
from app.routers import captures, patients

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    app.state.db = Database(config.DB_PATH).init()
    yield
    app.state.db.close()


app = FastAPI(title="슬릿램프 영상 시스템", lifespan=lifespan)

app.include_router(patients.router)
app.include_router(captures.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# 저장된 미디어 제공 (서버에 남긴 원본/영상)
config.ensure_dirs()
app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
