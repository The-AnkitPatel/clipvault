@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ===================================================
echo     ClipVault - Installer
echo     Encrypted Clipboard History + Flameshot
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%clipboard\setup-clipboard.bat" %*
