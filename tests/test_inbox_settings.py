"""설정에서 가져오기 폴더를 바꾸면 다시 시작하지 않아도 그 폴더로 넣은 사진을 가져온다."""
import os
import shutil
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _photo(demo_dir, i=0):
    return sorted(p for p in demo_dir.rglob("*.jpg") if p.is_file())[i]


def _images(db):
    return db._one("SELECT COUNT(*) AS n FROM images")["n"]


@pytest.fixture
def window(tmp_path):
    from PySide6.QtWidgets import QApplication

    from fundusview import autosetup
    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"), auto_detect=False,
                 stable_seconds=0.05, rescan_seconds=1)   # rescan: safety net for slow change events (macOS)
    autosetup.apply(s, [])                              # what the start-up does: watch the inbox
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    w.show()
    w.act_watch.setChecked(True)
    yield app, w, db
    w.close()
    db.close()


def _settings_ok(w, monkeypatch, edit):
    from fundusview.ui.dialogs import SettingsDialog

    def ok(dlg):
        edit(dlg)
        return True
    monkeypatch.setattr(SettingsDialog, "exec", ok)
    w._open_settings()


def _wait(app, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.05)
    return cond()


def test_new_inbox_imports_at_once_and_old_one_stops(window, tmp_path, demo_dir, monkeypatch):
    app, w, db = window
    new = tmp_path / "새 가져오기 폴더"
    _settings_ok(w, monkeypatch, lambda d: d.inbox.setText(str(new)))
    assert [os.path.basename(f.path) for f in w.settings.watch_folders] == ["새 가져오기 폴더"]
    assert "가져오기 폴더" in w.lbl_status.text() and "1개 폴더" in w.lbl_watch.text()

    photo = _photo(demo_dir)
    shutil.copy(photo, new / photo.name)
    assert _wait(app, lambda: _images(db) == 1 and not (new / photo.name).exists())   # moved into the library

    old = tmp_path / "inbox"                            # the old folder is no longer emptied
    shutil.copy(_photo(demo_dir, 1), old / "old.jpg")
    assert not _wait(app, lambda: _images(db) == 2, timeout=3)
    assert (old / "old.jpg").exists()

    from fundusview.config import Settings
    assert Settings.load().inbox == new                 # remembered


def test_inbox_inside_library_is_refused(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from fundusview.ui.dialogs import SettingsDialog

    app, w, _ = window
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    dlg = SettingsDialog(w.settings, w)
    dlg.inbox.setText(str(w.settings.library / "in"))
    dlg.accept()
    assert warned and "라이브러리" in warned[0] and dlg.result() != SettingsDialog.DialogCode.Accepted
