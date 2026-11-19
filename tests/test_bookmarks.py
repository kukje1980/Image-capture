"""The photo list by exam date (날짜 책갈피) and 미리 보기 — v0.10.0.

The photo list under the photos shows one exam's photos (OD row · OS row, as before); the bookmarks
over it — one per exam date, newest at the left, then 전체 — pick the exam, and so does the wheel
over the list. A patient opens on its newest exam, the newest OD | OS above. A photo of the list
under the mouse is shown above (미리 보기) until the mouse leaves it; a click pins it (numbered) —
several pinned: that many side by side — and a click on a pinned one lets it go."""
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
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    vp = w.thumbs.viewport()
    if image_id is None:
        QApplication.sendEvent(vp, QEvent(QEvent.Type.Leave))
    else:
        QTest.mouseMove(vp, w.thumbs.visualItemRect(_item(w, image_id)).center())
    app.processEvents()
    if w._peek_timer.isActive():               # (rested there long enough)
        w._peek_timer.stop()
        w._apply_peek()
    app.processEvents()


def test_the_photo_list_is_sorted_by_date_bookmarks(win):
    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2, od1, sheet = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2", "od1", "sheet"))
    # a bookmark per exam date, the newest at the left, then 전체 — the newest one open: its photos
    # in the list (OD row, OS row), the newest OD | OS above
    assert w.book_bar.isVisible() and _books(w) == ["2026-03-02", "2025-12-01", "2025-08-20", "*"]
    assert w.book_bar.currentIndex() == 0 and w._book == "2026-03-02"
    assert [w.book_bar.tabText(k) for k in range(4)] == ["2026-03-02 · 3장", "2025-12-01 · 2장",
                                                         "2025-08-20 · 2장", "전체 · 7장"]
    assert w._strip_ids() == [rf3, od3, os3] and w.thumbs.row_eyes() == ["OD", "OS"]
    assert w.picks() == [od3, os3] and _cells(w) == ([od3, os3], od3)
    assert w.book_bar.geometry().bottom() <= w.thumbs.geometry().top()      # over the list
    high = w.thumbs.height()

    # a click on a bookmark: that exam's photos in the list; nothing pinned — its OD | OS above
    w.book_bar.setCurrentIndex(1)
    app.processEvents()
    assert w._book == "2025-12-01" and w._strip_ids() == [od2, os2]
    assert w.picks() == [od2, os2] and _cells(w) == ([od2, os2], od2) and not w._own_picks()
    # an exam of one eye: one row of photos, the list as high as before (the photos above keep their size)
    w.book_bar.setCurrentIndex(2)
    app.processEvents()
    assert w._strip_ids() == [sheet, od1] or w._strip_ids() == [od1, sheet]
    assert w.thumbs.row_eyes() == ["OD"] and w.thumbs.height() == high
    assert w.picks() == [od1] and w.multi.count == 1
    # 전체: every exam in the list, the newest OD | OS above
    w.book_bar.setCurrentIndex(3)
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
    assert w._book == "2025-08-20" and w.book_bar.currentIndex() == 2 and w.picks() == [od1]
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
    assert w._book == "2025-12-01" and w.book_bar.currentIndex() == 1 and w._strip_ids() == [od2, os2]
    assert w.picks() == [od2, os2]                         # nothing pinned: that exam's OD | OS
    _wheel(app, w, -1)
    assert w._book == "2025-08-20" and w.picks() == [od1]
    _wheel(app, w, -1)
    assert w._book == "*" and len(w._strip_ids()) == 7 and w.picks() == [od3, os3]
    _wheel(app, w, -1)                                     # the last one: it stays
    assert w._book == "*"
    _wheel(app, w, 2)                                      # forward (up): newer — two notches, two bookmarks
    assert w._book == "2025-12-01"
    _wheel(app, w, 0.5)                                    # a fine wheel: a bookmark per whole notch
    assert w._book == "2025-12-01"
    _wheel(app, w, 0.5)
    assert w._book == "2026-03-02"
    _wheel(app, w, 3)                                      # the newest: it stays
    assert w._book == "2026-03-02" and w.book_bar.currentIndex() == 0
    # Shift+wheel: the list sideways, the bookmark stays
    _wheel(app, w, -1, Qt.KeyboardModifier.ShiftModifier)
    assert w._book == "2026-03-02"

    # photos pinned stay above whatever the bookmark; its tab counts them (✓)
    _click(app, w, os3)
    _wheel(app, w, -1)
    assert w._book == "2025-12-01" and w.picks() == [os3] and _cells(w) == ([os3], os3)
    _click(app, w, od2)
    assert w.picks() == [os3, od2] and w.multi.count == 2
    assert w.book_bar.tabText(0) == "2026-03-02 · 3장  ✓1" and w.book_bar.tabText(1) == "2025-12-01 · 2장  ✓1"
    assert w.book_bar.tabText(3) == "전체 · 7장  ✓2"
    _wheel(app, w, 1)
    assert w.picks() == [os3, od2] and w.current["id"] == od2      # (the photo being adjusted stays, too)


def test_a_photo_under_the_mouse_is_previewed_and_a_click_pins_it(win):
    from fundusview.ui.thumbs import PICK_ROLE, SHOWN

    app, w, db, refs, ids = win
    _open(app, w, refs["kim"])
    od3, os3, rf3, od2, os2 = (ids[k] for k in ("od3", "os3", "rf3", "od2", "os2"))
    assert w.act_peek.isChecked() and w.settings.hover_preview
    assert _cells(w) == ([od3, os3], od3)

    # the mouse on a photo of the list: that photo above — what a click would give (nothing pinned:
    # it alone) —, marked 미리 보기; nothing is pinned by it, and the photo being adjusted stays
    _hover(app, w, rf3)
    assert w._peek == rf3 and _cells(w) == ([rf3], None) and w.multi.count == 1
    cell = next(c for c in w.multi.cells if c.image_id == rf3)
    assert "미리 보기" in cell.label.text() and cell.view.has_image()
    assert w.picks() == [od3, os3] and not w._own_picks() and w.current["id"] == od3
    assert _item(w, rf3).data(PICK_ROLE) == 0 and _item(w, od3).data(PICK_ROLE) == SHOWN
    # … another photo: that one; the mouse off the list: the newest OD | OS again
    _hover(app, w, os3)
    assert _cells(w) == ([os3], None)
    _hover(app, w, None)
    assert w._peek is None and _cells(w) == ([od3, os3], od3) and w.multi.count == 2

    # a click pins the photo under the mouse: it stays above when the mouse leaves
    _hover(app, w, rf3)
    _click(app, w, rf3)
    assert w.picks() == [rf3] and w._peek is None and _cells(w) == ([rf3], rf3)
    assert "미리 보기" not in next(c for c in w.multi.cells if c.image_id == rf3).label.text()
    assert _item(w, rf3).data(PICK_ROLE) == 1 and w.lbl_picks.text() == "1장 고정"
    _hover(app, w, None)
    assert _cells(w) == ([rf3], rf3)
    # with a photo pinned the one under the mouse comes after it; a click pins it, too — as many
    # photos above as are pinned
    _hover(app, w, os3)
    assert _cells(w) == ([rf3, os3], rf3) and w.multi.count == 2 and w.picks() == [rf3]
    assert "미리 보기" in next(c for c in w.multi.cells if c.image_id == os3).label.text()
    _hover(app, w, rf3)                                    # (a pinned one under the mouse: as it is)
    assert w._peek is None and _cells(w) == ([rf3], rf3)
    _hover(app, w, os3)
    _click(app, w, os3)
    assert w.picks() == [rf3, os3] and _cells(w) == ([rf3, os3], os3)
    # … from another bookmark as well: three pinned, three above (2 × 2)
    w.set_book("2025-12-01")
    _hover(app, w, od2)
    assert _cells(w) == ([rf3, os3, od2], os3) and w.multi.count == 4
    _click(app, w, od2)
    assert w.picks() == [rf3, os3, od2] and _cells(w) == ([rf3, os3, od2], od2)
    _hover(app, w, None)
    assert _cells(w)[0] == [rf3, os3, od2]

    # a click on a pinned one lets it go — and it is not previewed again while the mouse stays on it
    _click(app, w, od2)
    _hover(app, w, od2)
    assert w.picks() == [rf3, os3] and w._peek is None and _cells(w)[0] == [rf3, os3]
    _hover(app, w, os2)                                    # (the next photo: previewed)
    assert _cells(w)[0] == [rf3, os3, os2]
    _hover(app, w, od2)                                    # … and back on it: previewed again
    assert _cells(w)[0] == [rf3, os3, od2]

    # the preview is Simple's: on Detail the mouse over the list changes nothing; a click shows the photo
    _hover(app, w, None)
    _click(app, w, os2, double=True)
    assert w._tab() == "all" and w.current["id"] == os2 and w.picks() == [rf3, os3]
    _hover(app, w, od2)
    assert w._peek is None and w.current["id"] == os2
    _hover(app, w, None)

    # 보기 → 사진 목록에 마우스를 올리면 미리 보기: off — no preview (remembered); the click still pins
    _press(w, "view:simple")
    w.set_book("2026-03-02")
    assert w.picks() == [od3, os3]
    w.act_peek.setChecked(False)
    assert not w.settings.hover_preview
    _hover(app, w, rf3)
    assert w._peek is None and _cells(w)[0] == [od3, os3]
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
