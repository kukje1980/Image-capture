"""회전 파일 + 콘솔 로깅 설정, 처리되지 않은 예외 기록."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional

from app import paths

log = logging.getLogger("app")


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logdir = paths.ensure_dir(paths.get_appdata_dir() / "logs")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)

    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fh = RotatingFileHandler(
            logdir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in root.handlers
    ):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    return root


def install_excepthook(notify: Optional[Callable[[str], None]] = None) -> None:
    """Qt 슬롯 등에서 잡히지 않은 예외를 app.log 에 남기고(exe 빌드에선 콘솔이 없어 그냥 사라진다),
    notify 가 있으면 사용자에게 한 번 알린다. 프로그램은 계속 실행된다."""

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("처리되지 않은 예외", exc_info=(exc_type, exc, tb))
        if notify is not None and threading.current_thread() is threading.main_thread():
            try:
                notify(f"{exc_type.__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass

    def thread_hook(args):
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
