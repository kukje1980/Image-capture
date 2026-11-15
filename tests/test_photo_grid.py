"""설정 → 일반 → 환자를 열면: 모두 보기 (the default) or the VK-2 way — 16장 보기, the patient's
photos 16 on one screen; a click picks a photo (numbered), [멀티] shows the picked ones in the
multi view, a double click opens one big, and [16장] goes back to the 16."""
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
                 watch_folders=[WatchFolder(path=str(many_dir))], watch_on_startup=False)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    w.resize(1600, 960)
    w.show()
    import_and_wait(app, w, [many_dir])
    w.show_page("patients")
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

    assert Settings().open_view == "overview"              # the screen as before, unless chosen
    s = Settings(open_view="grid")
    s.save(tmp_path / "settings.json")
    assert Settings.load(tmp_path / "settings.json").open_view == "grid"


def test_default_opens_on_overview(app, window):
    w = window
    _open(app, w)
    assert w.page() == "work" and w._tab() == "all"
    assert w.view_buttons["grid"].isHidden() and not w.view_acts["grid"].isVisible()
    assert w.thumbs.isVisible() and not w.grid_bar.isVisible()
    w._go("grid")                                            # (Ctrl+4 does nothing in this way)
    assert w._tab() == "all"


def test_vk2_way_grid_pick_multi_and_back(app, window):
    from PySide6.QtCore import Qt

    w = window
    w.settings.open_view = "grid"
    w._apply_open_view()
    pid = _open(app, w)
    assert w.page() == "work" and w._tab() == "grid"
    assert w.view_buttons["grid"].isVisible() and w.view_buttons["grid"].isChecked()
    assert w.view_acts["grid"].isVisible()

    # 16 photos on one screen, the same photos in the same order as the photo list (newest first)
    rows = w.db.images_for_patient(pid)
    strip = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.thumbs.count())]
    assert [p.image_id for p in w.grid.items()] == strip == [r["id"] for r in rows]
    assert len(strip) == N_PHOTOS and w.grid.pages() == 2
    assert all(p.eye in ("OD", "OS") for p in w.grid.items())
    # the grid is the photo list here: the strip's place shows its pages
    assert not w.thumbs.isVisible() and w.grid_bar.isVisible()
    cur = w.current["id"]
    assert cur in w.grid.visible_ids() and w.grid.page() == strip.index(cur) // 16
    w.grid.set_page(0)
    assert w.grid.visible_ids() == strip[:16] and "1–16" in w.lbl_grid_page.text()
    assert w.btn_grid_next.isEnabled() and not w.btn_grid_prev.isEnabled()

    # click = pick (numbered), again = out; picks are the strip's picks
    a, b, c = strip[0], strip[3], strip[5]
    for iid in (a, b, c):
        _click(app, w, iid)
    assert w.picks() == [a, b, c] and w.grid._picks == {a: 1, b: 2, c: 3}
    _click(app, w, b)
    assert w.picks() == [a, c]
    _click(app, w, b)
    assert w.picks() == [a, c, b]
    assert w._tab() == "grid"                               # picking stays on the 16

    # [멀티]: the picked photos, and only those, in the multi view
    w.btn_multi.click()
    app.processEvents()
    assert w._tab() == "multi" and w.multi.count == 4
    shown = [cell.image_id for cell in w.multi.cells if cell.isVisible() and cell.image_id is not None]
    assert shown == [a, c, b]
    # [16장]: back to the 16, the picks still there
    w.view_buttons["grid"].click()
    app.processEvents()
    assert w._tab() == "grid" and w.picks() == [a, c, b] and w.grid_bar.isVisible()
    # the 다중 button of the command toolbar goes back to the 16 as well
    w._on_action("multi")
    assert w._tab() == "multi"
    w._on_action("multi")
    assert w._tab() == "grid"

    # a double click opens the photo big in 모두 보기 (and does not pick it)
    w.grid.set_page(0)
    d = strip[7]
    _click(app, w, d, double=True)
    assert w._tab() == "all" and w.current["id"] == d and d not in w.picks()
    assert w.thumbs.isVisible() and not w.grid_bar.isVisible()
    w._go("grid")
    assert w.grid.page() == 0 and w.grid._current == d

    # Ctrl+click: the second photo (②) next to the one shown
    _click(app, w, strip[9], ctrl=True)
    assert w.compare is not None and w.compare["id"] == strip[9] and w.grid._second == strip[9]
    assert strip[9] not in w.picks()

    # the second page: the wheel and the page buttons; the photo list keys move through the photos
    w.btn_grid_next.click()
    assert w.grid.page() == 1 and w.grid.visible_ids() == strip[16:]
    assert "17–18" in w.lbl_grid_page.text() and not w.btn_grid_next.isEnabled()
    w.btn_grid_prev.click()
    assert w.grid.page() == 0
    w.thumbs.setCurrentRow(15)
    w._step(1)                                              # PageDown on the last photo of the page
    assert w.current["id"] == strip[16] and w.grid.page() == 1

    # the filters of the menu bar filter the 16 too
    w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
    app.processEvents()
    assert [p.eye for p in w.grid.items()] == ["OD"] * (N_PHOTOS // 2) and w.grid.pages() == 1
    w.f_eye.setCurrentIndex(0)


def test_switching_the_way_in_settings(app, window):
    from fundusview.ui.dialogs import SettingsDialog

    w = window
    _open(app, w)
    assert w._tab() == "all"
    dlg = SettingsDialog(w.settings, w)
    i = dlg.open_view.findData("grid")
    assert i >= 0 and dlg.open_view.findData("overview") >= 0
    dlg.open_view.setCurrentIndex(i)
    dlg.apply()
    assert w.settings.open_view == "grid"
    w._apply_open_view()
    assert w.view_buttons["grid"].isVisible()
    w._go(w._home())
    assert w._tab() == "grid"
    w.settings.open_view = "overview"                      # back: 16장 보기 is gone, its screen too
    w._apply_open_view()
    assert w._tab() == "all" and w.view_buttons["grid"].isHidden()
    assert w.thumbs.isVisible() and not w.grid_bar.isVisible()
    # changed while the patient list is on screen: the list stays
    w.settings.open_view = "grid"
    w._apply_open_view()
    w._go("grid")
    w.show_page("patients")
    w.settings.open_view = "overview"
    w._apply_open_view()
    assert w.page() == "patients" and w._tab() == "all"
