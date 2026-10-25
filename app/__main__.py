"""애플리케이션 진입점.

    python -m app                 # 설정에 따른 소스(기본 device)
    python -m app --source synthetic   # 하드웨어 없이 합성 영상으로 실행
    python -m app --source file        # 설정의 test_file_path 재생
    python -m app --brand keeler       # Keeler 전용 화면 (로고·색)
    python -m app --import-samples <폴더|zip>   # 질환별 샘플 사진을 등록하고 끝냄 (화면 없음)
"""
from __future__ import annotations

import logging
import sys

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


def _import_samples_arg(argv):
    for i, a in enumerate(argv):
        if a == "--import-samples" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--import-samples="):
            return a.split("=", 1)[1]
    return None


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    log = logging.getLogger("app")

    config = AppConfig.load()
    _apply_cli_overrides(argv, config)
    # 브랜드는 UI 모듈을 불러오기 전에 정한다 (아이콘 강조색 등이 import 시점에 정해짐)
    b = brand.select(brand.key_from(argv, getattr(config, "brand", "")))
    from app.ui.main_window import MainWindow
    from app.ui.theme import build_qss, make_app_icon
    log.info("source_mode=%s media_root=%s export_root=%s",
             config.source_mode, config.media_root, config.export_root)

    db = Database(config.db_path).init()

    samples = _import_samples_arg(argv)
    if samples:
        from app.services.sample_import import import_samples
        try:
            print(import_samples(db, config, samples).summary())
            return 0
        except (OSError, ValueError) as e:
            print(f"샘플 사진을 가져오지 못했습니다: {e}", file=sys.stderr)
            return 1
        finally:
            db.close()

    from PySide6.QtWidgets import QApplication

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
