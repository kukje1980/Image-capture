"""미리 보기 — how large the photos of the photo list grow under the mouse (보기 → 미리 보기 배율).

The photos of the list grow toward the mouse like the icons of the Dock of a Mac: the one under the
mouse ``scale`` times its size in the list, those beside it less and less, and they follow the mouse
(``thumbs.ThumbStrip.set_dock`` lays the row out, ``thumbs.DockOverlay`` paints it; the main window
drives both: ``MainWindow._hover_list``).
"""
from __future__ import annotations

SCALE = 2.0                     # the photo under the mouse: this many times its size in the list …
# … or as chosen in 보기 → 미리 보기 배율 (Settings.preview_scale)
SCALES = (1.5, 2.0, 2.5, 3.0, 4.0)

SIZE = 1.0                      # the photos of the list themselves: this many times THUMB_GRID …
# … or as chosen in 설정 → 일반 → 사진 목록의 사진 크기 (Settings.thumb_size)
SIZES = ((1.0, "보통"), (1.25, "조금 크게"), (1.5, "크게"), (2.0, "아주 크게"))


def nearest_size(size) -> float:
    try:
        size = float(size)
    except (TypeError, ValueError):
        size = SIZE
    return min((k for k, _name in SIZES), key=lambda k: abs(k - size))


def scale_name(scale: float) -> str:
    return f"{scale:g}배"
