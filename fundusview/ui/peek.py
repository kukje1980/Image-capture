"""미리 보기 — how large the photos of the photo list grow under the mouse (보기 → 미리 보기 배율).

The photos of the list grow toward the mouse like the icons of the Dock of a Mac: the one under the
mouse ``scale`` times its size in the list, those beside it less and less, and they follow the mouse
(``thumbs.ThumbStrip.set_dock`` lays the row out, ``thumbs.DockOverlay`` paints it; the main window
drives both: ``MainWindow._hover_list``).
"""
from __future__ import annotations

SCALE = 2.0                     # the photo under the mouse: this many times its size in the list …
# … or as chosen in 보기 → 미리 보기 배율 (Settings.preview_scale)
SCALES = (1.5, 2.0, 2.5, 3.0)


def scale_name(scale: float) -> str:
    return f"{scale:g}배"
