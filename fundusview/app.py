"""Application entry point.

    python -m fundusview [--home DIR] [--demo]

``--home`` keeps settings + library in one folder (portable / USB use);
``--demo`` fills an empty library with synthetic, de-identified sample
photos so the viewer can be tried without a camera.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import APP_NAME, APP_TITLE


def _apply_opengl_mode(mode: str) -> None:
    from PySide6.QtCore import QCoreApplication, Qt

    if mode == "software" or os.getenv("FUNDUSVIEW_SOFTWARE_GL") == "1":
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    elif mode == "desktop":
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fundusview", description=APP_TITLE)
    ap.add_argument("--home", help="settings + library folder (portable mode)")
    ap.add_argument("--demo", action="store_true", help="add synthetic demo photos to an empty library")
    args = ap.parse_args(argv)
    if args.home:
        os.environ["FUNDUSVIEW_HOME"] = str(Path(args.home).resolve())

    from .config import Settings
    settings = Settings.load()
    _apply_opengl_mode(settings.opengl)

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    from .ui.icon import qicon
    app.setWindowIcon(qicon())
    if sys.platform == "win32":
        app.setFont(QFont("Malgun Gothic", 9))
    style = Path(__file__).with_name("ui") / "style.qss"
    if style.exists():
        app.setStyleSheet(style.read_text(encoding="utf-8"))

    from .db import Database
    from .ui.main_window import MainWindow

    settings.library.mkdir(parents=True, exist_ok=True)
    db = Database(settings.library / "fundus.db")
    win = MainWindow(settings, db)
    if args.demo and not db.list_patients() and db.count_unassigned() == 0:
        from .config import config_dir
        from .demo import write_demo_folder
        demo_dir = config_dir() / "demo_drop"  # outside the library (the importer ignores the library)
        write_demo_folder(demo_dir)
        win.service.import_paths([str(demo_dir)])
    win.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
