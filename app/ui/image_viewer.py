"""썸네일 클릭 시 큰 보기. 동영상은 OS 기본 플레이어로 재생."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout


def open_in_default_player(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001
        pass


class ImageViewerDialog(QDialog):
    def __init__(self, capture, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"보기 - {capture.captured_at}")
        self.resize(920, 720)
        lay = QVBoxLayout(self)

        if capture.media_type == "video":
            open_in_default_player(capture.file_path)
            lay.addWidget(QLabel("동영상을 기본 플레이어로 재생합니다.\n\n" + capture.file_path))
        else:
            area = QScrollArea()
            area.setWidgetResizable(True)
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(capture.file_path)
            if not pm.isNull():
                lbl.setPixmap(
                    pm.scaled(900, 680, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )
            else:
                lbl.setText("이미지를 불러올 수 없습니다.")
            area.setWidget(lbl)
            lay.addWidget(area)
