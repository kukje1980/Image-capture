"""The photo list and VK-2 style picking: the strip shows the photos by eye (OD row on top, OS row
under it, newest first) — the photo filling its cell, the date on it, the eye said once at the right
end of each row. On Multi a plain click puts the photo on the view at once (numbered; the layout
fits the number picked), [Multi] goes back to the picked photos and a click on a cell lets the
processing toolbar change that photo only."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_eye_badges():
    from fundusview.ui.thumbs import eye_badge, eye_badge_html

    assert [eye_badge(e)[0] for e in ("OD", "OS", "OU")] == ["OD", "OS", "OU"]
    assert eye_badge(None)[0] == "미상" and eye_badge("")[0] == "미상"
    assert len({eye_badge(e)[1] for e in ("OD", "OS", "OU", None)}) == 4
    assert "OD" in eye_badge_html("OD")


def test_strip_rows_by_eye(app):
    """OD row on top, OS row under it, OU / 미상 in a third row; the rows start at the left and
    scroll sideways together (no vertical scrolling: the wheel goes sideways)."""
    import time

    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QListWidgetItem

    from fundusview.ui.thumbs import EYE_ROLE, ThumbStrip, eye_row

    assert [eye_row(e) for e in ("OD", "OS", "OU", "", None)] == [0, 1, 2, 2, 2]
    t = ThumbStrip()
    t.setGridSize(QSize(96, 104))
    t.resize(5 * 96 + 20, 400)
    eyes = ["OD"] * 8 + ["OS"] * 3 + ["", "OU"]              # added in the strip's order: OD, OS, the rest
    for k, e in enumerate(eyes):
        it = QListWidgetItem(str(k))
        it.setSizeHint(QSize(92, 102))
        it.setData(EYE_ROLE, e)
        t.addItem(it)
    t.set_by_eye(True)
    t.show()
    app.processEvents()

    def check():
        assert t.grid_shape() == (3, 8)
        r = [t.visualItemRect(t.item(i)) for i in range(len(eyes))]
        top = r[0].top()
        assert [x.top() - top for x in r] == [0] * 8 + [104] * 3 + [208] * 2
        assert [x.left() for x in r[8:11]] == [x.left() for x in r[:3]]       # the rows line up
        assert [x.left() for x in r[11:]] == [x.left() for x in r[:2]]
        h = t.horizontalScrollBar()
        assert h.maximum() == 8 * 96 - t.viewport().width() and t.verticalScrollBar().maximum() == 0

    check()
    t.scrollToItem(t.item(7))                                 # the end of the OD row
    app.processEvents()
    assert t.horizontalScrollBar().value() > 0
    assert t.row(t.itemAt(t.visualItemRect(t.item(7)).center())) == 7
    t.horizontalScrollBar().setValue(0)
    assert t.row(t.itemAt(t.visualItemRect(t.item(12)).center())) == 12
    t.resize(4 * 96, 400)                                     # Qt lays the list out again: still by eye
    deadline = time.time() + 2
    while time.time() < deadline:
        app.processEvents()
    check()
    # the eye of each row, top to bottom — said once per row at the left of the rows (EyeRail)
    from fundusview.ui.thumbs import EyeRail

    assert t.row_eyes() == ["OD", "OS", ""]
    rail = EyeRail(t)
    rail.resize(rail.WIDTH, t.height())
    badges = rail.badge_rects()
    assert [e for e, _ in badges] == ["OD", "OS", ""]
    port_top = t.viewport().mapTo(t, t.viewport().rect().topLeft()).y()
    for k, (_, rect) in enumerate(badges):                    # each at the middle of its row
        assert abs(rect.center().y() - (port_top + k * 104 + 52)) <= 1 and 0 <= rect.left() < rect.right() <= rail.WIDTH
    t.set_by_eye(False)                                       # one line, in the same order
    app.processEvents()
    assert t.grid_shape() == (1, len(eyes)) and t.row_eyes() == [] and rail.badge_rects() == []
    assert len({t.visualItemRect(t.item(i)).top() for i in range(len(eyes))}) == 1
    lefts = [t.visualItemRect(t.item(i)).left() for i in range(len(eyes))]
    assert lefts == sorted(lefts)
    t.close()


def test_the_photo_fills_its_cell_with_the_date_on_it(app, tmp_path):
    """No lines of caption under a photo of the list: the photo is as large as its cell, the date
    lies on it (top left) and the kind of photo (bottom left) is an option; a photo shown above is
    framed, on Multi with its number; one line: the eye badge on every photo."""
    from PIL import Image
    from PySide6.QtCore import QRect, QSize, Qt
    from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QListWidgetItem, QStyleOptionViewItem

    from fundusview.ui.thumbs import (DATE_ROLE, EYE_ROLE, KIND_ROLE, PICK_ROLE, SECOND_ROLE, SHOWN, ThumbDelegate,
                                      ThumbStrip)

    path = tmp_path / "t.png"
    Image.new("RGB", (320, 240), (150, 70, 40)).save(path)        # a 4:3 thumbnail, one colour
    t = ThumbStrip()
    t.setGridSize(QSize(94, 72))
    d = ThumbDelegate(t)
    t.setItemDelegate(d)
    it = QListWidgetItem(QIcon(QPixmap(str(path))), "2026-03-10\n컬러")
    it.setSizeHint(QSize(90, 70))
    for role, value in ((DATE_ROLE, "2026-03-10"), (KIND_ROLE, "컬러"), (EYE_ROLE, "OD")):
        it.setData(role, value)
    t.addItem(it)
    index = t.model().index(0, 0)
    cell = QRect(0, 0, 90, 70)

    def paint():
        img = QImage(cell.size(), QImage.Format.Format_RGB32)
        img.fill(Qt.GlobalColor.black)
        opt = QStyleOptionViewItem()
        opt.initFrom(t)
        opt.rect = cell
        p = QPainter(img)
        d.paint(p, opt, index)
        p.end()
        return img

    def differs(a, b, rect):
        return any(a.pixel(x, y) != b.pixel(x, y) for x in range(rect.left(), rect.right() + 1, 2)
                   for y in range(rect.top(), rect.bottom() + 1, 2))

    opt = QStyleOptionViewItem()
    opt.rect = cell
    photo = d.photo_rect(opt, index)
    # the photo: as wide as the cell allows, its own shape, nothing left for a caption under it
    assert photo.width() >= 82 and abs(photo.width() / photo.height() - 4 / 3) < 0.05
    assert cell.bottom() - photo.bottom() <= 6 and photo.top() - cell.top() <= 6
    assert d.show_date and not d.show_kind and not d.show_eye
    top_left = QRect(photo.left(), photo.top(), 64, 16)
    bottom_left = QRect(photo.left(), photo.bottom() - 16, 60, 16)
    bottom_right = QRect(photo.right() - 20, photo.bottom() - 20, 14, 14)   # (inside the frame of a shown photo)
    plain = paint()
    assert plain.pixelColor(photo.center()).red() > 120            # the photo itself, in the middle
    d.show_date = False
    bare = paint()
    assert differs(plain, bare, top_left) and not differs(plain, bare, bottom_left)   # the date: top left
    assert not differs(bare, bare, top_left)
    d.show_kind = True
    assert differs(paint(), bare, bottom_left) and not differs(paint(), bare, top_left)   # the kind: bottom left
    d.show_kind = False
    d.show_eye = True                                               # one line: the eye badge
    assert differs(paint(), bare, bottom_left)
    d.show_eye = False
    # shown above — Simple: framed; Multi: framed and numbered; the second photo: ②
    it.setData(PICK_ROLE, SHOWN)
    framed = paint()
    edge = QRect(photo.left(), photo.center().y() - 4, 4, 8)
    assert differs(framed, bare, edge) and not differs(framed, bare, bottom_right)
    it.setData(PICK_ROLE, 3)
    assert differs(paint(), framed, bottom_right)
    it.setData(PICK_ROLE, 0)
    it.setData(SECOND_ROLE, True)
    assert differs(paint(), bare, bottom_right)
    t.close()


def _click(w, item, double=False):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    pos = w.thumbs.visualItemRect(item).center()
    if double:
        QTest.mouseDClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    else:
        QTest.mouseClick(w.thumbs.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)


def test_pick_photos_and_edit_each_in_multi(app, tmp_path, demo_dir, import_and_wait):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from fundusview.config import Settings, WatchFolder
    from fundusview.db import Database
    from fundusview.ui.main_window import MainWindow
    from fundusview.ui.thumbs import EYE_ROLE, PICK_ROLE

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_folders=[WatchFolder(path=str(demo_dir))], watch_on_startup=False,
                 open_view="odos", ui_version=MainWindow.UI_VERSION)          # (환자를 열면: Simple)
    db = Database(tmp_path / "lib" / "fundus.db")
    w = MainWindow(s, db)
    try:
        w.resize(1600, 960)
        w.show()
        import_and_wait(app, w, [demo_dir / "RetiCam", demo_dir / "VK2_Export"])
        pid = db.find_patient("PID20260310-0A1B2C3D")["id"]
        w._select_patient_ref(pid)
        app.processEvents()
        assert w.thumbs.count() == 3
        rows = db.images_for_patient(pid)                           # newest exam first (VK-2)
        # the patient comes with its newest OD and OS picked (OD first)
        eyes = {r["id"]: r["laterality"] for r in rows}
        assert [eyes[i] for i in w.picks()] == ["OD", "OS"] and w.current["id"] == w.picks()[0]
        ids = [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)]
        by_eye = [r for e in ("OD", "OS") for r in rows if r["laterality"] == e]
        assert ids == [r["id"] for r in by_eye]                     # OD photos, then OS — each newest first
        assert [w.thumbs.item(i).data(EYE_ROLE) for i in range(3)] == ["OD", "OD", "OS"]
        assert all("°" not in w.thumbs.item(i).text() for i in range(3))     # the date and the kind, no angle

        # by eye: OD in the top row, OS in the row under it — low rows (the photo fills its cell, no
        # caption under it), the eye said once per row at its left; 보기 → 사진 목록 표시 → 눈별로 두 줄
        # switches to one line and back (remembered); one eye on the list = one row
        from fundusview.ui.main_window import THUMB_GRID
        from fundusview.ui.thumbs import DATE_ROLE, KIND_ROLE

        grid_h = w.thumbs.gridSize().height()
        assert grid_h == THUMB_GRID[1] <= 80 and w.book_bar.isVisible() and w.book_bar.height() <= 32
        assert w.strip_w.height() <= 2 * 80 + 12 + w.book_bar.height()      # the 날짜 책갈피 over the two rows
        from fundusview.models import MODALITY_LABELS
        assert w.thumbs.item(0).data(DATE_ROLE) == by_eye[0]["exam_date"]
        assert w.thumbs.item(0).data(KIND_ROLE) == MODALITY_LABELS[by_eye[0]["modality"]]
        assert w.thumbs.width() > w.width() - 200                    # the whole width: nothing beside the list

        def tops():
            return [w.thumbs.visualItemRect(w.thumbs.item(i)).top() for i in range(w.thumbs.count())]

        rects = [w.thumbs.visualItemRect(w.thumbs.item(i)) for i in range(3)]
        assert tops()[0] == tops()[1] and tops()[2] - tops()[0] == grid_h
        assert rects[0].left() == rects[2].left() < rects[1].left()   # each row starts at the left
        assert w.act_thumb_eyes.isChecked() and w.thumbs.height() == 2 * grid_h + 10
        assert w.eye_rail.isVisible() and [e for e, _ in w.eye_rail.badge_rects()] == ["OD", "OS"]
        assert w.eye_rail.x() + w.eye_rail.width() <= w.thumbs.x() and not w.thumb_paint.show_eye
        w.act_thumb_eyes.setChecked(False)
        assert s.thumb_rows == 1 and w.thumbs.height() == THUMB_GRID[1] + 10
        assert len(set(tops())) == 1 and not w.eye_rail.isVisible() and w.thumb_paint.show_eye
        w.act_thumb_eyes.setChecked(True)
        assert s.thumb_rows == 2 and tops()[2] - tops()[0] == grid_h and w.eye_rail.isVisible()
        # the date on the photos, and the kind (컬러 · 몽타주 …): options, remembered
        assert s.thumb_date and not s.thumb_kind and w.act_thumb_date.isChecked() and not w.act_thumb_kind.isChecked()
        w.act_thumb_kind.setChecked(True)
        w.act_thumb_date.setChecked(False)
        assert s.thumb_kind and not s.thumb_date and w.thumb_paint.show_kind and not w.thumb_paint.show_date
        from fundusview.config import Settings as _S, config_dir
        saved = _S.load(config_dir() / "settings.json")
        assert saved.thumb_kind and not saved.thumb_date
        w.act_thumb_kind.setChecked(False)
        w.act_thumb_date.setChecked(True)
        w.f_eye.setCurrentIndex(w.f_eye.findData("OS"))
        app.processEvents()
        assert w.thumbs.count() == 1 and w.thumbs.height() == grid_h + 10
        w.f_eye.setCurrentIndex(0)
        app.processEvents()
        assert w.thumbs.count() == 3 and w.thumbs.height() == 2 * grid_h + 10

        # 미상 (eye unknown): not in the list — 눈 → 미상 shows them, and so does a patient with nothing else
        from fundusview.ui.main_window import UNKNOWN_EYE

        def strip_ids():
            return [w.thumbs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.thumbs.count())]

        eye_of = {r["id"]: r["laterality"] for r in rows}
        db.update_image(ids[1], laterality=None)
        w._fill_thumbs()
        app.processEvents()
        assert strip_ids() == [ids[0], ids[2]] and w.thumbs.grid_shape() == (2, 1)
        assert w.thumbs.height() == 2 * grid_h + 10                  # two rows: OD, OS
        w.f_eye.setCurrentIndex(w.f_eye.findData(UNKNOWN_EYE))
        app.processEvents()
        assert strip_ids() == [ids[1]]
        w.f_eye.setCurrentIndex(w.f_eye.findData("OD"))
        app.processEvents()
        assert strip_ids() == [ids[0]]
        w.f_eye.setCurrentIndex(0)
        for k in ids:
            db.update_image(k, laterality=None)
        w._fill_thumbs()
        app.processEvents()
        assert sorted(strip_ids()) == sorted(ids) and w.thumbs.grid_shape() == (1, 3)
        for k in ids:
            db.update_image(k, laterality=eye_of[k])
        w._fill_thumbs()
        app.processEvents()
        assert strip_ids() == ids

        # [Simple]: the newest OD | OS — shown, not pinned (no [선택 해제])
        w.acts["view:simple"].trigger()
        app.processEvents()
        pair = w._newest_pair()
        assert w._tab() == "multi" and len(pair) == 2 and w.picks() == pair and w.acts["view:simple"].isChecked()
        assert "최신 OD | OS" in w.multi.mode_text and not w.btn_clear_picks.isVisible()
        assert [c.image_id for c in w.multi.cells if c.isVisible() and c.image_id] == pair and w.multi.count == 2

        # plain click = the photo pinned on the multi view at once (numbered, selected; the first one alone);
        # click again = it leaves
        _click(w, w.thumbs.item(2))
        app.processEvents()
        assert w._tab() == "multi" and w.picks() == [ids[2]] and w.multi.count == 1 and w.current["id"] == ids[2]
        _click(w, w.thumbs.item(0))
        assert w.picks() == [ids[2], ids[0]] and w.multi.count == 2 and w.current["id"] == ids[0]
        assert w.thumbs.item(2).data(PICK_ROLE) == 1 and w.thumbs.item(0).data(PICK_ROLE) == 2
        assert w.lbl_picks.text() == "2장 고정" and w.btn_clear_picks.isVisible()
        _click(w, w.thumbs.item(2))
        assert w.picks() == [ids[0]] and w.thumbs.item(0).data(PICK_ROLE) == 1 and w.multi.count == 1
        _click(w, w.thumbs.item(1))
        assert w.picks() == [ids[0], ids[1]] and w.multi.count == 2

        # double click = that photo large (Detail, whose big photo is the 2D view), the picks stay as they were
        _click(w, w.thumbs.item(2), double=True)
        assert w.current["id"] == ids[2] and w._tab() == "all"
        assert w.picks() == [ids[0], ids[1]]

        # back to the picked photos: 16장 보기 has them numbered, [Multi] shows them only, in pick order,
        # the first one selected
        w.show_grid()
        app.processEvents()
        assert w._tab() == "grid" and w.grid._picks == {ids[0]: 1, ids[1]: 2} and w.lbl_grid_picks.isVisible()
        assert w.lbl_grid_picks.text().startswith("2장 선택")
        w.acts["view:multi"].trigger()
        app.processEvents()
        assert w._tab() == "multi" and w.multi.count == 2 and w.acts["view:multi"].isChecked()
        cells = [c for c in w.multi.cells if c.isVisible()]
        assert [c.image_id for c in cells] == [ids[0], ids[1]]
        assert w.current["id"] == ids[0] and "고정한 사진 2장" in w.multi.mode_text
        assert "OD" in cells[0].label.text() or "OS" in cells[0].label.text() or "미상" in cells[0].label.text()

        # processing applies to the selected cell's photo only
        before_second = cells[1].view._rgb.copy()
        w._on_action("chan:redfree")
        assert w._channel == "rnfl"
        assert (cells[1].view._rgb == before_second).all()          # the other cell is untouched
        g = cells[0].view._rgb
        h, wd = g.shape[:2]
        mid = g[h // 3:2 * h // 3, wd // 3:2 * wd // 3]                 # Red-free 강화: grey on the retina
        assert (mid[..., 0] == mid[..., 2]).all() and (mid[..., 0] == mid[..., 1]).all()
        QTest.mouseClick(cells[1].view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        assert w._tab() == "multi"                                   # a click selects the cell (it stays)
        assert w.current["id"] == ids[1] and w._channel == "rgb"    # its own (untouched) processing
        w._on_action("op:sharpen")
        assert w._ops == ["sharpen"]
        assert not (cells[1].view._rgb == before_second).all()      # sharpened, in its cell
        QTest.mouseClick(cells[0].view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        app.processEvents()
        assert w.current["id"] == ids[0] and w._channel == "rnfl" and w._ops == []
        # a photo opened large keeps its processing there, and back with the picked photos each has its own
        w.acts["view:all"].trigger()                                 # (a double click on Multi: Simple)
        app.processEvents()
        assert w._tab() == "all" and w.current["id"] == ids[0] and w._channel == "rnfl"
        w.acts["view:multi"].trigger()                               # (from Detail: the picked photos)
        app.processEvents()
        cells = [c for c in w.multi.cells if c.isVisible()]
        assert w._tab() == "multi" and [c.image_id for c in cells] == [ids[0], ids[1]]
        mid = cells[0].view._rgb[h // 3:2 * h // 3, wd // 3:2 * wd // 3]
        assert (mid[..., 0] == mid[..., 1]).all() and (mid[..., 0] == mid[..., 2]).all()   # still red-free
        w._on_action("undo")                                         # each photo keeps its own undo
        assert w._channel == "rgb"
        assert w._per_photo[ids[1]]["state"]["ops"] == ["sharpen"]

        # clearing the picks: nothing pinned — the newest OD | OS again
        w.btn_clear_picks.click()
        app.processEvents()
        assert w.picks() == pair and "최신 OD | OS" in w.multi.mode_text and w.lbl_picks.text() == ""
        assert not w.btn_clear_picks.isVisible() and not w.multi.empty.isVisible()
        assert [c.image_id for c in w.multi.cells if c.isVisible() and c.image_id] == pair

        # another patient: the picks belong to the previous one — Simple again, that patient's own newest OD | OS
        _click(w, w.thumbs.item(0))
        assert w.picks() == [ids[0]]
        other = next(p["id"] for p in db.list_patients() if p["id"] != pid)
        w._select_patient_ref(other)
        theirs = {r["id"] for r in db.images_for_patient(other)}
        assert set(w.picks()) <= theirs and w._per_photo == {}
    finally:
        w.close()


def test_the_photos_of_the_list_have_round_corners():
    """0.10.11: a photo of the list is painted with round corners (as an icon of the Dock) — nothing of
    it in the very corner of its place, the photo itself a little inside."""
    from PySide6.QtCore import QRect, QSize, Qt
    from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QListWidgetItem, QStyleOptionViewItem

    from fundusview.ui.thumbs import ThumbDelegate, ThumbStrip

    app = QApplication.instance() or QApplication([])  # noqa: F841
    t = ThumbStrip()
    t.setGridSize(QSize(94, 72))
    d = ThumbDelegate(t)
    d.show_date = False
    t.setItemDelegate(d)
    pm = QPixmap(320, 240)
    pm.fill(QColor("#ff0000"))
    t.addItem(QListWidgetItem(QIcon(pm), ""))
    img = QImage(94, 72, QImage.Format.Format_ARGB32)
    img.fill(QColor("#0000ff"))
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 94, 72)
    p = QPainter(img)
    d.paint(p, opt, t.model().index(0, 0))
    p.end()
    photo = d.photo_rect(opt, t.model().index(0, 0))
    assert d.corner(photo) == pytest.approx(0.16 * min(photo.width(), photo.height())) and d.corner(photo) > 6
    red = lambda x, y: img.pixelColor(x, y).red() > 200 and img.pixelColor(x, y).blue() < 60  # noqa: E731
    assert red(photo.center().x(), photo.center().y()) and red(photo.left() + 1, photo.center().y())
    for x, y in ((photo.left(), photo.top()), (photo.right(), photo.top()), (photo.left(), photo.bottom()),
                 (photo.right(), photo.bottom())):
        assert not red(x, y)                                   # the corners: cut round
    assert Qt is not None


def test_the_big_photo_panes_have_round_corners():
    """0.10.11: a cell of Simple · Multi is round at its corners — what is around it is painted over them —
    and so is its frame, blue on the cell selected."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from fundusview.ui import theme
    from fundusview.ui.multi_view import _Cell
    from fundusview.ui.widgets import RoundCorners

    app = QApplication.instance() or QApplication([])
    cell = _Cell()
    cell.resize(300, 240)
    cell.show()
    app.processEvents()
    assert isinstance(cell.round, RoundCorners) and cell.round.geometry() == cell.rect() and cell.round.radius == 12
    assert cell.round.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)     # the mouse goes through
    cell.round.outside = QColor("#ff00ff")
    cell.select(True)
    assert cell.round.border == QColor(theme.ACCENT)
    img = QImage(cell.size(), QImage.Format.Format_ARGB32)
    cell.render(img)
    assert img.pixelColor(0, 0) == QColor("#ff00ff") and img.pixelColor(299, 239) == QColor("#ff00ff")
    edge = img.pixelColor(150, 0)                                   # the frame, on a straight edge
    assert edge.blue() > 200 and edge.red() < 80
    cell.select(False)
    assert cell.round.border == QColor(theme.CARD)
    cell.resize(200, 160)
    app.processEvents()
    assert cell.round.geometry() == cell.rect()
    cell.close()
