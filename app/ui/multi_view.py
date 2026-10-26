"""촬영 화면의 멀티 보기 — 오른쪽 목록에서 고른 사진들을 한 화면에 격자로 모아 본다.

1장=전체, 2장=좌우, 3~4장=2×2, 5~6장=3×2, 7~9장=3×3 … (선택 순서대로).
칸을 두 번 누르면 그 사진을 큰 화면으로 본다. composite() 는 보이는 그대로 한 장의 BGR 이미지로 만든다.
"""
from __future__ import annotations

import math
import os

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.capture.frame_utils import bgr_to_qimage
from app.ui.theme import EYE_COLORS

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def grid_shape(n: int) -> tuple[int, int]:
    """사진 수 → (열, 행)."""
    if n <= 1:
        return 1, 1
    if n == 2:
        return 2, 1
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def _load_bgr(cap):
    path = cap.file_path if cap.media_type == "photo" else (cap.thumbnail_path or "")
    if not path or cv2 is None or not os.path.exists(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)          # 한글 경로 대응
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class MultiView(QWidget):
    cellActivated = Signal(object)   # Capture — 칸을 두 번 누름

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self._caps: list = []
        self._imgs: list = []          # BGR ndarray | None
        self._pix: list = []

    def set_captures(self, caps: list) -> None:
        self._caps = list(caps)
        self._imgs = [_load_bgr(c) for c in self._caps]
        self._pix = [QPixmap.fromImage(bgr_to_qimage(im)) if im is not None else None for im in self._imgs]
        self.update()

    def clear(self) -> None:
        self.set_captures([])

    def captures(self) -> list:
        return list(self._caps)

    def count(self) -> int:
        return len(self._caps)

    # ---- 저장용 합성 ----
    def composite(self):
        imgs = [im for im in self._imgs if im is not None]
        if not imgs or cv2 is None:
            return None
        cols, rows = grid_shape(len(self._imgs))
        ref_h = max(im.shape[0] for im in imgs)
        ref_w = max(im.shape[1] for im in imgs)
        scale = min(1.0, 1600 / max(ref_w, 1))        # 칸 하나 최대 가로 1600px
        cw, ch = max(1, int(ref_w * scale)), max(1, int(ref_h * scale))
        gap = 8
        canvas = np.zeros((rows * ch + (rows - 1) * gap, cols * cw + (cols - 1) * gap, 3), dtype=np.uint8)
        for i, im in enumerate(self._imgs):
            if im is None:
                continue
            r, c = divmod(i, cols)
            s = min(cw / im.shape[1], ch / im.shape[0])
            w, h = max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))
            x0 = c * (cw + gap) + (cw - w) // 2
            y0 = r * (ch + gap) + (ch - h) // 2
            canvas[y0:y0 + h, x0:x0 + w] = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
            eye = self._caps[i].eye if self._caps[i].eye in ("OD", "OS", "OU") else ""
            label = f"{i + 1}" + (f" {eye}" if eye else "")
            fs = max(0.8, ch / 500)
            cv2.putText(canvas, label, (c * (cw + gap) + 14, r * (ch + gap) + int(36 * fs)),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), int(5 * fs), cv2.LINE_AA)
            cv2.putText(canvas, label, (c * (cw + gap) + 14, r * (ch + gap) + int(36 * fs)),
                        cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), max(1, int(2 * fs)), cv2.LINE_AA)
        return canvas

    # ---- 화면 ----
    def _cells(self):
        n = len(self._caps)
        cols, rows = grid_shape(n)
        gap = 6
        cw = (self.width() - gap * (cols - 1)) / cols
        ch = (self.height() - gap * (rows - 1)) / rows
        for i in range(n):
            r, c = divmod(i, cols)
            yield i, QRectF(c * (cw + gap), r * (ch + gap), cw, ch)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#000000"))
        if not self._caps:
            p.setPen(QColor("#8a94a6"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "오른쪽 목록에서 사진을 한 번씩 눌러 고른 뒤 '멀티'를 누르세요")
            return
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        for i, cell in self._cells():
            pm = self._pix[i]
            if pm is not None and not pm.isNull():
                s = pm.scaled(int(cell.width()), int(cell.height()), Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(int(cell.x() + (cell.width() - s.width()) / 2),
                             int(cell.y() + (cell.height() - s.height()) / 2), s)
            else:
                p.setPen(QColor("#6b7586"))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, "사진을 불러오지 못했습니다")
            cap = self._caps[i]
            eye = cap.eye if cap.eye in ("OD", "OS", "OU") else ""
            tag = f"{i + 1}" + (f"  {eye}" if eye else "") + (f"  {cap.captured_at[5:16]}" if cap.captured_at else "")
            fm = p.fontMetrics()
            tr = QRectF(cell.x() + 8, cell.y() + 8, fm.horizontalAdvance(tag) + 16, fm.height() + 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 11, 16, 175))
            p.drawRoundedRect(tr, 6, 6)
            p.setPen(QColor(EYE_COLORS.get(eye, "#facc15")))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, tag)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        for i, cell in self._cells():
            if cell.contains(event.position()):
                self.cellActivated.emit(self._caps[i])
                return
