"""FastAPI 진입점.

실행: uvicorn app.main:app --host 127.0.0.1 --port 8000
(web/ 디렉토리에서 실행). 인터넷 배포는 render.yaml / vercel.json 참고.
SLITLAMP_PASSWORD 환경변수를 주면 접속 비밀번호 로그인이 켜진다.
"""
from __future__ import annotations

import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config
from app.db.database import Database
from app.routers import captures, patients

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _ensure_db(app: FastAPI) -> None:
    if getattr(app.state, "db", None) is None:
        config.ensure_dirs()
        app.state.db = Database(config.DB_PATH).init()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_db(app)
    yield
    app.state.db.close()
    app.state.db = None


app = FastAPI(title="슬릿램프 영상 시스템", lifespan=lifespan)

# ---------------- 접속 비밀번호 (선택) ----------------
AUTH_COOKIE = "slitlamp_auth"
_OPEN_PATHS = ("/login", "/health", "/static/", "/favicon.ico")


def _auth_token() -> str:
    return hmac.new(config.PASSWORD.encode("utf-8"), b"slitlamp-web-v1", hashlib.sha256).hexdigest()


def _safe_next(target: str) -> str:
    """로그인 후 이동 경로 — 같은 사이트 안의 경로만 허용 (//evil, /\\evil 같은 외부 이동 차단)."""
    t = target or "/"
    if not t.startswith("/") or t.startswith("//") or "\\" in t or any(ord(ch) < 32 for ch in t):
        return "/"
    return t


def _authorized(request: Request) -> bool:
    if not config.PASSWORD:
        return True
    return hmac.compare_digest(request.cookies.get(AUTH_COOKIE, ""), _auth_token())


@app.middleware("http")
async def _gate(request: Request, call_next):
    # 서버리스 호스팅은 lifespan 이 실행되지 않을 수 있어 첫 요청에서 DB를 준비
    _ensure_db(request.app)
    path = request.url.path
    if not _authorized(request) and not path.startswith(_OPEN_PATHS):
        if path.startswith(("/api/", "/media/")):
            return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        return RedirectResponse(f"/login?next={quote(path)}", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, next: str = "/", error: int = 0):
    dest = _safe_next(next)
    if _authorized(request):
        return RedirectResponse(dest, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": dest, "error": bool(error)})


@app.post("/login", include_in_schema=False)
def login_submit(request: Request, password: str = Form(""), next: str = Form("/")):
    dest = _safe_next(next)
    if not config.PASSWORD or not hmac.compare_digest(password.encode("utf-8"), config.PASSWORD.encode("utf-8")):
        return RedirectResponse(f"/login?error=1&next={quote(dest)}", status_code=303)
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(AUTH_COOKIE, _auth_token(), max_age=30 * 24 * 3600, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")
    return resp


@app.get("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse("/login" if config.PASSWORD else "/", status_code=303)
    resp.delete_cookie(AUTH_COOKIE)
    return resp


app.include_router(patients.router)
app.include_router(captures.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# 저장된 미디어 제공 (서버에 남긴 원본/영상)
config.ensure_dirs()
app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(str(BASE_DIR / "static" / "favicon.ico"))


@app.get("/health")
def health():
    return {"status": "ok"}
