# PyInstaller 런타임 훅 — AI 에이전트 에디션 설치본은 항상 에이전트 에디션으로 실행 (데이터 폴더 SlitLampAgent)
import os

os.environ.setdefault("SLITLAMP_EDITION", "agent")
