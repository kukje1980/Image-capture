"""비교 창 — 2~4장을 나란히 놓고 확대·이동을 함께 움직여 본다.

2장 = 좌우, 3~4장 = 2×2. 휠 확대·드래그 이동은 모든 칸이 같이 움직인다.
채널(컬러 / Red-free / 흑백)과 밝기·대비는 모든 칸에 똑같이 적용된다 (원본은 그대로).

'화면 저장' 은 지금 보이는 비교 화면(확대·이동·보정·제목 포함)을 한 장의 사진으로 환자 기록에 저장하고,
'파일로 저장…' 은 같은 화면을 PNG/JPG 파일로 내보낸다 (참조 영상 비교 · 영상 비교 공용).
"""
from __future__ import annotations

import os
import time

import cv2
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.capture.image_process import Adjust
from app.ui.pro.image_canvas import ImageCanvas, qimage_to_bgr

MAX_ITEMS = 4
_CHANNELS = [("rgb", "컬러"), ("green", "Red-free"), ("red", "적색"), ("blue", "청색"), ("gray", "흑백")]


class CompareDialog(QDialog):
    def __init__(self, items: list, parent=None, title: str = "영상 비교", on_save=None):
        """items: [(bgr, caption), ...] — 앞의 4장까지.
        on_save(bgr) → 저장 결과 문자열 (실패·취소는 None) — 없으면 '화면 저장' 버튼을 숨긴다."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1280, 820)
        self._items = items[:MAX_ITEMS]
        self._on_save = on_save

        bar = QHBoxLayout()
        self.c_channel = QComboBox()
        for key, label in _CHANNELS:
            self.c_channel.addItem(label, key)
        self.s_bright = QSlider(Qt.Orientation.Horizontal)
        self.s_bright.setRange(-100, 100)
        self.s_contrast = QSlider(Qt.Orientation.Horizontal)
        self.s_contrast.setRange(20, 300)
        self.s_contrast.setValue(100)
        for s in (self.s_bright, self.s_contrast):
            s.setFixedWidth(150)
        b_fit = QPushButton("화면 맞춤")
        b_in = QPushButton("확대 +")
        b_out = QPushButton("축소 −")
        b_reset = QPushButton("보정 초기화")
        bar.addWidget(QLabel("채널"))
        bar.addWidget(self.c_channel)
        bar.addSpacing(10)
        bar.addWidget(QLabel("밝기"))
        bar.addWidget(self.s_bright)
        bar.addWidget(QLabel("대비"))
        bar.addWidget(self.s_contrast)
        bar.addWidget(b_reset)
        bar.addStretch(1)
        for b in (b_out, b_in, b_fit):
            bar.addWidget(b)
        bar.addSpacing(10)
        self.b_file = QPushButton("파일로 저장…")
        self.b_file.setToolTip("지금 보이는 비교 화면을 PNG / JPG 파일로 저장")
        self.b_save = QPushButton("화면 저장")
        self.b_save.setObjectName("Primary")
        self.b_save.setToolTip("지금 보이는 비교 화면(확대 · 보정 · 제목 포함)을 한 장의 사진으로 환자 기록에 저장")
        self.b_save.setVisible(on_save is not None)
        bar.addWidget(self.b_file)
        bar.addWidget(self.b_save)

        self.grid_box = QWidget()                   # 화면 저장 때 이 칸을 그대로 찍는다
        self.grid_box.setObjectName("CompareGrid")
        grid = QGridLayout(self.grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        cols = 2
        self.canvases: list[ImageCanvas] = []
        for i, (img, cap) in enumerate(self._items):
            cv = ImageCanvas()
            cv.set_image(img)
            cv.set_caption(cap)
            grid.addWidget(cv, i // cols, i % cols)
            for other in self.canvases:             # 모든 칸끼리 연결 (확대 신호는 한 단계만 전달됨)
                other.link(cv)
            self.canvases.append(cv)

        self.lbl_msg = QLabel("휠: 확대 · 끌기: 이동 (모든 칸이 함께 움직입니다)")
        self.lbl_msg.setObjectName("Muted")
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.grid_box, 1)
        lay.addWidget(self.lbl_msg)

        self.c_channel.currentIndexChanged.connect(self._apply)
        self.s_bright.valueChanged.connect(self._apply)
        self.s_contrast.valueChanged.connect(self._apply)
        b_reset.clicked.connect(self.reset_adjust)
        b_fit.clicked.connect(lambda: [cv.reset_view() for cv in self.canvases])
        b_in.clicked.connect(lambda: self.canvases and self.canvases[0].zoom_by(1.25))
        b_out.clicked.connect(lambda: self.canvases and self.canvases[0].zoom_by(0.8))
        self.b_save.clicked.connect(lambda: self.save_screen())
        self.b_file.clicked.connect(lambda: self.save_file())

    # ---- 화면 저장 ----
    def screen_bgr(self):
        """지금 보이는 비교 화면(모든 칸 · 제목 · 보정)을 한 장의 BGR 영상으로."""
        pm = self.grid_box.grab()
        if pm.isNull():
            return None
        return qimage_to_bgr(pm.toImage())

    def save_screen(self) -> str | None:
        if self._on_save is None:
            return None
        img = self.screen_bgr()
        if img is None:
            return None
        msg = self._on_save(img)
        if msg:
            self.lbl_msg.setText(msg)
        return msg

    def save_file(self, path: str | None = None) -> str | None:
        if path is None:
            name = f"비교_{time.strftime('%Y%m%d_%H%M%S')}.png"
            path, _ = QFileDialog.getSaveFileName(self, "비교 화면 저장", name, "PNG (*.png);;JPEG (*.jpg *.jpeg)")
            if not path:
                return None
        img = self.screen_bgr()
        ext = ".jpg" if path.lower().endswith((".jpg", ".jpeg")) else ".png"
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ext
        ok, buf = (False, None) if img is None else cv2.imencode(ext, img)
        if not ok:
            QMessageBox.warning(self, "비교 화면 저장", "저장하지 못했습니다.")
            return None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            buf.tofile(path)                        # 한글 경로도 저장되게 (cv2.imwrite 는 한글 경로 실패)
        except OSError as e:
            QMessageBox.warning(self, "비교 화면 저장", f"저장하지 못했습니다.\n{e}")
            return None
        self.lbl_msg.setText(f"파일로 저장했습니다: {path}")
        return path

    def adjust(self) -> Adjust:
        return Adjust(channel=self.c_channel.currentData(), brightness=float(self.s_bright.value()),
                      contrast=self.s_contrast.value() / 100.0)

    def _apply(self, *_):
        adj = self.adjust()
        for cv in self.canvases:
            cv.set_adjust(adj)

    def reset_adjust(self) -> None:
        for w, v in ((self.c_channel, 0), (self.s_bright, 0), (self.s_contrast, 100)):
            w.blockSignals(True)
            w.setCurrentIndex(v) if isinstance(w, QComboBox) else w.setValue(v)
            w.blockSignals(False)
        self._apply()
