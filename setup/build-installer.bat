@echo off
chcp 65001 >nul
echo ========================================================
echo   Building the single-file installer
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "BASE_DIR=%%~fI"

if not exist "%BASE_DIR%\bin\clipvault.exe" (
    echo [ERROR] Build the suite first: clipboard\build-exe.bat
    exit /b 1
)

echo [1/2] Packing %BASE_DIR%\bin into one executable...
"%BASE_DIR%\.venv\Scripts\pyinstaller.exe" --noconfirm --clean ^
    --distpath "%BASE_DIR%\release" ^
    --workpath "%SCRIPT_DIR%build" ^
    "%SCRIPT_DIR%installer.spec"

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Build failed.
    exit /b 1
)

echo [2/2] Done.
echo Installer: %BASE_DIR%\release\ClipVaultSetup.exe
echo.
pause
