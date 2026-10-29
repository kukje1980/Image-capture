# PyInstaller spec — Windows 10/11 build of the fundus viewer.
#
#   pip install -r requirements.txt pyinstaller
#   pyinstaller fundus_viewer.spec --noconfirm
#
# Output: dist/FundusViewer/FundusViewer.exe (one-folder build: starts fast,
# and the bundled opengl32sw.dll from PySide6 enables the software-OpenGL
# fallback on PCs without a capable GPU driver).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

sys.path.insert(0, str(Path(SPECPATH)))
from fundusview import __version__  # noqa: E402
from fundusview.ui.icon import write_ico  # noqa: E402

build_dir = Path(SPECPATH) / "build"
build_dir.mkdir(exist_ok=True)
icon = build_dir / "FundusViewer.ico"
write_ico(icon)

hidden = (
    collect_submodules("OpenGL.platform")
    + collect_submodules("OpenGL.arrays")
    + collect_submodules("pydicom.pixels")
    + ["pylibjpeg", "libjpeg", "watchdog.observers.read_directory_changes", "watchdog.observers.polling"]
)

a = Analysis(
    ["run_viewer.py"],
    pathex=[SPECPATH],
    datas=[("fundusview/ui/style.qss", "fundusview/ui")],
    hiddenimports=hidden,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FundusViewer",
    console=False,
    icon=str(icon),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FundusViewer")
