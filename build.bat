@echo off
echo Building WRSR Mod Installer executable...
echo.

REM Check if PyInstaller is installed
python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    python -m pip install PyInstaller==6.1.0
)

REM Build the executable using the spec file
REM This ensures logos folder and all assets are included
echo Creating executable...
pyinstaller "WRSR Mod Installer.spec" --onefile --windowed

echo.
echo Build complete! The executable is in the 'dist' folder.
pause
