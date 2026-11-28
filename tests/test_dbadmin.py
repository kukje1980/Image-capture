"""데이터베이스 관리 (dbadmin.py): backups, the check-up, going back to a backup."""
import os
import sqlite3
import time

import pytest

from fundusview import dbadmin
from fundusview.db import Database
from fundusview.models import ExtractedMeta


def _library(tmp_path, patients=2):
    lib = tmp_path / "lib"
    db = Database(lib / "fundus.db")
    for i in range(patients):
        ref = db.upsert_patient(ExtractedMeta(patient_id=f"P{i}", name=f"환자{i}"))
        photo = lib / f"p{i}.jpg"
        photo.write_bytes(b"jpg")
        db.insert_image(patient_ref=ref, file_path=str(photo), sha256=f"sha{i}")
    return lib, db


def test_backup_is_a_sound_copy_and_old_ones_are_pruned(tmp_path):
    lib, db = _library(tmp_path)
    try:
        b = dbadmin.backup(db, lib)
        assert b.path.parent == lib / "backups" and dbadmin.sound(b.path) and not list(b.path.parent.glob("*.part"))
        d = dbadmin.describe(b)
        assert (d.patients, d.images) == (2, 2)
        # written after the backup: not in it
        db.upsert_patient(ExtractedMeta(patient_id="P9", name="새 환자"))
        assert dbadmin.describe(b).patients == 2 and db.count_patients() == 3
        # only the newest ``keep`` stay
        for n in range(4):
            x = dbadmin.backup(db, lib, keep=3)
            os.utime(x.path, (time.time() + n + 1, time.time() + n + 1))
        left = dbadmin.list_backups(lib)
        assert x.path.exists() and len(left) <= 4 and dbadmin.prune(lib, keep=2) == len(left) - 2
        assert [x.path for x in dbadmin.list_backups(lib)] == [x.path for x in left[:2]]
    finally:
        db.close()


def test_auto_backup_once_a_day_and_never_raises(tmp_path, monkeypatch):
    empty = Database(tmp_path / "empty" / "fundus.db")
    try:
        assert dbadmin.auto_backup(empty, tmp_path / "empty") is None        # nothing to keep yet
    finally:
        empty.close()
    lib, db = _library(tmp_path)
    try:
        first = dbadmin.auto_backup(db, lib)
        assert first is not None and dbadmin.auto_backup(db, lib) is None     # one of today is there
        old = time.time() - 2 * 86400
        os.utime(first.path, (old, old))
        assert dbadmin.auto_backup(db, lib) is not None                       # another day
        monkeypatch.setattr(dbadmin, "backup", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        for b in dbadmin.list_backups(lib):
            os.utime(b.path, (old, old))
        assert dbadmin.auto_backup(db, lib) is None                           # (said nowhere: the program starts)
    finally:
        db.close()


def test_check_finds_missing_files_and_a_damaged_file(tmp_path):
    lib, db = _library(tmp_path, patients=3)
    try:
        rep = dbadmin.check(db)
        assert rep.ok and rep.integrity == "ok" and (rep.patients, rep.images, rep.checked_files) == (3, 3, 3)
        assert any("모두 제자리" in line for line in rep.lines())
        (lib / "p1.jpg").unlink()
        rep = dbadmin.check(db)
        assert not rep.ok and rep.missing == [str(lib / "p1.jpg")] and any("파일이 없는" in t for t in rep.lines())
        assert dbadmin.check(db, files=False).ok
    finally:
        db.close()
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all" * 100)
    assert not dbadmin.sound(junk) and not dbadmin.sound(tmp_path / "nothing.db")


def test_restore_puts_the_backup_back_and_keeps_what_there_was(tmp_path):
    lib, db = _library(tmp_path)
    b = dbadmin.backup(db, lib)
    db.upsert_patient(ExtractedMeta(patient_id="LATER", name="나중"))
    db.close()
    path = lib / "fundus.db"
    kept = dbadmin.restore(path, b.path)
    assert kept.exists() and kept.name.startswith("fundus.db.before-restore-") and b.path.exists()
    db = Database(path)
    try:
        assert db.count_patients() == 2 and db.find_patient("LATER") is None
    finally:
        db.close()
    con = sqlite3.connect(str(kept))                    # what there was: whole, with the later patient
    try:
        assert con.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 3
    finally:
        con.close()
    # a backup that cannot be read: refused, the database untouched
    bad = lib / "backups" / "fundus-bad.db"
    bad.write_bytes(b"junk" * 500)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        dbadmin.restore(path, bad)
    assert path.read_bytes() == before


def test_restore_asked_for_now_is_done_at_the_next_start(tmp_path):
    lib, db = _library(tmp_path)
    b = dbadmin.backup(db, lib)
    db.upsert_patient(ExtractedMeta(patient_id="LATER", name="나중"))
    with pytest.raises(ValueError):
        dbadmin.request_restore(lib, tmp_path / "nothing.db")
    assert dbadmin.pending_restore(lib) is None
    dbadmin.request_restore(lib, b.path)
    assert dbadmin.pending_restore(lib) == b.path.resolve()
    assert db.count_patients() == 3                     # (nothing yet: the database is open)
    db.close()
    path = lib / "fundus.db"
    kept, why = dbadmin.apply_pending(lib, path)
    assert kept is not None and why == "" and dbadmin.pending_restore(lib) is None
    assert dbadmin.apply_pending(lib, path) == (None, "")                     # once
    db = Database(path)
    try:
        assert db.count_patients() == 2
    finally:
        db.close()
    # the backup gone meanwhile: said, the database as it was, the request forgotten
    (lib / "backups").mkdir(exist_ok=True)
    (lib / "backups" / dbadmin.PENDING).write_text(str(tmp_path / "gone.db"), encoding="utf-8")
    kept, why = dbadmin.apply_pending(lib, path)
    assert kept is None and why and dbadmin.pending_restore(lib) is None and dbadmin.sound(path)


def test_the_program_starts_from_a_backup_when_the_database_is_damaged(tmp_path, monkeypatch):
    """A damaged database with a backup beside it: the start offers the newest sound backup."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    import fundusview.app as app_mod
    from fundusview.config import Settings

    QApplication.instance() or QApplication([])
    lib, db = _library(tmp_path)
    dbadmin.backup(db, lib)
    db.close()
    for tail in ("-wal", "-shm"):
        (lib / ("fundus.db" + tail)).unlink(missing_ok=True)
    (lib / "fundus.db").write_bytes(b"this is no database " * 400)
    s = Settings(library_dir=str(lib))
    pressed = []

    def run(box):
        back = next(b for b in box.buttons() if b.text().startswith("백업으로 되돌리기"))
        pressed.append(back.text())
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: back)
        return 0
    monkeypatch.setattr(QMessageBox, "exec", run)
    db = app_mod._open_library(s, gui=True)
    try:
        assert pressed and db is not None and db.count_patients() == 2
        assert list(lib.glob("fundus.db.before-restore-*"))                   # the damaged file is kept
    finally:
        if db is not None:
            db.close()


def test_the_window_backs_up_checks_and_asks_for_a_restore(tmp_path, monkeypatch):
    """파일 → 데이터베이스 관리…: 지금 백업 fills the list, 지금 점검 says what is wrong, 되돌리기 is asked for
    (done at the next start) and can be taken back."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from fundusview.config import Settings
    from fundusview.ui.dbadmin_dialog import DatabaseDialog

    QApplication.instance() or QApplication([])
    lib, db = _library(tmp_path)
    s = Settings(library_dir=str(lib))
    dlg = DatabaseDialog(db, s)
    try:
        assert dlg.list.count() == 0 and not dlg.b_restore.isEnabled() and "아직 백업이 없습니다" in dlg.lbl_note.text()
        assert "이상 없음" in dlg.lbl_state.text() and "환자 2명" in dlg.lbl_state.text()
        dlg.run_backup()
        assert dlg.list.count() == 1 and "환자 2명 · 사진 2장" in dlg.list.item(0).text() and dlg.b_restore.isEnabled()
        (lib / "p0.jpg").unlink()
        assert not dlg.run_check().ok and "확인이 필요합니다" in dlg.lbl_state.text()
        # 되돌리기: asked, confirmed — remembered for the next start, the database of now backed up too
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
        dlg.ask_restore()
        assert not dlg.restore_asked and dbadmin.pending_restore(lib) is None
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        wanted = dlg.current().path
        dlg.ask_restore()
        assert dlg.restore_asked and dbadmin.pending_restore(lib) == wanted.resolve()
        assert dlg.list.count() == 2 and not dlg.b_cancel.isHidden() and "다음에 프로그램을 시작할 때" in dlg.lbl_note.text()
        dlg.cancel_restore()
        assert not dlg.restore_asked and dbadmin.pending_restore(lib) is None and dlg.b_cancel.isHidden()
    finally:
        dlg.deleteLater()
        db.close()
