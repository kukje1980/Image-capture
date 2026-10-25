"""죽지 않는 예외 처리 · 한 번만 실행 잠금."""
from __future__ import annotations

import logging
import sys
import threading

from app.logging_setup import install_crash_guards


def test_excepthook_logs_and_does_not_raise(caplog):
    old = (sys.excepthook, threading.excepthook)
    try:
        install_crash_guards("테스트")
        with caplog.at_level(logging.ERROR, logger="app.crash"):
            sys.excepthook(RuntimeError, RuntimeError("boom"), None)
            t = threading.Thread(target=lambda: 1 / 0)
            t.start()
            t.join()
        msgs = [r.getMessage() for r in caplog.records]
        assert any("boom" in m for m in msgs)
        assert any("ZeroDivisionError" in m for m in msgs)
    finally:
        sys.excepthook, threading.excepthook = old


def test_single_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.__main__ import _acquire_single_instance
    first = _acquire_single_instance("x")
    assert first is not None
    # 두 번째는 잠금을 얻지 못한다 (안내창은 offscreen 에서 바로 닫히지 않으므로 호출을 흉내 냄)
    from PySide6.QtCore import QLockFile
    second = QLockFile(str(tmp_path / "SlitLampImaging" / "app.lock"))
    assert not second.tryLock(50)
    first.unlock()
    assert second.tryLock(50)
    second.unlock()
