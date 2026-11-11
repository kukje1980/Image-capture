"""The look of the application: one dark palette, one type scale, one set of shapes.

Modelled on a phone's dark mode — near-black surfaces that step up in lightness as they come
forward (window → card → control), one accent colour for what is selected or primary, text in
three strengths, 8 – 12 px corners, hairline separators. Photos sit on pure black.

``apply(app)`` sets the Fusion style with a matching palette (so native-drawn bits — message
boxes, item views, menus — agree), the fonts, and the stylesheet (``style.qss``, whose ``@NAME@``
placeholders are the colours below and the small images drawn here: chevrons, the check mark).
``dark_title_bar(widget)`` asks Windows for a dark window frame.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu

# -- colours ---------------------------------------------------------------------------------
BLACK = "#000000"        # photo canvases
BG = "#1c1c1e"           # windows, bars
CARD = "#2c2c2e"         # cards, inputs, menus
FILL = "#3a3a3c"         # buttons, segmented tracks on a card
FILL2 = "#48484a"        # hover, borders of floating things
FILL3 = "#636366"        # the selected segment
SEP = "#38383a"          # hairlines
TEXT = "#f2f2f7"
TEXT2 = "#aeaeb2"        # secondary
TEXT3 = "#8e8e93"        # captions, placeholders
TEXT4 = "#636366"        # disabled
ACCENT = "#0a84ff"
ACCENT_HI = "#409cff"
ACCENT_LO = "#0060df"
GREEN = "#30d158"
ORANGE = "#ff9f0a"
RED = "#ff453a"
YELLOW = "#ffd60a"
TEAL = "#64d2ff"

COLORS = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str) and v.startswith("#")}

FONT_PX = 13             # body text


def font_families() -> list[str]:
    if sys.platform == "win32":
        return ["Segoe UI Variable Text", "Segoe UI", "Malgun Gothic"]
    if sys.platform == "darwin":
        return [".AppleSystemUIFont", "Apple SD Gothic Neo"]
    return ["Inter", "Noto Sans CJK KR", "Noto Sans", "DejaVu Sans"]


def app_font() -> QFont:
    f = QFont()
    f.setFamilies(font_families())
    f.setPixelSize(FONT_PX)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def palette() -> QPalette:
    p = QPalette()
    c = QColor
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        p.setColor(group, QPalette.ColorRole.Window, c(BG))
        p.setColor(group, QPalette.ColorRole.WindowText, c(TEXT))
        p.setColor(group, QPalette.ColorRole.Base, c(CARD))
        p.setColor(group, QPalette.ColorRole.AlternateBase, c("#242426"))
        p.setColor(group, QPalette.ColorRole.Text, c(TEXT))
        p.setColor(group, QPalette.ColorRole.Button, c(FILL))
        p.setColor(group, QPalette.ColorRole.ButtonText, c(TEXT))
        p.setColor(group, QPalette.ColorRole.BrightText, c("#ffffff"))
        p.setColor(group, QPalette.ColorRole.Highlight, c(ACCENT))
        p.setColor(group, QPalette.ColorRole.HighlightedText, c("#ffffff"))
        p.setColor(group, QPalette.ColorRole.ToolTipBase, c(CARD))
        p.setColor(group, QPalette.ColorRole.ToolTipText, c(TEXT))
        p.setColor(group, QPalette.ColorRole.PlaceholderText, c(TEXT3))
        p.setColor(group, QPalette.ColorRole.Link, c(ACCENT_HI))
        p.setColor(group, QPalette.ColorRole.Light, c(FILL2))
        p.setColor(group, QPalette.ColorRole.Midlight, c(FILL))
        p.setColor(group, QPalette.ColorRole.Mid, c(SEP))
        p.setColor(group, QPalette.ColorRole.Dark, c("#141416"))
        p.setColor(group, QPalette.ColorRole.Shadow, c(BLACK))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, c(TEXT4))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, c(FILL2))
    return p


# -- small images the stylesheet uses ---------------------------------------------------------
def _glyph(name: str, size: int, draw) -> str:
    """Draw a glyph at 3× and keep it in the settings folder (the stylesheet needs a file)."""
    from ..config import config_dir

    folder = config_dir() / "theme"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    k = 3
    img = QImage(size * k, size * k, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(k, k)
    draw(p, float(size))
    p.end()
    img.setDevicePixelRatio(1.0)
    img.save(str(path))
    return path.as_posix()


def _stroke(p: QPainter, color: str, width: float, points) -> None:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    p.drawPath(path)


def glyphs() -> dict[str, str]:
    def chevron(color, up=False):
        def draw(p, s):
            y0, y1 = (0.62, 0.38) if up else (0.38, 0.62)
            _stroke(p, color, s * 0.13, [(s * 0.28, s * y0), (s * 0.5, s * y1), (s * 0.72, s * y0)])
        return draw

    def check(p, s):
        _stroke(p, "#ffffff", s * 0.14, [(s * 0.24, s * 0.52), (s * 0.43, s * 0.70), (s * 0.76, s * 0.32)])

    def dot(p, s):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(s * 0.3, s * 0.3, s * 0.4, s * 0.4))

    return {
        "IMG_DOWN": _glyph("chevron-down", 12, chevron(TEXT2)),
        "IMG_DOWN_OFF": _glyph("chevron-down-off", 12, chevron(TEXT4)),
        "IMG_UP": _glyph("chevron-up", 12, chevron(TEXT2, up=True)),
        "IMG_CHECK": _glyph("check", 16, check),
        "IMG_DOT": _glyph("dot", 16, dot),
    }


def stylesheet() -> str:
    text = (Path(__file__).with_name("style.qss")).read_text(encoding="utf-8")
    for name, value in {**COLORS, **glyphs()}.items():
        text = text.replace(f"@{name}@", value)
    return text


# -- window frame -----------------------------------------------------------------------------
def dark_title_bar(widget) -> None:
    """Windows 10 (1809+) / 11: a dark title bar for a dark window. Elsewhere: nothing."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        for attr in (20, 19):                # DWMWA_USE_IMMERSIVE_DARK_MODE (19 before 20H1)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:                         # an old Windows: the light frame stays
        pass


class _Chrome(QObject):
    """Every window gets the dark frame; every menu its rounded, shadow-free popup."""

    def eventFilter(self, obj, e) -> bool:
        t = e.type()
        if t == QEvent.Type.Show and isinstance(obj, (QMainWindow, QDialog)) and obj.isWindow():
            if not obj.property("_dark_frame"):
                obj.setProperty("_dark_frame", True)
                dark_title_bar(obj)
        elif t == QEvent.Type.Polish and isinstance(obj, QMenu):
            if not obj.property("_rounded"):
                obj.setProperty("_rounded", True)
                obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                obj.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
                obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        return False


_chrome: _Chrome | None = None


def apply(app: QApplication) -> None:
    """Dress the whole application (call once, before the first window)."""
    global _chrome
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setFont(app_font())
    app.setStyleSheet(stylesheet())
    if _chrome is None:
        _chrome = _Chrome(app)
        app.installEventFilter(_chrome)
