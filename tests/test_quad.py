"""QuadView(4분할) 로직 테스트."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _frame(v=50):
    return np.full((48, 64, 3), v, dtype=np.uint8)


def test_freeze_requires_frame(qapp):
    from app.ui.quad_view import QuadView
    q = QuadView()
    assert q.freeze_active("OD") is False   # 라이브 프레임 없음


def test_fill_four_and_compose(qapp):
    from app.ui.quad_view import QuadView
    q = QuadView()
    for eye, v in [("OD", 10), ("OS", 20), ("OD", 30), ("OS", 40)]:
        q.set_live_frame(_frame(v))
        assert q.freeze_active(eye) is True
    assert q.is_full() is True
    # 추가 정지 시도는 실패(모두 채워짐)
    q.set_live_frame(_frame(99))
    assert q.freeze_active("NA") is False

    imgs = q.images_for_save("NA")
    assert len(imgs) == 4
    assert [e for _, e in imgs] == ["OD", "OS", "OD", "OS"]

    comp = q.composite()
    assert comp is not None
    assert comp.shape == (48 * 2, 64 * 2, 3)


def test_click_cell_reactivates(qapp):
    from app.ui.quad_view import QuadView
    q = QuadView()
    q.set_live_frame(_frame(10)); q.freeze_active("OD")   # cell0 frozen, active=1
    q.set_active(0)                                        # cell0 다시 라이브 대상
    q.set_live_frame(_frame(55))
    assert q.freeze_active("OS") is True                  # 재동결 성공


def test_reset(qapp):
    from app.ui.quad_view import QuadView
    q = QuadView()
    q.set_live_frame(_frame()); q.freeze_active("OD")
    assert q.has_any() is True
    q.reset()
    assert q.has_any() is False
    assert q.composite() is None
