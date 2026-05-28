from __future__ import annotations

import numpy as np

from app.capture.frame_utils import bgr_to_qimage, make_thumbnail
from app.capture.sources import SyntheticSource


def _frame(h=120, w=160):
    return np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)


def test_bgr_to_qimage_size_and_format():
    f = _frame(120, 160)
    img = bgr_to_qimage(f)
    assert img.width() == 160
    assert img.height() == 120
    assert not img.isNull()


def test_make_thumbnail_max_side():
    f = _frame(720, 1280)
    thumb = make_thumbnail(f, max_side=120)
    assert max(thumb.shape[:2]) == 120
    assert thumb.shape[2] == 3


def test_make_thumbnail_no_upscale():
    f = _frame(50, 40)
    thumb = make_thumbnail(f, max_side=120)
    assert thumb.shape[:2] == (50, 40)


def test_synthetic_source_reads_frames():
    src = SyntheticSource(320, 240, fps=120.0)
    src.open()
    ok, frame = src.read()
    src.release()
    assert ok
    assert frame.shape == (240, 320, 3)
    assert frame.dtype == np.uint8
