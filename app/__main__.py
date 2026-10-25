"""애플리케이션 진입점.

    python -m app                 # 설정에 따른 소스(기본 device)
    python -m app --source synthetic   # 하드웨어 없이 합성 영상으로 실행
    python -m app --source file        # 설정의 test_file_path 재생
    python -m app --brand keeler       # Keeler 전용 화면 (로고·색)
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import brand, paths
from app.config import AppConfig
from app.db.database import Database
from app.logging_setup import install_crash_guards, setup_logging


def _apply_cli_overrides(argv, config: AppConfig) -> None:
    for i, a in enumerate(argv):
        if a == "--source" and i + 1 < len(argv):
            config.source_mode = argv[i + 1]
        elif a.startswith("--source="):
            config.source_mode = a.split("=", 1)[1]


def _acquire_single_instance(app_name: str) -> QLockFile | None:
    """같은 PC 에서 두 번 실행되면(카메라를 서로 뺏고 DB 를 동시에 쓰는 일) 두 번째는 안내 후 종료."""
    lock = QLockFile(str(paths.get_appdata_dir() / "app.lock"))
    lock.setStaleLockTime(0)                      # 비정상 종료로 남은 잠금은 PID 로 판별해 자동 해제
    if lock.tryLock(300):
        return lock
    if lock.removeStaleLockFile() and lock.tryLock(300):
        return lock
    QMessageBox.information(None, app_name, "프로그램이 이미 실행 중입니다.\n열려 있는 창을 사용하세요.")
    return None


def _open_database(config: AppConfig, app_name: str) -> Database | None:
    try:
        return Database(config.db_path).init()
    except Exception as e:  # noqa: BLE001 — 복구까지 실패(권한·디스크 등): 추적 대신 원인과 경로를 보여 준다
        logging.getLogger("app").exception("database open failed")
        QMessageBox.critical(None, app_name,
                             "환자 데이터베이스를 열 수 없습니다.\n\n"
                             f"파일: {config.db_path}\n원인: {e}\n\n"
                             "폴더 권한·디스크 공간을 확인한 뒤 다시 실행하세요.")
        return None


def _notify_recovery(win, db: Database) -> None:
    r = db.recovery
    if not r:
        return
    msg = ("환자 데이터베이스 파일이 손상되어 있어 자동으로 복구했습니다.\n\n"
           + (f"• 최근 백업에서 복원: {r['restored_from']}\n" if r.get("restored_from")
              else "• 복원할 백업이 없어 빈 데이터베이스로 시작합니다.\n")
           + (f"• 손상된 원본 보관: {r['quarantined']}\n" if r.get("quarantined") else "")
           + "\n촬영 사진·동영상 파일은 그대로 남아 있습니다.")
    box = QMessageBox(QMessageBox.Icon.Warning, "데이터베이스 복구", msg, QMessageBox.StandardButton.Ok, win)
    box.setModal(False)
    box.show()


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

    app = QApplication(argv)
    app.setApplicationName(b["app_name"])
    app.setStyle("Fusion")
    app.setWindowIcon(make_app_icon())
    app.setStyleSheet(build_qss(config.theme))
    install_crash_guards(app_name=b["app_name"])   # 예외가 나도 프로그램이 꺼지지 않고 기록·안내

    lock = _acquire_single_instance(b["app_name"])
    if lock is None:
        return 0
    db = _open_database(config, b["app_name"])
    if db is None:
        return 1

    win = MainWindow(config, db)
    win.show()
    QTimer.singleShot(400, lambda: _notify_recovery(win, db))
    try:
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())
