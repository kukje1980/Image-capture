"""Reference cycles are collected on the GUI thread only.

Python's cycle collector runs on whichever thread happens to be allocating when a collection is
due: the import worker, a preview thread, a thread pool. A window or widget that is closed but
still caught in a reference cycle (a dialog, a 3D view) is then destroyed on that thread, and Qt
widgets must not be: ``QWidget::~QWidget`` → ``QWindow::close`` →
``QWindowSystemInterface::flushWindowSystemEvents`` waits for the GUI thread to take the window's
pending events. If the worker holds the database lock at that moment (inside any read, or a
``Database.batch`` of an import) while the window waits for that lock to list the new photo, each
waits for the other for good: the import stops and the window freezes. The bulk import of
tests/test_import_stress.py hung exactly so — a reader thread destroying a 3D view left by an
earlier test, inside ``fetchall`` with the lock held. Elsewhere a widget destroyed off its thread
can crash Qt.

:func:`install` turns the automatic collection off and collects on a timer of the GUI thread
instead, by the same thresholds (pyqtgraph does the same for the same reason): cycles are still
freed, within a tick, but always on the GUI thread. Objects without cycles are freed by reference
counting as before, on any thread.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer

TICK_MS = 1000

_collector: _Collector | None = None


class _Collector(QObject):
    def __init__(self, app: QCoreApplication):
        super().__init__(app)
        self.thresholds = gc.get_threshold()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.collect)
        self.timer.start(TICK_MS)

    def collect(self) -> int:
        """The collection the automatic collector would have made by now, if any: the oldest
        generation over its threshold. Returns the number of unreachable objects found."""
        if gc.isenabled():                # something switched it back on: off again
            gc.disable()
        c0, c1, c2 = gc.get_count()
        t0, t1, t2 = self.thresholds
        if c0 <= t0:
            return 0
        return gc.collect(2 if c1 > t1 and c2 > t2 else 1 if c1 > t1 else 0)


def _alive(c: _Collector | None) -> bool:
    try:
        return c is not None and c.timer.isActive()
    except RuntimeError:                  # its QApplication (the parent) is gone
        return False


def install(app: QCoreApplication | None = None) -> None:
    """From now on collect reference cycles on the GUI thread only (on its event loop's timer).
    Call it on the GUI thread once the QApplication exists; again is harmless."""
    global _collector
    app = app or QCoreApplication.instance()
    if app is None or _alive(_collector):
        return
    if QThread.currentThread() is not app.thread():
        raise RuntimeError("gui_gc.install() must be called on the GUI thread")
    gc.disable()
    _collector = _Collector(app)


def collect() -> int:
    """Collect now what is due (GUI thread only; nothing when :func:`install` was not called)."""
    return _collector.collect() if _alive(_collector) else 0
