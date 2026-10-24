@echo off
rem 슬릿램프 영상 시스템 (웹) - 원클릭 실행 런처 (Windows)
rem 처음 실행 시 가상환경 생성 + 의존성 설치, 이후에는 바로 서버 시작.
rem 서버가 실제로 응답하면 브라우저를 http://127.0.0.1:8000 으로 연다.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ====================================================
echo  슬릿램프 영상 시스템 (웹) 시작
echo ====================================================
echo.

rem --- Python 3.11 ~ 3.13 우선 선택 (py 런처), 없으면 PATH 의 python (3.11 이상) ---
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [오류] Python 3.11 이상을 찾을 수 없습니다.
  echo        https://www.python.org/downloads/ 에서 설치하고,
  echo        설치 첫 화면의 "Add python.exe to PATH" 를 체크하세요.
  pause & exit /b 1
)
echo 사용할 Python: %PY%

rem --- 최초 설치 (설치가 끝까지 성공해야 .installed 표시가 생긴다) ---
if not exist ".venv\.installed" (
  echo.
  echo [최초 1회] 가상환경 생성 및 의존성 설치 중... 1~2분 걸립니다.
  if exist ".venv" rmdir /s /q ".venv"
  %PY% -m venv .venv
  if errorlevel 1 ( echo [오류] 가상환경 생성 실패 & pause & exit /b 1 )
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [오류] 의존성 설치 실패. 인터넷 연결을 확인한 뒤 다시 실행하세요.
    pause & exit /b 1
  )
  echo ok> ".venv\.installed"
) else (
  call ".venv\Scripts\activate.bat"
)

echo.
echo 서버를 시작합니다. 준비되면 브라우저가 자동으로 열립니다.
echo   주소: http://127.0.0.1:8000
echo   이 창을 닫으면 프로그램이 종료됩니다.
echo.

rem 서버가 응답할 때까지(최대 60초) 기다렸다가 브라우저 열기
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8000/' | Out-Null; Start-Process 'http://127.0.0.1:8000'; break}catch{Start-Sleep -Seconds 1}}"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo ====================================================
echo  서버가 종료되었습니다. 위에 오류 메시지가 있으면 확인하세요.
echo  (이미 다른 창에서 실행 중이면 "address already in use" 가 표시됩니다 -
echo   그 경우 브라우저에서 http://127.0.0.1:8000 을 열면 됩니다.)
echo ====================================================
pause
