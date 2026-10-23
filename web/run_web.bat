@echo off
rem 슬릿램프 영상 시스템 (웹) - 원클릭 실행 런처
rem 처음 실행 시 가상환경 생성 + 의존성 설치, 이후에는 바로 서버 시작.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ====================================================
echo  슬릿램프 영상 시스템 (웹) 시작
echo ====================================================
echo.

if not exist ".venv" (
  echo [최초 1회] 가상환경 생성 및 의존성 설치 중... 잠시만 기다려 주세요.
  python -m venv .venv
  if errorlevel 1 ( echo [오류] Python 이 설치되어 있는지 확인하세요. & pause & exit /b 1 )
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt
  if errorlevel 1 ( echo [오류] 의존성 설치 실패 & pause & exit /b 1 )
) else (
  call ".venv\Scripts\activate.bat"
)

echo.
echo 브라우저가 곧 http://localhost:8000 으로 열립니다.
echo 이 창을 닫으면 프로그램이 종료됩니다.
echo.

rem 서버가 뜰 시간을 준 뒤 기본 브라우저로 자동 접속
start "" /b cmd /c "timeout /t 3 >nul & start "" http://localhost:8000"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
