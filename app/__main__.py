"""애플리케이션 진입점.

    python -m app                 # 설정에 따른 소스(기본 device)
    python -m app --source synthetic   # 하드웨어 없이 합성 영상으로 실행
    python -m app --source file        # 설정의 test_file_path 재생
    python -m app --brand keeler       # Keeler 전용 화면 (로고·색)
    python -m app --brand fundus       # 안저판 (안저카메라 사진 폴더 자동 가져오기)
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app import brand
from app.config import AppConfig
from app.db.database import Database
from app.logging_setup import setup_logging


def _apply_cli_overrides(argv, config: AppConfig) -> None:
    for i, a in enumerate(argv):
        if a == "--source" and i + 1 < len(argv):
            config.source_mode = argv[i + 1]
        elif a.startswith("--source="):
            config.source_mode = a.split("=", 1)[1]


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # 제품(슬릿램프/안저)은 실행 옵션·환경변수로 먼저 정한다 — 데이터 폴더(설정·DB·로그)가 제품마다 다름
    fixed = brand.fixed_key(argv)
    if fixed:
        brand.select(fixed)
    setup_logging()
    log = logging.getLogger("app")

    config = AppConfig.load()
    _apply_cli_overrides(argv, config)
    # 브랜드는 UI 모듈을 불러오기 전에 정한다 (아이콘 강조색 등이 import 시점에 정해짐)
    b = brand.select(brand.choose(argv, getattr(config, "brand", "")))
    from app.ui.theme import build_qss, make_app_icon
    if brand.is_fundus():
        from app.ui.fundus_window import FundusWindow as MainWindow
    else:
        from app.ui.main_window import MainWindow
    log.info("brand=%s source_mode=%s media_root=%s export_root=%s",
             b["key"], config.source_mode, config.media_root, config.export_root)

    db = Database(config.db_path).init()

    app = QApplication(argv)
    app.setApplicationName(b["app_name"])
    app.setStyle("Fusion")
    app.setWindowIcon(make_app_icon())
    app.setStyleSheet(build_qss(config.theme))

    win = MainWindow(config, db)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
