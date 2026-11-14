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
def window(tmp_path, monkeypatch):
    """The viewer as it starts up: it begins watching the inbox by itself.

    Message boxes are recorded instead of shown — a modal box would wait forever for a
    click on a headless CI runner — and every test checks that none appeared.
    """
    from PySide6.QtWidgets import QApplication, QMessageBox

    from fundusview import autosetup
    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    shown = []
    for name in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: shown.append((_n, a[2] if len(a) > 2 else "")) or QMessageBox.StandardButton.No))
    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"), auto_detect=False,
                 stable_seconds=0.2, rescan_seconds=1)   # rescan: safety net for slow change events (macOS)
    autosetup.apply(s, [])                              # the inbox, as at every start
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    w.show()
    # start-up turns watching on by itself; let it settle before anything restarts it
    assert _wait(app, lambda: w.act_watch.isChecked(), timeout=10)
    _wait(app, lambda: False, timeout=1.0)
    yield app, w, db, shown
    _wait(app, lambda: False, timeout=0.5)
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
    app, w, db, shown = window
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
    assert shown == []


def test_inbox_inside_library_is_refused(window):
    from fundusview.ui.dialogs import SettingsDialog

    app, w, _, shown = window
    dlg = SettingsDialog(w.settings, w)
    dlg.inbox.setText(str(w.settings.library / "in"))
    dlg.accept()
    assert [k for k, _ in shown] == ["warning"] and "라이브러리" in shown[0][1]
    assert dlg.result() != SettingsDialog.DialogCode.Accepted
