"""질환 샘플: the program's own sample photos (samples.py, ``fundusview/sample_photos``) and the 환자 설명
그림 — each disease explained stage by stage with drawn pictures (diseases.py, disease_art.py,
ui/disease_view.py) on the 질환 샘플 window."""
import json
import os

import numpy as np
import pytest
from PIL import Image

from fundusview import diseases as D
from fundusview.samples import BUILTIN_DIR, BUILTIN_INDEX, DEFAULT_DISEASES, SampleLibrary

FREE = ("CC0", "퍼블릭 도메인", "CC BY 2.0", "CC BY 3.0", "CC BY 4.0", "CC BY-SA 2.0", "CC BY-SA 3.0", "CC BY-SA 4.0")


def _builtin(folder, n=2):
    folder.mkdir(parents=True)
    photos = []
    for k in range(n):
        rgb = np.full((90, 120, 3), (60 + 40 * k, 90, 40), np.uint8)
        Image.fromarray(rgb).save(folder / f"src_{k}.jpg")
        photos.append({"disease": "당뇨망막병증" if k == 0 else "망막색소변성", "file": f"src_{k}.jpg",
                       "note": f"설명 {k}", "credit": f"작가 {k} · CC BY 4.0 · Wikimedia Commons"})
    photos.append({"disease": "황반원공", "file": "missing.jpg", "note": "", "credit": ""})   # (not there: skipped)
    (folder / BUILTIN_INDEX).write_text(json.dumps({"version": 1, "photos": photos}, ensure_ascii=False), "utf-8")
    return folder


def test_the_programs_samples_go_in_once_with_their_credits(tmp_path):
    src = _builtin(tmp_path / "builtin")
    lib = SampleLibrary(tmp_path / "lib")
    assert len(SampleLibrary.builtin_list(src)) == 2
    assert lib.install_builtin(src) == 2
    p = lib.photos("당뇨망막병증")[0]
    assert p.name == "당뇨망막병증_001.jpg" and lib.note(p) == "설명 0" and "CC BY 4.0" in lib.credit(p)
    assert lib.install_builtin(src) == 0                     # once only
    lib.remove_photo(p)                                      # deleted: not brought back by itself …
    assert lib.credit(p) == "" and SampleLibrary(tmp_path / "lib").install_builtin(src) == 0
    lib = SampleLibrary(tmp_path / "lib")
    assert lib.restore_builtin(src) == 1 and lib.count("당뇨망막병증") == 1   # … but when asked
    assert lib.restore_builtin(src) == 0
    # renamed: the credits go along
    lib.rename_disease("망막색소변성", "망막색소변성 (RP)")
    q = lib.photos("망막색소변성 (RP)")[0]
    assert "작가 1" in lib.credit(q)
    assert SampleLibrary(tmp_path / "lib").restore_builtin(src) == 0


def test_the_bundled_samples_are_openly_licensed_photos_of_the_diseases():
    items = SampleLibrary.builtin_list()
    data = json.loads((BUILTIN_DIR / BUILTIN_INDEX).read_text("utf-8"))
    assert len(items) == len(data["photos"]) >= 20            # every listed file is there
    names = {it["file"] for it in items}
    assert names == {p.name for p in BUILTIN_DIR.iterdir() if p.suffix.lower() in (".jpg", ".png")}
    for it in items:
        assert it["disease"] in DEFAULT_DISEASES, it
        assert any(lic in it["credit"] for lic in FREE), it      # author · licence · source
        assert it["source"].startswith("https://commons.wikimedia.org/wiki/File:"), it
        with Image.open(BUILTIN_DIR / it["file"]) as im:
            assert max(im.size) <= 1400 and min(im.size) >= 300
        if "oct" in it["file"]:                                  # not a fundus photo: the note says so
            assert it["note"].startswith("OCT 단면 (안저 사진 아님"), it
    covered = {it["disease"] for it in items}
    assert len(covered) >= 11
    assert (BUILTIN_DIR / "CREDITS.md").is_file()


def test_every_disease_of_the_library_has_an_explanation_at_every_stage():
    assert [d.name for d in D.DISEASES] == list(DEFAULT_DISEASES)
    assert D.find("당뇨망막병증 (DR)").name == "당뇨망막병증" and D.find("CSC") is D.BY_NAME["중심장액맥락망막병증"]
    assert D.find("포도막염") is None and D.find(None) is None
    for d in D.DISEASES:
        assert d.about and d.symptoms and d.care and d.stages and all(s.name and s.text for s in d.stages)
        for k in range(len(d.stages)):
            p = D.picture(d.name, k)
            assert p.fundus.shape == (640, 640, 3) and p.section.shape == (250, 640, 3)
            assert p.sight.ndim == 3 and p.sight.dtype == np.uint8
            assert p.fundus_marks, (d.name, k)
            for m in p.fundus_marks:
                assert 0 <= m.x <= 640 and 0 <= m.y <= 640, (d.name, k, m)
            for m in p.section_marks:
                assert 0 <= m.x <= 640 and 0 <= m.y <= 250, (d.name, k, m)
            assert (p.amsler is not None) == (k in d.amsler)
            assert (p.inset is not None) == (d.name in ("녹내장 (시신경 유두)", "시신경 유두부종"))
    # the stages are different pictures; the same stage is the same picture (fixed seeds)
    a, b = D.picture("당뇨망막병증", 0), D.picture("당뇨망막병증", 3)
    assert (np.abs(a.fundus.astype(int) - b.fundus.astype(int)).max(axis=2) > 40).mean() > 0.01
    D.picture.cache_clear()
    assert np.array_equal(D.picture("당뇨망막병증", 0).fundus, a.fundus)
    # glaucoma keeps the stages and the visual field of the glaucoma window
    from fundusview import glaucoma as G
    g = D.BY_NAME["녹내장 (시신경 유두)"]
    assert [s.name for s in g.stages] == list(G.STAGES)
    assert np.array_equal(D.picture(g.name, 3).sight, G.field_simulation(3, 600, G.sample_scene(600)))


def test_every_disease_has_its_mechanism_drawn_step_by_step():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from fundusview.ui import mechanism_view as MV

    QApplication.instance() or QApplication([])
    assert set(D.MECHANISMS) == set(D.BY_NAME)
    kinds = {"vessel", "eye", "nerve", "section", "cells"}
    for d in D.DISEASES:
        steps = D.MECHANISMS[d.name]
        assert 3 <= len(steps) <= 4, d.name
        for st in steps:
            assert st.title and st.text and st.art.split(":")[0] in kinds, (d.name, st)
        rgb = MV.compose_mechanism(d)
        assert rgb.shape[1] == 1600 and 560 < rgb.shape[0] < 900
    # every drawing draws something (not the empty box) and they differ from one another
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from fundusview.ui.image_view import from_qimage
    seen = {}
    for art in sorted({st.art for v in D.MECHANISMS.values() for st in v}):
        img = QImage(360, 270, QImage.Format.Format_RGB888)
        img.fill(QColor(0, 0, 0))
        p = QPainter(img)
        MV.draw_art(p, QRectF(0, 0, 360, 270), art)
        p.end()
        a = from_qimage(img)
        assert a.std() > 20, art
        seen[art] = a
    assert not np.array_equal(seen["vessel:sugar"], seen["vessel:leak"])
    assert not np.array_equal(seen["nerve:healthy"], seen["nerve:lost"])


def test_what_the_patient_sees():
    from fundusview import disease_art as A

    scene = np.full((200, 300, 3), 200, np.uint8)
    assert np.array_equal(A.vision(scene, A.Sight()), scene)
    dark = A.vision(scene, A.Sight(center_dark=1.0, center_r=0.15))
    assert dark[100, 150].max() < 60 and dark[10, 10].min() > 190             # the middle, not the edge
    tunnel = A.vision(scene, A.Sight(tunnel=0.3))
    assert tunnel[100, 150].min() > 190 and tunnel[5, 5].max() < 60
    curtain = A.vision(scene, A.Sight(curtain=(225, 0.7, 1.0)))             # from the lower left
    assert curtain[195, 5].max() < 60 and curtain[5, 295].min() > 190
    grid = A.amsler(A.Sight(warp=1.0))
    assert grid.shape == (300, 300, 3) and not np.array_equal(grid, A.amsler_grid(300))


@pytest.fixture
def win(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import fundusview.samples as samples_mod
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow
    from test_review import _library

    monkeypatch.setattr(samples_mod, "BUILTIN_DIR", _builtin(tmp_path / "builtin"))
    app = QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False, last_patient="")
    w = MainWindow(s, db)
    w.patient_list.select_delay = 0
    w.show()
    app.processEvents()
    yield app, w, tmp_path
    if w._sample_dlg is not None:
        w._sample_dlg.close()
    w.close()
    db.close()


def test_the_sample_window_explains_the_chosen_disease(win, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    app, w, tmp_path = win
    # the program's samples are in the library the first time, with where they come from
    assert w.samples.count("당뇨망막병증") == 1 and w.samples.count("망막색소변성") == 1
    assert w.act_explain.shortcut().toString() == "Ctrl+Shift+D"
    dlg = w.open_samples()
    app.processEvents()
    assert dlg.mode_key() == "compare"
    dlg.select_disease("당뇨망막병증")
    assert "출처: 작가 0" in dlg.lbl_sample.text() and "설명 0" in dlg.lbl_sample.text()

    # 환자 설명 그림: the chosen disease, stage by stage
    w.act_explain.trigger()
    app.processEvents()
    ex = dlg.explain
    assert dlg.mode_key() == "explain" and ex.disease.name == "당뇨망막병증"
    assert ex.stages.count() == 5 and ex.stage == 0 and ex.picture() is not None
    first = ex.picture()
    assert first.shape[1] == 1600 and ex.lbl_about.text() and "미세혈관류" in ex.lbl_stage.text()
    ex.stages.setCurrentRow(4)                                  # 당뇨황반부종
    app.processEvents()
    assert ex.stage == 4 and "황반" in ex.lbl_stage.text() and not np.array_equal(first, ex.picture())
    assert ex.note() == "당뇨망막병증 — 당뇨황반부종 (설명용 모형)"
    # another disease on the left: the page follows
    dlg.select_disease("시신경 유두부종")
    app.processEvents()
    assert ex.disease.name == "시신경 유두부종" and ex.stage == 0 and ex.stages.count() == 3
    dlg.select_disease("정상 안저")
    assert not ex.card_stages.isVisible() or ex.stages.count() == 1

    # 기전: how the disease comes about, step by step (the switch above the words)
    dlg.select_disease("황반원공")
    stage_pic = ex.picture()
    ex.seg_mech.click()
    app.processEvents()
    assert ex.kind == "mechanism" and not ex.card_stages.isVisible() and not ex.card_stage.isVisible()
    mech = ex.picture()
    assert mech.shape[1] == 1600 and mech.shape != stage_pic.shape or not np.array_equal(mech, stage_pic)
    assert ex.note() == "황반원공 — 기전 (설명용 그림)"
    dlg.select_disease("망막박리")                               # another disease: still its 기전
    app.processEvents()
    assert ex.kind == "mechanism" and ex.disease.name == "망막박리" and not np.array_equal(ex.picture(), mech)
    out2 = tmp_path / "기전.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out2), "")))
    ex.b_save.click()
    assert out2.is_file()
    ex.seg_stage.click()
    app.processEvents()
    assert ex.kind == "stage" and ex.stages.count() == 3 and "망막박리" in ex.note()
    dlg.select_disease("정상 안저")

    # save · copy (never into the patient's record: there is no such button here)
    out = tmp_path / "설명.jpg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    ex.b_save.click()
    assert out.is_file() and Image.open(out).size[0] == 1600 and "저장했습니다" in ex.status.text()
    ex.b_copy.click()
    assert not QApplication.clipboard().image().isNull()

    # a disease of the user's own without a picture: says so
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", staticmethod(lambda *a, **k: ("포도막염", True)))
    dlg._add_disease()
    assert dlg.current_disease() == "포도막염"
    assert ex.disease is None and ex.lbl_none.isVisible() and "포도막염" in ex.lbl_none.text()
    assert not ex.b_save.isEnabled()

    # back to the comparison; the program's deleted samples come back when asked
    dlg.set_mode("compare")
    assert dlg.mode_key() == "compare"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dlg.select_disease("망막색소변성")
    dlg.b_remove.click()
    assert w.samples.count("망막색소변성") == 0
    w.restore_builtin_samples()
    assert w.samples.count("망막색소변성") == 1 and "1장" in w.lbl_status.text()
