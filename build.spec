# PyInstaller 스펙 (Windows, one-folder).
#   빌드:  pyinstaller build.spec
#   결과:  dist/SlitLampImaging/SlitLampImaging.exe
#
# imageio-ffmpeg 의 ffmpeg 바이너리와 PySide6 Qt 플러그인을 함께 수집한다.
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = ["imageio_ffmpeg"]

# 번들 ffmpeg 바이너리 동봉 (mp4 H.264 보장)
binaries += collect_dynamic_libs("imageio_ffmpeg")
datas += collect_data_files("imageio_ffmpeg")

# DB 스키마 파일 동봉
datas += [("app/db/schema.sql", "app/db")]

# 앱 아이콘 동봉
datas += [("assets/icons/app.ico", "assets/icons"),
          ("assets/icons/app.png", "assets/icons")]

block_cipher = None

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SlitLampImaging",
    console=False,
    icon="assets/icons/app.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="SlitLampImaging",
)
