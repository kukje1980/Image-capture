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
