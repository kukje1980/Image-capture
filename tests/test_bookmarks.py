"""The photo list by exam date (날짜 책갈피) and 미리 보기 — v0.10.0.

The photo list under the photos shows one exam's photos (OD row · OS row, as before); the bookmarks
over it — 전체 at the left, then one per exam date, newest first — pick the exam, and so does the wheel
over the list. A patient opens on its newest exam, the newest OD | OS above. A photo of the list
under the mouse grows where it is, the photos after it moving right, like the Dock of a Mac (미리 보기,
v0.10.9 — the photos of the views stay) until the mouse leaves it; a click pins it (numbered) — several pinned: that many
side by side — and a click on a pinned one lets it go."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_open_multi import _cells, _click, _item, _open, _press, win  # noqa: E402,F401  (the same library)


def _books(w):
    return [w.book_bar.tabData(k) for k in range(w.book_bar.count())]


def _wheel(app, w, notches, modifiers=None):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    vp = w.thumbs.viewport()
    pos = QPointF(vp.width() / 2, vp.height() / 2)
    e = QWheelEvent(pos, QPointF(vp.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, int(120 * notches)),
                    Qt.MouseButton.NoButton, modifiers or Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(vp, e)
    app.processEvents()


def _hover(app, w, image_id):
    """The mouse comes to rest on that photo of the list (None: it leaves the list)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    vp = w.thumbs.viewport()
    if image_id is None:
        QApplication.sendEvent(vp, QEvent(QEvent.Type.Leave))
    else:                                      # (no button held, whatever QTest clicked last)
        pos = QPointF(w.thumbs.visualItemRect(_item(w, image_id)).center())
        QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, pos, QPointF(vp.mapToGlobal(pos.toPoint())),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                               Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    if w._peek_timer.isActive():               # (rested there long enough)
        w._peek_timer.stop()
        w._apply_peek()
    app.processEvents()


def test_the_photo_list_is_sorted_by_date_bookmarks(win):
    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2, od1, sheet = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2", "od1", "sheet"))
    # 전체 at the left, then a bookmark per exam date, the newest first — the newest one open: its photos
    # in the list (OD row, OS row), the newest OD | OS above
    assert w.book_bar.isVisible() and _books(w) == ["*", "2026-03-02", "2025-12-01", "2025-08-20"]
    assert w.book_bar.currentIndex() == 1 and w._book == "2026-03-02"
    assert [w.book_bar.tabText(k) for k in range(4)] == ["전체 · 7장", "2026-03-02 · 3장",
                                                         "2025-12-01 · 2장", "2025-08-20 · 2장"]
    assert w._strip_ids() == [rf3, od3, os3] and w.thumbs.row_eyes() == ["OD", "OS"]
    assert w.picks() == [od3, os3] and _cells(w) == ([od3, os3], od3)
    assert w.book_bar.geometry().bottom() <= w.thumbs.geometry().top()      # over the list
    high = w.thumbs.height()

    # a click on a bookmark: that exam's photos in the list; nothing pinned — its OD | OS above
    w.book_bar.setCurrentIndex(2)
    app.processEvents()
    assert w._book == "2025-12-01" and w._strip_ids() == [od2, os2]
    assert w.picks() == [od2, os2] and _cells(w) == ([od2, os2], od2) and not w._own_picks()
    # an exam of one eye: one row of photos, the list as high as before (the photos above keep their size)
    w.book_bar.setCurrentIndex(3)
    app.processEvents()
    assert w._strip_ids() == [sheet, od1] or w._strip_ids() == [od1, sheet]
    assert w.thumbs.row_eyes() == ["OD"] and w.thumbs.height() == high
    assert w.picks() == [od1] and w.multi.count == 1
    # 전체: every exam in the list, the newest OD | OS above
    w.book_bar.setCurrentIndex(0)
    app.processEvents()
    assert w._book == "*" and len(w._strip_ids()) == 7 and w.picks() == [od3, os3]
    # [Simple] starts again from the bookmark's exam
    w.set_book("2025-12-01")
    _click(app, w, os2)
    assert w.picks() == [os2]
    _press(w, "view:simple")
    assert w.picks() == [od2, os2] and w._book == "2025-12-01"

    # the exam selected in the patient list: its bookmark
    w.show_patient_list()
    w.patient_list.set_exam("2025-08-20")
    app.processEvents()
    assert w._book == "2025-08-20" and w.book_bar.currentIndex() == 3 and w.picks() == [od1]
    # 16장 보기 has no bookmarks (every photo is on it) and no list; back on Simple they are there again
    w.patient_list.hide()
    _press(w, "view:multi")
    assert w._tab() == "grid" and not w.book_bar.isVisible() and not w.thumbs.isVisible()
    assert len(w.grid.items()) == 7
    _press(w, "view:simple")
    assert w.book_bar.isVisible() and w.thumbs.isVisible()
    # Detail: ◀ ▶ go through the photos of the bookmark; the bookmark changed there keeps the photo
    w.set_book("2026-03-02")
    _click(app, w, od3, double=True)
    assert w._tab() == "all" and w.current["id"] == od3 and w.thumbs.currentRow() == 1
    w._step(1)
    assert w.current["id"] == os3
    w._step(1)
    assert w.current["id"] == os3                          # (the last of this bookmark)

    # another patient: its own bookmarks, the newest open; one exam only — one bookmark, no 전체
    _open(app, w, refs["park"])
    assert _books(w) == ["2026-03-09"] and w._book == "2026-03-09" and w._strip_ids() == [ids["p_od"]]


def test_the_wheel_over_the_photo_list_turns_the_bookmarks(win):
    from PySide6.QtCore import Qt

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, od2, os2, od1 = (ids[k] for k in ("od3", "os3", "od2", "os2", "od1"))
    assert w._book == "2026-03-02"
    _wheel(app, w, -1)                                     # back (down): the exam before
    assert w._book == "2025-12-01" and w.book_bar.currentIndex() == 2 and w._strip_ids() == [od2, os2]
    assert w.picks() == [od2, os2]                         # nothing pinned: that exam's OD | OS
    _wheel(app, w, -1)
    assert w._book == "2025-08-20" and w.picks() == [od1]
    _wheel(app, w, -1)                                     # the oldest: it stays
    assert w._book == "2025-08-20"
    _wheel(app, w, 1)                                      # forward (up): newer
    assert w._book == "2025-12-01"
    _wheel(app, w, 0.5)                                    # a fine wheel: a bookmark per whole notch
    assert w._book == "2025-12-01"
    _wheel(app, w, 0.5)
    assert w._book == "2026-03-02"
    _wheel(app, w, 1)                                      # past the newest: 전체 (the leftmost)
    assert w._book == "*" and len(w._strip_ids()) == 7 and w.picks() == [od3, os3]
    _wheel(app, w, 3)                                      # the first one: it stays
    assert w._book == "*" and w.book_bar.currentIndex() == 0
    _wheel(app, w, -1)
    assert w._book == "2026-03-02" and w.book_bar.currentIndex() == 1
    # Shift+wheel: the list sideways, the bookmark stays
    _wheel(app, w, -1, Qt.KeyboardModifier.ShiftModifier)
    assert w._book == "2026-03-02"

    # photos pinned stay above whatever the bookmark; its tab counts them (✓)
    _click(app, w, os3)
    _wheel(app, w, -1)
    assert w._book == "2025-12-01" and w.picks() == [os3] and _cells(w) == ([os3], os3)
    _click(app, w, od2)
    assert w.picks() == [os3, od2] and w.multi.count == 2
    assert w.book_bar.tabText(1) == "2026-03-02 · 3장  ✓1" and w.book_bar.tabText(2) == "2025-12-01 · 2장  ✓1"
    assert w.book_bar.tabText(0) == "전체 · 7장  ✓2"
    _wheel(app, w, 1)
    assert w.picks() == [os3, od2] and w.current["id"] == od2      # (the photo being adjusted stays, too)


def test_a_photo_under_the_mouse_is_previewed_and_a_click_pins_it(win):
    from fundusview.ui.thumbs import PICK_ROLE, SHOWN

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2 = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2"))
    pane = w.peek_pane
    assert w.act_peek.isChecked() and w.settings.hover_preview and not pane.isVisible()
    assert _cells(w) == ([od3, os3], od3)

    # the mouse on a photo of the list: that photo large over the views, marked 미리 보기 — the photos
    # under it stay as they are, nothing is pinned by it, and the photo being adjusted stays
    _hover(app, w, rf3)
    assert w._peek == rf3 and pane.isVisible() and pane.image_id == rf3 and pane.view.has_image()
    # … only its eye on it (top left of the photo) — no line of text over the photo; what a click does: the status line
    assert "OD" in pane.label.text() and "미리 보기" not in pane.label.text() and "2026" not in pane.label.text()
    assert pane.label.isVisible() and pane.view.y() <= 6           # (ImageView.geometry is something else)
    assert pane.view.x() <= pane.label.x() < 40 and pane.view.y() <= pane.label.y() < 40
    assert "클릭해서 고정" in w.lbl_status.text()
    # … like the Dock of a Mac: the photo grows where it is — twice its size in the list, its left edge
    # and the bottom of its row where they were — and the photos after it in its row move right by
    # the room it takes; the other row and the photos before it stay
    from PySide6.QtCore import QPoint, QRect

    from fundusview.ui.main_window import THUMB_GRID

    t, vp = w.thumbs, w.thumbs.viewport()
    gw, gh = THUMB_GRID
    k = t.row(_item(w, rf3))
    cell = t.cell_rect(k)
    at = QRect(vp.mapTo(pane.parentWidget(), cell.topLeft()), cell.size())
    assert pane.parentWidget() is w.centralWidget() and w.settings.preview_scale == 2.0
    assert (pane.width(), pane.height()) == (2 * gw, 2 * gh)
    assert pane.geometry().left() == at.left() and pane.geometry().bottom() == at.bottom()
    assert t.grown() == k and t.grown_rect() == cell.adjusted(0, 0, gw, 0)
    row_of = {i: t._slots[i] for i in range(t.count())}
    for i in range(t.count()):
        pushed = row_of[i][0] == row_of[k][0] and row_of[i][1] > row_of[k][1]
        assert t.visualItemRect(t.item(i)).left() - t.cell_rect(i).left() == (gw if pushed else 0) + 2, i
    assert any(row_of[i][0] == row_of[k][0] and row_of[i][1] > row_of[k][1] for i in range(t.count()))
    # … the mouse anywhere on the grown photo's room is on that photo (a click there is a click on it)
    assert t.itemAt(cell.center() + QPoint(gw, 0)) is _item(w, rf3)
    assert t.horizontalScrollBar().maximum() == 0                  # (the list scrolls no further for it)
    assert _cells(w) == ([od3, os3], od3) and w.multi.count == 2
    assert w.picks() == [od3, os3] and not w._own_picks() and w.current["id"] == od3
    assert _item(w, rf3).data(PICK_ROLE) == 0 and _item(w, od3).data(PICK_ROLE) == SHOWN
    # … another photo: that one; the mouse off the list: the pane is gone
    _hover(app, w, os3)
    assert pane.isVisible() and pane.image_id == os3 and "OS" in pane.label.text()
    assert t.grown() == t.row(_item(w, os3))
    # … a photo of the lower row grows into the row over it: there the photos from its column on move
    # out of its way (it hides none)
    k = t.row(_item(w, os3))
    over = [i for i in range(t.count()) if row_of[i][0] == row_of[k][0] - 1 and row_of[i][1] >= row_of[k][1]]
    assert over and all(t.visualItemRect(t.item(i)).left() - t.cell_rect(i).left() == 2 * gw + 2 for i in over)
    assert not any(t.visualItemRect(t.item(i)).intersects(pane.geometry().translated(-vp.mapTo(
        pane.parentWidget(), QPoint(0, 0)))) for i in range(t.count()) if i != k)
    _hover(app, w, None)
    assert w._peek is None and not pane.isVisible() and _cells(w) == ([od3, os3], od3)
    assert t.grown() is None                               # … and every photo in its own place again
    assert all(t.visualItemRect(t.item(i)).left() - t.cell_rect(i).left() == 2 for i in range(t.count()))

    # a click pins the photo looked at: the pane closes, the photo is above (alone: the first one)
    _hover(app, w, rf3)
    _click(app, w, rf3)
    assert w.picks() == [rf3] and w._peek is None and not pane.isVisible() and _cells(w) == ([rf3], rf3)
    assert _item(w, rf3).data(PICK_ROLE) == 1 and w.lbl_picks.text() == "1장 고정"
    _hover(app, w, rf3)                                    # (not again while the mouse stays on it)
    assert not pane.isVisible()
    # more photos pinned: as many above as are pinned — the pane never changes them
    _hover(app, w, os3)
    assert pane.isVisible() and pane.image_id == os3 and _cells(w) == ([rf3], rf3) and w.multi.count == 1
    _click(app, w, os3)
    assert w.picks() == [rf3, os3] and _cells(w) == ([rf3, os3], os3) and not pane.isVisible()
    w.set_book("2025-12-01")                               # … from another bookmark as well (2 × 2)
    _hover(app, w, od2)
    assert pane.image_id == od2 and _cells(w) == ([rf3, os3], os3)
    _click(app, w, od2)
    assert w.picks() == [rf3, os3, od2] and _cells(w) == ([rf3, os3, od2], od2) and w.multi.count == 4
    # a pinned photo under the mouse is looked at large, too (small cells): a click lets it go
    _hover(app, w, os2)
    _hover(app, w, od2)
    assert pane.isVisible() and pane.image_id == od2 and "클릭하면 뺍니다" in w.lbl_status.text()
    _click(app, w, od2)
    assert w.picks() == [rf3, os3] and not pane.isVisible()

    # the pane follows the window's size, and goes with the view
    _hover(app, w, os2)
    w.resize(1300, 800)
    app.processEvents()
    k = t.row(_item(w, os2))
    at = vp.mapTo(pane.parentWidget(), t.cell_rect(k).bottomLeft())
    assert pane.isVisible() and (pane.geometry().left(), pane.geometry().bottom()) == (at.x(), at.y())
    _press(w, "view:multi")
    assert not pane.isVisible() and w._peek is None
    _press(w, "view:simple")

    # Detail: the mouse on the list previews as well (the big photo stays); a click shows the photo
    _hover(app, w, None)
    w.set_book("2025-12-01")
    _click(app, w, os2, double=True)
    assert w._tab() == "all" and w.current["id"] == os2 and not pane.isVisible()
    _hover(app, w, None)
    _hover(app, w, od2)
    assert pane.isVisible() and pane.image_id == od2 and w.current["id"] == os2
    _click(app, w, od2)
    assert not pane.isVisible() and w.current["id"] == od2 and w._tab() == "all"
    _hover(app, w, None)

    # 보기 → 사진 목록에 마우스를 올리면 미리 보기: off — no pane (remembered); the click still pins
    _press(w, "view:simple")
    w.set_book("2026-03-02")
    assert w.picks() == [od3, os3]
    w.act_peek.setChecked(False)
    assert not w.settings.hover_preview
    _hover(app, w, rf3)
    assert w._peek is None and not pane.isVisible()
    _click(app, w, rf3)
    assert w.picks() == [rf3]
    w.act_peek.setChecked(True)
    assert w.settings.hover_preview


def test_settings_of_before_open_on_simple_once(tmp_path):
    """A settings file of an earlier version (16장 보기): the new look once — Simple with the bookmarks;
    16장 보기 chosen after that stays."""
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow
    from test_review import _library

    QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    assert Settings().open_view == "odos" and Settings().hover_preview
    for before, version, after in (("grid", 7, "odos"), ("grid", MainWindow.UI_VERSION, "grid")):
        s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False,
                     last_patient="", open_view=before, ui_version=version)
        w = MainWindow(s, db)
        try:
            assert s.open_view == after and s.ui_version == MainWindow.UI_VERSION
        finally:
            w.close()
    db.close()


def test_the_left_button_on_a_photo_not_zoomed_yet_shows_the_loupe(win):
    """Simple · Multi cells and Detail's big photo: with the whole photo on screen (before any zoom) the
    left button held down shows the loupe under the mouse; once zoomed, a drag moves the photo as before."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    cell = next(c for c in w.multi.cells if c.image_id == ids["os3"])
    view, vp = cell.view, cell.view.viewport()
    at = QPoint(vp.width() // 2, vp.height() // 2)
    assert view.click_loupe and view._fit and not view._loupe.isVisible()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=at)
    assert view._loupe.isVisible() and w.current["id"] == ids["os3"]       # (the click selects the cell, too)
    assert abs(view._loupe.geometry().center().x() - at.x()) <= 1
    QTest.mouseMove(vp, at + QPoint(40, 10))                               # it follows the mouse
    assert abs(view._loupe.geometry().center().x() - at.x() - 40) <= 1
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=at + QPoint(40, 10))
    assert not view._loupe.isVisible() and view._fit
    # zoomed in: the left button moves the photo, no loupe
    view.zoom_to(view._fit_zoom() * 3)
    assert not view._fit
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=at)
    assert not view._loupe.isVisible() and view._drag["kind"] == "pan"
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=at)
    view.fit()
    # Detail's big photo the same; other views (the 황반 · 디스크 panes …) as before
    assert w.view2d.click_loupe and not cell.zooms["disc"].click_loupe


def test_how_large_the_preview_grows_is_chosen_in_the_view_menu(win):
    """보기 → 미리 보기 배율: 1.5 · 2 · 2.5 · 3배 — the photo under the mouse grows that many times,
    the photos after it make that much room, remembered."""
    from fundusview.config import Settings, config_dir
    from fundusview.ui.main_window import THUMB_GRID
    from fundusview.ui.peek import SCALES

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    pane, t = w.peek_pane, w.thumbs
    gw, gh = THUMB_GRID
    assert SCALES == (1.5, 2.0, 2.5, 3.0) and w.settings.preview_scale == 2.0
    assert w.peek_scale_acts[2.0].isChecked() and pane.scale == 2.0
    _hover(app, w, ids["rf3"])
    k = t.row(_item(w, ids["rf3"]))
    for scale in SCALES:
        w.peek_scale_acts[scale].trigger()
        app.processEvents()
        assert w.settings.preview_scale == scale and pane.scale == scale and w.peek_scale_acts[scale].isChecked()
        assert pane.isVisible() and (pane.width(), pane.height()) == (round(gw * scale), round(gh * scale))
        assert t.grown() == k and t.grown_rect().width() == gw + round(gw * (scale - 1))
        assert pane.geometry().top() >= 0
    assert Settings.load(config_dir() / "settings.json").preview_scale == 3.0
    w.peek_scale_acts[2.0].trigger()
    _hover(app, w, None)


def test_the_preview_grows_step_by_step(win):
    """With 부드러운 움직임 the photo grows from its size in the list to the 배율, the room in its row with it."""
    from fundusview.ui import motion
    from fundusview.ui.main_window import THUMB_GRID

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    pane, t = w.peek_pane, w.thumbs
    tk = motion.ticker()
    motion.set_enabled(True)
    tk.manual = True
    try:
        _hover(app, w, ids["rf3"])
        assert pane.isVisible() and pane.width() == THUMB_GRID[0] and t.grown_rect().width() == THUMB_GRID[0]
        tk.advance(0.05)
        mid = pane.width()
        assert THUMB_GRID[0] < mid < 2 * THUMB_GRID[0] and t.grown_rect().width() == mid
        tk.advance(0.2)
        assert pane.width() == 2 * THUMB_GRID[0] and t.grown_rect().width() == 2 * THUMB_GRID[0]
        _hover(app, w, None)
        assert not pane.isVisible() and t.grown() is None
    finally:
        tk.manual = False
        motion.set_enabled(False)
