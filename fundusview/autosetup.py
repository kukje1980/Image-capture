"""Automatic import setup — photos come in without configuring anything.

At every start:

* the **inbox** folder (``Documents\\안저사진 가져오기``) is created and watched;
  photos dropped there are *moved* into the library, so an empty inbox means
  everything was imported;
* the capture software's own folders are looked for on every drive letter
  (local and mapped network drives; on macOS every volume under
  ``/Volumes``) and added with the right camera profile:

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


def drive_roots(volumes: str = "/Volumes") -> list[str]:
    """Where capture-software folders may live: drive letters on Windows,
    mounted volumes (USB disks, NAS / SMB shares) on macOS."""
    if sys.platform == "darwin":
        return mac_volume_roots(volumes)
    if sys.platform != "win32":
        return []
    if hasattr(os, "listdrives"):  # Python 3.12+
        try:
            return [d for d in os.listdrives() if d[:1].upper() not in "AB"]
        except OSError:
            pass
    return [f"{c}:\\" for c in string.ascii_uppercase[2:] if os.path.exists(f"{c}:\\")]


def mac_volume_roots(volumes: str = "/Volumes") -> list[str]:
    """Mounted volumes, without the start-up disk (``/Volumes/Macintosh HD``
    is a link to ``/``, whose folders are found through the home folder)."""
    try:
        names = sorted(os.listdir(volumes))
    except OSError:
        return []
    roots = []
    for name in names:
        p = os.path.join(volumes, name)
        try:
            if os.path.islink(p) and os.path.realpath(p) == "/":
                continue
            if os.path.isdir(p):
                roots.append(p)
        except OSError:
            continue
    return roots


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


def inbox_problem(inbox: str, library: str) -> str | None:
    """Why ``inbox`` cannot be the import folder (Korean message), or ``None``.

    An inbox inside the library would import the library's own copies again,
    and :func:`apply` / :func:`change_inbox` silently skip such a folder, so the
    settings dialog refuses it up front instead.
    """
    if not inbox.strip():
        return None
    k, lib = _key(inbox.strip()), _key(library.strip()) if library.strip() else ""
    if lib and (k == lib or k.startswith(lib + os.sep)):
        return ("가져오기 폴더는 라이브러리 폴더와 같거나 그 안에 둘 수 없습니다.\n"
                "(가져온 사진을 다시 가져오게 됩니다) 다른 폴더를 고르세요.")
    try:
        Path(inbox.strip()).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"가져오기 폴더를 만들 수 없습니다:\n{inbox.strip()}\n({e.strerror or e})"
    return None


def change_inbox(settings: Settings, old: str) -> WatchFolder | None:
    """The inbox was changed in the settings: watch the new folder right away.

    The old inbox's watch entry is moved to the new path (its options kept)
    instead of being left behind — otherwise the old folder kept emptying
    itself into the library while photos dropped into the new one waited for
    a restart. The old folder is not remembered as removed, so choosing it
    again later works. Returns the new inbox entry, or ``None`` when nothing
    changed or the folder cannot be watched (inside the library).
    """
    new = str(settings.inbox)
    nk, ok = _key(new), _key(old)
    if nk == ok:
        return None
    lib = _key(str(settings.library))
    if nk == lib or nk.startswith(lib + os.sep):
        return None
    Path(new).mkdir(parents=True, exist_ok=True)
    # chosen by the user: never treat it as a removed auto folder
    settings.ignored_auto_folders = [p for p in settings.ignored_auto_folders if _key(p) != nk]
    folders: list[WatchFolder] = []
    entry = next((f for f in settings.watch_folders if _key(f.path) == nk), None)
    for f in settings.watch_folders:
        if _key(f.path) == ok:              # the old inbox -> the new one, same options
            if entry is None:
                f.path = new
                entry = f
                folders.append(f)
        else:
            folders.append(f)
    if entry is None:                       # the old inbox had been removed from the list
        entry = WatchFolder(path=new, profile="auto", recursive=True, action=ACTION_MOVE)
        folders.insert(0, entry)
    settings.watch_folders = folders
    return entry


def remember_removed(settings: Settings, before: list[WatchFolder]) -> None:
    """Folders the user deleted in the settings are not auto-added again."""
    now = {_key(f.path) for f in settings.watch_folders}
    for f in before:
        if _key(f.path) not in now and f.path not in settings.ignored_auto_folders:
            settings.ignored_auto_folders.append(f.path)
