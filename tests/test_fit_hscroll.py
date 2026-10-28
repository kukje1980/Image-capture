"""HScroll: 만드는 도중(맥에서는 setFrameShape 등에서 바로 resizeEvent 가 옴)에는 on_compact 를 부르지 않는다.

v1.18.0 첫 빌드가 맥에서만 실패한 원인 — 검사 기록 화면의 on_compact 가 아직 대입 전인 self.head_buttons 를 읽었다.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from app.ui import fit


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def mac_like_resize(monkeypatch):
    """맥처럼: 만드는 도중 setFrameShape 에서 아주 좁은 크기로 resizeEvent 가 바로 온다."""
    orig = fit.HScroll.setFrameShape

    def set_frame_shape(self, shape):
        orig(self, shape)
        self.resize(40, 30)
        self.resizeEvent(QResizeEvent(QSize(40, 30), QSize(0, 0)))
    monkeypatch.setattr(fit.HScroll, "setFrameShape", set_frame_shape)


def _row(n=6):
    row = QWidget()
    lay = QHBoxLayout(row)
    for i in range(n):
        b = QPushButton(f"버튼 {i}")
        b.setMinimumWidth(90)
        lay.addWidget(b)
    return row


def test_no_compact_callback_during_construction(qapp, mac_like_resize):
    calls = []
    hs = fit.HScroll(_row(), on_compact=calls.append)
    assert calls == []                                   # 만드는 중에는 부르지 않음
    hs.resize(60, 40)
    hs.resizeEvent(QResizeEvent(QSize(60, 40), QSize(40, 30)))
    assert calls == [True]                               # 다 만든 뒤 좁으면 아이콘만으로
    hs.resize(2000, 40)
    hs.resizeEvent(QResizeEvent(QSize(2000, 40), QSize(60, 40)))
    assert calls == [True, False]                        # 넓어지면 되돌림


def test_exam_screen_builds_with_mac_like_resize(qapp, app_env, mac_like_resize):
    from app.ui.exam_screen import ExamScreen
    config, db = app_env
    ex = ExamScreen(db, config)                          # 예전: AttributeError 'head_buttons'
    assert isinstance(ex.head_buttons, fit.HScroll)
    ex._compact_head_buttons(True)                       # 좁은 창: 아이콘만
    assert ex.btn_pdf._tx.isHidden()
    ex._compact_head_buttons(False)
    assert not ex.btn_pdf._tx.isHidden()
