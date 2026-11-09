import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Keep settings / inbox / library of every test out of the real home folder.
os.environ["FUNDUSVIEW_HOME"] = tempfile.mkdtemp(prefix="fundusview-test-")


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    from fundusview.demo import write_demo_folder

    root = tmp_path_factory.mktemp("demo_drop")
    write_demo_folder(root, small=True)
    return root


@pytest.fixture
def wait_imports():
    """``wait(app, window)``: run the event loop until every queued photo is imported and the
    window has taken in all results (they are coalesced on a 300 ms timer, and a new photo may
    be opened automatically). Waiting for one expected patient is not enough: on a slow runner
    the last photos arrive later and the window switches to them."""
    def wait(app, w, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        quiet_since = None
        while time.time() < deadline:
            app.processEvents()
            if w.service.idle and not w._results and not w._result_timer.isActive():
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since > 0.25:
                    return
            else:
                quiet_since = None
            time.sleep(0.02)
        raise AssertionError(f"imports still running after {timeout:.0f} s (queued {w.service.queued})")
    return wait
