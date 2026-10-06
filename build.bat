@echo off
setlocal
cd /d "%~dp0"
echo Building WRSR Mod Installer...
echo.

REM Build with the project's own virtual environment (.venv), so the exe always gets the
REM app's requirements, whatever else is installed in the Python on PATH.
if not exist ".venv\Scripts\python.exe" (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if errorlevel 1 (
        echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/
        goto :failed
    )
    echo Creating a virtual environment in .venv...
    python -m venv .venv || goto :failed
)

echo Installing the requirements into .venv...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :failed

echo Creating the executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm "WRSR Mod Installer.spec" || goto :failed

echo.
echo Build complete! The executable is in the 'dist' folder.
pause
exit /b 0

:failed
echo.
echo Build failed. See the messages above.
echo If WRSR Mod Installer is open, close it and run build.bat again.
pause
exit /b 1
