"""회전 파일 + 콘솔 로깅 설정."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app import paths


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
