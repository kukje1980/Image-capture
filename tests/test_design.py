"""The dark look (theme.py, style.qss) and its controls (widgets.py): a switch that slides, a
segmented control whose selection glides, cards of rows, and the cross-fade between tabs."""
import os
import re

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def live(app):
    """Motion on, with the clock in the test's hands (as in test_motion.py)."""
    from fundusview.ui import motion

    t = motion.ticker()
    was, t.manual = motion.enabled(), True
    motion.set_enabled(True)

    def run(seconds: float, dt: float = 1 / 120) -> None:
        for _ in range(int(round(seconds / dt))):
            t.advance(dt)

    yield run
    t.finish_all()
    t.manual = False
    motion.set_enabled(was)


def test_stylesheet_is_complete_and_dark(app):
    from PySide6.QtGui import QColor, QPalette

    from fundusview.ui import theme

    qss = theme.stylesheet()
    assert not re.search(r"@[A-Z_0-9]+@", qss)                      # every colour and image filled in
    for path in re.findall(r"url\(([^)]+)\)", qss):
        assert os.path.isfile(path), path                            # chevrons, check mark: drawn and saved
    assert theme.BG in qss and theme.ACCENT in qss
    pal = theme.palette()
    window, text = pal.color(QPalette.ColorRole.Window), pal.color(QPalette.ColorRole.WindowText)
    assert window == QColor(theme.BG) and window.lightness() < 40 and text.lightness() > 220
    assert pal.color(QPalette.ColorRole.Highlight) == QColor(theme.ACCENT)
    assert pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).lightness() < text.lightness()
    f = theme.app_font()
    assert f.pixelSize() == theme.FONT_PX and len(f.families()) >= 2
    theme.dark_title_bar(None)                                       # not Windows: nothing to do, no error


def test_theme_applies_to_the_application(app):
    from PySide6.QtWidgets import QMenu, QPushButton

    from fundusview.ui import theme

    from PySide6.QtGui import QColor, QPalette

    before = (app.palette(), app.font(), app.styleSheet())
    try:
        theme.apply(app)
        assert theme.BG in app.styleSheet()
        assert app.palette().color(QPalette.ColorRole.Window) == QColor(theme.BG)
        assert app.font().pixelSize() == theme.FONT_PX
        b = QPushButton("확인")
        b.setObjectName("primary")
        b.show()
        app.processEvents()
        img = b.grab().toImage()
        c = img.pixelColor(4, img.height() // 2)
        assert c.blue() > 200 and c.red() < 80                       # the accent-coloured primary button
        m = QMenu()                                                  # menus: rounded, on a see-through popup
        m.addAction("열기")
        m.ensurePolished()
        from PySide6.QtCore import Qt
        assert m.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        b.close()
    finally:
        app.setStyleSheet(before[2])
        app.setPalette(before[0])
        app.setFont(before[1])


def test_switch_is_a_checkbox_that_slides(app, live):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from fundusview.ui import motion
    from fundusview.ui.widgets import Switch, knob_center

    seen = []
    s = Switch("입체 조명")
    s.toggled.connect(seen.append)
    s.resize(220, 30)
    s.show()
    app.processEvents()
    assert not s.isChecked() and s.sizeHint().width() > Switch.TRACK_W + 30
    track = s.track_rect()
    assert track.right() == pytest.approx(220.0) and track.width() == Switch.TRACK_W      # at the right edge
    x_off = knob_center(s).x()
    QTest.mouseClick(s, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 15))   # on the label
    assert s.isChecked() and seen == [True]
    assert knob_center(s).x() == pytest.approx(x_off)                # it does not jump …
    live(0.06)
    mid = knob_center(s).x()
    assert x_off < mid < x_off + (Switch.TRACK_W - Switch.TRACK_H)
    live(0.3)
    assert knob_center(s).x() == pytest.approx(x_off + Switch.TRACK_W - Switch.TRACK_H)   # … it slides across
    s.setChecked(False)
    live(0.3)
    assert knob_center(s).x() == pytest.approx(x_off) and seen == [True, False]
    lead = Switch("자동", trailing=False)                            # the switch first, then its label
    lead.resize(120, 30)
    assert lead.track_rect().left() == 0.0
    motion.set_enabled(False)                                        # off: there at once
    s.setChecked(True)
    assert knob_center(s).x() == pytest.approx(x_off + Switch.TRACK_W - Switch.TRACK_H)
    assert not s.grab().toImage().isNull()
    s.setEnabled(False)
    assert not s.grab().toImage().isNull()
    s.close()


def test_segmented_selection_glides(app, live):
    from fundusview.ui import motion
    from fundusview.ui.widgets import Segmented, segment

    a, b, c = segment("간단히"), segment("자세히", "실제 해부 구조"), segment("단면")
    picked = []
    for btn in (a, b, c):
        btn.clicked.connect(lambda _=False, t=btn.text(): picked.append(t))
    seg = Segmented([a, b, c])
    a.setChecked(True)
    seg.resize(300, 30)
    seg.show()
    app.processEvents()
    assert seg._thumb == a.geometry() and b.toolTip() == "실제 해부 구조"
    c.click()
    assert c.isChecked() and not a.isChecked() and picked == ["단면"]            # one choice
    assert seg._thumb == a.geometry()                                            # the thumb has not jumped
    live(0.08)
    assert a.geometry().x() < seg._thumb.x() < c.geometry().x()
    live(0.4)
    assert seg._thumb == c.geometry()
    motion.set_enabled(False)
    b.setChecked(True)
    assert seg._thumb == b.geometry()
    seg.resize(360, 30)                                                          # it follows the layout
    app.processEvents()
    assert seg._thumb == b.geometry()
    assert not seg.grab().toImage().isNull()
    seg.close()


def test_cards_group_rows_with_hairlines(app):
    from PySide6.QtWidgets import QFrame, QLabel, QSlider

    from fundusview.ui.widgets import Switch, card, row

    r1, r2, r3 = row("깊이", QSlider(), "자르는 깊이"), Switch("망막 투시"), Switch("화각 표시")
    box = card("안구 열기", r1, r2, r3)
    assert box.findChild(QLabel, "cardTitle").text() == "안구 열기"
    assert len(box.frame.findChildren(QFrame, "hairline")) == 2                  # between the three rows
    assert r1.label.text() == "깊이" and r1.toolTip() == "자르는 깊이"
    plain = card("", Switch("a"), Switch("b"), lines=False)
    assert plain.findChild(QLabel, "cardTitle") is None and not plain.frame.findChildren(QFrame, "hairline")


def test_crossfade_between_two_states_of_a_widget(app, live):
    from PySide6.QtWidgets import QLabel

    from fundusview.ui import motion

    w = QLabel("2D 보기")
    w.resize(200, 80)
    w.show()
    app.processEvents()
    fade = motion.Crossfade(w, duration=0.2)
    fade.snap()                                   # what it shows now …
    w.setText("3D 안구")
    fade.play()                                   # … fades away over what it shows next
    over = fade._label
    assert over is not None and over.isVisible() and over.graphicsEffect().opacity() == pytest.approx(1.0)
    live(0.1)
    assert 0.0 < over.graphicsEffect().opacity() < 0.6
    live(0.2)
    assert not over.isVisible()
    motion.set_enabled(False)                     # off: no layer at all
    fade.snap()
    fade.play()
    assert not over.isVisible()
    w.close()


def test_images_load_from_a_settings_folder_with_spaces(app, tmp_path, monkeypatch):
    """Windows user folders often have spaces or Korean names; the stylesheet's images still load."""
    from PySide6.QtWidgets import QCheckBox

    from fundusview.ui import theme

    home = tmp_path / "홍 길동 (PC)" / "App Data"
    home.mkdir(parents=True)
    monkeypatch.setenv("FUNDUSVIEW_HOME", str(home))
    qss = theme.stylesheet()
    assert str(home.as_posix()) in qss and (home / "theme" / "check.png").is_file()

    def white(sheet: str) -> int:
        box = QCheckBox("밝기 맞추기")
        box.setChecked(True)
        box.setStyleSheet(sheet)
        box.resize(140, 30)
        box.show()
        app.processEvents()
        img = box.grab().toImage()
        box.close()
        return sum(img.pixelColor(x, y).lightness() > 215 for x in range(22) for y in range(img.height()))

    assert white(qss) > white(qss.replace("check.png", "missing.png")) + 5      # the check mark is drawn


def test_toolbar_icons_are_colour_tiles_with_white_glyphs(app):
    """0.10.18: every toolbar icon is a rounded colour tile (photo thumbnails: a rounded photo) with
    clear corners; the glyph alone (``plain``) stays a light line drawing with no tile behind it.
    (0.13.6: one of the looks of 보기 → 아이콘 모양 — "tile".)"""
    from fundusview.ui import icons
    from fundusview.ui.toolbars import COMMANDS, PROCESSING, icon_for

    specs = [c[3] for c in COMMANDS] + [c[3] for c in PROCESSING if c]
    was = icons.style()
    icons.set_style("tile")
    try:
        for spec in specs:
            img = icon_for(spec).pixmap(64, 64).toImage()
            assert img.pixelColor(0, 0).alpha() == 0 and img.pixelColor(63, 63).alpha() == 0, spec   # round corners
            assert img.pixelColor(32, 5).alpha() == 255 and img.pixelColor(5, 32).alpha() == 255, spec  # the tile
            if not spec.startswith("fundus:"):
                assert spec in icons.TILE_OF or spec.startswith("multi"), spec       # a colour chosen for it
                top, bottom = icons.tile_colors(spec)
                edge = img.pixelColor(32, 57)
                assert abs(edge.red() - bottom.red()) < 40 and abs(edge.blue() - bottom.blue()) < 40, spec
                white = sum(img.pixelColor(x, y).lightness() > 240 for x in range(10, 54) for y in range(10, 54))
                assert white > 40, spec                                             # the glyph, in white
    finally:
        icons.set_style(was)
    # neighbours on the command toolbar differ in colour where it helps to tell them apart
    assert icons.tile_colors("simple") != icons.tile_colors("multi16") != icons.tile_colors("detail")
    assert icons.tile_colors("exit")[1].red() > 200
    plain = icons.icon("prev", plain=True).pixmap(64, 64).toImage()
    assert plain.pixelColor(32, 5).alpha() == 0 and plain.pixelColor(5, 32).alpha() == 0
    assert any(plain.pixelColor(x, 32).alpha() == 255 for x in range(64))


def test_icon_looks_put_the_glyph_first(app):
    """0.13.6: 보기 → 아이콘 모양 — the line looks have no tile and a glyph that fills its square, in few
    colours with a meaning ("group", as first set); the tile looks keep a tile but a quiet one."""
    from PySide6.QtGui import QColor

    from fundusview.config import Settings
    from fundusview.ui import icons
    from fundusview.ui.toolbars import COMMANDS, PROCESSING

    assert Settings().icon_style == icons.DEFAULT_STYLE == "group"
    names = [c[3] for c in COMMANDS] + [c[3] for c in PROCESSING if c and not c[3].startswith("fundus:")]

    def picture(name, look):
        return icons.icon(name, style=look).pixmap(64, 64).toImage()

    def box(img):
        pts = [(x, y) for x in range(64) for y in range(64) if img.pixelColor(x, y).alpha() > 60]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        return max(max(xs) - min(xs), max(ys) - min(ys))        # (a chevron is narrow, but tall)

    for name in names:
        for look in ("group", "mono", "color", "accent"):
            img = picture(name, look)
            assert img.pixelColor(1, 1).alpha() == 0 and img.pixelColor(62, 62).alpha() == 0, (name, look)
            assert box(img) >= 34, (name, look)                     # the glyph is large …
            clear = sum(img.pixelColor(x, y).alpha() < 30 for x in range(64) for y in range(64))
            assert clear > 64 * 64 * 0.3, (name, look)              # … and there is no tile behind it
        for look in ("dark", "tint", "flat", "tile"):
            img = picture(name, look)
            assert img.pixelColor(32, 5).alpha() == 255 and img.pixelColor(0, 0).alpha() == 0, (name, look)
        # "group": the colour says what kind of command it is
        img = picture(name, "group")
        want = QColor(icons.GROUPS[icons.group_of(name)][0])
        hit = sum(1 for x in range(64) for y in range(64)
                  if img.pixelColor(x, y).alpha() == 255
                  and abs(img.pixelColor(x, y).red() - want.red()) + abs(img.pixelColor(x, y).green() - want.green())
                  + abs(img.pixelColor(x, y).blue() - want.blue()) < 12)
        assert hit > 25, name
    # 0.13.10 "accent": the mono lines, and colour only where it says something — the retina in the colour of
    # a fundus photo, the end in red; a glyph with nothing to say (a chevron) is the mono one
    def near(img, color, tol=40):
        c = QColor(color)
        return sum(1 for x in range(64) for y in range(64)
                   if img.pixelColor(x, y).alpha() == 255
                   and abs(img.pixelColor(x, y).red() - c.red()) + abs(img.pixelColor(x, y).green() - c.green())
                   + abs(img.pixelColor(x, y).blue() - c.blue()) < tol)

    assert picture("prev", "accent") == picture("prev", "mono")
    for name, color in (("glaucoma", icons.A_RETINA), ("fit", icons.A_RETINA), ("montage", icons.A_RETINA),
                        ("exit", icons.A_RED), ("cd", icons.A_GREEN), ("cd", icons.A_YELLOW), ("angle", icons.A_YELLOW)):
        assert near(picture(name, "accent"), color) > 15, (name, color)
        assert near(picture(name, "mono"), color) == 0, (name, color)
    assert near(picture("glaucoma", "accent"), "#e6e9ee") > 30          # … on light grey lines
    assert icons.group_of("simple") == icons.group_of("multi16") == icons.group_of("detail") == "view"
    assert icons.group_of("glaucoma") == icons.group_of("eye3d") == "exam" and icons.group_of("exit") == "danger"
    # the tiles of "dark" are all the same quiet grey; an unknown look is the first one
    assert picture("simple", "dark").pixelColor(32, 6) == picture("exit", "dark").pixelColor(32, 6)
    was = icons.style()
    try:
        assert icons.set_style("nonsense") == "group"
    finally:
        icons.set_style(was)


def test_icon_look_is_chosen_in_the_view_menu(app, tmp_path):
    """0.13.6: 보기 → 아이콘 모양 redraws every toolbar icon at once and is remembered."""
    from fundusview.config import Settings
    from fundusview.db import Database
    from fundusview.ui import icons
    from fundusview.ui.main_window import MainWindow

    s = Settings(library_dir=str(tmp_path / "lib"), stable_seconds=0.05, rescan_seconds=0,
                 watch_on_startup=False, auto_detect=False)
    window = MainWindow(s, Database(tmp_path / "lib" / "fundus.db"))
    try:
        assert window.settings.icon_style == icons.style() == "group"
        assert window.icon_style_acts["group"].isChecked() and len(window.icon_style_acts) == len(icons.STYLES)

        def corner(key):
            return window.acts[key].icon().pixmap(64, 64).toImage().pixelColor(32, 5).alpha()

        assert corner("view:simple") == 0 and corner("flip_v") == 0
        window.icon_style_acts["flat"].trigger()
        assert icons.style() == window.settings.icon_style == "flat"
        assert corner("view:simple") == 255 and corner("flip_v") == 255       # tiles now, on both toolbars
        window.icon_style_acts["mono"].trigger()
        assert corner("view:simple") == 0 and window.icon_style_acts["mono"].isChecked()
    finally:
        icons.set_style(icons.DEFAULT_STYLE)
        window.close()

