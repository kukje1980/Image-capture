"""테스트 공통 픽스처. Qt는 offscreen 플랫폼으로 강제."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.config import AppConfig
from app.db.database import Database


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """APPDATA를 임시 폴더로 돌려 설정/DB/미디어를 격리한다."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config = AppConfig.load()
    config.export_root = str(tmp_path / "export")
    config.start_screen = "capture"              # 테스트는 촬영 화면에서 시작 (홈 화면 테스트는 따로 지정)
    db = Database(config.db_path).init()
    yield config, db
    db.close()
