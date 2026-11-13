"""안저 검토 화면의 영상 뷰포트 — 휠 확대(커서 기준)·끌어서 이동·더블클릭 맞춤, 안구/일시 오버레이."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QToolButton, QWidget

from app.ui.pro.pro_workspace import load_bgr
from app.ui.theme import EYE_COLORS, palette
from app.ui.thumbnail_panel import day_label
from app.ui.video_view import scaled_font

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

CAPTURE_MIME = "application/x-slitlamp-capture-id"
VIEW_MODES = ("color", "redfree", "choroid")
_MAX_ZOOM = 16.0            # 화면 px / 영상 px
_LEVEL_MIN_SIDE = 1200      # 축소 단계(밉맵)를 만들 최소 크기


def capture_label(cap) -> str:
    """'OD · 2026.10.23 (금) 10:30:00' 형태의 영상 설명."""
    if cap is None:
        return ""
    at = cap.captured_at or ""
    eye = cap.eye if cap.eye in ("OD", "OS") else ""
    return " · ".join(x for x in (eye, f"{day_label(at[:10])} {at[11:]}".strip()) if x)


class FundusViewport(QWidget):
    activated = Signal()                 # 클릭 → 활성 뷰포트
    viewChanged = Signal()               # 사용자가 확대·이동함 (연동용)
    changed = Signal()                   # 화면에 보이는 내용이 바뀜 (확대창 갱신용)
    magnifierRequested = Signal(QPoint)  # 가운데 버튼 클릭 위치 (뷰포트 좌표)
    captureDropped = Signal(int)         # 타임라인에서 끌어다 놓은 영상 id
    priorStep = Signal(int)              # +1 = 더 이전 검사, -1 = 더 최근 검사

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FundusViewport")
        self.setMinimumSize(240, 200)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._capture = None
        self._bgr: np.ndarray | None = None
        self._mode = "color"
        self._levels: list[tuple[int, QImage]] = []
        self._zoom = 1.0
        self._cx = 0.0
        self._cy = 0.0
        self._fit = True
        self._active = False
        self._tag = ""
        self._placeholder = "영상 없음"
        self._drag_from: QPointF | None = None
        self._accent = palette("dark")["accent"]

        self.b_older = self._nav_button("◀", "더 이전 검사 ([)", 1)
        self.b_newer = self._nav_button("▶", "더 최근 검사 (])", -1)
        self.set_prior_nav(False)

    def _nav_button(self, text: str, tip: str, delta: int) -> QToolButton:
        b = QToolButton(self)
        b.setObjectName("FundusNav")
        b.setText(text)
        b.setToolTip(tip)
        b.setFixedSize(28, 24)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda: self.priorStep.emit(delta))
        return b

    # ================= 영상 / 상태 =================
    def set_capture(self, capture, tag: str = "", image: np.ndarray | None = None) -> None:
        """영상(Capture)을 표시한다. None 이면 비움. image 를 주면 파일을 다시 읽지 않는다."""
        self._capture = capture
        self._tag = tag
        self._bgr = None if capture is None else (image if image is not None else load_bgr(capture.file_path))
        self._rebuild_display()
        self.fit()

    def capture(self):
        return self._capture

    def has_image(self) -> bool:
        return bool(self._levels)

    def image_size(self) -> tuple[int, int]:
        if self._bgr is None:
            return 0, 0
        return self._bgr.shape[1], self._bgr.shape[0]

    def tag(self) -> str:
        return self._tag

    def set_tag(self, tag: str) -> None:
        self._tag = tag
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def label_text(self) -> str:
        return capture_label(self._capture)

    def set_active(self, on: bool) -> None:
        if on != self._active:
            self._active = on
            self.update()

    def is_active(self) -> bool:
        return self._active

    def set_prior_nav(self, visible: bool, can_older: bool = False, can_newer: bool = False) -> None:
        """비교 단계에서 이전 검사를 넘기는 ◀ ▶ 버튼."""
        for b, en in ((self.b_older, can_older), (self.b_newer, can_newer)):
            b.setVisible(visible)
            b.setEnabled(en)
        self._place_nav()

    def view_mode(self) -> str:
        return self._mode

    def set_view_mode(self, mode: str) -> None:
        mode = mode if mode in VIEW_MODES else "color"
        if mode != self._mode:
            self._mode = mode
            self._rebuild_display()
            self.update()
            self.changed.emit()

    def display_array(self) -> np.ndarray | None:
        """현재 보기(컬러 / 감각망막 / 맥락막)로 변환한 영상 — 컬러는 RGB, 나머지는 단일 채널."""
        if self._bgr is None:
            return None
        if self._mode == "redfree":              # 적색 제거 = 녹색 채널
            return np.ascontiguousarray(self._bgr[..., 1])
        if self._mode == "choroid":              # 녹색 제거 = 적색 채널
            return np.ascontiguousarray(self._bgr[..., 2])
        return np.ascontiguousarray(self._bgr[..., ::-1])

    def _rebuild_display(self) -> None:
        self._levels = []
        arr = self.display_array()
        if arr is None:
            return
        factor = 1
        while True:
            self._levels.append((factor, _to_qimage(arr)))
            if cv2 is None or max(arr.shape[:2]) // 2 < _LEVEL_MIN_SIDE:
                break
            arr = cv2.resize(arr, (arr.shape[1] // 2, arr.shape[0] // 2), interpolation=cv2.INTER_AREA)
            factor *= 2

    # ================= 확대 / 이동 =================
    def fit_zoom(self) -> float:
        w, h = self.image_size()
        if not w or not h:
            return 1.0
        return max(1e-6, min(self.width() / w, self.height() / h))

    def zoom(self) -> float:
        return self._zoom

    def is_fit(self) -> bool:
        return self._fit

    def fit(self) -> None:
        w, h = self.image_size()
        self._fit = True
        self._zoom = self.fit_zoom()
        self._cx, self._cy = w / 2.0, h / 2.0
        self.update()
        self.changed.emit()

    def zoom_by(self, factor: float, anchor: QPointF | None = None, notify: bool = True) -> None:
        """anchor(뷰포트 좌표, 없으면 가운데)를 고정한 채 확대·축소."""
        if not self.has_image():
            return
        anchor = anchor if anchor is not None else QPointF(self.width() / 2.0, self.height() / 2.0)
        before = self.image_at(anchor)
        fz = self.fit_zoom()
        self._zoom = max(fz * 0.5, min(self._zoom * factor, max(_MAX_ZOOM, fz)))
        self._fit = False
        self._cx = before.x() - (anchor.x() - self.width() / 2.0) / self._zoom
        self._cy = before.y() - (anchor.y() - self.height() / 2.0) / self._zoom
        self._clamp_center()
        self.update()
        self.changed.emit()
        if notify:
            self.viewChanged.emit()

    def pan_by(self, dx: float, dy: float, notify: bool = True) -> None:
        if not self.has_image():
            return
        self._cx -= dx / self._zoom
        self._cy -= dy / self._zoom
        self._fit = False
        self._clamp_center()
        self.update()
        self.changed.emit()
        if notify:
            self.viewChanged.emit()

    def _clamp_center(self) -> None:
        w, h = self.image_size()
        self._cx = min(max(self._cx, 0.0), float(w))
        self._cy = min(max(self._cy, 0.0), float(h))

    def image_at(self, pos) -> QPointF:
        """뷰포트 좌표 → 영상 좌표."""
        return QPointF(self._cx + (pos.x() - self.width() / 2.0) / self._zoom,
                       self._cy + (pos.y() - self.height() / 2.0) / self._zoom)

    def view_state(self) -> tuple[float, float, float]:
        """연동용 상태: (맞춤 대비 배율, 중심 x 비율, 중심 y 비율)."""
        w, h = self.image_size()
        if not w or not h:
            return 1.0, 0.5, 0.5
        return self._zoom / self.fit_zoom(), self._cx / w, self._cy / h

    def set_view_state(self, rel: float, nx: float, ny: float) -> None:
        if not self.has_image():
            return
        w, h = self.image_size()
        self._zoom = self.fit_zoom() * rel
        self._cx, self._cy = nx * w, ny * h
        self._fit = abs(rel - 1.0) < 1e-6 and abs(nx - 0.5) < 1e-6 and abs(ny - 0.5) < 1e-6
        self.update()
        self.changed.emit()

    # ================= 그리기 =================
    def draw_region(self, p: QPainter, rect: QRectF, center: QPointF, scale: float) -> None:
        """영상의 center(영상 좌표)를 rect 가운데에 두고 scale(화면 px / 영상 px)로 그린다."""
        if not self._levels:
            return
        factor, img = self._levels[0]
        for f, im in self._levels:               # 화면보다 촘촘한 단계 중 가장 작은 것
            if f * scale <= 1.0:
                factor, img = f, im
        p.save()
        p.setClipRect(rect)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(rect.center())
        p.scale(scale * factor, scale * factor)
        p.translate(-center.x() / factor, -center.y() / factor)
        p.drawImage(0, 0, img)
        p.restore()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#000000"))
        if self.has_image():
            self.draw_region(p, QRectF(self.rect()), QPointF(self._cx, self._cy), self._zoom)
        else:
            p.setPen(QColor("#6b7586"))
            p.setFont(scaled_font(self.font(), 1.05))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
        self._paint_overlay(p)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._active:
            p.setPen(QPen(QColor(self._accent), 2))
            p.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        else:
            p.setPen(QPen(QColor("#1d242f"), 1))
            p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))

    def _paint_overlay(self, p: QPainter) -> None:
        c = self._capture
        if c is None:
            return
        f_bold = scaled_font(self.font(), 0.95, True)
        p.setFont(f_bold)
        fm = p.fontMetrics()
        x, y, h = 10.0, 10.0, 24.0
        at = c.captured_at or ""
        when = f"{day_label(at[:10])}  {at[11:]}".strip()
        chips = []
        if c.eye in ("OD", "OS"):
            chips.append((c.eye, EYE_COLORS[c.eye], True))
        chips.append((when, "#e7eaf0", False))
        if self._tag:
            chips.append((self._tag, "#facc15" if self._tag.startswith("이전") else "#a3acba", True))
        for text, col, boxed in chips:
            w = fm.horizontalAdvance(text) + 16
            r = QRectF(x, y, w, h)
            p.setPen(QPen(QColor(col), 1) if boxed else Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 11, 16, 200))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor(col))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            x += w + 6

    # ================= 입력 =================
    def _place_nav(self) -> None:
        x = self.width() - 10
        for b in (self.b_newer, self.b_older):
            x -= b.width()
            b.move(x, 10)
            x -= 4

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._place_nav()
        if self._fit:
            self.fit()
        else:
            self.changed.emit()

    def wheelEvent(self, e) -> None:  # noqa: N802
        dy = e.angleDelta().y()
        if dy and self.has_image():
            self.zoom_by(1.15 ** (dy / 120.0), e.position())
        e.accept()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.activated.emit()
        if e.button() == Qt.MouseButton.MiddleButton:
            self.magnifierRequested.emit(e.position().toPoint())
        elif e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        e.accept()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_from is not None and e.buttons() & Qt.MouseButton.LeftButton:
            d = e.position() - self._drag_from
            self._drag_from = e.position()
            self.pan_by(d.x(), d.y())
        e.accept()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.has_image():
            self.fit()
            self.viewChanged.emit()
        e.accept()

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasFormat(CAPTURE_MIME):
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e) -> None:  # noqa: N802
        try:
            cid = int(bytes(e.mimeData().data(CAPTURE_MIME)).decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return
        e.acceptProposedAction()
        self.activated.emit()
        self.captureDropped.emit(cid)


def _to_qimage(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    if arr.ndim == 2:
        return QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
