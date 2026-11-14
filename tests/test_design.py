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
