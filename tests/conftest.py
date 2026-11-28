import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Keep settings / inbox / library of every test out of the real home folder.
os.environ["FUNDUSVIEW_HOME"] = tempfile.mkdtemp(prefix="fundusview-test-")
# Animations finish at once (the same end state, no waiting); tests of the motion itself switch
# it on and step the clock by hand (``motion`` fixture in test_motion.py).
os.environ["FUNDUSVIEW_NO_MOTION"] = "1"


@pytest.fixture(autouse=True)
def _multi_view_on(monkeypatch):
    """[Multi] · 16장 보기 are an option since 0.13.17 (설정 → 화면 · 툴바, off at first). The tests of those
    views were written with them on: here a ``Settings`` made without saying so has the option on. A test
    of the first setting passes ``multi_view=False`` itself."""
    from fundusview.config import Settings

    init = Settings.__init__

    def with_multi(self, *args, **kwargs):
        kwargs.setdefault("multi_view", True)
        init(self, *args, **kwargs)
    monkeypatch.setattr(Settings, "__init__", with_multi)


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch):
    """A message box waits for a click that never comes on a headless runner, so one shown
    by mistake hung the whole CI job until its time limit. Here every QMessageBox.warning /
    information / critical / question is recorded, answers at once (No / Ok), and fails the
    test with its text. A test that expects a box patches QMessageBox itself (that wins)."""
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        yield
        return
    shown = []
    for name in ("warning", "information", "critical", "question"):
        def box(*args, _name=name, **kwargs):
            shown.append(f"{_name}: " + " / ".join(str(a) for a in args[1:3]))
            return QMessageBox.StandardButton.No if _name == "question" else QMessageBox.StandardButton.Ok
        monkeypatch.setattr(QMessageBox, name, staticmethod(box))
    yield
    assert not shown, "message box shown during the test (it would hang the CI): " + "; ".join(shown)


def _collect_on_the_gui_thread() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    if QApplication.instance() is not None:
        from fundusview.ui import gui_gc
        gui_gc.install()
        gui_gc.collect()


@pytest.fixture(autouse=True)
def _gui_thread_gc():
    """As the program does (fundusview/ui/gui_gc.py, installed by app.main): once a QApplication
    exists, reference cycles are collected on this thread only, here between tests and on the
    event loop's timer. Windows an earlier test left in a cycle are then never destroyed on a
    worker thread of a later test: that hung the bulk import of test_import_stress (a reader
    holding the database lock waited in ~QWidget for this thread, which waited for the lock)."""
    _collect_on_the_gui_thread()
    yield
    _collect_on_the_gui_thread()


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    from fundusview.demo import write_demo_folder

    root = tmp_path_factory.mktemp("demo_drop")
    write_demo_folder(root, small=True)
    return root


def _import_and_wait(app, window, paths, timeout: float = 60.0) -> int:
    """Import ``paths`` through the window's service and wait until every file is processed
    and the coalesced results are on screen.

    Waiting for a patient to appear is not enough: on a slow runner the worker is still
    importing the rest, and a late result re-selects the patient / photo in the middle of a
    test. The worker reports "가져오는 중: …" before each file and "대기 중" when the queue
    is empty, so count those instead of sleeping.
    """
    import time

    statuses: list[str] = []
    window.bridge.status.connect(statuses.append)
    try:
        n = window.service.import_paths([str(p) for p in paths])
        deadline = time.time() + timeout
        while time.time() < deadline:
            app.processEvents()
            started = sum(s.startswith("가져오는 중") for s in statuses)
            if (started >= n and statuses and statuses[-1] == "대기 중"
                    and not window._result_timer.isActive() and not window._results):
                app.processEvents()
                return n
            time.sleep(0.02)
        raise AssertionError(f"import of {n} files did not finish in {timeout:.0f} s (status: {statuses[-3:]})")
    finally:
        window.bridge.status.disconnect(statuses.append)


@pytest.fixture
def import_and_wait():
    """``import_and_wait(app, window, paths)`` — see :func:`_import_and_wait`."""
    return _import_and_wait


def pytest_sessionfinish(session, exitstatus):
    """The windows still alive when the tests are over are taken down here, in order, while the
    QApplication still exists. Left to the interpreter's shutdown they are destroyed in any order —
    now and then after the objects they hold ("QObject: shared QObject was deleted directly"), and the
    process died (exit 139 / 1) after every test had passed, failing the CI job."""
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    import gc

    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    for _ in range(3):
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
