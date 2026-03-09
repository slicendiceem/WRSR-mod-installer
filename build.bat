@echo off
echo Building WRSR Mod Installer executable...
echo.

REM Check if PyInstaller is installed
python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    python -m pip install PyInstaller==6.1.0
)

REM Build the executable
echo Creating executable...
pyinstaller --onefile --windowed --name "WRSR Mod Installer" mod_installer.py

echo.
echo Build complete! The executable is in the 'dist' folder.
pause
