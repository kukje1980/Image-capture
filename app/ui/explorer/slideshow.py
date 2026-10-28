"""슬라이드쇼 — 고른 영상을 전체 화면으로 차례대로 보여 준다 (환자 설명·학술 발표용).

  Space 일시정지/재개   ← → 이전/다음   + − 넘김 간격   Home/End 처음/끝   Esc 닫기
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.ui.video_view import draw_chip


class SlideShow(QWidget):
    closed = Signal()

    def __init__(self, items: list, seconds: int = 3, parent=None):
        """items: [(이미지 경로, 캡션), ...]"""
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("슬라이드쇼")
        self.setStyleSheet("background:#000;")
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._items = items
        self._idx = 0
        self._pm: QPixmap | None = None
        self.seconds = max(1, int(seconds))
        self.paused = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.next)
        self._load()
        self._timer.start(self.seconds * 1000)

    def index(self) -> int:
        return self._idx

    def _load(self) -> None:
        if not self._items:
            self._pm = None
            return
        pm = QPixmap(self._items[self._idx][0])
        self._pm = None if pm.isNull() else pm
        self.update()

    def go(self, idx: int) -> None:
        if self._items:
            self._idx = idx % len(self._items)
            self._load()
            if not self.paused:
                self._timer.start(self.seconds * 1000)   # 직접 넘겼으면 간격을 처음부터

    def next(self) -> None:
        self.go(self._idx + 1)

    def prev(self) -> None:
        self.go(self._idx - 1)

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self._timer.stop() if self.paused else self._timer.start(self.seconds * 1000)
        self.update()

    def set_seconds(self, s: int) -> None:
        self.seconds = min(30, max(1, int(s)))
        if not self.paused:
            self._timer.start(self.seconds * 1000)
        self.update()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.close()
        elif k == Qt.Key.Key_Space:
            self.toggle_pause()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_Down):
            self.next()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Up):
            self.prev()
        elif k == Qt.Key.Key_Home:
            self.go(0)
        elif k == Qt.Key.Key_End:
            self.go(len(self._items) - 1)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_seconds(self.seconds + 1)
        elif k == Qt.Key.Key_Minus:
            self.set_seconds(self.seconds - 1)
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.prev() if e.button() == Qt.MouseButton.RightButton else self.next()

    def closeEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        self.closed.emit()
        super().closeEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#000"))
        W, H = self.width(), self.height()
        if self._pm is not None:
            pm = self._pm.scaled(W, H, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((W - pm.width()) // 2, (H - pm.height()) // 2, pm)
        else:
            p.setPen(QColor("#8b95a3"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "영상을 불러올 수 없습니다")
        if not self._items:
            return
        f = QFont(self.font())
        f.setPointSizeF(max(10.0, H / 70))
        p.setFont(f)
        cap = self._items[self._idx][1]
        state = "일시정지" if self.paused else f"{self.seconds}초"
        draw_chip(p, 18, 18, f"{self._idx + 1} / {len(self._items)}  ·  {state}")
        if cap:
            p.setPen(QColor("#e7eaf0"))
            p.drawText(QRectF(0, H - H / 14, W, H / 16), Qt.AlignmentFlag.AlignCenter, cap)
