@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ===================================================
echo     Windows Enhancement Suite - Installer
echo     Clipboard Manager + Performance Boost
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%clipboard\setup-clipboard.bat" %*
