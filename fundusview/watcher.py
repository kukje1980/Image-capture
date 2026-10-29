"""Folder watching and the background import queue.

* ``watchdog`` delivers create / modify / move events (ReadDirectoryChangesW
  on Windows) for local folders.
* Folders flagged ``polling`` (network shares such as the APOLLO
  ``PatientCapture`` SMB share, mapped drives, NAS) are scanned every
  ``POLL_SECONDS`` instead — change events over SMB are unreliable.
* A periodic rescan of every folder is the safety net for missed events and
  for files that arrived while the viewer was closed.
* Scans are cheap on large trees: files already handled are remembered as
  ``path -> (size, mtime)`` (preloaded from the DB), and a directory whose
  modification time has not changed since the last scan is not listed again
  (new files always bump their directory's mtime).
* One worker thread imports files in arrival order. Callbacks run on that
  thread — the GUI wraps them in Qt signals.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .config import Settings, WatchFolder
from .db import Database
from .importer import Importer, ImportResult, is_candidate
from .profiles import IMAGE_EXTS

POLL_SECONDS = 10


def _cheap_candidate(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in IMAGE_EXTS or ext == ""


def is_network_path(path: str) -> bool:
    """UNC path or (on Windows) a mapped network drive."""
    if path.startswith(("\\\\", "//")):
        return True
    if sys.platform == "win32" and len(path) >= 2 and path[1] == ":":
        try:
            import ctypes
            DRIVE_REMOTE = 4
            return ctypes.windll.kernel32.GetDriveTypeW(path[:2] + "\\") == DRIVE_REMOTE
        except Exception:
            return False
    return False


class ImportService:
    def __init__(self, db: Database, settings: Settings,
                 on_result: Callable[[ImportResult], None] | None = None,
                 on_status: Callable[[str], None] | None = None):
        self.db = db
        self.settings = settings
        self.importer = Importer(db, settings)
        self.on_result = on_result or (lambda r: None)
        self.on_status = on_status or (lambda s: None)
        self._q: queue.Queue = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._known: dict[str, tuple[int, float]] = db.seen_index()
        self._dir_mtime: dict[str, tuple[float, float]] = {}  # dir -> (mtime, listed at)
        self._scan_lock = threading.Lock()
        self._observers: list = []
        self._poll_folders: list[WatchFolder] = []
        self._watching = threading.Event()
        self._stop = threading.Event()
        self._timers: list[threading.Thread] = []
        self._worker = threading.Thread(target=self._run, name="fundus-import", daemon=True)
        self._worker.start()

    # -- queue ---------------------------------------------------------------
    def enqueue(self, path: str | Path, folder: WatchFolder | None = None, force: bool = False) -> None:
        p = os.path.normpath(str(path))
        with self._lock:
            if p in self._pending:
                return
            self._pending.add(p)
        self._q.put((p, folder, force))

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._pending)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                p, folder, force = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if p is None:
                break
            with self._lock:
                self._pending.discard(p)
            try:
                self.on_status(f"가져오는 중: {os.path.basename(p)} (대기 {self.queued})")
                res = self.importer.import_file(p, folder, force=force)
                if res.status != "pending":  # pending = still being written: retry later
                    try:
                        st = os.stat(p)
                        self._known[p] = (st.st_size, st.st_mtime)
                    except OSError:  # moved into the library
                        pass
                if res.status not in ("skipped", "pending") or force:
                    self.on_result(res)
            except Exception as exc:  # never let the worker die
                self.on_result(ImportResult("error", p, str(exc)))
            if self.queued == 0:
                self.on_status("대기 중")

    # -- folders -------------------------------------------------------------
    def folder_for(self, path: str) -> WatchFolder | None:
        best, best_len = None, -1
        np_ = os.path.normcase(os.path.abspath(path))
        for f in self.settings.watch_folders:
            root = os.path.normcase(os.path.abspath(f.path))
            if (np_ == root or np_.startswith(root.rstrip("\\/") + os.sep)) and len(root) > best_len:
                best, best_len = f, len(root)
        return best

    def scan_folder(self, folder: WatchFolder, full: bool = False) -> int:
        """Enqueue files in ``folder`` that are new or changed since last seen.

        ``full`` lists every directory again (first scan of a session, manual
        "지금 검사"); otherwise directories with an unchanged mtime are skipped.
        """
        n = 0
        root = folder.path
        if not os.path.isdir(root):
            return 0
        with self._scan_lock:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")] if folder.recursive else []
                try:
                    mt = os.stat(dirpath).st_mtime
                except OSError:
                    continue
                prev = self._dir_mtime.get(dirpath)
                # Skip only if unchanged *and* settled well before the last
                # listing (FAT/exFAT timestamps have 2 s resolution).
                if not full and prev is not None and prev[0] == mt and mt < prev[1] - 3:
                    continue
                self._dir_mtime[dirpath] = (mt, time.time())
                for name in filenames:
                    p = os.path.normpath(os.path.join(dirpath, name))
                    if not _cheap_candidate(p):
                        continue
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    if self._known.get(p) == (st.st_size, st.st_mtime):
                        continue
                    if is_candidate(Path(p)):
                        self.enqueue(p, folder)
                        n += 1
        return n

    def scan_all(self, full: bool = False) -> int:
        return sum(self.scan_folder(f, full) for f in self.settings.watch_folders if f.enabled)

    def import_paths(self, paths: list[str], force: bool = False) -> int:
        """Manual import of files and/or folders (drag & drop, menu)."""
        n = 0
        for p in paths:
            if os.path.isdir(p):
                for dirpath, _, filenames in os.walk(p):
                    for name in filenames:
                        fp = os.path.join(dirpath, name)
                        if _cheap_candidate(fp):
                            self.enqueue(fp, self.folder_for(fp) or WatchFolder(path=p), force)
                            n += 1
            elif os.path.isfile(p):
                self.enqueue(p, self.folder_for(p), force)
                n += 1
        return n

    # -- watching ------------------------------------------------------------
    @property
    def is_watching(self) -> bool:
        return self._watching.is_set()

    def start_watching(self) -> list[str]:
        """Start observers / pollers; returns error messages for folders that failed."""
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        self.stop_watching()
        service = self
        errors: list[str] = []

        class Handler(FileSystemEventHandler):
            def __init__(self, folder: WatchFolder):
                self.folder = folder

            def _maybe(self, path: str) -> None:
                if _cheap_candidate(path) and os.path.isfile(path):
                    service.enqueue(path, self.folder)

            def on_created(self, event):
                if not event.is_directory:
                    self._maybe(event.src_path)

            def on_modified(self, event):
                if not event.is_directory:
                    self._maybe(event.src_path)

            def on_moved(self, event):  # Export Tool writes *.tmp then renames
                if not event.is_directory:
                    self._maybe(event.dest_path)

        for f in self.settings.watch_folders:
            if not f.enabled:
                continue
            if not os.path.isdir(f.path):
                errors.append(f"폴더 없음: {f.path}")
                continue
            if f.polling:
                self._poll_folders.append(f)
                continue
            obs = Observer()
            try:
                obs.schedule(Handler(f), f.path, recursive=f.recursive)
                obs.start()
                self._observers.append(obs)
            except Exception as exc:
                errors.append(f"{f.path}: {exc}")
        if not (self._observers or self._poll_folders):
            self.on_status("감시할 폴더 없음")
            return errors
        self._watching.set()
        self._start_loop("fundus-poll", POLL_SECONDS, lambda: [self.scan_folder(f) for f in self._poll_folders],
                         first=lambda: self.scan_all(full=True))
        if self.settings.rescan_seconds > 0:
            self._start_loop("fundus-rescan", self.settings.rescan_seconds, self.scan_all)
        self.on_status("폴더 감시 중")
        return errors

    def _start_loop(self, name: str, every: float, fn, first=None) -> None:
        generation = self._watching

        def loop():
            if first is not None:
                first()
            while not self._stop.is_set() and generation.is_set():
                if self._stop.wait(every) or not generation.is_set():
                    break
                try:
                    fn()
                except Exception as exc:
                    self.on_status(f"폴더 검사 오류: {exc}")

        t = threading.Thread(target=loop, name=name, daemon=True)
        t.start()
        self._timers.append(t)

    def stop_watching(self) -> None:
        self._watching.clear()
        self._watching = threading.Event()  # old loops see their own (cleared) event and exit
        for obs in self._observers:
            try:
                obs.stop()
                obs.join(timeout=3)
            except Exception:
                pass
        self._observers = []
        self._poll_folders = []
        self._timers = []

    def shutdown(self) -> None:
        self.stop_watching()
        self._stop.set()
        self._q.put((None, None, False))
        self._worker.join(timeout=5)
