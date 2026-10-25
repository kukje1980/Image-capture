"""4분할 정지영상 비교 뷰 (2×2).

활성(active) 칸은 라이브로 갱신되고, '정지영상'을 누르면 그 칸이 정지(freeze)되며
다음 칸으로 자동 이동(1→2→3→4, 이후 순환)한다. 각 칸은 클릭으로 활성 지정 가능.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.capture.frame_utils import frame_to_pixmap

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

_ACTIVE = "#14b8a6"
_FROZEN = "#334155"
_EMPTY = "#1e293b"


class QuadView(QWidget):
    cellClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self._frames: list = [None, None, None, None]   # numpy BGR
        self._eyes: list = ["NA"] * 4
        self._frozen: list = [False] * 4
        self._active = 0
        self._pix: list = [None] * 4

    # ---- 상태 ----
    def reset(self) -> None:
        self._frames = [None] * 4
        self._eyes = ["NA"] * 4
        self._frozen = [False] * 4
        self._active = 0
        self._pix = [None] * 4
        self.update()

    def set_live_frame(self, frame: np.ndarray) -> None:
        # 활성(라이브) 칸에만 반영. 모두 채워지면 _active 가 None.
        if self._active is not None and not self._frozen[self._active]:
            self._frames[self._active] = frame
            self._pix[self._active] = None
            self.update()

    def freeze_active(self, eye: str = "NA") -> bool:
        if self._active is None or self._frames[self._active] is None:
            return False
        self._frozen[self._active] = True
        self._eyes[self._active] = eye
        # 다음 '빈' 칸을 찾아 라이브로. 없으면 라이브 칸 없음(None).
        nxt = None
        for j in range(1, 5):
            k = (self._active + j) % 4
            if not self._frozen[k]:
                nxt = k
                break
        if nxt is None:
            self._active = None
        else:
            self._active = nxt
            self._frozen[nxt] = False
            self._frames[nxt] = None
            self._pix[nxt] = None
        self.update()
        return True

    def is_full(self) -> bool:
        return all(self._frozen)

    def set_active(self, idx: int) -> None:
        if 0 <= idx < 4:
            self._active = idx
            self._frozen[idx] = False
            self._frames[idx] = None
            self._pix[idx] = None
            self.update()

    def images_for_save(self, live_eye: str) -> list:
        """저장 대상: 이미지가 있는 모든 칸 (정지 칸 + 현재 라이브 활성 칸)."""
        out = []
        for i in range(4):
            f = self._frames[i]
            if f is None:
                continue
            eye = self._eyes[i] if self._frozen[i] else live_eye
            out.append((f, eye))
        return out

    def has_any(self) -> bool:
        return any(f is not None for f in self._frames)

    def composite(self):
        """화면에 보이는 그대로 2×2 합성 BGR 이미지 생성 (빈 칸은 검정)."""
        ref = next((f for f in self._frames if f is not None), None)
        if ref is None or cv2 is None:
            return None
        h, w = ref.shape[:2]
        canvas = np.zeros((h * 2, w * 2, 3), dtype=np.uint8)
        for i in range(4):
            r, c = divmod(i, 2)
            f = self._frames[i]
            if f is not None:
                canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = cv2.resize(f, (w, h))
        return canvas

    # ---- 렌더 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))
        cw, ch = self.width() // 2, self.height() // 2
        origins = [(0, 0), (cw, 0), (0, ch), (cw, ch)]
        for i, (x, y) in enumerate(origins):
            frame = self._frames[i]
            if frame is not None:
                if self._pix[i] is None or self._pix[i].width() > cw - 4 or self._pix[i].height() > ch - 4:
                    self._pix[i] = frame_to_pixmap(frame, cw - 4, ch - 4)     # 칸 크기로 줄여서 변환
                pm = self._pix[i]
                p.drawPixmap(x + (cw - pm.width()) // 2, y + (ch - pm.height()) // 2, pm)
            else:
                p.setPen(QColor("#475569"))
                p.drawText(x, y, cw, ch, Qt.AlignmentFlag.AlignCenter, str(i + 1))

            # 테두리
            if i == self._active:
                pen = QPen(QColor(_ACTIVE)); pen.setWidth(3)
            elif self._frozen[i]:
                pen = QPen(QColor(_FROZEN)); pen.setWidth(1)
            else:
                pen = QPen(QColor(_EMPTY)); pen.setWidth(1)
            p.setPen(pen)
            p.drawRect(x + 1, y + 1, cw - 2, ch - 2)

            # 라벨
            if i == self._active:
                tag = "● 라이브"
            elif self._frozen[i]:
                tag = "정지" + (f" · {self._eyes[i]}" if self._eyes[i] not in ("NA", None) else "")
            else:
                tag = ""
            if tag:
                p.fillRect(x + 6, y + 6, 92, 20, QColor(0, 0, 0, 150))
                p.setPen(QColor("#e2e8f0"))
                p.drawText(x + 12, y + 21, tag)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        cw, ch = self.width() // 2, self.height() // 2
        col = 0 if event.position().x() < cw else 1
        row = 0 if event.position().y() < ch else 1
        self.cellClicked.emit(row * 2 + col)
