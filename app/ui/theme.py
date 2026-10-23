"""앱 테마(QSS) + 윈도우 아이콘.

웹 버전과 동일한 임상용 티얼(teal) 팔레트를 사용. light / dark 지원.
Fusion 스타일 위에 QSS를 올려 OS와 무관하게 일관된 외형을 보장한다.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

# 팔레트 (웹 app.css 와 동일 계열)
LIGHT = {
    "bg": "#f5f7fa", "panel": "#ffffff", "panel2": "#eef2f7",
    "ink": "#0f172a", "ink_soft": "#475569", "ink_muted": "#94a3b8",
    "rule": "#e2e8f0", "accent": "#0d9488", "accent_hover": "#0f766e",
    "accent_soft": "#ccfbf1", "record": "#dc2626", "record_hover": "#b91c1c",
    "record_soft": "#fee2e2", "field": "#ffffff", "shadow": "rgba(15,23,42,0.08)",
    "disabled": "#cbd5e1",
}
DARK = {
    "bg": "#0b1220", "panel": "#131b2c", "panel2": "#1a2437",
    "ink": "#e2e8f0", "ink_soft": "#94a3b8", "ink_muted": "#64748b",
    "rule": "#1e293b", "accent": "#14b8a6", "accent_hover": "#2dd4bf",
    "accent_soft": "#0e3831", "record": "#f87171", "record_hover": "#ef4444",
    "record_soft": "#3b1a1a", "field": "#0f172a", "shadow": "rgba(0,0,0,0.5)",
    "disabled": "#334155",
}


def palette(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT


def build_qss(mode: str = "light") -> str:
    c = palette(mode)
    return f"""
    QWidget {{
        background: {c['bg']};
        color: {c['ink']};
        font-family: "Pretendard", "Malgun Gothic", "맑은 고딕", "Segoe UI", sans-serif;
        font-size: 14px;
    }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}

    /* 패널 역할 위젯 */
    QFrame#Panel, #PatientPanel, #ThumbnailPanel {{
        background: {c['panel']};
        border: 1px solid {c['rule']};
        border-radius: 10px;
    }}

    /* 라벨 */
    QLabel {{ background: transparent; color: {c['ink']}; }}
    QLabel#Muted {{ color: {c['ink_soft']}; }}
    QLabel#StatusLabel {{ color: {c['ink_soft']}; }}
    QLabel#PanelHeader {{
        color: {c['ink_soft']}; font-weight: 700; font-size: 11px;
        padding: 10px 12px; letter-spacing: 1px;
    }}

    /* 입력/콤보 */
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QDateEdit {{
        background: {c['field']};
        border: 1px solid {c['rule']};
        border-radius: 6px;
        padding: 6px 10px;
        min-height: 22px;
        selection-background-color: {c['accent']};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus {{
        border: 1px solid {c['accent']};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c['panel']};
        border: 1px solid {c['rule']};
        selection-background-color: {c['accent_soft']};
        selection-color: {c['ink']};
        outline: none;
    }}

    /* 일반 버튼 */
    QPushButton {{
        background: {c['panel']};
        border: 1px solid {c['rule']};
        border-radius: 6px;
        padding: 7px 14px;
        min-height: 20px;
        color: {c['ink']};
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {c['panel2']}; }}
    QPushButton:pressed {{ background: {c['panel2']}; }}
    QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['rule']}; }}

    /* 주요(캡처) 버튼 */
    QPushButton#Primary {{
        background: {c['accent']}; color: #ffffff; border: none; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#Primary:disabled {{ background: {c['disabled']}; color: {c['panel']}; }}

    /* 녹화 버튼 */
    QPushButton#Record {{
        background: transparent; color: {c['record']};
        border: 1px solid {c['record']}; font-weight: 600;
    }}
    QPushButton#Record:hover {{ background: {c['record_soft']}; }}
    QPushButton#Record:checked {{ background: {c['record']}; color: #ffffff; border: none; }}
    QPushButton#Record:disabled {{ color: {c['disabled']}; border-color: {c['rule']}; }}

    /* 일시정지 / 4분할 토글 */
    QPushButton#Pause:checked {{
        background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['accent_hover']};
    }}

    /* 정지영상 버튼 */
    QPushButton#Freeze {{
        background: {c['panel']}; color: {c['accent_hover']};
        border: 1px solid {c['accent']}; font-weight: 600;
    }}
    QPushButton#Freeze:hover {{ background: {c['accent_soft']}; }}
    QPushButton#Freeze:disabled {{ color: {c['disabled']}; border-color: {c['rule']}; }}

    /* 툴바 */
    QToolBar {{ background: {c['panel']}; border-bottom: 1px solid {c['rule']}; spacing: 4px; padding: 4px 6px; }}
    QToolBar QToolButton {{ background: transparent; border-radius: 6px; padding: 6px 12px; color: {c['ink']}; }}
    QToolBar QToolButton:hover {{ background: {c['panel2']}; }}

    /* 상태바 */
    QStatusBar {{ background: {c['panel']}; border-top: 1px solid {c['rule']}; color: {c['ink_soft']}; }}

    /* 스크롤 영역/바 */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['rule']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['ink_muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

    /* 썸네일 카드 */
    QFrame#ThumbCard {{ background: {c['panel2']}; border: 2px solid transparent; border-radius: 8px; }}
    QFrame#ThumbCard:hover {{ border: 2px solid {c['accent']}; }}

    /* ===== Pro 모드 ===== */
    QFrame#ProToolbar {{
        background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 10px;
    }}
    QFrame#ProSep {{ background: {c['rule']}; margin: 4px 6px; }}
    QPushButton#ProBtn, QPushButton#ProCapture {{
        padding: 6px 10px; font-weight: 600; font-size: 13px;
    }}
    QPushButton#ProBtn:checked {{
        background: {c['accent']}; color: #ffffff; border-color: {c['accent']};
    }}
    QPushButton#ProCapture {{ color: {c['accent_hover']}; border: 1px solid {c['accent']}; }}
    QPushButton#ProCapture:checked {{ background: {c['record']}; color: #ffffff; border-color: {c['record']}; }}
    QStackedWidget#ProDisplay {{ background: #000000; border-radius: 10px; }}
    QFrame#ProSide {{
        background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 10px;
    }}
    QLabel#ProInfo {{
        background: {c['panel']}; border: 1px solid {c['rule']}; border-radius: 8px;
        padding: 8px 14px; color: {c['ink']};
    }}
    QFrame#MultiCell {{ background: #0b0f17; border: 2px solid #1e293b; border-radius: 6px; }}
    QFrame#MultiCell:hover {{ border-color: {c['accent']}; }}
    QFrame#MultiCell[selected="true"] {{ border: 3px solid #facc15; }}
    QLabel#MultiCaption {{ background: transparent; color: #cbd5e1; font-size: 11px; }}
    QLabel#SelBadge {{
        background: #facc15; color: #0f172a; font-weight: 700; font-size: 11px;
        padding: 2px 8px; border-radius: 8px;
    }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['rule']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c['accent']}; width: 14px; margin: -6px 0; border-radius: 7px;
    }}

    QMenuBar {{ background: {c['panel']}; }}
    QMenuBar::item:selected {{ background: {c['panel2']}; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['rule']}; }}
    QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['ink']}; }}
    """


def make_app_icon() -> QIcon:
    """슬릿램프를 상징하는 눈(eye) 아이콘을 벡터로 그려 QIcon 생성."""
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
