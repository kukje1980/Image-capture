@echo off
rem Build dist\FundusViewer\FundusViewer.exe on Windows 10/11 (Python 3.10+ in PATH).
rem (Messages are in English: cmd.exe shows UTF-8 Korean text garbled.)
setlocal
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller pytest || goto :error
set QT_QPA_PLATFORM=offscreen
python -m pytest -q tests || goto :error
set QT_QPA_PLATFORM=
pyinstaller fundus_viewer.spec --noconfirm || goto :error
echo.
echo Done: dist\FundusViewer\FundusViewer.exe
echo Copy the whole dist\FundusViewer folder. Try it with: FundusViewer.exe --demo
exit /b 0
:error
echo Build failed.
exit /b 1
