@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ===================================================
echo     ClipVault - Uninstaller
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%clipboard\uninstall-clipboard.bat" %*
