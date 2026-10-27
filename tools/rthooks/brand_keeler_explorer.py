# PyInstaller 런타임 훅 — Keeler Explorer 판 설치본은 항상 Keeler 로고·색의 Explorer 화면으로 실행
import os

os.environ.setdefault("SLITLAMP_BRAND", "keeler_explorer")
