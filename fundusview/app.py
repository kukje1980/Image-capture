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


def _connect(settings):
    """The library of the server this computer is connected to (설정 → 공유). When the server does
    not answer the user chooses: try again, open this computer's own library for now (``None``),
    or quit (``False``)."""
    from PySide6.QtWidgets import QMessageBox

    from .share import RemoteDatabase, ShareError

    while True:
        remote = RemoteDatabase(settings.server_url, settings.share_key, timeout=6)
        try:
            remote.ping()
            remote.timeout = 20
            remote.close()
            return remote
        except ShareError as exc:
            box = QMessageBox(QMessageBox.Icon.Warning, APP_TITLE,
                              f"서버 {settings.server_url} 에 연결하지 못했습니다.\n{exc}\n\n"
                              "서버 컴퓨터에서 뷰어가 켜져 있는지, 주소와 접속 암호가 맞는지 확인하세요.\n"
                              "(설정 → 공유 에서 바꿀 수 있습니다)")
            retry = box.addButton("다시 시도", QMessageBox.ButtonRole.AcceptRole)
            local = box.addButton("이 컴퓨터의 자료로 열기", QMessageBox.ButtonRole.ActionRole)
            box.addButton("끝내기", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is local:
                return None
            if box.clickedButton() is not retry:
                return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fundusview", description=APP_TITLE)
    ap.add_argument("--home", help="settings + library folder (portable mode)")
    ap.add_argument("--demo", action="store_true", help="add synthetic demo photos to an empty library")
    ap.add_argument("--serve", action="store_true",
                    help="share the library with other computers without opening a window (share.py)")
    args = ap.parse_args(argv)
    if args.home:
        os.environ["FUNDUSVIEW_HOME"] = str(Path(args.home).resolve())

    from .config import Settings
    settings = Settings.load()
    if args.serve:
        from .db import Database
        from .share import serve
        settings.library.mkdir(parents=True, exist_ok=True)
        db = Database(settings.library / "fundus.db")
        try:
            return serve(settings, db)
        finally:
            db.close()
    _apply_opengl_mode(settings.opengl)

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    from .ui import theme
    from .ui.icon import qicon
    app.setWindowIcon(qicon())
    theme.apply(app)                  # the dark look: style, palette, fonts, stylesheet, window frames

    from .db import Database
    from .ui.main_window import MainWindow

    db = _connect(settings) if settings.share_mode == "client" and settings.server_url else None
    if db is False:                   # no server, and the user chose to quit
        return 1
    if db is None:                    # this computer's own library
        settings.library.mkdir(parents=True, exist_ok=True)
        db = Database(settings.library / "fundus.db")
    win = MainWindow(settings, db)
    if args.demo and not db.list_patients() and db.count_unassigned() == 0:
        from .config import config_dir
        from .demo import write_demo_folder
        demo_dir = config_dir() / "demo_drop"  # outside the library (the importer ignores the library)
        write_demo_folder(demo_dir, montage=True, history=True)
        win.hold_follow()             # the patient list stays in front while the demo comes in
        win.service.import_paths([str(demo_dir)])
    win.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
