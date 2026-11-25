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


def _open_library(settings, gui: bool):
    """This computer's library. A database file that cannot be read (damaged by a power cut, a
    disk error, another program's file under its name) used to end the program without a word:
    now the user is told and may start an empty library — the damaged file is kept beside it
    (``fundus.db.corrupt-날짜``), never deleted, and the photos themselves are not touched. None:
    not opened."""
    import sqlite3
    import time

    from .db import Database

    path = settings.library / "fundus.db"
    try:
        settings.library.mkdir(parents=True, exist_ok=True)
        return Database(path)
    except (sqlite3.Error, OSError) as exc:
        text = (f"라이브러리를 열 수 없습니다.\n{path}\n{exc}\n\n"
                "데이터베이스 파일이 손상되었거나 다른 프로그램의 파일입니다.")
        if not gui:
            print(text, file=sys.stderr)
            return None
        if isinstance(exc, OSError) or not path.is_file():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, APP_TITLE, text + "\n\n설정의 라이브러리 폴더를 확인하세요.")
            return None
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(QMessageBox.Icon.Critical, APP_TITLE,
                      text + "\n\n손상된 파일을 옆에 보관하고 빈 라이브러리로 시작할 수 있습니다. "
                             "사진 파일은 그대로 있으며, 사진 폴더를 다시 가져오면 목록이 만들어집니다.")
    fresh = box.addButton("보관하고 새로 시작", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("끝내기", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is not fresh:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        for tail in ("", "-wal", "-shm"):
            part = path.with_name(path.name + tail)
            if part.exists():
                os.replace(part, path.with_name(f"{path.name}.corrupt-{stamp}{tail}"))
        return Database(path)
    except (sqlite3.Error, OSError) as exc:
        QMessageBox.critical(None, APP_TITLE, f"새 라이브러리를 만들지 못했습니다.\n{exc}")
        return None


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
        db = _open_library(settings, gui=False)
        if db is None:
            return 1
        try:
            return serve(settings, db)
        finally:
            db.close()
    _apply_opengl_mode(settings.opengl)

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    from .ui import gui_gc
    gui_gc.install(app)               # reference cycles (closed windows among them) freed on this thread only
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
        db = _open_library(settings, gui=True)
        if db is None:                # the library's database cannot be read, and the user chose to quit
            return 1
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
