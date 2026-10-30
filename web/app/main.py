"""FastAPI 진입점.

실행: uvicorn app.main:app --host 127.0.0.1 --port 8000
(web/ 디렉토리에서 실행). 인터넷 배포는 render.yaml / vercel.json 참고.
SLITLAMP_PASSWORD 환경변수를 주면 접속 비밀번호 로그인이 켜진다.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import brands, config
from app.db.database import Database
from app.routers import captures, patients, references

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
BRAND = brands.get_brand()            # SLITLAMP_BRAND 환경변수 (기본 / keeler …)
templates.env.globals["brand"] = BRAND
templates.env.globals["brand_public"] = brands.public(BRAND)
templates.env.globals["storage_policy"] = config.STORAGE_POLICY


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
    # '이 PC 에만 저장' 정책이면 서버는 환자 정보·영상을 받지 않는다 (예전 화면·직접 호출 포함)
    if config.STORAGE_POLICY == "local" and path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse({"detail": "이 서버는 'PC에만 저장' 모드라 환자 정보·영상을 받지 않습니다."}, status_code=403)
    return await call_next(request)


# 로그인 비밀번호 무차별 대입 방지: 같은 주소에서 5번 틀리면 1분간 막음
_LOGIN_FAILS: dict[str, tuple[int, float]] = {}


def _login_blocked(ip: str) -> bool:
    n, until = _LOGIN_FAILS.get(ip, (0, 0.0))
    return n >= 5 and time.time() < until


def _login_failed(ip: str) -> None:
    n, until = _LOGIN_FAILS.get(ip, (0, 0.0))
    if n >= 5 and time.time() >= until:
        n = 0
    n += 1
    _LOGIN_FAILS[ip] = (n, time.time() + 60)
    if len(_LOGIN_FAILS) > 10000:
        _LOGIN_FAILS.clear()


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, next: str = "/", error: int = 0):
    dest = _safe_next(next)
    if _authorized(request):
        return RedirectResponse(dest, status_code=303)
    b = _brand_for_path(dest)
    if b is BRAND:
        b = _brand_for_host(request)
    return templates.TemplateResponse(request, "login.html", {"next": dest, "error": int(error or 0),
                                                             "brand": b, "brand_public": brands.public(b)})


@app.post("/login", include_in_schema=False)
def login_submit(request: Request, password: str = Form(""), next: str = Form("/")):
    dest = _safe_next(next)
    ip = request.client.host if request.client else "-"
    if _login_blocked(ip):
        return RedirectResponse(f"/login?error=2&next={quote(dest)}", status_code=303)
    if not config.PASSWORD or not hmac.compare_digest(password.encode("utf-8"), config.PASSWORD.encode("utf-8")):
        _login_failed(ip)
        return RedirectResponse(f"/login?error=1&next={quote(dest)}", status_code=303)
    _LOGIN_FAILS.pop(ip, None)
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
app.include_router(references.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# 저장된 미디어 제공 (서버에 남긴 원본/영상)
config.ensure_dirs()
app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    b = _brand_for_host(request)
    return templates.TemplateResponse(request, "index.html", {"brand": b, "brand_public": brands.public(b)})


def _brand_for_host(request: Request) -> dict:
    """접속 주소(도메인)에 브랜드 이름이 들어 있으면 그 브랜드 (예: keeler-slitlamp.vercel.app → Keeler).
    별도 배포를 만들 때 환경변수 없이 프로젝트 이름만으로 브랜드가 정해지게 한다."""
    host = (request.headers.get("host") or "").lower()
    for key in brands.BRANDS:
        if key != "default" and key in host:
            return brands.get_brand(key)
    return BRAND


def _brand_for_path(path: str) -> dict:
    """/keeler… 처럼 브랜드 경로면 그 브랜드, 아니면 배포 기본 브랜드."""
    first = (path or "/").lstrip("/").split("/", 1)[0].split("?", 1)[0].lower()
    if first in brands.BRANDS and first != "default":
        return brands.get_brand(first)
    return BRAND


def _brand_page(key: str):
    def page(request: Request):
        b = brands.get_brand(key)
        return templates.TemplateResponse(request, "index.html", {"brand": b, "brand_public": brands.public(b)})
    return page


# 같은 주소에서 브랜드 화면 제공: https://<주소>/keeler  (별도 배포 없이 바로 사용)
for _key in brands.BRANDS:
    if _key != "default":
        app.get(f"/{_key}", response_class=HTMLResponse, include_in_schema=False)(_brand_page(_key))


@app.get("/favicon.ico", include_in_schema=False)
def favicon(request: Request):
    b = _brand_for_host(request)
    if b.get("favicon"):
        return FileResponse(str(BASE_DIR / b["favicon"].lstrip("/")))
    return FileResponse(str(BASE_DIR / "static" / "favicon.ico"))


@app.get("/health")
def health():
    return {"status": "ok"}
