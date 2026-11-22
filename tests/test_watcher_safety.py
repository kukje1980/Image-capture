"""A completed file must be noticed even when its directory did not change."""
import os
import time

from fundusview.config import Settings, WatchFolder
from fundusview.db import Database
from fundusview.watcher import ImportService


def test_polling_detects_existing_file_changes_without_directory_mtime_change(tmp_path, monkeypatch):
    root = tmp_path / "drop"
    root.mkdir()
    path = root / "image.png"
    path.write_bytes(b"partial")
    old = time.time() - 30
    os.utime(root, (old, old))
    folder = WatchFolder(path=str(root), polling=True)
    db = Database(tmp_path / "library.sqlite")
    service = ImportService(db, Settings(watch_folders=[folder]))
    queued = []
    monkeypatch.setattr(service, "enqueue", lambda *args: queued.append(args))
    try:
        assert service.scan_all(full=True) == 1
        st = path.stat()
        service._known[str(path)] = (st.st_size, st.st_mtime)
        queued.clear()
        path.write_bytes(b"complete-image-content")
        assert root.stat().st_mtime == old
        assert service.scan_all() == 1
        assert [args[0] for args in queued] == [str(path)]
    finally:
        service.shutdown()
        db.close()


def test_scheduled_rescan_recovers_missed_native_modification_event(tmp_path, monkeypatch):
    import watchdog.observers

    class SilentObserver:
        def schedule(self, *args, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def join(self, **kwargs): pass

    monkeypatch.setattr(watchdog.observers, "Observer", SilentObserver)
    root = tmp_path / "drop"
    root.mkdir()
    path = root / "image.png"
    path.write_bytes(b"partial")
    old = time.time() - 30
    os.utime(root, (old, old))
    db = Database(tmp_path / "library.sqlite")
    service = ImportService(db, Settings(watch_folders=[WatchFolder(path=str(root))], rescan_seconds=60))
    loops, queued = {}, []
    monkeypatch.setattr(service, "_start_loop", lambda name, every, fn, first=None: loops.update({name: (fn, first)}))
    monkeypatch.setattr(service, "enqueue", lambda *args: queued.append(args))
    try:
        assert service.start_watching() == []
        loops["fundus-poll"][1]()
        st = path.stat()
        service._known[str(path)] = (st.st_size, st.st_mtime)
        queued.clear()
        path.write_bytes(b"complete-image-content")
        assert root.stat().st_mtime == old
        loops["fundus-rescan"][0]()
        assert [args[0] for args in queued] == [str(path)]
    finally:
        service.shutdown()
        db.close()
