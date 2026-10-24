from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 데이터 디렉토리를 임시 경로로 격리
    monkeypatch.setenv("SLITLAMP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SLITLAMP_MEDIA_DIR", str(tmp_path / "data" / "media"))
    monkeypatch.setenv("SLITLAMP_DB_PATH", str(tmp_path / "data" / "test.db"))

    # config/main 모듈을 새 환경변수로 재로딩
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import main as main_mod
    importlib.reload(main_mod)

    with TestClient(main_mod.app) as c:
        yield c
