"""Reference cycles are collected on the GUI thread only (fundusview/ui/gui_gc.py): a window left
in a cycle is never destroyed by a worker thread that happens to allocate — Qt waits there for the
GUI thread, and with the database lock held the import and the window waited for each other."""
import gc
import os
import threading
import time
import weakref

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from fundusview.ui import gui_gc  # noqa: E402


def test_a_window_left_in_a_cycle_is_freed_on_the_gui_thread_not_by_a_busy_worker():
    app = QApplication.instance() or QApplication([])
    gui_gc.install(app)
    assert not gc.isenabled()
    where = []
    w = QWidget()
    w.resize(240, 160)
    w.show()                                   # a window of its own, its events not taken yet
    w.cycle = w                                # only the cycle collector can free it
    ref = weakref.ref(w, lambda _: where.append(threading.current_thread().name))
    del w
    kept = []
    # far past every threshold: the automatic collector would have run here, on the worker
    worker = threading.Thread(target=lambda: kept.extend([] for _ in range(300_000)), name="worker")
    worker.start()
    worker.join(10)
    stuck = worker.is_alive()
    deadline = time.time() + 10
    while ref() is not None and time.time() < deadline:
        app.processEvents()                    # the GUI thread's timer collects it
        time.sleep(0.02)
    worker.join(10)
    assert not stuck, "the worker hung destroying a window (waiting for the GUI thread)"
    assert where == ["MainThread"]
    kept.clear()
