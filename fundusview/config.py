"""Persistent user settings (JSON).

Stored per Windows user in ``%APPDATA%\\FundusViewer\\settings.json`` (or
``~/.config/fundusviewer`` elsewhere). ``FUNDUSVIEW_HOME`` overrides the
directory, which keeps tests and portable installs self-contained.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

# What happens to a source file after it has been imported.
ACTION_COPY = "copy"            # copy into the library, leave the original (default, safe)
ACTION_MOVE = "move"            # move into the library (the drop folder is emptied)
ACTION_REFERENCE = "reference"  # leave in place, the DB points at the original path
ACTIONS = (ACTION_COPY, ACTION_MOVE, ACTION_REFERENCE)


def config_dir() -> Path:
    env = os.getenv("FUNDUSVIEW_HOME")
    if env:
        return Path(env)
    appdata = os.getenv("APPDATA")
    if appdata:  # Windows
        return Path(appdata) / APP_NAME
    return Path.home() / ".config" / APP_NAME.lower()


def default_library_dir() -> Path:
    env = os.getenv("FUNDUSVIEW_HOME")
    if env:
        return Path(env) / "Library"
    return Path.home() / "Documents" / f"{APP_NAME}Library"


@dataclass
class WatchFolder:
    path: str
    profile: str = "auto"         # camera profile key (see profiles.py) or "auto"
    recursive: bool = True
    action: str = ACTION_COPY
    polling: bool = False         # use polling (network drives / NAS where change events are unreliable)
    enabled: bool = True


@dataclass
class Settings:
    library_dir: str = ""
    watch_folders: list[WatchFolder] = field(default_factory=list)
    watch_on_startup: bool = True
    # Seconds a new file's size must stay unchanged before it is imported
    # (the capture software may still be writing it).
    stable_seconds: float = 1.5
    # Safety-net rescan interval for missed change events (seconds, 0 = off).
    rescan_seconds: int = 60
    # "auto" | "desktop" | "software" — software = bundled Mesa llvmpipe
    # (opengl32sw.dll), for PCs whose GPU driver lacks OpenGL 2.1.
    opengl: str = "auto"
    # Extra user-defined filename regexes tried before the profile patterns.
    custom_filename_patterns: list[str] = field(default_factory=list)
    last_patient: str = ""

    @property
    def library(self) -> Path:
        return Path(self.library_dir) if self.library_dir else default_library_dir()

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or (config_dir() / "settings.json")
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        folders = [WatchFolder(**{k: v for k, v in f.items() if k in WatchFolder.__dataclass_fields__})
                   for f in raw.pop("watch_folders", [])]
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(watch_folders=folders, **known)

    def save(self, path: Path | None = None) -> None:
        path = path or (config_dir() / "settings.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
