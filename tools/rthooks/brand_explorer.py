# PyInstaller 런타임 훅 — Explorer 판 설치본은 항상 Explorer 화면으로 실행
import os

os.environ.setdefault("SLITLAMP_BRAND", "explorer")
