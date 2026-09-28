@echo off
rem OCR review tool launcher (Windows)
rem First run creates .venv in this folder and installs Flask.
cd /d "%~dp0"
set PYTHONUTF8=1

if exist ".venv\Scripts\python.exe" goto run

set PY=
py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && set PY=py -3
if not defined PY (
    python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>&1 && set PY=python
)
if not defined PY (
    echo Python 3.8+ not found. Please install it from https://www.python.org/downloads/
    echo During install, check "Add python.exe to PATH".
    pause
    exit /b 1
)

echo First run: creating environment and installing Flask ...
%PY% -m venv .venv
if errorlevel 1 ( pause & exit /b 1 )
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ( pause & exit /b 1 )

:run
".venv\Scripts\python.exe" tool.py %*
pause
