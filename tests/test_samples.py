"""질환 샘플: sample photos of retinal diseases kept by disease (samples.py), and the window that sets the
patient's photo beside them (질환 샘플 → 질환 샘플과 비교, ui/sample_compare.py)."""
import os

import numpy as np
import pytest
from PIL import Image

from fundusview.samples import DEFAULT_DISEASES, FOLDER, SampleLibrary, folder_name


def _photo(path, color=(180, 90, 50), size=(120, 100)):
    rgb = np.zeros((size[1], size[0], 3), np.uint8)
    rgb[:] = color
    Image.fromarray(rgb).save(path)
    return path


def test_a_new_library_has_the_usual_diseases_and_keeps_them_in_the_library_folder(tmp_path):
    lib = SampleLibrary(tmp_path)
    assert lib.root == tmp_path / FOLDER
    assert lib.diseases() == list(DEFAULT_DISEASES) and "당뇨망막병증" in lib.diseases()
    assert all(lib.count(d) == 0 for d in lib.diseases())
    assert lib.add_disease("  미숙아   망막병증 ") == "미숙아 망막병증"
    assert lib.diseases()[-1] == "미숙아 망막병증"
    with pytest.raises(ValueError):
        lib.add_disease("미숙아 망막병증")                # (already there)
    with pytest.raises(ValueError):
        lib.add_disease("   ")
    # what a file system does not take is not in the folder's name
    assert folder_name('a/b:c*?') == "a_b_c__"
    # the order and the notes are kept for the next time
    again = SampleLibrary(tmp_path)
    assert again.diseases() == lib.diseases()


def test_photos_are_copied_in_under_names_of_their_own_with_notes(tmp_path):
    lib = SampleLibrary(tmp_path / "lib")
    src = _photo(tmp_path / "홍길동_12345_20260301_OD.jpg")
    p1 = lib.add_file("당뇨망막병증", src, note="증식성")
    p2 = lib.add_file("당뇨망막병증", _photo(tmp_path / "x.png", (10, 200, 10)))
    assert p1.parent == lib.root / "당뇨망막병증" and p1.name == "당뇨망막병증_001.jpg"   # nothing of the patient
    assert "홍길동" not in p1.name and "12345" not in p1.name
    assert p2.name == "당뇨망막병증_002.png" and src.exists()                          # copied, not moved
    assert lib.photos("당뇨망막병증") == [p1, p2] and lib.count("당뇨망막병증") == 2
    assert lib.note(p1) == "증식성" and lib.note(p2) == ""
    lib.set_note(p2, "  비증식성 ")
    assert SampleLibrary(tmp_path / "lib").note(p2) == "비증식성"
    with pytest.raises(ValueError):
        lib.add_file("당뇨망막병증", tmp_path / "notes.txt")
    # pixels as shown (a patient's photo taken as a sample)
    p3 = lib.add_rgb("새 질환", np.full((50, 60, 3), 99, np.uint8), "메모")
    assert "새 질환" in lib.diseases() and p3.name == "새 질환_001.jpg" and lib.note(p3) == "메모"
    # renamed: the folder and the notes go along; removed: the photo and its note
    lib.rename_disease("당뇨망막병증", "당뇨망막병증 (DR)")
    moved = lib.photos("당뇨망막병증 (DR)")
    assert len(moved) == 2 and lib.note(moved[0]) == "증식성" and not (lib.root / "당뇨망막병증").exists()
    lib.remove_photo(moved[0])
    assert lib.count("당뇨망막병증 (DR)") == 1 and lib.note(moved[0]) == ""
    lib.remove_disease("당뇨망막병증 (DR)")
    assert "당뇨망막병증 (DR)" not in lib.diseases() and not (lib.root / "당뇨망막병증 (DR)").exists()
    # a folder put there by hand is a disease too
    (lib.root / "포도막염").mkdir()
    _photo(lib.root / "포도막염" / "a.jpg")
    fresh = SampleLibrary(tmp_path / "lib")
    assert "포도막염" in fresh.diseases() and fresh.count("포도막염") == 1


@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import fundusview.samples as samples_mod

    # (the program's own samples are tested in test_disease_explain.py: here the library starts empty)
    monkeypatch.setattr(samples_mod, "BUILTIN_DIR", tmp_path / "no builtin samples")
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow
    from test_review import _library

    app = QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="")
    w = MainWindow(s, db)
    w.patient_list.select_delay = 0
    w.show()
    app.processEvents()
    yield app, w, db, refs, ids, tmp_path
    if w._sample_dlg is not None:
        w._sample_dlg.close()
    w.close()
    db.close()


def test_the_compare_window_sets_a_sample_beside_the_patients_photo(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    app, w, db, refs, ids, tmp_path = win
    w._select_patient_ref(refs["kim"])
    w._select_from_multi(ids["od3"])
    app.processEvents()
    assert w.act_samples.shortcut().toString() == "Ctrl+D"
    w.act_samples.trigger()                                   # 질환 샘플 → 질환 샘플과 비교
    dlg = w._sample_dlg
    app.processEvents()
    assert dlg.isVisible() and dlg.v_patient.has_image() and "OD" in dlg.lbl_patient.text()
    assert dlg.current_disease() == DEFAULT_DISEASES[0] and not dlg.v_sample.has_image()
    assert "샘플 사진이 없습니다" in dlg.lbl_sample.text()

    # register: files (as dropped or picked), shown at once with their number
    dlg.select_disease("당뇨망막병증")
    files = [str(_photo(tmp_path / f"s{k}.jpg", (40 * k, 80, 60), (200 + 40 * k, 160))) for k in range(3)]
    assert dlg.add_files(files) == 3
    assert dlg.strip.count() == 3 and dlg.v_sample.has_image() and dlg.strip.currentRow() == 2
    assert "당뇨망막병증  (3)" in [dlg.diseases.item(i).text() for i in range(dlg.diseases.count())]
    assert "3 / 3" in dlg.lbl_sample.text()
    dlg.b_prev.click()
    assert dlg.strip.currentRow() == 1 and "2 / 3" in dlg.lbl_sample.text()
    dlg.note.setText("비증식성 — 점상 출혈")
    dlg.note.editingFinished.emit()
    assert w.samples.note(dlg._sample) == "비증식성 — 점상 출혈" and "점상 출혈" in dlg.lbl_sample.text()

    # 함께 확대 · 이동: zoom one, the other shows the same part of itself
    dlg.resize(1400, 860)
    app.processEvents()
    v1, v2 = dlg.v_patient, dlg.v_sample
    h, wd = v1._rgb.shape[:2]
    from PySide6.QtCore import QRectF
    v1.zoom_to_rect(QRectF(wd * 0.25, h * 0.25, wd * 0.25, h * 0.25), animate=False)
    app.processEvents()
    a, b = dlg._shown(v1), dlg._shown(v2)
    assert b.center().x() == pytest.approx(a.center().x(), abs=0.05)
    assert b.center().y() == pytest.approx(a.center().y(), abs=0.05)
    assert b.width() < 0.6
    dlg.c_sync.setChecked(False)
    v1.fit()
    app.processEvents()
    assert dlg._shown(v2).width() < 0.6                       # (off: the other stays)

    # the photo on screen as a sample: as shown, black outside its circle, nothing of the patient
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("환자 사진에서", True)))
    dlg.b_take.click()
    assert dlg.strip.count() == 4
    saved = dlg._sample
    assert saved.name == "당뇨망막병증_004.jpg" and w.samples.note(saved) == "환자 사진에서"
    px = np.asarray(Image.open(saved))
    assert px[0, 0].max() < 20 and px[-1, -1].max() < 20      # corners (outside the circle): black

    # another photo on screen: the window follows
    w._select_from_multi(ids["os3"])
    app.processEvents()
    assert "OS" in dlg.lbl_patient.text()

    # removing a sample, and a disease with its photos (asked first)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dlg.b_remove.click()
    assert dlg.strip.count() == 3 and w.samples.count("당뇨망막병증") == 3
    dlg.b_del_disease.click()
    assert "당뇨망막병증" not in w.samples.diseases() and dlg.current_disease() != "당뇨망막병증"


def test_registering_the_photo_on_screen_from_the_menu(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    app, w, db, refs, ids, tmp_path = win
    w._select_patient_ref(refs["kim"])
    w._select_from_multi(ids["od3"])
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("황반원공", True)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("전층 황반원공", True)))
    w.register_sample()
    photos = w.samples.photos("황반원공")
    assert len(photos) == 1 and w.samples.note(photos[0]) == "전층 황반원공"
    assert "황반원공" in w.lbl_status.text()
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("새로운 질환", True)))
    w.register_sample()                                        # a name not there: a new disease
    assert w.samples.count("새로운 질환") == 1
