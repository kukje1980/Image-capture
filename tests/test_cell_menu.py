"""Right click on a photo of Simple · Multi: the cell is selected and its menu starts with what the
command toolbar does with the photos on screen — 3D · Montage · Glaucoma · Detail."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_right_click_on_a_cell_offers_3d_montage_glaucoma(tmp_path, demo_dir, import_and_wait, monkeypatch):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui.image_view import ImageView
    from fundusview.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_on_startup=False, auto_detect=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.show()
        import_and_wait(app, w, [demo_dir])
        w._select_patient_ref(db.find_patient("20260115001")["id"])       # one OD and one OS photo
        w.show_simple()
        app.processEvents()
        assert w._tab() == "multi" and len(w._picks) == 2
        cells = [c for c in w.multi.cells if c.image_id is not None]
        other = next(c for c in cells if c.image_id != w.current["id"])

        menus = []
        monkeypatch.setattr(ImageView, "_popup", lambda self, menu, gpos: menus.append(menu))   # (no waiting)
        other.view._context_menu(QPoint(0, 0), QPointF(5, 5))
        app.processEvents()
        menu = menus[-1]
        assert w.current["id"] == other.image_id and other.selected            # the right click selects it
        acts = {a.text(): a for a in menu.actions() if a.text()}
        texts = list(acts)
        assert texts[0] == "3D — 이 사진" and "3D — 화면의 사진 모두 (2장)" in texts
        assert acts["Montage — 화면의 사진 2장…"].isEnabled()
        assert "녹내장 분석…" in texts and "Detail — 크게 보기" in texts
        # one entry each (0.13.17): no "(② 사진과)" · "(다른 한 장과)" variants
        assert "스테레오 보기…" in texts and "시간별 비교…" in texts and not any("(다른" in t or "②" in t for t in texts)
        assert "화면에 맞춤" in texts                                           # the photo's own entries follow

        opened = []
        monkeypatch.setattr(w, "open_montage", lambda *a, **k: opened.append("montage"))
        monkeypatch.setattr(w, "open_glaucoma", lambda *a, **k: opened.append(("glaucoma", a)))
        other.view._context_menu(QPoint(0, 0), QPointF(5, 5))
        acts = {a.text(): a for a in menus[-1].actions() if a.text()}
        acts["Montage — 화면의 사진 2장…"].trigger()
        acts["녹내장 분석…"].trigger()                    # this photo (a same-eye pick comes along by itself)
        assert opened == ["montage", ("glaucoma", ())]

        acts["3D — 화면의 사진 모두 (2장)"].trigger()                            # both on 3D eyes
        app.processEvents()
        assert w._tab() == "3d2" and w.pair3d.image_ids == w._picks
        w._on_action("view3d")                                                 # [3D] again: back
        app.processEvents()
        assert w._tab() == "multi"
        acts["3D — 이 사진"].trigger()
        app.processEvents()
        assert w._tab() == "3d" and w.current["id"] == other.image_id
        w._on_action("view3d")
        app.processEvents()
        acts["Detail — 크게 보기"].trigger()
        app.processEvents()
        assert w._tab() == "all" and w.current["id"] == other.image_id

        # the big photo of Detail has no such entries (its toolbar is right there)
        w.view2d._context_menu(QPoint(0, 0), QPointF(5, 5))
        assert menus[-1].actions()[0].text().startswith("여기를 시신경 유두로")
        w.show_simple()
        app.processEvents()

        # the photo list's menu: 녹내장 분석… on every photo — one photo is enough (no ② photo needed), and
        # it is that photo that is analysed (an OD | OS pair on screen is not taken as a pair)
        shown = []
        opened.clear()
        cur, away = w.current["id"], next(i for i in w._picks if i != w.current["id"])
        monkeypatch.setattr(w, "open_glaucoma", lambda *a, **k: opened.append(k))
        for iid in (cur, away):
            menu = w._build_photo_menu(iid)
            shown.append([x.text() for x in menu.actions()])
            next(x for x in menu.actions() if x.text() == "녹내장 분석…").trigger()
            assert shown[-1].count("녹내장 분석…") == 1 and not any("(" in t and "사진과" in t for t in shown[-1])
        assert "스테레오 보기…" in shown[-1] and "스테레오 보기…" not in shown[-2]     # (that needs two)
        assert opened == [{"first_id": cur}, {"first_id": away}]
        dlg, why = w._build_glaucoma(first_id=away)       # the window itself: built from that one photo
        assert dlg is not None and why == ""
        dlg.deleteLater()
    finally:
        w.close()
