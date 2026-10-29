"""Application icon, drawn procedurally (no binary asset in the repo)."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw


def icon_image(size: int = 256) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([s * 0.04, s * 0.04, s * 0.96, s * 0.96], fill=(31, 42, 51, 255))
    d.ellipse([s * 0.14, s * 0.14, s * 0.86, s * 0.86], fill=(196, 96, 52, 255))
    d.ellipse([s * 0.30, s * 0.30, s * 0.70, s * 0.70], fill=(214, 118, 66, 255))
    cx, cy = s * 0.62, s * 0.48
    for ang, ln in ((-0.9, 0.42), (0.9, 0.42), (-2.4, 0.40), (2.4, 0.40)):
        d.line([cx, cy, cx + math.cos(ang) * s * ln, cy + math.sin(ang) * s * ln * 0.8],
               fill=(120, 28, 22, 255), width=max(2, s // 40))
    r = s * 0.075
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 226, 170, 255))
    d.ellipse([s * 0.40 - r * 0.5, s * 0.50 - r * 0.5, s * 0.40 + r * 0.5, s * 0.50 + r * 0.5],
              fill=(120, 40, 25, 255))
    return img


def qicon():
    from PySide6.QtGui import QIcon, QImage, QPixmap

    im = icon_image(256)
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888).copy()
    return QIcon(QPixmap.fromImage(qimg))


def write_ico(path) -> None:
    icon_image(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def write_icns(path) -> None:
    """macOS app icon (16 … 1024 px, Retina sizes included)."""
    icon_image(1024).save(path, format="ICNS")
