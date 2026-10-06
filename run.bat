@echo off
setlocal
cd /d "%~dp0"

REM Run with the project's own virtual environment (.venv), setting it up when needed.
if not exist ".venv\Scripts\python.exe" (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if errorlevel 1 (
        echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/
        goto :failed
    )
    echo Setting up a virtual environment in .venv...
    python -m venv .venv || goto :failed
)
".venv\Scripts\python.exe" -c "import PyQt5, requests" >nul 2>&1
if errorlevel 1 (
    echo Installing the requirements into .venv...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :failed
)

".venv\Scripts\python.exe" mod_installer.py
if errorlevel 1 pause
exit /b

:failed
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
