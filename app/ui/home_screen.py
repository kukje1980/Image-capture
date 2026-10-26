"""시작(홈) 화면 — 큰 아이콘 메뉴로 바로 가기: 신규 환자 · 환자 목록 · 촬영 · Pro 검토 · 검사 기록 · 설정.

참고한 장비 프로그램의 Welcome 화면처럼, 왼쪽에 인사말, 오른쪽에 아이콘 타일을 둔다.
'다음부터 촬영 화면으로 바로 시작' 을 켜면 config.start_screen = "capture".
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import brand as app_brand
from app.ui import icons
from app.ui.theme import ICON_ACCENT

# (동작 id, 이름, 아이콘, 설명)
TILES = [
    ("newPatient", "신규 환자", "user-plus", "환자 정보를 등록하고 촬영을 시작합니다"),
    ("patients", "환자 목록", "list", "등록된 환자를 검색·선택합니다"),
    ("capture", "촬영", "camera", "슬릿램프 실시간 영상 · 사진 캡처 · 녹화"),
    ("pro", "Pro 검토", "review", "MULTI · 비교 · 보정 · 편집 · 인쇄"),
    ("exam", "검사 기록", "clipboard", "촬영일별 영상과 소견을 한눈에"),
    ("settings", "설정", "sliders", "카메라 · 저장 위치 · 형식"),
]


class HomeScreen(QWidget):
    action = Signal(str)          # TILES 의 동작 id
    startScreenChanged = Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("Home")
        root = QHBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 28)
        root.setSpacing(40)

        # 왼쪽: 인사말 + 안내
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addStretch(2)
        hello = QLabel("환영합니다")
        hello.setObjectName("HomeTitle")
        sub = QLabel(app_brand.current()["app_name"])
        sub.setObjectName("HomeSub")
        guide = QLabel("환자를 등록하거나 선택한 뒤 촬영을 시작하세요.\n"
                       "촬영한 사진·동영상은 환자별로 저장되고, 검사 기록에서 소견과 함께 볼 수 있습니다.")
        guide.setObjectName("HomeGuide")
        guide.setWordWrap(True)
        left.addWidget(hello)
        left.addWidget(sub)
        left.addSpacing(10)
        left.addWidget(guide)
        left.addStretch(3)
        links = QHBoxLayout()
        links.setSpacing(14)
        self.btn_keys = self._link("단축키 안내", "keyboard")
        self.btn_keys.clicked.connect(lambda: self.action.emit("shortcuts"))
        links.addWidget(self.btn_keys)
        links.addStretch(1)
        left.addLayout(links)
        self.chk_skip = QCheckBox("다음부터 촬영 화면으로 바로 시작")
        self.chk_skip.setChecked(getattr(config, "start_screen", "home") == "capture")
        self.chk_skip.toggled.connect(self._on_skip)
        left.addSpacing(8)
        left.addWidget(self.chk_skip)
        root.addLayout(left, 4)

        # 오른쪽: 아이콘 타일
        grid_box = QFrame()
        grid_box.setObjectName("HomeTiles")
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        self.tiles: dict[str, QToolButton] = {}
        for i, (aid, text, icon, tip) in enumerate(TILES):
            b = QToolButton()
            b.setObjectName("HomeTile")
            b.setText(text)
            b.setToolTip(tip)
            b.setIcon(icons.icon(icon, ICON_ACCENT, 40, disabled="#4a5262"))
            b.setIconSize(QSize(40, 40))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFixedSize(176, 132)
            b.clicked.connect(lambda _=False, a=aid: self.action.emit(a))
            self.tiles[aid] = b
            grid.addWidget(b, i // 3, i % 3)
        wrap = QVBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(grid_box, 0, Qt.AlignmentFlag.AlignCenter)
        wrap.addStretch(1)
        root.addLayout(wrap, 6)

    @staticmethod
    def _link(text: str, icon: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("HomeLink")
        b.setText(text)
        b.setIcon(icons.icon(icon, "#98a2b3", 18))
        b.setIconSize(QSize(18, 18))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    def _on_skip(self, on: bool) -> None:
        self.config.start_screen = "capture" if on else "home"
        try:
            self.config.save()
        except Exception:  # noqa: BLE001
            pass
        self.startScreenChanged.emit(self.config.start_screen)
