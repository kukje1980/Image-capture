"""안저 검토 화면 아래 타임라인 — 촬영일별(최신 먼저)로 묶은 가로 썸네일 띠. 접을 수 있다."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.fundus.viewport import CAPTURE_MIME
from app.ui.theme import EYE_COLORS, palette
from app.ui.thumbnail_panel import day_label
from app.ui.thumbnail_widget import _load_pixmap
from app.ui.video_view import scaled_font

THUMB_W, THUMB_H = 108, 81


class TimelineThumb(QWidget):
    clicked = Signal(object)  # Capture

    def __init__(self, capture, parent=None):
        super().__init__(parent)
        self.capture = capture
        self._pm = _load_pixmap(capture)
        self._hover = False
        self._shown = False
        self._press = None
        self._accent = palette("dark")["accent"]
        self.setFixedSize(THUMB_W, THUMB_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        eye = capture.eye if capture.eye in ("OD", "OS") else "안구 미지정"
        self.setToolTip(" · ".join(x for x in (capture.captured_at, eye, capture.note or "") if x)
                        + "\n클릭 또는 뷰포트로 끌어다 놓기")

    def set_shown(self, on: bool) -> None:
        if on != self._shown:
            self._shown = on
            self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        c = self.capture
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor("#000000"))
        if self._pm is not None:
            s = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s)
        f = scaled_font(self.font(), 0.8, True)
        p.setFont(f)
        # 시각
        when = (c.captured_at or "")[11:16]
        band = QRectF(1, self.height() - 17, self.width() - 2, 16)
        p.fillRect(band, QColor(0, 0, 0, 170))
        p.setPen(QColor("#e7eaf0"))
        p.drawText(band.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, when)
        # 안구 배지
        eye = c.eye if c.eye in ("OD", "OS") else "?"
        col = EYE_COLORS.get(eye, "#a3acba")
        br = QRectF(5, 5, p.fontMetrics().horizontalAdvance(eye) + 12, 17)
        p.setPen(QPen(QColor(col), 1))
        p.setBrush(QColor(8, 11, 16, 200))
        p.drawRoundedRect(br, 5, 5)
        p.setPen(QColor(col))
        p.drawText(br, Qt.AlignmentFlag.AlignCenter, eye)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._shown or self._hover:
            p.setPen(QPen(QColor(self._accent), 2))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawRect(r)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._press is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        if (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(CAPTURE_MIME, QByteArray(str(self.capture.id).encode("ascii")))
        drag.setMimeData(mime)
        if self._pm is not None:
            drag.setPixmap(self._pm.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit(self.capture)


class _HScroll(QScrollArea):
    """세로 휠로 가로 스크롤."""

    def wheelEvent(self, e) -> None:  # noqa: N802
        d = e.angleDelta().y() or e.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - d)
        e.accept()


class FundusTimeline(QFrame):
    captureClicked = Signal(object)  # Capture

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self._thumbs: list[TimelineThumb] = []
        self._days: list[str] = []
        self._current_day = ""
        self._accent = palette("dark")["accent"]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.b_toggle = QPushButton("▾ 타임라인")
        self.b_toggle.setObjectName("ProGhost")
        self.b_toggle.setCheckable(True)
        self.b_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.b_toggle.setToolTip("타임라인 접기 / 펼치기")
        self.b_toggle.toggled.connect(self.set_collapsed)
        self._badge = QLabel("")
        self._badge.setObjectName("CountBadge")
        self._hint = QLabel("사진을 누르거나 화면으로 끌어다 놓으면 그 자리에 뜹니다")
        self._hint.setObjectName("Muted")
        head.addWidget(self.b_toggle)
        head.addWidget(self._badge)
        head.addWidget(self._hint)
        head.addStretch(1)
        lay.addLayout(head)

        self._scroll = _HScroll()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(THUMB_H + 44)
        self._inner = QWidget()
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(14)
        self._scroll.setWidget(self._inner)
        lay.addWidget(self._scroll)

    # ---- 공개 API ----
    def set_captures(self, captures: list, current_day: str = "") -> None:
        """captures: 최신 먼저 정렬된 안저 사진 목록. current_day: '현재' 검사일 (표시용)."""
        while self._row.count():
            w = self._row.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._thumbs = []
        self._days = []
        groups: dict[str, list] = {}
        for c in captures:
            groups.setdefault((c.captured_at or "")[:10], []).append(c)
        self._badge.setText(f"검사 {len(groups)}회 · {len(captures)}장")
        self._current_day = current_day
        for day, items in groups.items():
            self._days.append(day)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            cur = bool(current_day) and day == current_day
            h = QLabel(f"{day_label(day)}   ·   {len(items)}장" + ("   ·   현재" if cur else ""))
            h.setObjectName("DayHeader")
            if cur:                              # '현재' 검사 표시
                h.setStyleSheet(f"color: {self._accent}; font-weight: 700;")
            v.addWidget(h)
            line = QHBoxLayout()
            line.setSpacing(5)
            for c in items:
                t = TimelineThumb(c)
                t.clicked.connect(self.captureClicked.emit)
                line.addWidget(t)
                self._thumbs.append(t)
            line.addStretch(1)
            v.addLayout(line)
            self._row.addWidget(box)
        self._row.addStretch(1)                  # 왼쪽부터 채움

    def thumbs(self) -> list:
        return list(self._thumbs)

    def days(self) -> list[str]:
        return list(self._days)

    def current_day(self) -> str:
        return self._current_day

    def set_shown_ids(self, ids) -> None:
        """뷰포트에 떠 있는 영상을 표시."""
        ids = set(ids)
        for t in self._thumbs:
            t.set_shown(t.capture.id in ids)

    def is_collapsed(self) -> bool:
        return self.b_toggle.isChecked()

    def set_collapsed(self, on: bool) -> None:
        if self.b_toggle.isChecked() != on:
            self.b_toggle.setChecked(on)
            return
        self._scroll.setVisible(not on)
        self._hint.setVisible(not on)
        self.b_toggle.setText(("▸" if on else "▾") + " 타임라인")
