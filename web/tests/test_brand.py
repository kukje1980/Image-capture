"""브랜드 버전(SLITLAMP_BRAND) — 기본 / Keeler."""
from __future__ import annotations

import importlib
import shutil

import pytest
from fastapi.testclient import TestClient

from app import brands


def _client(monkeypatch, tmp_path, brand):
    monkeypatch.setenv("SLITLAMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SLITLAMP_PASSWORD", "")
    if brand is None:
        monkeypatch.delenv("SLITLAMP_BRAND", raising=False)
    else:
        monkeypatch.setenv("SLITLAMP_BRAND", brand)
    from app import config as config_mod, main as main_mod
    importlib.reload(config_mod)
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    monkeypatch.delenv("SLITLAMP_BRAND", raising=False)
    from app import config as config_mod, main as main_mod
    importlib.reload(config_mod)
    importlib.reload(main_mod)


def test_default_brand_unchanged(monkeypatch, tmp_path):
    html = _client(monkeypatch, tmp_path, None).get("/").text
    assert "<title>슬릿램프 영상 시스템</title>" in html
    assert 'class="brand-default"' in html and "brand/keeler" not in html


def test_keeler_brand(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, "keeler")
    html = c.get("/").text
    assert "<title>Keeler 슬릿램프 영상 시스템</title>" in html
    assert 'class="brand-keeler"' in html
    assert "/static/brand/keeler/theme.css" in html
    assert '"key": "keeler"' in html and "report_title" in html
    assert c.get("/static/brand/keeler/theme.css").status_code == 200


def test_unknown_brand_falls_back():
    assert brands.get_brand("nope")["key"] == "default"


def test_logo_file_is_picked_up(tmp_path, monkeypatch):
    fake = tmp_path / "static"
    (fake / "brand" / "keeler").mkdir(parents=True)
    shutil.copy(brands.STATIC_DIR / "brand" / "keeler" / "theme.css", fake / "brand" / "keeler" / "theme.css")
    monkeypatch.setattr(brands, "STATIC_DIR", fake)
    assert brands.get_brand("keeler")["logo"] is None
    (fake / "brand" / "keeler" / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    b = brands.get_brand("keeler")
    assert b["logo"] == "/static/brand/keeler/logo.svg" and b["logo_dark"] == b["logo"]


def test_keeler_path_on_default_deployment(monkeypatch, tmp_path):
    """기본 배포에서도 /keeler 주소로 Keeler 화면이 열린다."""
    c = _client(monkeypatch, tmp_path, None)
    html = c.get("/keeler").text
    assert "<title>Keeler 슬릿램프 영상 시스템</title>" in html and 'class="brand-keeler"' in html
    assert "<title>슬릿램프 영상 시스템</title>" in c.get("/").text


def test_keeler_login_branding(monkeypatch, tmp_path):
    monkeypatch.setenv("SLITLAMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SLITLAMP_BRAND", raising=False)
    monkeypatch.setenv("SLITLAMP_PASSWORD", "pw")
    from app import config as config_mod, main as main_mod
    importlib.reload(config_mod)
    importlib.reload(main_mod)
    c = TestClient(main_mod.app)
    r = c.get("/keeler", follow_redirects=False)
    assert r.headers["location"].startswith("/login?next=/keeler")
    page = c.get(r.headers["location"]).text
    assert "Keeler" in page and "brand-keeler" in page
    ok = c.post("/login", data={"password": "pw", "next": "/keeler"}, follow_redirects=False)
    assert ok.headers["location"] == "/keeler"
    assert "brand-keeler" in c.get("/keeler").text
