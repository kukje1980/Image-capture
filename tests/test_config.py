from __future__ import annotations

from app.config import AppConfig


def test_defaults_resolved(app_env):
    config, _ = app_env
    assert config.media_root
    assert config.db_path.endswith("slitlamp.db")
    assert config.source_mode in ("device", "file", "synthetic")


def test_save_and_reload(app_env):
    config, _ = app_env
    config.camera_index = 3
    config.photo_format = "jpg"
    config.save()

    reloaded = AppConfig.load()
    assert reloaded.camera_index == 3
    assert reloaded.photo_format == "jpg"
