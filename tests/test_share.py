"""Sharing one library between computers (share.py): the server answers, a connected viewer reads
and edits through it, photos are fetched into a cache, and nothing but the database's own files
is ever sent."""
import json
import urllib.error
import urllib.request

import numpy as np
import pytest

from fundusview import share
from fundusview.config import Settings
from fundusview.db import Database
from fundusview.importer import Importer
from fundusview.models import ExtractedMeta


@pytest.fixture
def shared(tmp_path, demo_dir):
    settings = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.0, share_key="비밀 1234")
    db = Database(settings.library / "fundus.db")
    importer = Importer(db, settings)
    for f in sorted(p for p in demo_dir.rglob("*") if p.is_file())[:4]:
        importer.import_file(f, wait=False)
    changes = []
    server = share.ShareServer(db, settings, importer, port=0, on_change=lambda: changes.append(1))
    server.start()
    errors = []
    remote = share.RemoteDatabase(f"127.0.0.1:{server.port}", "비밀 1234", tmp_path / "cache",
                                  on_error=errors.append)
    yield db, server, remote, changes, errors
    remote.close()
    server.stop()
    db.close()


def test_reads_match_the_server(shared):
    db, server, remote, _, errors = shared
    assert remote.ping()["auth"]
    local, far = db.list_patients(), remote.list_patients()
    assert [p["patient_id"] for p in far] == [p["patient_id"] for p in local] and far
    assert remote.count_patients() == db.count_patients()
    assert remote.count_unassigned() == db.count_unassigned()
    assert remote.unassigned_summary()["n_images"] == db.unassigned_summary()["n_images"]
    ref = local[0]["id"]
    assert remote.get_patient(ref)["name"] == local[0]["name"]
    assert remote.find_patient("없는 환자") is None
    assert [r["id"] for r in remote.images_for_patient(ref)] == [r["id"] for r in db.images_for_patient(ref)]
    assert not errors


def test_photo_files_are_fetched_into_the_cache(shared):
    db, server, remote, _, errors = shared
    row = db.images_for_patient(db.list_patients()[0]["id"])[0]
    far = remote.get_image(row["id"])
    for column in ("file_path", "thumb_path"):
        local = far[column]
        assert local != row[column] and str(remote.cache) in local
        assert open(local, "rb").read() == open(row[column], "rb").read()
    assert far["file_path"].endswith(row["file_path"].replace("\\", "/").rsplit("/", 1)[-1])   # its own name
    assert far["display_path"] is None or far["display_path"]
    assert far["original_path"] == row["original_path"]      # not a file of this computer: as stored
    server.stop()                                            # a fetched photo needs no server
    assert open(remote.local_file(far, "file_path"), "rb").read(4)
    assert not errors


def test_edits_are_stored_on_the_server(shared):
    db, server, remote, changes, _ = shared
    p = db.list_patients()[0]
    remote.update_patient(p["id"], name="김 수정", note="메모")
    assert db.get_patient(p["id"])["name"] == "김 수정" and db.get_patient(p["id"])["note"] == "메모"
    img = db.images_for_patient(p["id"])[0]
    stored = img["file_path"]
    remote.update_image(img["id"], note="황반 변성", fovea_x=12.5, file_path="C:/elsewhere.jpg")
    got = db.get_image(img["id"])
    assert got["note"] == "황반 변성" and got["fovea_x"] == 12.5
    assert got["file_path"] == stored                        # a path is never taken from another computer
    ref = remote.upsert_patient(ExtractedMeta(patient_id="NEW-1", name="새 환자"))
    assert db.get_patient(ref)["patient_id"] == "NEW-1"
    remote.merge_patients(ref, p["id"])
    assert db.get_patient(ref) is None
    assert len(changes) >= 4                                 # the server's window is told each time


def test_change_is_noticed_by_the_other_computers(shared):
    db, server, remote, _, _ = shared
    other = share.RemoteDatabase(f"127.0.0.1:{server.port}", "비밀 1234", remote.cache)
    other.ping()
    remote.ping()
    assert not other.changed() and not remote.changed()
    p = db.list_patients()[0]
    remote.update_patient(p["id"], note="x")
    assert not remote.changed()                              # its own change
    assert other.changed() and not other.changed()
    db.update_patient(p["id"], note="y")                     # made at the server itself
    assert other.changed() and remote.changed()
    other.close()


def test_derived_picture_and_upload(shared, tmp_path, demo_dir):
    db, server, remote, _, _ = shared
    p = db.list_patients()[0]
    row = remote.images_for_patient(p["id"])[0]
    n = len(db.images_for_patient(p["id"]))
    rgb = np.zeros((60, 80, 3), np.uint8)
    rgb[20:40, 30:50] = (200, 80, 40)
    service = share.RemoteImportService(remote, Settings())
    new_id = service.importer.add_derived(row, rgb, "몽타주 2장", suffix="몽타주", derived_from=[row["id"]],
                                          modality="montage", fov_deg=200.0, meta_json={"montage": {"a": 1}})
    made = db.get_image(new_id)
    assert made["modality"] == "montage" and made["note"] == "몽타주 2장" and made["patient_ref"] == p["id"]
    assert json.loads(made["meta_json"])["montage"] == {"a": 1}
    assert str(db.path.parent) in made["file_path"]          # stored in the server's library
    assert len(db.images_for_patient(p["id"])) == n + 1

    results = []
    service.on_result = results.append
    files = sorted(f for f in demo_dir.rglob("*") if f.is_file())
    total = db.revision()
    assert service.import_paths([str(files[-1])], force=True) == 1
    service.shutdown()
    assert results and results[0].status in ("imported", "duplicate")
    assert results[0].status == "duplicate" or db.revision() > total
    assert not list((share.config_dir() / "uploads").glob("*"))      # nothing is left behind


def test_import_review_and_the_patient_list_on_a_client(shared, tmp_path):
    """A connected viewer: 사진 가져오기 → 환자 정보 확인 reads the photos there and sends them to the
    server with the patient confirmed for each; the patient list's searches ask the server."""
    from PIL import Image

    from fundusview.models import PatientAssign

    db, server, remote, _, errors = shared
    # the patient list window: patients by name, patients photographed in a time
    p = db.list_patients()[0]
    assert [r["id"] for r in remote.patients_named(p["name"])] == [r["id"] for r in db.patients_named(p["name"])]
    assert remote.patients_examined("1900-01-01", "2999-12-31") == db.patients_examined("1900-01-01", "2999-12-31")
    assert isinstance(remote.patients_examined("2000-01-01", "2000-01-02"), set)

    folder = tmp_path / "new" / "77001_홍길동"
    folder.mkdir(parents=True)
    rgb = np.zeros((90, 120, 3), np.uint8)
    rgb[30:60, 40:80] = (180, 60, 30)
    Image.fromarray(rgb).save(folder / "20260401_OD.jpg")
    rgb[10:20, 10:20] = (20, 200, 20)
    Image.fromarray(rgb).save(tmp_path / "new" / "loose.jpg")
    (tmp_path / "new" / "empty.jpg").write_bytes(b"")
    known = db.images_for_patient(p["id"])[0]

    service = share.RemoteImportService(remote, Settings())
    results = []
    service.on_result = results.append
    items = service.preview_paths([str(folder), str(tmp_path / "new" / "loose.jpg"),
                                   str(tmp_path / "new" / "empty.jpg"), known["file_path"]])
    by_name = {i.path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]: i for i in items}
    assert by_name["20260401_OD.jpg"].status == "new" and by_name["20260401_OD.jpg"].meta.patient_id == "77001"
    assert by_name["20260401_OD.jpg"].meta.name == "홍길동"                  # the folder's name, read here
    assert by_name["loose.jpg"].status == "new" and by_name["empty.jpg"].status == "error"
    dup = next(i for i in items if i.status == "duplicate")
    assert dup.image_id == known["id"] and dup.patient_ref == p["id"]
    # imported as confirmed: the folder's photo as read, the loose one given to a patient by hand
    n = service.import_items([(by_name["20260401_OD.jpg"], None),
                              (by_name["loose.jpg"], PatientAssign("77002", "김철수"))])
    assert n == 2
    service.shutdown()
    assert sorted(r.status for r in results) == ["imported", "imported"]
    a, b = db.find_patient("77001"), db.find_patient("77002")
    assert a is not None and a["name"] == "홍길동" and len(db.images_for_patient(a["id"])) == 1
    assert b is not None and b["name"] == "김철수" and len(db.images_for_patient(b["id"])) == 1
    assert not list((share.config_dir() / "uploads").glob("*")) and not errors


def test_password_and_files_are_guarded(shared):
    db, server, remote, _, errors = shared
    wrong = share.RemoteDatabase(f"127.0.0.1:{server.port}", "틀린 암호", remote.cache, on_error=errors.append)
    with pytest.raises(share.ShareError) as e:
        wrong.ping()
    assert e.value.unauthorized
    assert wrong.list_patients() == [] and errors            # nothing without the password
    base = f"http://127.0.0.1:{server.port}"
    for path in ("/api/rev", "/api/file/1/file", "/api/file/1/view"):
        with pytest.raises(urllib.error.HTTPError) as he:
            urllib.request.urlopen(base + path)
        assert he.value.code == 401
    page = urllib.request.urlopen(base + "/").read().decode("utf-8")
    assert "접속 암호" in page                                # the browser page asks for it
    req = urllib.request.Request(base + "/api/login", json.dumps({"key": "비밀 1234"}).encode(), method="POST")
    cookie = urllib.request.urlopen(req).headers["Set-Cookie"].split(";")[0]
    head = {"Cookie": cookie}
    img = db.images_for_patient(db.list_patients()[0]["id"])[0]
    got = urllib.request.urlopen(urllib.request.Request(f"{base}/api/file/{img['id']}/view", headers=head)).read()
    assert got == open(img["display_path"] or img["file_path"], "rb").read()
    for bad in ("/api/file/999999/file", "/api/file/1/../../fundus.db", "/api/file/1/db"):
        with pytest.raises(urllib.error.HTTPError) as he:
            urllib.request.urlopen(urllib.request.Request(base + bad, headers=head))
        assert he.value.code == 404
    body = json.dumps({"method": "_exec", "args": ["DROP TABLE images"]}).encode()
    with pytest.raises(urllib.error.HTTPError) as he:
        urllib.request.urlopen(urllib.request.Request(base + "/api/db", body, head, method="POST"))
    assert he.value.code == 403
    assert db.count_patients() > 0
    wrong.close()


def test_server_away(tmp_path):
    errors = []
    remote = share.RemoteDatabase("127.0.0.1:9", "x", tmp_path / "cache", on_error=errors.append, timeout=1)
    assert remote.list_patients() == [] and remote.get_patient(1) is None and remote.count_unassigned() == 0
    remote.update_patient(1, name="a")
    assert any("저장되지 않았습니다" in e for e in errors)
    assert not remote.online and not remote.changed()


def test_normalize_url():
    assert share.normalize_url("192.168.0.10") == "http://192.168.0.10:8765"
    assert share.normalize_url(" http://pc-server:9000/ ") == "http://pc-server:9000"
    assert share.normalize_url("") == ""


def _spin(app, until, timeout=20.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_two_windows_share_one_library(tmp_path, demo_dir, import_and_wait):
    """The server's window and a connected viewer: the same patients and photos, an edit on either
    side is shown on the other, and a picture saved on the client lands in the server's library."""
    import os
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from fundusview.config import WatchFolder
    from fundusview.ui.dialogs import SettingsDialog
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0, auto_detect=False,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False,
                 share_mode="server", share_port=0)
    db = Database(tmp_path / "lib" / "fundus.db")
    server_win = MainWindow(s, db)
    client_win = None
    try:
        server_win.show()
        import_and_wait(app, server_win, [demo_dir])
        server_win._apply_share()
        assert server_win.share_server is not None and s.share_key           # a password was made
        assert str(server_win.share_server.port) in server_win.lbl_share.text() and server_win.lbl_share.isVisible()

        cs = Settings(share_mode="client", server_url=f"http://127.0.0.1:{server_win.share_server.port}",
                      share_key=s.share_key, auto_detect=False, library_dir=str(tmp_path / "unused"))
        remote = share.RemoteDatabase(cs.server_url, cs.share_key, tmp_path / "cache")
        remote.ping()
        client_win = MainWindow(cs, remote)
        client_win.show()
        client_win._apply_share()
        assert client_win.remote and "서버 연결" in client_win.lbl_watch.text() and not client_win.act_watch.isEnabled()
        # one patient list window on each computer, the same patients in both
        assert client_win.patient_list.table.rowCount() == server_win.patient_list.table.rowCount() == 7

        ref = db.find_patient("20260115001")["id"]
        client_win._select_patient_ref(ref)
        assert client_win.thumbs.count() == 2 and client_win.view2d.has_image()      # fetched and shown
        assert "김민수" in client_win.banner.text()
        assert not (tmp_path / "unused").exists()                                  # no library of its own

        # an edit on the client is stored on the server and shown in the server's window
        client_win.db.update_patient(ref, name="김민수 (수정)")
        table = server_win.patient_list.table
        _spin(app, lambda: any("김민수 (수정)" in (table.item(r, 1).text()) for r in range(table.rowCount())))
        # … and one made at the server reaches the client (asked for every few seconds)
        server_win._select_patient_ref(ref)
        iid = client_win.current["id"]
        db.update_image(iid, note="서버에서 쓴 메모")
        client_win._poll_share()
        _spin(app, lambda: client_win.current is not None and client_win.current["note"] == "서버에서 쓴 메모")

        # a picture saved on the client (편집 영상) is a new photo of the patient on the server
        n = len(db.images_for_patient(ref))
        client_win._save_view_record()
        assert len(db.images_for_patient(ref)) == n + 1 and client_win.thumbs.count() == n + 1
        _spin(app, lambda: server_win.thumbs.count() == n + 1)

        # the settings dialog shows the sharing tab's values and stores them
        dlg = SettingsDialog(cs, client_win)
        assert dlg.share_mode.currentData() == "client" and dlg.server_url.text() == cs.server_url
        dlg.server_url.setText("192.168.0.20")
        dlg.apply()
        assert cs.server_url == "http://192.168.0.20:8765"
    finally:
        if client_win is not None:
            client_win.close()
        server_win.close()
        db.close()
    assert server_win.share_server is None


def test_worklist_order_is_kept_on_the_server(shared):
    """워크리스트 on a connected viewer: the order is stored with the server's database."""
    db, server, remote, _, errors = shared
    order = {"patient_id": "W1", "name": "홍길동", "date": "2026-11-21", "accession": "ACC-1", "study_uid": "1.2.3"}
    remote.save_order(order)
    row = remote.order_for("W1", "2026-11-21")
    assert json.loads(row["data_json"]) == order and json.loads(db.order_for("W1", "2026-11-21")["data_json"]) == order
    assert remote.order_for("W1", "2026-11-22") is None and not errors
