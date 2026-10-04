"""assets/icons/app.ico + app.png 생성기 (오프스크린 Qt 렌더 → Pillow로 ICO 패킹).

    QT_QPA_PLATFORM=offscreen python tools/generate_icon.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtWidgets import QApplication

from app.ui.theme import _render_icon

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons")
SIZES = [16, 24, 32, 48, 64, 128, 256]


def qpixmap_to_png_bytes(pm) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication(sys.argv)  # noqa: F841 (QPixmap 렌더에 필요)

    import io

    from PIL import Image

    images = []
    for s in SIZES:
        png = qpixmap_to_png_bytes(_render_icon(s))
        img = Image.open(io.BytesIO(png)).convert("RGBA")
        images.append(img)
        if s == 256:
            img.save(os.path.join(OUT_DIR, "app.png"))

    ico_path = os.path.join(OUT_DIR, "app.ico")
    images[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in SIZES])
    print("wrote", ico_path, "and app.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
