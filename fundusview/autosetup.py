"""Automatic import setup — photos come in without configuring anything.

At every start:

* the **inbox** folder (``Documents\\안저사진 가져오기``) is created and watched;
  photos dropped there are *moved* into the library, so an empty inbox means
  everything was imported;
* the capture software's own folders are looked for on every drive letter
  (local and mapped network drives) and added with the right camera profile:

  ===================  ==================================================
  RetiCam 3100 Plus    ``X:\\reticam``, ``X:\\레티캠``, ``X:\\SYSEYE``
  Microclear APOLLO    ``X:\\MicroClearClient\\ImageData``, ``X:\\MC\\Cro\\PatientCapture``,
                       ``%USERPROFILE%\\MicroClearClient\\ImageData``
  ===================  ==================================================

Device folders are copied from (never moved), and network drives are
polled. A folder the user removes in the settings is remembered and not
added again. Detection can block on a disconnected network drive, so the
GUI runs :func:`detect` on a worker thread and applies the result with
:func:`apply`.
"""
from __future__ import annotations

import os
import string
import sys
from pathlib import Path

from .config import ACTION_COPY, ACTION_MOVE, Settings, WatchFolder

DEVICE_DIRS = (
    ("reticam", ("reticam", "RetiCam", "레티캠", "SYSEYE")),
    ("apollo", ("MicroClearClient/ImageData", "MC/Cro/PatientCapture")),
)
HOME_DIRS = (
    ("apollo", "MicroClearClient/ImageData"),
)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


def drive_roots() -> list[str]:
    if sys.platform != "win32":
        return []
    if hasattr(os, "listdrives"):  # Python 3.12+
        try:
            return [d for d in os.listdrives() if d[:1].upper() not in "AB"]
        except OSError:
            pass
    return [f"{c}:\\" for c in string.ascii_uppercase[2:] if os.path.exists(f"{c}:\\")]


def detect(roots: list[str] | None = None, home: Path | None = None) -> list[tuple[str, str]]:
    """``(folder, profile)`` pairs of capture-software folders that exist."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in (drive_roots() if roots is None else roots):
        for profile, names in DEVICE_DIRS:
            for name in names:
                p = os.path.join(root, *name.split("/"))
                try:
                    ok = os.path.isdir(p)
                except OSError:
                    ok = False
                if ok and _key(p) not in seen:
                    seen.add(_key(p))
                    found.append((p, profile))
    home = Path.home() if home is None else home
    for profile, rel in HOME_DIRS:
        p = str(home.joinpath(*rel.split("/")))
        if os.path.isdir(p) and _key(p) not in seen:
            seen.add(_key(p))
            found.append((p, profile))
    return found


def apply(settings: Settings, detected: list[tuple[str, str]]) -> list[WatchFolder]:
    """Add the inbox and newly detected folders to ``settings``; returns the additions."""
    from .watcher import is_network_path

    existing = {_key(f.path) for f in settings.watch_folders}
    ignored = {_key(p) for p in settings.ignored_auto_folders}
    library = _key(str(settings.library))
    added: list[WatchFolder] = []

    inbox = settings.inbox
    try:
        inbox.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    candidates = [WatchFolder(path=str(inbox), profile="auto", recursive=True, action=ACTION_MOVE)]
    if settings.auto_detect:
        for path, profile in detected:
            candidates.append(WatchFolder(path=path, profile=profile, recursive=True, action=ACTION_COPY,
                                          polling=is_network_path(path)))
    for f in candidates:
        k = _key(f.path)
        if k in existing or k in ignored or k == library or k.startswith(library + os.sep):
            continue
        if not os.path.isdir(f.path):
            continue
        settings.watch_folders.append(f)
        existing.add(k)
        added.append(f)
    return added


def remember_removed(settings: Settings, before: list[WatchFolder]) -> None:
    """Folders the user deleted in the settings are not auto-added again."""
    now = {_key(f.path) for f in settings.watch_folders}
    for f in before:
        if _key(f.path) not in now and f.path not in settings.ignored_auto_folders:
            settings.ignored_auto_folders.append(f.path)
