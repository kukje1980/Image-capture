"""The photo list by exam date (날짜 책갈피) and 미리 보기 — v0.10.0.

The photo list under the photos shows one exam's photos (OD row · OS row, as before); the bookmarks
over it — 전체 at the left, then one per exam date, newest first — pick the exam, and so does the wheel
over the list. A patient opens on its newest exam, the newest OD | OS above. A photo of the list
and its neighbours grow toward the mouse like the icons of the Dock of a Mac (미리 보기, v0.10.11 — the
photos of the views stay) until the mouse leaves the list; a click pins it (numbered) — several pinned: that many
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


def _move(app, w, pos):
    """The mouse moves to ``pos`` of the photo list, no button held (None: it leaves the list)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    vp = w.thumbs.viewport()
    if pos is None:
        QApplication.sendEvent(vp, QEvent(QEvent.Type.Leave))
    else:
        pos = QPointF(pos)
        QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, pos, QPointF(vp.mapToGlobal(pos.toPoint())),
                                               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                               Qt.KeyboardModifier.NoModifier))
    app.processEvents()


def _hover(app, w, image_id):
    """The mouse comes onto that photo of the list (None: it leaves the list). The photos move as
    they grow, so the mouse goes along the photo's row until that photo is the one under it."""
    from PySide6.QtCore import QPoint

    if image_id is None:
        _move(app, w, None)
        return None
    t = w.thumbs
    cell = t.cell_rect(t.row(_item(w, image_id)))
    for x in [cell.center().x()] + list(range(2, t.viewport().width(), 6)):
        at = QPoint(x, cell.center().y())
        _move(app, w, at)
        if w._peek == image_id:
            return at
    raise AssertionError(f"photo {image_id} never came under the mouse")


def _press_at(app, w, at):
    """A click where the mouse is on the list (the photo grown there takes it)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
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


def test_the_photos_under_the_mouse_grow_like_the_dock_and_a_click_pins(win):
    from PySide6.QtCore import QPoint

    from fundusview.ui.main_window import THUMB_GRID
    from fundusview.ui.thumbs import PICK_ROLE, SHOWN

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2 = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2"))
    t, vp, dock = w.thumbs, w.thumbs.viewport(), w.dock
    gw, gh = THUMB_GRID
    assert w.act_peek.isChecked() and w.settings.hover_preview and not dock.isVisible() and t.dock_row() is None
    assert _cells(w) == ([od3, os3], od3) and w.settings.preview_scale == 2.0

    # the mouse on the list: the photos of the row under it grow toward it, like the icons of the Dock
    # of a Mac — the one under the mouse twice its size, those beside it less and less; the photos of
    # the views stay as they are, nothing is pinned by it, and the photo being adjusted stays
    at = _hover(app, w, rf3)
    k = t.row(_item(w, rf3))
    rects = dict(t.dock_rects())
    assert w._peek == rf3 and dock.isVisible() and t.dock_row() == t._slots[k][0]
    assert sorted(rects) == [i for i in range(t.count()) if t._slots[i][0] == t._slots[k][0]]
    assert rects[k].left() <= at.x() < rects[k].right() and t.itemAt(at) is _item(w, rf3)
    widths = [rects[i].width() for i in sorted(rects, key=lambda i: rects[i].left())]
    assert max(widths) == rects[k].width() and 1.6 * gw < rects[k].width() <= 2 * gw
    assert all(gw <= x <= 2 * gw for x in widths) and len(set(round(x) for x in widths)) > 1
    for i, r in rects.items():                                  # as wide, as high; all on the bottom of their row
        assert r.height() == pytest.approx(r.width() * gh / gw) and r.bottom() == pytest.approx(t.cell_rect(k).bottom() + 1)
    order = sorted(rects, key=lambda i: rects[i].left())        # side by side, in the list's order, none over another
    assert order == sorted(rects) and all(rects[a].right() == pytest.approx(rects[b].left())
                                          for a, b in zip(order, order[1:]))
    assert rects[order[0]].left() >= 0                           # (the row never starts left of its start)
    # … painted over the list and the room above it (they grow upwards), the mouse let through
    top = vp.mapTo(dock.parentWidget(), QPoint(0, 0))
    assert dock.parentWidget() is w.centralWidget() and dock.geometry().bottom() == top.y() + vp.height() - 1
    assert dock.geometry().top() < top.y() and dock.width() == vp.width()
    assert {i for i, _r in dock.rects()} == set(rects)
    assert "클릭해서 고정" in w.lbl_status.text()
    assert _cells(w) == ([od3, os3], od3) and w.multi.count == 2
    assert w.picks() == [od3, os3] and not w._own_picks() and w.current["id"] == od3
    assert _item(w, rf3).data(PICK_ROLE) == 0 and _item(w, od3).data(PICK_ROLE) == SHOWN
    # … the photos follow the mouse: a little to the side, the same photo a little smaller, its neighbour larger
    was = rects[k].width()
    _move(app, w, at + QPoint(12, 0))
    assert dict(t.dock_rects())[k].width() != was
    # … the other row: that one grows, the first as it was; off the list: every photo as in the list
    _hover(app, w, os3)
    assert w._peek == os3 and t.dock_row() == t._slots[t.row(_item(w, os3))][0] != t._slots[k][0]
    _hover(app, w, None)
    assert w._peek is None and not dock.isVisible() and t.dock_row() is None and t.dock_rects() == []
    assert _cells(w) == ([od3, os3], od3)

    # a click pins the photo under the mouse — the grown one, wherever its cell is in the list; the row
    # stays grown while the mouse is on it (the Dock)
    at = _hover(app, w, rf3)
    _press_at(app, w, at)
    assert w.picks() == [rf3] and _cells(w) == ([rf3], rf3) and w._peek == rf3 and dock.isVisible()
    assert _item(w, rf3).data(PICK_ROLE) == 1 and w.lbl_picks.text() == "1장 고정"
    # more photos pinned: as many above as are pinned — looking at a photo never changes them
    at = _hover(app, w, os3)
    assert _cells(w) == ([rf3], rf3) and w.multi.count == 1
    _press_at(app, w, at)
    assert w.picks() == [rf3, os3] and _cells(w) == ([rf3, os3], os3)
    _hover(app, w, None)
    w.set_book("2025-12-01")                               # … from another bookmark as well (2 × 2)
    at = _hover(app, w, od2)
    assert _cells(w) == ([rf3, os3], os3)
    _press_at(app, w, at)
    assert w.picks() == [rf3, os3, od2] and _cells(w) == ([rf3, os3, od2], od2) and w.multi.count == 4
    # a pinned photo under the mouse: a click lets it go
    _hover(app, w, os2)
    at = _hover(app, w, od2)
    assert "클릭하면 뺍니다" in w.lbl_status.text()
    _press_at(app, w, at)
    assert w.picks() == [rf3, os3]

    # the grown row follows the window's size, and goes with the view
    _hover(app, w, os2)
    w.resize(1300, 800)
    app.processEvents()
    top = vp.mapTo(dock.parentWidget(), QPoint(0, 0))
    assert dock.isVisible() and dock.geometry().bottom() == top.y() + vp.height() - 1 and dock.width() == vp.width()
    _press(w, "view:multi")
    assert not dock.isVisible() and w._peek is None and t.dock_row() is None
    _press(w, "view:simple")

    # Detail: the photos grow under the mouse as well (the big photo stays); a click shows the photo
    _hover(app, w, None)
    w.set_book("2025-12-01")
    _click(app, w, os2, double=True)
    assert w._tab() == "all" and w.current["id"] == os2
    _hover(app, w, None)
    at = _hover(app, w, od2)
    assert dock.isVisible() and w._peek == od2 and w.current["id"] == os2
    _press_at(app, w, at)
    assert w.current["id"] == od2 and w._tab() == "all"
    _hover(app, w, None)

    # 보기 → 사진 목록에 마우스를 올리면 미리 보기: off — nothing grows (remembered); the click still pins
    _press(w, "view:simple")
    w.set_book("2026-03-02")
    assert w.picks() == [od3, os3]
    w.act_peek.setChecked(False)
    assert not w.settings.hover_preview
    _move(app, w, t.cell_rect(t.row(_item(w, rf3))).center())
    assert w._peek is None and not dock.isVisible() and t.dock_row() is None
    _click(app, w, rf3)
    assert w.picks() == [rf3]
    w.act_peek.setChecked(True)
    assert w.settings.hover_preview


def test_the_list_grows_as_soon_as_the_mouse_is_on_it(win):
    """미리 보기 needs no move over the list first (0.13.2): the photos grow like the Dock when the mouse
    comes onto the list, when the list comes up under the resting mouse (another view, the patient list
    going away from over it), and when the left button is said to be held without a press on the list
    (the double click on the patient list that opened the patient) — a drag from a photo of the list
    still changes nothing."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QCursor, QEnterEvent, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    t, vp, pl = w.thumbs, w.thumbs.viewport(), w.patient_list
    k = t.row(_item(w, ids["rf3"]))
    at, row = t.cell_rect(k).center(), t._slots[k][0]
    assert t.dock_row() is None and not w.dock.isVisible()

    # the mouse comes onto the list (an Enter, no move yet): grown at once; off it: as in the list
    QApplication.sendEvent(vp, QEnterEvent(QPointF(at), QPointF(at), QPointF(vp.mapToGlobal(at))))
    app.processEvents()
    assert t.dock_row() == row and w.dock.isVisible() and w._peek is not None
    _move(app, w, None)
    assert t.dock_row() is None and w._peek is None

    # a move with the left button "held" that was never pressed on the list: only the mouse on it
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, QPointF(at), QPointF(vp.mapToGlobal(at)),
                                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                           Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    assert t.dock_row() == row and w._dock_at == (row, at.x())
    # … pressed on a photo of the list and dragged: the click decides, the way changes nothing
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, QPointF(at.x() + 30, at.y()),
                                           QPointF(vp.mapToGlobal(at)), Qt.MouseButton.NoButton,
                                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert w._dock_at == (row, at.x())
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    _move(app, w, None)
    assert t.dock_row() is None

    was = QCursor.pos()
    try:
        QCursor.setPos(vp.mapToGlobal(at))             # the mouse on the list, then resting there
        app.processEvents()
        assert t.dock_row() == row
        w._go("all")                                   # another view (a key): the list grows there too
        assert t.dock_row() is None                    # (the last view's preview is over)
        app.processEvents()
        assert w._tab() == "all" and t.dock_row() == row and w.dock.isVisible()
        w.show_patient_list()                          # the patient list over it: not on the list …
        app.processEvents()
        assert w._mouse_on_list() is None
        w._end_peek()
        pl.hide()                                      # … gone: the photos under the resting mouse grow
        assert t.dock_row() is None
        app.processEvents()
        assert t.dock_row() == row and w.dock.isVisible()
    finally:
        QCursor.setPos(was)                            # (the next tests' windows: no mouse on their lists)
        app.processEvents()


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


def test_settings_of_before_drop_the_loupe_under_the_mouse_and_grow_the_list_once(tmp_path):
    """0.13.2 (9): the large photos have no loupe without a button any more (as before 0.10.16) and the
    photo list grows like the Dock under the mouse — once for a settings file of before; chosen after
    that (보기 menu), it stays."""
    from PySide6.QtWidgets import QApplication

    from fundusview.config import Settings
    from fundusview.ui.main_window import MainWindow
    from test_review import _library

    QApplication.instance() or QApplication([])
    db, refs, ids = _library(tmp_path)
    assert not Settings().hover_loupe and Settings().hover_preview
    for version, after in ((8, (False, True)), (MainWindow.UI_VERSION, (True, False))):
        s = Settings(library_dir=str(tmp_path / "lib"), watch_on_startup=False, auto_detect=False,
                     last_patient="", hover_loupe=True, hover_preview=False, ui_version=version)
        w = MainWindow(s, db)
        try:
            assert (s.hover_loupe, s.hover_preview) == after and s.ui_version == MainWindow.UI_VERSION
            assert (w.act_hover_loupe.isChecked(), w.act_peek.isChecked()) == after
            assert w.view2d.hover_loupe == after[0] == w.multi.hover_loupe
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
    assert view._fit and view._drag is None            # let go: gone (보기 → 큰 사진에 마우스를 올리면 돋보기
    assert not view.hover_loupe and not view._loupe.isVisible()     # is off at first: only while held)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=at)
    assert view._loupe.isVisible()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=at)
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


def test_the_mouse_over_a_photo_not_zoomed_yet_shows_the_loupe_without_a_button(win):
    """보기 → 큰 사진에 마우스를 올리면 돋보기 — off at first (0.13.2: as before 0.10.16, the loupe only while
    the left button is held). Switched on, Simple · Multi cells and Detail's big photo: with the whole photo
    on screen the loupe is under the mouse as soon as it is over the photo — no button; off the photo,
    once zoomed in, or switched off again (remembered) there is none."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtTest import QTest
    from fundusview.config import Settings

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    cell = next(c for c in w.multi.cells if c.image_id == ids["os3"])
    view, vp = cell.view, cell.view.viewport()
    at = QPoint(vp.width() // 2, vp.height() // 2)
    assert not Settings().hover_loupe and not w.act_hover_loupe.isChecked()
    assert not view.hover_loupe and not w.view2d.hover_loupe and not w.multi.hover_loupe
    QTest.mouseMove(vp, at)
    assert not view._loupe.isVisible()                                     # at first: no loupe without a button
    w.act_hover_loupe.setChecked(True)                                     # 보기: on (remembered)
    assert w.settings.hover_loupe and view.hover_loupe and w.view2d.hover_loupe
    assert not cell.zooms["disc"].hover_loupe
    QTest.mouseMove(vp, at)
    assert view._loupe.isVisible() and abs(view._loupe.geometry().center().x() - at.x()) <= 1
    QTest.mouseMove(vp, at + QPoint(40, 10))                               # it follows the mouse
    assert abs(view._loupe.geometry().center().x() - at.x() - 40) <= 1
    QTest.mouseMove(vp, QPoint(1, at.y()) if view.mapToScene(QPoint(1, at.y())).x() < 0 else QPoint(at.x(), 1))
    assert not view._loupe.isVisible()                                     # beside the photo: none
    QTest.mouseMove(vp, at)
    # the button held is the loupe as before, and it stays when the button is let go
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=at)
    assert view._loupe.isVisible()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=at)
    assert view._loupe.isVisible() and view._fit
    app.sendEvent(vp, QEvent(QEvent.Type.Leave))                           # the mouse leaves: gone
    assert not view._loupe.isVisible()
    QTest.mouseMove(vp, at + QPoint(3, 3))
    assert view._loupe.isVisible()
    view.zoom_to(view._fit_zoom() * 3)                                     # zoomed in: none (a drag moves)
    QTest.mouseMove(vp, at + QPoint(5, 5))
    assert not view._fit and not view._loupe.isVisible()
    view.fit()
    QTest.mouseMove(vp, at)
    assert view._loupe.isVisible()
    view.set_tool("length")                                                # measuring: none
    assert not view._loupe.isVisible()
    view.set_tool("zoom")
    assert view._loupe.isVisible()
    w.act_hover_loupe.setChecked(False)                                    # 보기: off again
    assert not w.settings.hover_loupe and not view.hover_loupe and not w.view2d.hover_loupe
    assert not view._loupe.isVisible()
    QTest.mouseMove(vp, at + QPoint(10, 0))
    assert not view._loupe.isVisible()


def test_how_large_the_preview_grows_is_chosen_in_the_view_menu(win):
    """보기 → 미리 보기 배율: 1.5 · 2 · 2.5 · 3배 — the photo under the mouse grows that many times (those
    beside it less), remembered."""
    from fundusview.config import Settings, config_dir
    from fundusview.ui.main_window import THUMB_GRID
    from fundusview.ui.peek import SCALES

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    t = w.thumbs
    gw, gh = THUMB_GRID
    assert SCALES == (1.5, 2.0, 2.5, 3.0) and w.settings.preview_scale == 2.0
    assert w.peek_scale_acts[2.0].isChecked()
    k = t.row(_item(w, ids["rf3"]))
    largest = {}
    for scale in SCALES:
        w.peek_scale_acts[scale].trigger()
        app.processEvents()
        assert w.settings.preview_scale == scale and w.peek_scale_acts[scale].isChecked()
        _hover(app, w, ids["rf3"])
        r = dict(t.dock_rects())[k]
        largest[scale] = r.width()
        assert 0.8 * scale * gw < r.width() <= scale * gw + 1e-6 and r.height() <= scale * gh + 1e-6
        assert w.dock.isVisible() and w.dock.geometry().top() >= 0
        _hover(app, w, None)
    assert largest[1.5] < largest[2.0] < largest[2.5] < largest[3.0]
    assert Settings.load(config_dir() / "settings.json").preview_scale == 3.0
    w.peek_scale_acts[2.0].trigger()


def test_the_photos_grow_and_shrink_step_by_step(win):
    """With 부드러운 움직임 the photos grow from their size in the list to the 배율 when the mouse comes onto
    the list, and shrink back when it leaves."""
    from fundusview.ui import motion
    from fundusview.ui.main_window import THUMB_GRID

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    t = w.thumbs
    gw = THUMB_GRID[0]
    k = t.row(_item(w, ids["rf3"]))
    at = t.cell_rect(k).center()
    largest = lambda: max(r.width() for _i, r in t.dock_rects())  # noqa: E731
    tk = motion.ticker()
    motion.set_enabled(True)
    tk.manual = True
    try:
        _move(app, w, at)
        assert w.dock.isVisible() and largest() == pytest.approx(gw)          # (as in the list, to begin with)
        tk.advance(0.05)
        mid = largest()
        assert gw < mid < 1.9 * gw
        tk.advance(0.2)
        full = largest()
        assert mid < full <= 2 * gw
        _move(app, w, None)                                                    # off the list: back, step by step
        assert t.dock_row() is not None
        tk.advance(0.05)
        assert gw < largest() < full
        tk.advance(0.2)
        assert t.dock_row() is None and not w.dock.isVisible() and w._peek is None
    finally:
        tk.manual = False
        motion.set_enabled(False)


def test_the_list_opens_on_the_newest_exam_or_on_all_as_set(win, monkeypatch):
    """설정 → 일반 → 환자를 열면 사진 목록은: 최신 검사 (처음 설정) — the newest exam's bookmark — or 전체: the
    photos of every exam; the newest OD | OS above either way. Remembered."""
    from fundusview.config import Settings, config_dir
    from fundusview.ui.dialogs import SettingsDialog

    app, w, db, refs, ids = win
    od3, os3 = ids["od3"], ids["os3"]
    assert w.settings.open_book == "latest"
    _open(app, w, refs["kim"])
    assert w._book == "2026-03-02" and w.thumbs.count() == 3 and _cells(w) == ([od3, os3], od3)

    def choose(dlg):
        assert [dlg.open_book.itemData(i) for i in range(dlg.open_book.count())] == ["latest", "all"]
        dlg.open_book.setCurrentIndex(dlg.open_book.findData(want))
        return True
    monkeypatch.setattr(SettingsDialog, "exec", choose)
    want = "all"
    w._open_settings()
    assert w.settings.open_book == "all" and Settings.load(config_dir() / "settings.json").open_book == "all"
    other = next(k for k in refs if k != "kim")
    _open(app, w, refs[other])
    _open(app, w, refs["kim"])
    assert w._book == "*" and w.thumbs.count() == 7 and _cells(w) == ([od3, os3], od3)
    want = "latest"
    w._open_settings()
    _open(app, w, refs[other])
    _open(app, w, refs["kim"])
    assert w._book == "2026-03-02" and w.thumbs.count() == 3
