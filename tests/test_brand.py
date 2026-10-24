"""데스크탑 브랜드 (기본 / Keeler 전용)."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from app import brand


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_brand(monkeypatch):
    monkeypatch.delenv(brand.ENV_KEY, raising=False)
    yield


def test_key_priority(monkeypatch):
    assert brand.key_from([], None) == "default"
    assert brand.key_from([], "keeler") == "keeler"                 # 설정 파일
    monkeypatch.setenv(brand.ENV_KEY, "keeler")
    assert brand.key_from([], "") == "keeler"                       # 환경변수(설치본)
    assert brand.key_from(["app", "--brand", "default"], "keeler") == "default"   # 실행 옵션이 최우선
    assert brand.key_from(["app", "--brand=keeler"], None) == "keeler"


def test_select_unknown_falls_back():
    assert brand.select("nope")["key"] == "default"
    assert brand.select("keeler")["key"] == "keeler"


def test_keeler_assets_and_palette(qapp):
    b = brand.select("keeler")
    for k in ("logo", "logo_dark", "icon"):
        assert brand.asset(b[k]), k
    from app.ui import theme
    dark, light = theme.palette("dark"), theme.palette("light")
    assert dark["accent"] == "#6cbce8" and light["accent"] == "#1981b7"
    assert "#052133" in theme.build_qss("light")
    assert not theme.make_app_icon().isNull()
    brand.select("default")
    assert theme.palette("dark")["accent"] == "#33c2b1"            # 기본 브랜드는 그대로


def test_keeler_build_files():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    iss = (root / "installer" / "keeler.iss").read_text(encoding="utf-8-sig")
    assert "KeelerSlitLamp.exe" in iss and "brand\\keeler\\app.ico" in iss
    assert "8F2A6C14" not in iss                                     # 기본판과 다른 AppId (나란히 설치 가능)
    spec = (root / "build.spec").read_text(encoding="utf-8")
    assert "KeelerSlitLamp" in spec and "brand_keeler.py" in spec
    assert (root / "tools" / "rthooks" / "brand_keeler.py").is_file()
    for f in ("app.ico", "app.icns", "app.png", "logo.svg", "logo-dark.svg"):
        assert (root / "assets" / "brand" / "keeler" / f).is_file(), f
