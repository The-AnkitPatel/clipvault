@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo =======================================================
echo    Windows Clipboard Enhancement Suite - Uninstaller
echo =======================================================
echo.

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_LNK=%STARTUP_DIR%\clipboard-daemon.lnk"
set "STARTUP_VBS=%STARTUP_DIR%\clipboard-daemon.vbs"

echo [1/3] Terminating running clipboard processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*clipboard-daemon*' -or $_.CommandLine -like '*clipboard-daemon*' -or $_.CommandLine -like '*clipboard-popup*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo   - Processes stopped.

echo [2/3] Removing from Windows Startup...
if exist "%STARTUP_LNK%" del /f /q "%STARTUP_LNK%" >nul 2>&1
if exist "%STARTUP_VBS%" del /f /q "%STARTUP_VBS%" >nul 2>&1
echo   - Startup entry removed.

echo [3/3] Restoring Windows default settings...
reg add "HKCU\Software\Microsoft\Clipboard" /v EnableClipboardHistory /t REG_DWORD /d 1 /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v DisabledHotkeys /f >nul 2>&1
reg add "HKCU\Control Panel\Keyboard" /v PrintScreenKeyForSnippingEnabled /t REG_DWORD /d 1 /f >nul 2>&1
echo   - Windows built-in Clipboard History and Snipping Tool re-enabled.

echo.
echo =======================================================
echo  [OK] Uninstalled successfully.
echo =======================================================
echo.
if "%~1"=="" (
    echo Press any key to continue . . .
    powershell -NoProfile -Command "Start-Sleep -Seconds 3" >nul 2>&1
)
