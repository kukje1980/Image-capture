# PyInstaller 런타임 훅 — 안저판 설치본은 항상 안저 제품으로 실행 (데이터 폴더 FundusImaging)
import os

os.environ.setdefault("SLITLAMP_BRAND", "fundus")
