"""앱 테마(QSS) + 윈도우 아이콘 — "Clinical Graphite".

안과 영상 프로그램(VK-2, EyeSuite, IMAGEnet 등)처럼 어두운 그래파이트 작업 공간을 기본으로 하고
웹 버전(app.css)과 같은 팔레트·형태를 쓴다. light / dark 지원.
Fusion 스타일 위에 QSS를 올려 OS와 무관하게 일관된 외형을 보장한다.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

from app import brand as _brand

# 팔레트 (웹 app.css 토큰과 동일)
DARK = {
    "bg": "#0b0e13", "panel": "#12161d", "panel2": "#181d26", "raised": "#1d2330",
    "ink": "#e7eaf0", "ink_soft": "#a3acba", "ink_muted": "#6b7586",
    "rule": "#232a35", "rule_strong": "#303846",
    "accent": "#33c2b1", "accent_hover": "#6fdccf", "accent_ink": "#032321", "accent_soft": "#13302d",
    "record": "#f0524f", "record_hover": "#ff6b68", "record_soft": "#3a1a1c",
    "field": "#0f1319", "disabled": "#3a4352",
    "od": "#5aa9ff", "os": "#f5a524", "ou": "#b18cff",
}
LIGHT = {
    "bg": "#eef1f5", "panel": "#ffffff", "panel2": "#f4f6f9", "raised": "#ffffff",
    "ink": "#111827", "ink_soft": "#4b5563", "ink_muted": "#8b95a3",
    "rule": "#dfe4eb", "rule_strong": "#cbd3dd",
    "accent": "#0f8f84", "accent_hover": "#0b7268", "accent_ink": "#ffffff", "accent_soft": "#daf3ef",
    "record": "#dc2626", "record_hover": "#b91c1c", "record_soft": "#fde4e4",
    "field": "#ffffff", "disabled": "#c3cad4",
    "od": "#2563eb", "os": "#c2410c", "ou": "#7c3aed",
}

# 아이콘 색 (양쪽 테마에서 모두 읽히는 중간 톤) — 브랜드가 강조색을 바꿀 수 있음
_B = _brand.current()
ICON = "#98a2b3"
ICON_ACCENT = _B.get("icon_accent", "#2fb5a5")
ICON_RECORD = "#ef4f4c"
ICON_ON_ACCENT = _B.get("icon_on_accent", "#06231f")
EYE_COLORS = {"OD": "#5aa9ff", "OS": "#f5a524", "OU": "#b18cff"}


def palette(mode: str) -> dict:
    base = DARK if mode == "dark" else LIGHT
    over = _brand.current().get("palette", {}).get("dark" if mode == "dark" else "light", {})
    return {**base, **over}


def build_qss(mode: str = "dark") -> str:
    c = palette(mode)
    return f"""
    QWidget {{
        background: {c['bg']};
        color: {c['ink']};
        font-family: "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QToolTip {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['rule_strong']}; padding: 5px 8px; border-radius: 6px; }}

    /* ---------- 상단바 ---------- */
    QFrame#TopBar {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['rule']}; }}
    QLabel#BrandTitle {{ background: transparent; font-size: 15px; font-weight: 700; }}
    QLabel#BrandSub {{ background: transparent; color: {c['ink_muted']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
    QFrame#ModeSwitch {{ background: {c['bg']}; border: 1px solid {c['rule']}; border-radius: 10px; }}
    QPushButton#ModeBtn {{
        background: transparent; border: none; border-radius: 7px; padding: 6px 14px;
        color: {c['ink_soft']}; font-weight: 600; min-height: 20px;
    }}
    QPushButton#ModeBtn:hover {{ color: {c['ink']}; }}
    QPushButton#ModeBtn:checked {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['rule_strong']}; }}
    QPushButton#IconBtn {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; color: {c['ink_soft']}; font-weight: 600; }}
    QPushButton#IconBtn:hover {{ background: {c['panel2']}; border-color: {c['rule']}; color: {c['ink']}; }}

    /* ---------- 패널 ---------- */
    QFrame#Panel, #ThumbnailPanel {{ background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 12px; }}
    QFrame#Banner {{ background: {c['panel']}; border: none; border-bottom: 1px solid {c['rule']}; }}
    QFrame#BannerSep {{ background: {c['rule']}; }}
    QLabel#Avatar {{ background: {c['accent_soft']}; color: {c['accent_hover'] if mode == 'dark' else c['accent']};
        border-radius: 19px; font-size: 15px; font-weight: 700; }}
    QLabel#PatientName {{ background: transparent; font-size: 16px; font-weight: 700; }}
    QLabel#ChartNo {{ background: transparent; color: {c['ink_muted']}; font-family: Menlo, Consolas, "JetBrains Mono", monospace; font-size: 12px; }}
    QLabel#PatientMeta {{ background: transparent; color: {c['ink_soft']}; font-size: 12px; }}

    /* 라벨 */
    QLabel {{ background: transparent; color: {c['ink']}; }}
    QLabel#Muted {{ color: {c['ink_soft']}; }}
    QLabel#StatusLabel {{ color: {c['ink_soft']}; font-family: Menlo, Consolas, "JetBrains Mono", monospace; font-size: 12px; }}
    QLabel#PanelHeader {{ color: {c['ink_muted']}; font-weight: 700; font-size: 11px; padding: 8px 2px 2px; letter-spacing: 1px; }}
    QLabel#CountBadge {{ background: {c['accent_soft']}; color: {c['accent_hover'] if mode == 'dark' else c['accent']};
        border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700; }}
    QLabel#ThumbTitle {{ font-weight: 700; font-size: 13px; }}
    QLabel#DayHeader {{ color: {c['ink_muted']}; font-size: 11px; font-weight: 700; padding: 6px 2px 0; }}

    /* 입력/콤보 */
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QDateEdit, QDoubleSpinBox {{
        background: {c['field']}; border: 1px solid {c['rule']}; border-radius: 8px;
        padding: 6px 10px; min-height: 20px;
        selection-background-color: {c['accent']}; selection-color: {c['accent_ink']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus {{
        border: 1px solid {c['accent']};
    }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {c['panel']}; border: 1px solid {c['rule_strong']}; padding: 4px;
        selection-background-color: {c['accent_soft']}; selection-color: {c['ink']}; outline: none;
    }}
    QCheckBox {{ background: transparent; spacing: 8px; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {c['rule_strong']}; background: {c['field']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

    /* 일반 버튼 */
    QPushButton {{
        background: {c['raised']}; border: 1px solid {c['rule_strong']}; border-radius: 8px;
        padding: 7px 14px; min-height: 18px; color: {c['ink']}; font-weight: 600;
    }}
    QPushButton:hover {{ background: {c['panel2']}; border-color: {c['ink_muted']}; }}
    QPushButton:pressed {{ background: {c['panel2']}; }}
    QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['rule']}; background: transparent; }}

    QPushButton#Primary {{ background: {c['accent']}; color: {c['accent_ink']}; border: none; font-weight: 700; }}
    QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#Primary:disabled {{ background: {c['rule']}; color: {c['disabled']}; }}

    /* 하단 촬영 도크 */
    QFrame#Dock {{ background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 12px; }}
    QFrame#Dock QLabel {{ background: transparent; }}
    QFrame#DockSep {{ background: {c['rule']}; }}
    QFrame#EyeSeg {{ background: {c['bg']}; border: 1px solid {c['rule']}; border-radius: 10px; }}
    QPushButton#EyeBtn {{
        background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 2px 6px; min-width: 40px; min-height: 34px;
        color: {c['ink_soft']}; font-family: Menlo, Consolas, "JetBrains Mono", monospace; font-size: 13px; font-weight: 700;
    }}
    QPushButton#EyeBtn:hover {{ color: {c['ink']}; }}
    QPushButton#EyeBtn:checked {{ background: {c['raised']}; border: 1px solid {c['rule_strong']}; color: {c['ink']}; }}
    QPushButton#EyeBtn[eye="OD"]:checked {{ color: {c['od']}; border: 1px solid {c['od']}; }}
    QPushButton#EyeBtn[eye="OS"]:checked {{ color: {c['os']}; border: 1px solid {c['os']}; }}
    QPushButton#EyeBtn[eye="OU"]:checked {{ color: {c['ou']}; border: 1px solid {c['ou']}; }}
    QPushButton#SmartBtn {{
        background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 2px 10px; min-height: 28px;
        color: {c['ink_soft']}; font-weight: 600;
    }}
    QPushButton#SmartBtn:hover {{ color: {c['ink']}; }}
    QPushButton#SmartBtn:checked {{ background: {c['accent_soft']}; border: 1px solid {c['accent']}; color: {c['accent_hover'] if mode == 'dark' else c['accent']}; }}
    QLabel#SmartTitle {{ color: {c['ink']}; font-weight: 700; padding-right: 4px; }}
    QLabel#SmartMeter {{ color: {c['ink_soft']}; font-family: Menlo, Consolas, "JetBrains Mono", monospace; font-size: 12px; padding: 0 3px; }}
    QLabel#SmartHint {{ color: {c['ink_soft']}; font-size: 12px; padding-left: 6px; }}
    QPushButton#ToolBtn, QPushButton#Pause, QPushButton#Freeze {{
        background: transparent; border: 1px solid transparent; color: {c['ink_soft']}; padding: 8px 12px;
    }}
    QPushButton#ToolBtn:hover, QPushButton#Pause:hover, QPushButton#Freeze:hover {{ background: {c['panel2']}; border-color: {c['rule']}; color: {c['ink']}; }}
    QPushButton#Pause:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['accent_hover'] if mode == 'dark' else c['accent']}; }}
    QPushButton#Freeze {{ color: {c['accent_hover'] if mode == 'dark' else c['accent']}; }}
    QPushButton#ToolBtn:disabled, QPushButton#Pause:disabled, QPushButton#Freeze:disabled {{ color: {c['disabled']}; background: transparent; border-color: transparent; }}
    QPushButton#Shutter {{
        background: {c['accent']}; color: {c['accent_ink']}; border: none; border-radius: 23px;
        padding: 6px 20px 6px 12px; min-height: 34px; font-size: 14px; font-weight: 700;
    }}
    QPushButton#Shutter:hover {{ background: {c['accent_hover']}; }}
    QPushButton#Shutter:disabled {{ background: {c['rule']}; color: {c['disabled']}; }}
    QPushButton#Record {{ background: transparent; color: {c['record']}; border: 1px solid transparent; padding: 8px 12px; font-weight: 700; }}
    QPushButton#Record:hover {{ background: {c['record_soft']}; }}
    QPushButton#Record:checked {{ background: {c['record']}; color: #ffffff; }}
    QPushButton#Record:disabled {{ color: {c['disabled']}; background: transparent; }}

    /* 상태바 */
    QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['rule']}; color: {c['ink_soft']}; }}
    QStatusBar QLabel {{ background: transparent; }}

    /* 스크롤 영역/바 */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['rule_strong']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['ink_muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['rule_strong']}; border-radius: 4px; min-width: 30px; }}

    /* 썸네일 */
    QPushButton#FilterChip {{
        background: transparent; border: 1px solid {c['rule']}; border-radius: 6px; padding: 3px 4px;
        color: {c['ink_soft']}; font-size: 11px; font-weight: 600; min-height: 16px;
    }}
    QPushButton#FilterChip:hover {{ color: {c['ink']}; border-color: {c['rule_strong']}; }}
    QPushButton#FilterChip:checked {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['rule_strong']}; border-bottom: 2px solid {c['accent']}; }}
    QFrame#ThumbSep {{ background: {c['rule']}; }}

    /* ===== Pro 모드 ===== */
    QFrame#ProToolbar {{ background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 12px; }}
    QFrame#ProSep {{ background: {c['rule']}; margin: 6px 4px; }}
    QFrame#ProSeg {{ background: {c['bg']}; border: 1px solid {c['rule']}; border-radius: 9px; }}
    QPushButton#ProBtn, QPushButton#ProCapture, QPushButton#ProGhost, QPushButton#ProPrimary, QPushButton#ProSegBtn {{
        padding: 6px 11px; font-weight: 600; font-size: 12px; border-radius: 7px;
    }}
    QPushButton#ProSegBtn {{ background: transparent; border: 1px solid transparent; color: {c['ink_soft']}; }}
    QPushButton#ProSegBtn:hover {{ background: {c['panel2']}; color: {c['ink']}; }}
    QPushButton#ProSegBtn:checked, QPushButton#ProBtn:checked {{ background: {c['accent']}; color: {c['accent_ink']}; border-color: {c['accent']}; }}
    QPushButton#ProGhost {{ background: transparent; border-color: transparent; color: {c['ink_soft']}; }}
    QPushButton#ProGhost:hover {{ background: {c['panel2']}; color: {c['ink']}; }}
    QPushButton#ProPrimary {{ background: {c['accent']}; color: {c['accent_ink']}; border: none; }}
    QPushButton#ProPrimary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#ProCapture {{ color: {c['accent_hover'] if mode == 'dark' else c['accent']}; border: 1px solid {c['accent']}; background: transparent; }}
    QPushButton#ProCapture:checked {{ background: {c['record']}; color: #ffffff; border-color: {c['record']}; }}
    QToolButton#ProTool {{
        background: {c['raised']}; border: 1px solid {c['rule_strong']}; border-radius: 8px;
        padding: 4px 2px; font-size: 11px; font-weight: 600; color: {c['ink']};
    }}
    QToolButton#ProTool:hover {{ background: {c['panel2']}; border-color: {c['ink_muted']}; }}
    QToolButton#ProTool:checked {{ background: {c['accent']}; color: {c['accent_ink']}; border-color: {c['accent']}; }}
    QToolButton#ProTool:disabled {{ color: {c['disabled']}; background: transparent; border-color: {c['rule']}; }}
    QStackedWidget#ProDisplay {{ background: #000000; border-radius: 12px; }}
    QFrame#ProSide {{ background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 12px; }}
    QFrame#ProCard {{ background: {c['panel2']}; border: 1px solid {c['rule']}; border-radius: 9px; }}
    QFrame#ProCard QLabel {{ background: transparent; }}
    QLabel#ProInfo {{
        background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 9px;
        padding: 7px 14px; color: {c['ink_soft']};
    }}
    QTabWidget#ProTabs::pane {{ border: none; }}
    QTabWidget#ProTabs QStackedWidget, QWidget#ProTabPage,
    QFrame#ProSide QScrollArea, QFrame#ProSide QWidget#qt_scrollarea_viewport {{ background: {c['panel']}; }}
    QTabWidget#ProTabs QTabBar {{ background: {c['bg']}; border: 1px solid {c['rule']}; border-radius: 9px; }}
    QTabWidget#ProTabs QTabBar::tab {{
        background: transparent; color: {c['ink_soft']}; padding: 6px 0; margin: 3px 2px; min-width: 76px;
        border: 1px solid transparent; border-radius: 6px; font-weight: 700;
    }}
    QTabWidget#ProTabs QTabBar::tab:selected {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['rule_strong']}; }}
    QTabWidget#ProTabs QTabBar::tab:hover {{ color: {c['ink']}; }}
    QFrame#ProTabGrid {{ background: {c['bg']}; border: 1px solid {c['rule']}; border-radius: 9px; }}
    QPushButton#ProTabBtn {{
        background: transparent; color: {c['ink_soft']}; padding: 5px 0; min-height: 22px;
        border: 1px solid transparent; border-radius: 6px; font-weight: 700;
    }}
    QPushButton#ProTabBtn:checked {{ background: {c['raised']}; color: {c['ink']}; border: 1px solid {c['rule_strong']}; }}
    QPushButton#ProTabBtn:hover {{ color: {c['ink']}; }}
    QLabel#Histogram {{ background: #070a0f; border: 1px solid {c['rule']}; border-radius: 7px; }}
    QFrame#MultiCell {{ background: #0a0d12; border: 1px solid #1d242f; border-radius: 6px; }}
    QFrame#MultiCell:hover {{ border: 2px solid {c['accent']}; }}
    QFrame#MultiCell[selected="true"] {{ border: 3px solid #facc15; }}
    QLabel#MultiCaption {{ background: transparent; color: #c7cdd8; font-size: 11px; }}
    QLabel#SelBadge {{
        background: #facc15; color: #111827; font-weight: 800; font-size: 11px;
        padding: 1px 8px; border-radius: 6px;
    }}
    QSlider {{ background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['rule_strong']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c['accent']}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
        border: 2px solid {c['panel']};
    }}
    QSlider#SliderR::handle:horizontal, QSlider#SliderR::sub-page:horizontal {{ background: #f87171; }}
    QSlider#SliderG::handle:horizontal, QSlider#SliderG::sub-page:horizontal {{ background: #4ade80; }}
    QSlider#SliderB::handle:horizontal, QSlider#SliderB::sub-page:horizontal {{ background: #60a5fa; }}

    QMenuBar {{ background: {c['panel']}; }}
    QMenuBar::item:selected {{ background: {c['panel2']}; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['rule_strong']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['ink']}; }}
    """


def make_app_icon() -> QIcon:
    """앱 아이콘. 브랜드 아이콘 파일이 있으면 그것을, 없으면 눈(eye) 아이콘을 벡터로 그려 생성."""
    path = _brand.asset(_brand.current().get("icon"))
    if path:
        return QIcon(path)
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render_icon(size))
    return icon


def _render_icon(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size

    # 둥근 사각 배경 (티얼)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#0d9488")))
    r = s * 0.14
    p.drawRoundedRect(QRectF(0, 0, s, s), r, r)

    # 눈 외곽 (아몬드형) — 흰색 스트로크
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.5, s * 0.055))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    cx, cy = s / 2, s / 2
    half_w = s * 0.34
    half_h = s * 0.20
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.moveTo(cx - half_w, cy)
    path.quadTo(cx, cy - half_h * 2.0, cx + half_w, cy)
    path.quadTo(cx, cy + half_h * 2.0, cx - half_w, cy)
    p.drawPath(path)

    # 홍채
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#ffffff")))
    ir = s * 0.145
    p.drawEllipse(QRectF(cx - ir, cy - ir, ir * 2, ir * 2))
    # 동공 (티얼)
    p.setBrush(QBrush(QColor("#0d9488")))
    pr = s * 0.07
    p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

    p.end()
    return pm
