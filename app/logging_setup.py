"""회전 파일 + 콘솔 로깅 설정, 그리고 '죽지 않는' 예외 처리."""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler

from app import paths

log = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logdir = paths.ensure_dir(paths.get_appdata_dir() / "logs")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)

    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fh = RotatingFileHandler(
            logdir / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
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


_last_popup = 0.0
_POPUP_INTERVAL = 15.0      # 같은 오류가 연달아 나도 안내창은 15초에 한 번만


def install_crash_guards(app_name: str = "") -> None:
    """처리되지 않은 예외가 나도 프로그램이 꺼지지 않게 한다.

    - 모든 스레드의 예외를 logs/app.log 에 기록
    - GUI 스레드 예외는 작은 안내창(비모달)으로 알리되 15초에 한 번만
    - Qt 자체 경고(qWarning 등)도 로그에 남긴다
    """
    def _report(exc_type, exc, tb, where: str) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.getLogger("app.crash").error("%s 처리되지 않은 예외:\n%s", where, text)
        if where == "GUI":
            _popup(app_name, exc_type.__name__, str(exc))

    def excepthook(exc_type, exc, tb):
        _report(exc_type, exc, tb, "GUI")

    def thread_hook(args):
        _report(args.exc_type, args.exc_value, args.exc_traceback,
                f"스레드 {getattr(args.thread, 'name', '?')}")

    sys.excepthook = excepthook
    threading.excepthook = thread_hook

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
                  QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
                  QtMsgType.QtFatalMsg: logging.CRITICAL}

        def qt_handler(kind, _ctx, message):
            if "propagateSizeHints" in message:          # 오프스크린 플랫폼의 무해한 반복 경고
                return
            logging.getLogger("qt").log(levels.get(kind, logging.WARNING), message)

        qInstallMessageHandler(qt_handler)
    except Exception:  # noqa: BLE001
        log.debug("Qt message handler 설치 실패", exc_info=True)


def _popup(app_name: str, kind: str, detail: str) -> None:
    global _last_popup
    now = time.monotonic()
    if now - _last_popup < _POPUP_INTERVAL:
        return
    _last_popup = now
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is None or threading.current_thread() is not threading.main_thread():
            return
        box = QMessageBox(QMessageBox.Icon.Warning, app_name or "오류",
                          "작업 중 예상치 못한 오류가 발생했습니다. 프로그램은 계속 실행됩니다.\n\n"
                          f"{kind}: {detail[:300]}\n\n자세한 내용은 logs/app.log 에 기록되었습니다.",
                          QMessageBox.StandardButton.Ok)
        box.setModal(False)
        box.show()
        _popup.keep = box          # 참조를 잡아 두어 바로 사라지지 않게
    except Exception:  # noqa: BLE001
        pass
