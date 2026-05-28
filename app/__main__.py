"""애플리케이션 진입점.

    python -m app                 # 설정에 따른 소스(기본 device)
    python -m app --source synthetic   # 하드웨어 없이 합성 영상으로 실행
    python -m app --source file        # 설정의 test_file_path 재생
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.db.database import Database
from app.logging_setup import setup_logging
from app.ui.main_window import MainWindow


def _apply_cli_overrides(argv, config: AppConfig) -> None:
    for i, a in enumerate(argv):
        if a == "--source" and i + 1 < len(argv):
            config.source_mode = argv[i + 1]
        elif a.startswith("--source="):
            config.source_mode = a.split("=", 1)[1]


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    log = logging.getLogger("app")

    config = AppConfig.load()
    _apply_cli_overrides(argv, config)
    log.info("source_mode=%s media_root=%s export_root=%s",
             config.source_mode, config.media_root, config.export_root)

    db = Database(config.db_path).init()

    app = QApplication(argv)
    win = MainWindow(config, db)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
