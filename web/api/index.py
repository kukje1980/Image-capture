"""Vercel 서버리스 진입점 (MedFix 와 같은 구성). Vercel 프로젝트의 Root Directory 를 web 으로 지정."""
from app.main import app  # noqa: F401
