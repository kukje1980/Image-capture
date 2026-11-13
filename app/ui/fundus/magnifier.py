"""확대창 — 뷰포트 위에 떠 있는 정사각형 돋보기.

끌어서 옮기고, 휠로 배율(1.5×~6×)을 바꾼다. 오른쪽 클릭으로 '반대쪽 영상' 모드를 켜면
같은 영상 좌표의 반대쪽 뷰포트 영상을 보여 준다 (이전 ↔ 현재를 한 지점에서 비교).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui.theme import palette
from app.ui.video_view import scaled_font

MIN_FACTOR, MAX_FACTOR, FACTOR_STEP = 1.5, 6.0, 0.25
DEFAULT_SIZE, DEFAULT_FACTOR = 220, 2.5


class Magnifier(QWidget):
    visibilityChanged = Signal(bool)

    def __init__(self, area: QWidget, viewports: list):
        super().__init__(area)
        self._area = area
        self._viewports = list(viewports)
        self._factor = DEFAULT_FACTOR
        self._other = False
        self._drag: QPoint | None = None
        self._accent = palette("dark")["accent"]
        self.setFixedSize(DEFAULT_SIZE, DEFAULT_SIZE)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("끌어서 이동 · 휠: 배율 · 오른쪽 클릭: 반대쪽 영상")
        for vp in self._viewports:
            vp.changed.connect(self.update)
        self.hide()

    # ---- 상태 ----
    def factor(self) -> float:
        return self._factor

    def set_factor(self, f: float) -> None:
        self._factor = min(MAX_FACTOR, max(MIN_FACTOR, float(f)))
        self.update()

    def other_mode(self) -> bool:
        return self._other

    def set_other_mode(self, on: bool) -> None:
        self._other = bool(on)
        self.update()

    def show_at(self, center: QPoint) -> None:
        """area 좌표의 center 에 가운데를 맞춰 보인다."""
        self.move_center(center)
        self.set_shown(True)

    def is_shown(self) -> bool:
        return not self.isHidden()

    def set_shown(self, on: bool) -> None:
        if on == self.is_shown():
            return
        self.setVisible(on)
        if on:
            self.raise_()
        self.visibilityChanged.emit(on)

    def move_center(self, center: QPoint) -> None:
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        x = min(max(0, x), max(0, self._area.width() - self.width()))
        y = min(max(0, y), max(0, self._area.height() - self.height()))
        self.move(x, y)
        self.update()

    def host(self):
        """확대창 가운데 아래에 있는 뷰포트 (사이 틈이면 가장 가까운 쪽)."""
        c = self.geometry().center()
        best, dist = None, None
        for vp in self._viewports:
            g = vp.geometry()
            if g.contains(c):
                return vp
            d = abs(g.center().x() - c.x())
            if dist is None or d < dist:
                best, dist = vp, d
        return best

    def source(self):
        """(영상을 가져올 뷰포트, 영상 좌표 중심, 배율) — 그릴 것이 없으면 None."""
        host = self.host()
        if host is None or not host.has_image():
            return None
        pt = host.image_at(host.mapFrom(self._area, self.geometry().center()))
        scale = host.zoom() * self._factor
        if self._other:
            others = [v for v in self._viewports if v is not host and v.has_image()]
            if others:
                o = others[0]
                hw, hh = host.image_size()
                ow, oh = o.image_size()
                # 크기가 다른 영상도 같은 위치·같은 시야가 되게 비율로 맞춘다
                return o, QPointF(pt.x() * ow / hw, pt.y() * oh / hh), scale * hw / ow
        return host, pt, scale

    # ---- 그리기 ----
    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        p.fillRect(r, QColor("#05070a"))
        src = self.source()
        if src is not None:
            vp, center, scale = src
            vp.draw_region(p, r, center, scale)
            cap = vp.capture()                   # 좁은 창이라 '안구 날짜' 만
            at = (cap.captured_at or "")[:10].replace("-", ".") if cap is not None else ""
            eye = cap.eye if cap is not None and cap.eye in ("OD", "OS") else ""
            what = " ".join(x for x in (eye, at) if x) or "영상"
        else:
            what = "영상 없음"
        # 가운데 십자 표시
        c = r.center()
        p.setPen(QPen(QColor(255, 255, 255, 110), 1))
        p.drawLine(QPointF(c.x() - 7, c.y()), QPointF(c.x() + 7, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 7), QPointF(c.x(), c.y() + 7))
        # 설명 띠
        text = f"{self._factor:g}×  ·  {what}" + ("  ·  반대쪽" if self._other else "")
        p.setFont(scaled_font(self.font(), 0.8, True))
        band = QRectF(0, r.height() - 20, r.width(), 20)
        p.fillRect(band, QColor(8, 11, 16, 205))
        col = "#facc15" if self._other else "#e7eaf0"
        p.setPen(QColor(col))
        el = p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(band.width()) - 10)
        p.drawText(band.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, el)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#facc15" if self._other else self._accent), 2))
        p.drawRect(r.adjusted(1, 1, -1, -1))

    # ---- 입력 ----
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()
        elif e.button() == Qt.MouseButton.RightButton:
            self.set_other_mode(not self._other)
        elif e.button() == Qt.MouseButton.MiddleButton:
            self.set_shown(False)
        e.accept()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            top_left = e.globalPosition().toPoint() - self._drag
            self.move_center(top_left + QPoint(self.width() // 2, self.height() // 2))
        e.accept()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None
        e.accept()

    def wheelEvent(self, e) -> None:  # noqa: N802
        dy = e.angleDelta().y()
        if dy:
            self.set_factor(self._factor + (FACTOR_STEP if dy > 0 else -FACTOR_STEP))
        e.accept()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        e.accept()
