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


def test_wrong_types_ignored(app_env):
    config, _ = app_env
    import json
    p = AppConfig.config_path()
    p.write_text(json.dumps({"camera_index": "1", "shortcuts": ["x"], "capture_width": None,
                             "px_per_mm": 12, "newest_on_top": 0, "theme": "light"}), encoding="utf-8")
    c = AppConfig.load()
    assert c.camera_index == 0 and c.shortcuts == {} and c.capture_width == 1920
    assert c.px_per_mm == 12.0 and c.newest_on_top is True and c.theme == "light"


def test_corrupt_config_is_kept_aside(app_env):
    config, _ = app_env
    p = AppConfig.config_path()
    p.write_text("{ broken", encoding="utf-8")
    c = AppConfig.load()
    assert c.camera_index == 0
    assert p.with_name(p.name + ".broken").read_text(encoding="utf-8") == "{ broken"


def test_save_is_atomic(app_env):
    config, _ = app_env
    config.save()
    p = AppConfig.config_path()
    assert p.exists() and not p.with_name(p.name + ".tmp").exists()
