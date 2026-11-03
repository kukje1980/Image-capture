"""썸네일 패널의 단일 항목 (클릭 가능): 4:3 영상 + 안구 배지(사진 위 OD/OS/OU/미지정) + 시각·코멘트 오버레이."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.models.capture import Capture
from app.ui import icons
from app.ui.theme import EYE_COLORS
from app.ui.video_view import scaled_font

_cache: dict[str, QPixmap] = {}
_EYE_TEXT = {"OD": "#04192f", "OS": "#2a1700", "OU": "#1b0f3a"}   # 색 배지 위 글자색 (어두운 톤)


def eye_label(eye: str | None) -> tuple[str, str, str]:
    """사진 위 안구 배지 (글자, 배경색, 글자색). 지정 안 한 사진은 회색 '미지정'."""
    if eye in _EYE_TEXT:
        return eye, EYE_COLORS[eye], _EYE_TEXT[eye]
    return "미지정", "#3a4352", "#c3cad4"


def _load_pixmap(capture: Capture) -> QPixmap | None:
    path = capture.thumbnail_path
    if not path and capture.media_type == "photo":
        path = capture.file_path
    if not path:
        return None
    pm = _cache.get(path)
    if pm is None:
        pm = QPixmap(path)
        if pm.isNull():
            return None
        if pm.width() > 480:
            pm = pm.scaledToWidth(480, Qt.TransformationMode.SmoothTransformation)
        _cache[path] = pm
    return pm


class ThumbnailWidget(QWidget):
    clicked = Signal(object)        # Capture — 한 번 클릭 (촬영 화면: 선택)
    doubleClicked = Signal(object)  # Capture — 두 번 클릭 (큰 화면으로 보기)
    rightClicked = Signal(object)   # Capture — 오른쪽 클릭 (촬영 화면: 멀티로 모아 보기)

    def __init__(self, capture: Capture, parent=None):
        super().__init__(parent)
        self.capture = capture
        self.setObjectName("ThumbCard")
        self._pm = _load_pixmap(capture)
        self._hover = False
        self._rank = 0                  # 선택 순서 (0 = 선택 안 됨)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(72, 54)            # 2 · 3열로 놓아도 줄어들 수 있게 (높이는 너비의 3/4)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        eye = capture.eye if capture.eye and capture.eye != "NA" else ""
        self.setToolTip(" · ".join(x for x in (capture.captured_at, eye, capture.note or "") if x))

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return int(w * 3 / 4)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def resizeEvent(self, e) -> None:  # noqa: N802
        self.setFixedHeight(self.heightForWidth(self.width()))
        super().resizeEvent(e)

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
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(r, 9, 9)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 9, 9)
        p.setClipPath(clip)
        if self._pm is not None:
            s = self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s)
        else:
            p.drawPixmap(self.width() // 2 - 15, self.height() // 2 - 15,
                         icons.pixmap("play" if c.media_type == "video" else "image", "#6b7586", 30))
        small = self.width() < 130                 # 2 · 3열의 작은 카드
        # 하단 그라데이션 + 시각·코멘트
        gh = 38 if small else 44
        g = QLinearGradient(0, self.height() - gh, 0, self.height())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 215))
        p.fillRect(QRectF(0, self.height() - gh, self.width(), gh), g)
        f = scaled_font(self.font(), 0.8 if small else 0.85, True)
        p.setFont(f)
        when = c.captured_at[-8:] if c.captured_at else ""
        note = c.note or ""
        y = self.height() - (31 if note else 19) if small else self.height() - (32 if note else 20)
        pad = 6 if small else 8
        p.setPen(QColor("#e7eaf0"))
        p.drawText(QRectF(pad, y, self.width() - 2 * pad, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, when)
        if note:
            p.setFont(scaled_font(self.font(), 0.8 if small else 0.85))
            p.setPen(QColor("#a3acba"))
            el = p.fontMetrics().elidedText(note, Qt.TextElideMode.ElideRight, self.width() - 2 * pad)
            p.drawText(QRectF(pad, y + 15, self.width() - 2 * pad, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, el)
        # 안구 배지 (사진 위 왼쪽, 색이 채워진 큰 글자 — 미지정은 회색) + 동영상 길이
        text, bg, fg = eye_label(c.eye)
        p.setFont(scaled_font(self.font(), 0.9 if small else 1.05, True))
        fm = p.fontMetrics()
        bh = fm.height() + 4
        br = QRectF(5, 5, fm.horizontalAdvance(text) + 14, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(br, 5, 5)
        p.setPen(QColor(fg))
        p.drawText(br, Qt.AlignmentFlag.AlignCenter, text)
        if c.media_type == "video":
            p.setFont(f)
            vt = f"▶ {round((c.duration_ms or 0) / 1000)}s"
            vr = QRectF(br.right() + 4, 5 + (bh - 18) / 2, p.fontMetrics().horizontalAdvance(vt) + 12, 18)
            p.setPen(QPen(QColor("#ff8a87"), 1))
            p.setBrush(QColor(8, 11, 16, 190))
            p.drawRoundedRect(vr, 5, 5)
            p.setPen(QColor("#ff8a87"))
            p.drawText(vr, Qt.AlignmentFlag.AlignCenter, vt)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._rank:
            p.setPen(QPen(QColor("#facc15"), 3))
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 9, 9)
            # 오른쪽 위 선택 번호
            p.setFont(scaled_font(self.font(), 0.95, True))
            br = QRectF(self.width() - 31, 5, 26, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#facc15"))
            p.drawRoundedRect(br, 6, 6)
            p.setPen(QColor("#111827"))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, str(self._rank))
        else:
            p.setPen(QPen(QColor("#33c2b1"), 2) if self._hover else QPen(QColor(255, 255, 255, 18), 1))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)

    def set_rank(self, rank: int) -> None:
        if rank != self._rank:
            self._rank = rank
            self.update()

    def rank(self) -> int:
        return self._rank

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.capture)
        elif event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(self.capture)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit(self.capture)
