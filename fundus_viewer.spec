# PyInstaller spec — Windows 10/11 and macOS build of the fundus viewer.
#
#   pip install -r requirements.txt pyinstaller
#   pyinstaller fundus_viewer.spec --noconfirm
#
# Windows: dist/FundusViewer/FundusViewer.exe (one-folder build: starts fast,
# and the bundled opengl32sw.dll from PySide6 enables the software-OpenGL
# fallback on PCs without a capable GPU driver).
# macOS:   dist/FundusViewer.app for the architecture of the building Mac
# (Apple Silicon = arm64, Intel = x86_64); build_mac.sh signs it ad hoc and
# packs a .dmg.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

sys.path.insert(0, str(Path(SPECPATH)))
from fundusview import __version__  # noqa: E402
from fundusview.ui.icon import write_icns, write_ico  # noqa: E402

MAC = sys.platform == "darwin"

build_dir = Path(SPECPATH) / "build"
build_dir.mkdir(exist_ok=True)
icon = build_dir / ("FundusViewer.icns" if MAC else "FundusViewer.ico")
(write_icns if MAC else write_ico)(icon)

hidden = (
    collect_submodules("OpenGL.platform")
    + collect_submodules("OpenGL.arrays")
    + collect_submodules("pydicom.pixels")
    + ["pylibjpeg", "libjpeg", "watchdog.observers.polling"]
    + (["watchdog.observers.fsevents"] if MAC else ["watchdog.observers.read_directory_changes"])
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
    argv_emulation=False,
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FundusViewer")

if MAC:
    app = BUNDLE(
        coll,
        name="FundusViewer.app",
        icon=str(icon),
        bundle_identifier="com.kukjemd.fundusviewer",
        version=__version__,
        info_plist={
            "CFBundleName": "FundusViewer",
            "CFBundleDisplayName": "안저 사진 뷰어",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            # shown when macOS first asks for access to these folders
            "NSDocumentsFolderUsageDescription":
                "안저 사진 보관함과 [안저사진 가져오기] 폴더가 문서 폴더에 있습니다.",
            "NSRemovableVolumesUsageDescription":
                "USB 저장장치에 있는 안저 사진을 가져오기 위해 필요합니다.",
            "NSNetworkVolumesUsageDescription":
                "NAS · 공유 폴더에 저장된 안저 카메라 사진을 가져오기 위해 필요합니다.",
            "NSDesktopFolderUsageDescription":
                "바탕화면에 있는 사진을 가져오거나 저장할 때 필요합니다.",
            "NSDownloadsFolderUsageDescription":
                "다운로드 폴더에 있는 사진을 가져올 때 필요합니다.",
        },
    )
