"""인터넷 호스팅(Render/Vercel) 관련: 접속 비밀번호, 서버리스(lifespan 없음) 동작, 배포 설정."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

WEB = Path(__file__).resolve().parents[1]


def _load(monkeypatch, tmp_path, password=""):
    monkeypatch.setenv("SLITLAMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SLITLAMP_MEDIA_DIR", str(tmp_path / "data" / "media"))
    monkeypatch.setenv("SLITLAMP_DB_PATH", str(tmp_path / "data" / "t.db"))
    monkeypatch.setenv("SLITLAMP_PASSWORD", password)
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    return main_mod.app


@pytest.fixture(autouse=True)
def _restore_modules():
    yield
    from app import config as config_mod, main as main_mod
    importlib.reload(config_mod)
    importlib.reload(main_mod)


def test_password_gate(monkeypatch, tmp_path):
    app = _load(monkeypatch, tmp_path, "secret-1")
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200                     # 상태 확인은 열림
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
        assert c.get("/api/v1/patients").status_code == 401
        assert c.get("/login").status_code == 200
        bad = c.post("/login", data={"password": "nope", "next": "/"}, follow_redirects=False)
        assert "error=1" in bad.headers["location"]
        ok = c.post("/login", data={"password": "secret-1", "next": "/"}, follow_redirects=False)
        assert ok.status_code == 303 and "slitlamp_auth" in ok.headers.get("set-cookie", "")
        assert c.get("/api/v1/patients").status_code == 200
        assert c.get("/").status_code == 200
        c.get("/logout")
        assert c.get("/api/v1/patients").status_code == 401


def test_open_redirect_blocked(monkeypatch, tmp_path):
    app = _load(monkeypatch, tmp_path, "pw")
    with TestClient(app) as c:
        for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "/\tevil"):
            r = c.post("/login", data={"password": "pw", "next": bad}, follow_redirects=False)
            assert r.headers["location"] == "/", bad
        # 이미 로그인한 상태의 GET /login?next=… 도 외부로 보내지 않는다
        r = c.get("/login", params={"next": "//evil.example"}, follow_redirects=False)
        assert r.headers["location"] == "/"


def test_no_password_is_open(monkeypatch, tmp_path):
    app = _load(monkeypatch, tmp_path, "")
    with TestClient(app) as c:
        r = c.get("/login", params={"next": "//evil.example"}, follow_redirects=False)
        assert r.headers["location"] == "/"
        assert c.get("/").status_code == 200
        assert c.get("/api/v1/patients").status_code == 200


def test_works_without_lifespan(monkeypatch, tmp_path):
    """서버리스 런타임처럼 startup 이벤트 없이 첫 요청이 와도 DB 가 준비돼야 한다."""
    app = _load(monkeypatch, tmp_path, "")
    c = TestClient(app)                     # with 블록 없이 → lifespan 미실행
    r = c.post("/api/v1/patients", json={"chart_no": "S1", "name": "서버리스"})
    assert r.status_code in (200, 201)


def test_vercel_defaults_to_tmp(monkeypatch):
    monkeypatch.delenv("SLITLAMP_DATA_DIR", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    from app import config as config_mod
    importlib.reload(config_mod)
    assert str(config_mod.DATA_DIR) == "/tmp/slitlamp"


def test_deploy_files():
    v = json.loads((WEB / "vercel.json").read_text(encoding="utf-8"))
    assert v["builds"][0]["src"] == "api/index.py"
    assert "from app.main import app" in (WEB / "api" / "index.py").read_text(encoding="utf-8")
    import yaml
    r = yaml.safe_load((WEB.parent / "render.yaml").read_text(encoding="utf-8"))
    svc = r["services"][0]
    assert svc["rootDir"] == "web" and "$PORT" in svc["startCommand"]
    assert any(e["key"] == "SLITLAMP_PASSWORD" for e in svc["envVars"])
