"""설정 → 일반 → 환자를 열면: 16장 보기 (the VK-2 way, the default) — the patient's photos 16 on one screen
(newest first); a click picks a photo (numbered), [Multi] shows the picked ones only on the multi view, [Multi]
again goes back to the 16, a double click opens one big — or Simple, the newest OD | OS on the multi view."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PID = "D0002000"
N_PHOTOS = 18                                 # more than one page of 16


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def many_dir(tmp_path_factory):
    """One patient with 18 photos (VK-2 export names: both eyes, three exams)."""
    import numpy as np
    from PIL import Image

    from fundusview.demo import synth_fundus

    root = tmp_path_factory.mktemp("many") / "VK2_Export"
    root.mkdir()
    for k in range(N_PHOTOS):
        day = ("20260310", "20251104", "20250512")[k // 6]
        i = k % 6
        eye = "R" if i % 2 == 0 else "L"
        rgb = synth_fundus(eye="OD" if eye == "R" else "OS", fov_deg=45, fov_type="external",
                           projection="perspective", size=(160, 160), seed=200 + k)
        Image.fromarray(np.ascontiguousarray(rgb[20:140])).save(
            root / f"{PID}_{day}_{10 + i:02d}0000_{eye}_FUNDUS (COLOR)_{i + 1}.jpg", quality=85)
    return root


@pytest.fixture
def window(app, tmp_path, many_dir, import_and_wait):
    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(many_dir))], watch_on_startup=False,
                 open_view="grid", ui_version=MainWindow.UI_VERSION)      # (환자를 열면: 16장 보기)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    w.resize(1600, 960)
    w.show()
    import_and_wait(app, w, [many_dir])
    w.show_patient_list()
    try:
        yield w
    finally:
        w.close()
        w.deleteLater()
        app.processEvents()


def _open(app, w):
    pid = w.db.find_patient(PID)["id"]
    w._pick_patient(pid)
    w.open_patient(pid)
    app.processEvents()
    return pid


def _click(app, w, iid, double=False, ctrl=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    rect = w.grid.photo_rect(iid)
    assert rect is not None, "the photo is not on the page shown"
    mod = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    if double:          # as a mouse does it: the first click, then the double click
        QTest.mouseClick(w.grid, Qt.MouseButton.LeftButton, mod, rect.center())
        QTest.mouseDClick(w.grid, Qt.MouseButton.LeftButton, mod, rect.center())
    else:
        QTest.mouseClick(w.grid, Qt.MouseButton.LeftButton, mod, rect.center())
    app.processEvents()


def test_setting_is_saved(tmp_path):
    from fundusview.config import Settings

    assert Settings().open_view == "odos"                  # Simple, unless chosen
    s = Settings(open_view="grid")
    s.save(tmp_path / "settings.json")
    assert Settings.load(tmp_path / "settings.json").open_view == "grid"


def test_simple_way_opens_on_the_newest_od_and_os(app, window):
    w = window
    w.settings.open_view = "odos"
    pid = _open(app, w)
    rows = w.db.images_for_patient(pid)
    assert w.patient_list.isHidden() and w._tab() == "multi"
    assert [w.db.get_image(i)["laterality"] for i in w.picks()] == ["OD", "OS"]
    assert all(w.db.get_image(i)["exam_date"] == rows[0]["exam_date"] for i in w.picks())
    assert w.acts["view:simple"].isChecked() and not w.acts["view:multi"].isChecked()
    assert w.thumbs.isVisible() and not w.grid_bar.isVisible()
    # [Multi] there (nothing picked by hand): 16장 보기, Multi off
    w.tb_cmd.widgetForAction(w.acts["view:multi"]).click()
    assert w._tab() == "grid" and not w.acts["view:multi"].isChecked() and w.grid_bar.isVisible()


def test_default_16_photos_pick_multi_and_back(app, window):
    from PySide6.QtCore import Qt

    w = window
    assert w.settings.open_view == "grid"                   # (chosen in 설정 → 일반 → 환자를 열면)
    pid = _open(app, w)
    assert w.patient_list.isHidden() and w._tab() == "grid" and w.picks() == []
    assert not w.acts["view:multi"].isChecked() and not w.acts["view:simple"].isChecked()
    assert not w.lbl_grid_picks.isVisible() and not w.btn_grid_clear.isVisible()
    # [Multi] with nothing picked: pick first — the 16 stay
    w.tb_cmd.widgetForAction(w.acts["view:multi"]).click()
    assert w._tab() == "grid" and not w.acts["view:multi"].isChecked() and w.lbl_status.text() == w.PICK_FIRST_HINT

    # 16 photos on one screen: the photos of the photo list, newest first (the list is by eye: OD row · OS row)
    rows = w.db.images_for_patient(pid)
    strip = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.thumbs.count())]
    order = [p.image_id for p in w.grid.items()]
    assert order == [r["id"] for r in rows] and sorted(order) == sorted(i for i, _eye, _day in w._listed)
    assert set(strip) < set(order) and len(strip) == 6      # (the photo list: one exam's bookmark)
    assert len(order) == N_PHOTOS and w.grid.pages() == 2
    assert all(p.eye in ("OD", "OS") for p in w.grid.items())
    # the grid is the photo list here: the strip's place shows its pages
    assert not w.thumbs.isVisible() and w.grid_bar.isVisible()
    cur = w.current["id"]
    assert cur in w.grid.visible_ids() and w.grid.page() == order.index(cur) // 16
    w.grid.set_page(0)
    assert w.grid.visible_ids() == order[:16] and "1–16" in w.lbl_grid_page.text()
    assert w.btn_grid_next.isEnabled() and not w.btn_grid_prev.isEnabled()

    # click = pick (numbered), again = out; picks are the strip's picks
    a, b, c = order[0], order[3], order[5]
    for iid in (a, b, c):
        _click(app, w, iid)
    assert w.picks() == [a, b, c] and w.grid._picks == {a: 1, b: 2, c: 3}
    _click(app, w, b)
    assert w.picks() == [a, c]
    _click(app, w, b)
    assert w.picks() == [a, c, b]
    assert w._tab() == "grid"                               # picking stays on the 16

    # [Multi]: the picked photos, and only those, one cell each — Multi lit
    assert w.lbl_grid_picks.isVisible() and w.lbl_grid_picks.text().startswith("3장 선택")
    w.tb_cmd.widgetForAction(w.acts["view:multi"]).click()
    app.processEvents()
    assert w._tab() == "multi" and w.multi.count == 4 and w.lbl_picks.text() == "3장 고정"
    assert w.acts["view:multi"].isChecked() and not w.acts["view:simple"].isChecked()
    shown = [cell.image_id for cell in w.multi.cells if cell.isVisible() and cell.image_id is not None]
    assert shown == [a, c, b]
    # [Multi] again: back to the 16, the picks still there (Ctrl+2 · 보기 → Multi the same)
    w.tb_cmd.widgetForAction(w.acts["view:multi"]).click()
    app.processEvents()
    assert w._tab() == "grid" and w.picks() == [a, c, b] and w.grid_bar.isVisible()
    assert not w.acts["view:multi"].isChecked()
    w.view_acts["multi"].trigger()
    assert w._tab() == "multi" and w.acts["view:multi"].isChecked()
    w.view_acts["multi"].trigger()
    assert w._tab() == "grid" and w.picks() == [a, c, b]

    # a double click opens the photo big in 모두 보기 (and does not pick it)
    w.grid.set_page(0)
    d = order[7]
    _click(app, w, d, double=True)
    assert w._tab() == "all" and w.current["id"] == d and d not in w.picks()
    assert w.thumbs.isVisible() and not w.grid_bar.isVisible()
    w._go("grid")
    assert w.grid.page() == 0 and w.grid._current == d

    # Ctrl+click: the second photo (②) next to the one shown
    _click(app, w, order[9], ctrl=True)
    assert w.compare is not None and w.compare["id"] == order[9] and w.grid._second == order[9]
    assert order[9] not in w.picks()

    # the second page: the wheel and the page buttons; the page follows the photo shown (이전 / 다음)
    w.btn_grid_next.click()
    assert w.grid.page() == 1 and w.grid.visible_ids() == order[16:]
    assert "17–18" in w.lbl_grid_page.text() and not w.btn_grid_next.isEnabled()
    w.btn_grid_prev.click()
    assert w.grid.page() == 0
    strip = [i for i, _eye, _day in w._listed]              # (every photo, by eye — the list's order)
    w._select_from_multi(order[15])
    k = strip.index(order[15])
    w._step(1)                                              # PageDown: the next photo of the photo list
    assert w.current["id"] == strip[k + 1] and w.grid.page() == order.index(strip[k + 1]) // 16

    # the filters of the menu bar filter the 16 too
    w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
    app.processEvents()
    assert [p.eye for p in w.grid.items()] == ["OD"] * (N_PHOTOS // 2) and w.grid.pages() == 1
    w.f_eye.setCurrentIndex(0)


def test_switching_the_way_in_settings(app, window):
    from fundusview.ui.dialogs import SettingsDialog

    w = window
    _open(app, w)
    assert w._tab() == "grid"
    dlg = SettingsDialog(w.settings, w)
    assert [dlg.open_view.itemData(k) for k in range(dlg.open_view.count())] == ["odos", "grid"]
    assert dlg.open_view.currentData() == "grid"
    assert dlg.open_view.itemText(0).startswith("Simple") and dlg.open_view.itemText(1).startswith("16장 보기")
    i = dlg.open_view.findData("odos")
    dlg.open_view.setCurrentIndex(i)
    dlg.apply()
    assert w.settings.open_view == "odos"
    _open(app, w)                                          # a patient opens on Simple now
    assert w._tab() == "multi" and len(w.picks()) == 2 and w.acts["view:simple"].isChecked()
    w.settings.open_view = "grid"                          # back: on 16장 보기 again
    _open(app, w)
    assert w._tab() == "grid" and w.picks() == [] and not w.acts["view:multi"].isChecked()
    # an older settings file's "overview" is 16장 보기
    w.settings.open_view = "overview"
    assert w._grid_mode()
    assert SettingsDialog(w.settings, w).open_view.currentData() == "grid"
