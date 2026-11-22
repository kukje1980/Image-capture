"""DICOM in the windows: 설정 → DICOM, the 워크리스트 window opening a patient, and DICOM 전송 from the
main window to a PACS of this test's own."""
import json
import os
import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pynetdicom")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fundusview import dicomnet  # noqa: E402
from fundusview.dicomnet import Order  # noqa: E402
from test_dicomnet import pacs  # noqa: E402,F401  (the PACS fixture)


def _wait(app, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def window(tmp_path, demo_dir, import_and_wait):
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), inbox_dir=str(tmp_path / "inbox"), auto_detect=False,
                 watch_on_startup=False, stable_seconds=0.0)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    w.show()
    import_and_wait(app, w, sorted(p for p in demo_dir.rglob("*") if p.is_file()))
    yield app, w, db
    w.close()
    db.close()


def _a_patient(db):
    """A patient with photos, and those photos."""
    for p in db.list_patients():
        rows = db.images_for_patient(p["id"])
        if len(rows) >= 2 and rows[0]["exam_date"]:
            return p, rows
    raise AssertionError("no demo patient with photos")


def test_settings_tab_keeps_the_servers_and_tests_the_connection(window, pacs):
    from fundusview.ui.dialogs import SettingsDialog

    app, w, db = window
    p = pacs()
    dlg = SettingsDialog(w.settings, w)
    dlg.dicom_ae.setText("eyeroom1")
    dlg.pacs_host.setText("127.0.0.1")
    dlg.pacs_port.setValue(p.port)
    dlg.pacs_ae.setText("TESTPACS")
    dlg.mwl_host.setText("127.0.0.1")
    dlg.mwl_port.setValue(p.port)
    dlg.mwl_modality.setText("xc")
    dlg.dicom_sop.setCurrentIndex(dlg.dicom_sop.findData("sc"))
    dlg._test_dicom(dlg.pacs_host, dlg.pacs_port, dlg.pacs_ae, "PACS")
    assert "연결되었습니다" in dlg.dicom_info.text()
    dlg.mwl_host.clear()
    dlg._test_dicom(dlg.mwl_host, dlg.mwl_port, dlg.mwl_ae, "워크리스트 서버")
    assert "서버 주소를 입력" in dlg.dicom_info.text()
    dlg.mwl_host.setText("127.0.0.1")
    dlg.apply()
    s = w.settings
    assert (s.dicom_ae, s.pacs_host, s.pacs_port, s.pacs_ae) == ("EYEROOM1", "127.0.0.1", p.port, "TESTPACS")
    assert (s.mwl_host, s.mwl_port, s.mwl_modality, s.dicom_sop) == ("127.0.0.1", p.port, "XC", "sc")
    dlg.deleteLater()


def test_worklist_opens_a_new_patient_and_keeps_the_order(window):
    app, w, db = window
    known, rows = _a_patient(db)
    day = rows[0]["exam_date"]
    orders = [Order(patient_id="W900001", name="새환자", pn="Sae^Hwanja=새^환자", birth_date="1970-01-02", sex="F",
                    date=day, time="09:10:00", accession="ACC-1", study_uid="1.2.3.1", description="안저 촬영"),
              Order(patient_id=known["patient_id"], name=known["name"] or "", date=day, time="09:30:00",
                    accession="ACC-2", study_uid="1.2.3.2")]
    w.settings.mwl_host, w.settings.mwl_port = "worklist.test", 104
    dlg = w.open_worklist()
    asked = []
    dlg.find = lambda s, d: (asked.append(d), orders)[1]
    dlg.refresh()
    assert _wait(app, lambda: dlg.table.rowCount() == 2)
    assert dlg.table.item(0, 1).text() == "W900001" and dlg.table.item(0, 8).text() == "새 환자"
    assert dlg.table.item(1, 8).text().startswith("등록된 환자 · 이 날 사진")
    assert asked[-1] == dlg.iso_day()
    dlg.search.setText("새환")                       # the search box narrows what was read
    assert dlg.table.rowCount() == 1 and dlg.lbl_count.text() == "1 / 2건"
    dlg.open_selected()
    app.processEvents()
    new = db.find_patient("W900001")
    assert new is not None and (new["name"], new["birth_date"], new["sex"]) == ("새환자", "1970-01-02", "F")
    assert w._patient_ref == new["id"] and not dlg.isVisible()
    assert "워크리스트 환자" in w.lbl_status.text()
    assert dicomnet.order_of(db.order_for("W900001", day)).accession == "ACC-1"
    # the patient with photos: opened on them
    dlg = w.open_worklist()
    dlg.find = lambda s, d: orders
    dlg.search.clear()
    dlg.refresh()
    assert _wait(app, lambda: dlg.table.rowCount() == 2 and not dlg._busy)
    dlg.table.selectRow(1)
    dlg.open_selected()
    app.processEvents()
    assert w._patient_ref == known["id"] and w.current is not None


def test_worklist_says_when_no_server_is_set_or_it_fails(window):
    app, w, db = window
    dlg = w.open_worklist()
    app.processEvents()
    assert "설정되지 않았습니다" in dlg.lbl_info.text() and not dlg.btn_open.isEnabled()
    w.settings.mwl_host = "worklist.test"

    def fail(s, d):
        raise dicomnet.DicomError("서버가 연결을 거부했습니다")
    dlg.find = fail
    dlg.refresh()
    assert _wait(app, lambda: "거부" in dlg.lbl_info.text())
    assert dlg.table.rowCount() == 0 and dlg.btn_refresh.isEnabled()
    dlg.hide()


def test_send_the_exam_to_the_pacs_under_its_order(window, pacs):
    app, w, db = window
    p = pacs()
    for k, v in vars(p.settings()).items():
        if k.startswith(("pacs_", "dicom_")):
            setattr(w.settings, k, v)
    patient, rows = _a_patient(db)
    day = rows[0]["exam_date"]
    db.save_order(Order(patient_id=patient["patient_id"], name=patient["name"] or "", date=day,
                        accession="ACC-77", study_uid="1.2.3.77").as_dict())
    w.open_patient(patient["id"])
    app.processEvents()
    of_day = [r for r in rows if r["exam_date"] == w.current["exam_date"]]
    dlg = w.dicom_send("exam", run=False)
    assert dlg.table.rowCount() == len(of_day) and dlg.btn_send.isEnabled()
    if w.current["exam_date"] == day:
        assert dlg.table.item(0, 3).text() == "ACC-77"
    dlg.start()
    assert _wait(app, lambda: not dlg.sending and dlg.btn_send.text() == "다시 전송", timeout=60)
    assert all(r.ok for r in dlg.results.values()), [r.message for r in dlg.results.values()]
    assert len(p.stored) == len(of_day) and "전송했습니다" in dlg.lbl_head.text()
    assert {ds.PatientID for ds in p.stored} == {patient["patient_id"]}
    if w.current["exam_date"] == day:
        assert {ds.AccessionNumber for ds in p.stored} == {"ACC-77"}
    sent = json.loads(db.get_image(of_day[0]["id"])["meta_json"])["dicom_sent"]
    assert sent["to"] == "TESTPACS@127.0.0.1:%d" % p.port and sent["sop_uid"]
    assert not dlg.btn_send.isEnabled()              # nothing left to send again
    dlg.done(0)
    again = w.dicom_send("one", of_day[0]["id"], run=False)
    assert "전송함" in again.table.item(0, 4).text()
    again.done(0)


def test_send_window_without_a_pacs_and_unassigned_photos(window, tmp_path):
    app, w, db = window
    patient, rows = _a_patient(db)
    db.update_image(rows[0]["id"], patient_ref=None)          # a photo of nobody
    from fundusview.ui.dicom_dialogs import DicomSendDialog

    dlg = DicomSendDialog(db, w.settings, [db.get_image(r["id"]) for r in rows[:2]], w)
    assert dlg.table.rowCount() == 1 and dlg.skipped == 1
    assert "설정되지 않았습니다" in dlg.lbl_head.text() and not dlg.btn_send.isEnabled()
    assert "미분류" in dlg.lbl_note.text()
    dlg.done(0)
    # a PACS that is not there: said in the window, nothing marked as sent
    w.settings.pacs_host, w.settings.pacs_port = "127.0.0.1", 1
    dlg = DicomSendDialog(db, w.settings, [db.get_image(rows[1]["id"])], w)
    dlg.start()
    assert _wait(app, lambda: not dlg.sending and "전송하지 못했습니다" in dlg.lbl_head.text(), timeout=40)
    assert "dicom_sent" not in json.loads(db.get_image(rows[1]["id"])["meta_json"] or "{}")
    dlg.done(0)


def test_photo_saved_as_a_dicom_file(window, tmp_path):
    import pydicom

    app, w, db = window
    patient, rows = _a_patient(db)
    w.open_patient(patient["id"])
    app.processEvents()
    dest = tmp_path / "out.dcm"
    w.save_dicom_file(str(dest))
    ds = pydicom.dcmread(dest)
    assert ds.PatientID == patient["patient_id"] and "저장했습니다" in w.lbl_status.text()
