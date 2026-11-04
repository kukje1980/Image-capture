"""안저판 하단 도크: 새 사진 안구(OD/OS/OU) + 자동 가져오기 켜기/끄기 + 사진 가져오기 + 안구 수정 + 상태.

실시간 영상이 없으므로 슬릿램프판의 캡처·녹화·4분할 대신, 안저카메라가 폴더에 저장한 사진을
자동으로 받아 오는 데 필요한 조작만 둔다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy

from app.ui import icons
from app.ui.theme import ICON, ICON_ACCENT, ICON_ON_ACCENT

EYE_CODES = ["NA", "OD", "OS", "OU"]
_EYE_BUTTONS = [("OD", "OD", "우안"), ("OS", "OS", "좌안"), ("OU", "OU", "양안"), ("NA", "—", "미지정")]
EYE_KO = {"OD": "OD 우안", "OS": "OS 좌안", "OU": "OU 양안", "NA": "미지정"}
_DOT = {"ok": "#3ccf7a", "warn": "#f5a524", "error": "#f0524f"}


class _ElideLabel(QLabel):
    """남은 폭에 맞춰 가운데를 '…'로 줄여 보이는 상태 글자 (버튼 자리를 빼앗지 않게)."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(10, self.width())))


class FundusBar(QFrame):
    eyeChanged = Signal(str)
    watchToggled = Signal(bool)
    importClicked = Signal()
    fixEyeRequested = Signal(str)        # 지금 보이는 사진의 안구를 이 값으로

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Dock")
        self._eye = "NA"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(6)

        cap = QLabel("새 사진")
        cap.setObjectName("Muted")
        cap.setToolTip("다음에 들어올 사진의 안구.\n파일 이름에 R/L·OD/OS·우안/좌안 이 있으면 그것을 따릅니다 (설정).")
        lay.addWidget(cap)
        seg = QFrame()
        seg.setObjectName("EyeSeg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.eye_group = QButtonGroup(self)
        self.eye_buttons: dict[str, QPushButton] = {}
        for code, text, ko in _EYE_BUTTONS:
            b = QPushButton(text)
            b.setObjectName("EyeBtn")
            b.setProperty("eye", code)
            b.setCheckable(True)
            b.setToolTip(f"새 사진 안구: {ko}")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.eye_group.addButton(b)
            self.eye_buttons[code] = b
            sl.addWidget(b)
            b.clicked.connect(lambda _=False, c=code: self.set_eye(c))
        self.eye_buttons["NA"].setChecked(True)
        lay.addWidget(seg)
        lay.addWidget(self._sep())

        self.btn_watch = self._button("자동 가져오기", "live", "Pause", checkable=True,
                                      tip="안저카메라 사진 폴더 감시 켜기/끄기\n(꺼져 있는 동안 저장된 사진은 '사진 가져오기'로 등록)")
        self.btn_import = self._button("사진 가져오기", "folder", "Shutter", color=ICON_ON_ACCENT,
                                       tip="사진 파일을 직접 골라 지금 환자에게 등록")
        self.btn_import.setMinimumWidth(140)
        self.btn_fix = self._button("안구 수정", "eye", "ToolBtn", tip="화면에 보이는 사진의 안구 바꾸기")
        menu = QMenu(self.btn_fix)
        for code in ("OD", "OS", "OU", "NA"):
            act = menu.addAction(EYE_KO[code])
            act.triggered.connect(lambda _=False, c=code: self.fixEyeRequested.emit(c))
        self.btn_fix.setMenu(menu)
        lay.addWidget(self.btn_watch)
        lay.addSpacing(8)
        lay.addWidget(self.btn_import)
        lay.addWidget(self.btn_fix)
        lay.addSpacing(10)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status = _ElideLabel("준비")
        self.status.setObjectName("StatusLabel")
        lay.addWidget(self.status_dot)
        lay.addWidget(self.status, 1)
        self.set_status("준비")

        self.btn_watch.toggled.connect(self._on_watch)
        self.btn_import.clicked.connect(self.importClicked.emit)
        self.set_import_enabled(False)
        self.set_fix_enabled(False)

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setObjectName("DockSep")
        f.setFixedSize(1, 28)
        return f

    @staticmethod
    def _button(text, icon_name, obj, checkable=False, color=ICON, tip="") -> QPushButton:
        b = QPushButton(icons.gap(text))
        b.setObjectName(obj)
        b.setCheckable(checkable)
        b.setIcon(icons.icon(icon_name, color, 18))
        b.setIconSize(QSize(16, 16))
        b.setMinimumHeight(40)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tip:
            b.setToolTip(tip)
        return b

    # ---- 안구 ----
    def current_eye(self) -> str:
        return self._eye

    def set_eye(self, code: str) -> None:
        if code not in EYE_CODES:
            return
        self._eye = code
        self.eye_buttons[code].setChecked(True)
        self.eyeChanged.emit(code)

    # ---- 상태 ----
    def _on_watch(self, on: bool) -> None:
        self._sync_watch_icon(on)
        self.watchToggled.emit(on)

    def _sync_watch_icon(self, on: bool) -> None:
        self.btn_watch.setText(icons.gap("자동 가져오기" if on else "자동 꺼짐"))
        self.btn_watch.setIcon(icons.icon("live" if on else "pause", ICON_ACCENT if on else ICON, 18))

    def set_watch_state(self, on: bool) -> None:
        """신호 없이 버튼 표시만 맞춘다 (설정에서 바뀐 경우 등)."""
        self.btn_watch.blockSignals(True)
        self.btn_watch.setChecked(on)
        self.btn_watch.blockSignals(False)
        self._sync_watch_icon(on)

    def set_import_enabled(self, on: bool) -> None:
        self.btn_import.setEnabled(on)

    def set_fix_enabled(self, on: bool) -> None:
        self.btn_fix.setEnabled(on)

    def set_status(self, text: str, level: str = "ok") -> None:
        self.status.set_full_text(text)
        self.status_dot.setStyleSheet(f"background:{_DOT.get(level, _DOT['ok'])};border-radius:4px;")
