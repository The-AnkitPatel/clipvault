@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo =======================================================
echo    Compiling Standalone Windows Clipboard Executable
echo =======================================================
echo.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "BASE_DIR=%%~fI"

cd /d "%SCRIPT_DIR%"

echo [1/3] Running PyInstaller build...
"%BASE_DIR%\.venv\Scripts\pyinstaller.exe" --noconfirm --clean clipboard.spec

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed!
    exit /b 1
)

echo [2/3] Deploying binaries to %BASE_DIR%\bin ...
if exist "%BASE_DIR%\bin" rd /s /q "%BASE_DIR%\bin"
xcopy /E /I /Y "%SCRIPT_DIR%dist\clipboard" "%BASE_DIR%\bin" >nul

echo [3/3] Build completed successfully!
echo Executable located at: %BASE_DIR%\bin\clipboard-daemon.exe
echo Executable located at: %BASE_DIR%\bin\clipboard-popup.exe
echo.
pause
