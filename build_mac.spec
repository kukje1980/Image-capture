# PyInstaller 스펙 (macOS, .app 번들).
#   빌드:  ./build_mac.sh   (또는 pyinstaller build_mac.spec)
#   결과:  dist/SlitLampImaging.app  (SLITLAMP_BUILD_BRAND=keeler 이면 dist/KeelerSlitLamp.app)
#
# Windows 용 build.spec 과 같은 구성에 macOS 번들 정보(카메라 권한 문구·아이콘)를 더한다.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

APP_VERSION = "1.11.0"
BRAND = os.environ.get("SLITLAMP_BUILD_BRAND", "default").lower()
KEELER = BRAND == "keeler"
APP_NAME = "KeelerSlitLamp" if KEELER else "SlitLampImaging"
DISPLAY_NAME = "Keeler 슬릿램프 영상 시스템" if KEELER else "슬릿램프 영상 시스템"
APP_ICON = "assets/brand/keeler/app.icns" if KEELER else "assets/icons/app.icns"
BUNDLE_ID = "com.kukjemd.keelerslitlamp" if KEELER else "com.kukjemd.slitlampimaging"

datas = []
binaries = []
hiddenimports = ["imageio_ffmpeg"]

# 번들 ffmpeg 바이너리 동봉 (mp4 H.264 보장)
binaries += collect_dynamic_libs("imageio_ffmpeg")
datas += collect_data_files("imageio_ffmpeg")

# DICOM 내보내기 (pydicom 은 일부 모듈을 실행 중에 불러오므로 하위 모듈을 모두 포함, 테스트·예제 제외)
hiddenimports += collect_submodules("pydicom", filter=lambda n: ".tests" not in n and ".examples" not in n)

# DB 스키마 파일 동봉
datas += [("app/db/schema.sql", "app/db")]

# 앱 아이콘 동봉
datas += [("assets/icons/app.png", "assets/icons")]
datas += [("assets/brand", "assets/brand")]
# 효과음 (캡처 찰칵 · 정지영상 · 녹화 삐)
datas += [("assets/sounds", "assets/sounds")]

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=["tools/rthooks/brand_keeler.py"] if KEELER else [],
    excludes=[],
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    argv_emulation=False,
    target_arch=None,          # 빌드하는 Mac 의 아키텍처 (Apple Silicon = arm64, Intel = x86_64)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=APP_ICON,
    bundle_identifier=BUNDLE_ID,
    version=APP_VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": DISPLAY_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # 카메라(HDMI 캡처 장비) 접근 시 macOS 가 보여 주는 권한 요청 문구 — 없으면 카메라를 열 수 없다
        "NSCameraUsageDescription": "세극등 HDMI 캡처 장비(카메라)의 실시간 영상을 촬영·녹화하기 위해 카메라 접근이 필요합니다.",
        "NSMicrophoneUsageDescription": "동영상 녹화 장비가 오디오 장치로도 인식될 때 필요할 수 있습니다.",
    },
)
