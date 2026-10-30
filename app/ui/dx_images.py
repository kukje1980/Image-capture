"""참고 사진·모식도 이미지 로딩 (SVG 모식도 → 픽스맵/BGR, 사진 파일 → 픽스맵/BGR)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_cache: dict[tuple[str, int], QPixmap] = {}


def is_svg(path: str) -> bool:
    return (path or "").lower().endswith(".svg")


def render_svg(path: str, width: int = 1200) -> QImage:
    r = QSvgRenderer(path)
    size = r.defaultSize()
    if not r.isValid() or size.width() <= 0:
        return QImage()
    h = max(1, round(size.height() * width / size.width()))
    img = QImage(width, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r.render(p, QRectF(0, 0, width, h))
    p.end()
    return img


def load_pixmap(path: str, max_w: int = 1200) -> QPixmap | None:
    """모식도(SVG)·사진 파일을 픽스맵으로 (크기별 캐시). 실패하면 None."""
    key = (path, max_w)
    pm = _cache.get(key)
    if pm is not None:
        return pm
    if is_svg(path):
        img = render_svg(path, max_w)
        pm = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
    else:
        pm = QPixmap(path)
        if not pm.isNull() and pm.width() > max_w:
            pm = pm.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
    if pm.isNull():
        return None
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = pm
    return pm


def qimage_to_bgr(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    rgb = buf[:, : w * 3].reshape(h, w, 3)
    return np.ascontiguousarray(rgb[..., ::-1])


def load_bgr(path: str, svg_width: int = 1200) -> np.ndarray | None:
    """비교 이미지 합성·인쇄용 BGR 배열. 모식도는 svg_width 폭으로 렌더."""
    if is_svg(path):
        img = render_svg(path, svg_width)
        return None if img.isNull() else qimage_to_bgr(img)
    from app.ui.pro.pro_workspace import load_bgr as _load
    return _load(path)
