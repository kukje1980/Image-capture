# PyInstaller 런타임 훅 — Keeler 전용 설치본은 항상 Keeler 브랜드로 실행
import os

os.environ.setdefault("SLITLAMP_BRAND", "keeler")
