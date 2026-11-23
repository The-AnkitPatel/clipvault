@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo =======================================================
echo    Windows Clipboard Enhancement Suite - Installer
echo =======================================================
echo.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "BASE_DIR=%%~fI"

set "BIN_EXE=%BASE_DIR%\bin\clipboard-daemon.exe"
set "POPUP_EXE=%BASE_DIR%\bin\clipboard-popup.exe"
set "VENV_PYTHONW=%BASE_DIR%\.venv\Scripts\pythonw.exe"
set "DAEMON_SCRIPT=%SCRIPT_DIR%clipboard_daemon.pyw"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_LNK=%STARTUP_DIR%\clipboard-daemon.lnk"
set "STARTUP_VBS=%STARTUP_DIR%\clipboard-daemon.vbs"

:: Clean any legacy VBScript startup files
if exist "%STARTUP_VBS%" del /f /q "%STARTUP_VBS%" >nul 2>&1

echo [1/4] Disabling Windows default Clipboard history conflict...
reg add "HKCU\Software\Microsoft\Clipboard" /v EnableClipboardHistory /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v DisabledHotkeys /t REG_SZ /d "V" /f >nul 2>&1
echo   - Windows built-in Win+V freed successfully.

echo [2/4] Configuring PrintScreen for Flameshot...
reg add "HKCU\Control Panel\Keyboard" /v PrintScreenKeyForSnippingEnabled /t REG_DWORD /d 0 /f >nul 2>&1
echo   - Windows Snipping Tool override disabled (PrtScn assigned to Flameshot).

echo [3/4] Registering auto-start on Windows login...
if exist "%BIN_EXE%" (
    powershell -NoProfile -Command "$sh = New-Object -ComObject WScript.Shell; $sc = $sh.CreateShortcut('%STARTUP_LNK%'); $sc.TargetPath = '%BIN_EXE%'; $sc.WorkingDirectory = '%BASE_DIR%\bin'; $sc.Description = 'Windows Clipboard Enhancement Daemon'; $sc.Save()" >nul 2>&1
    echo   - Standalone Daemon executable registered in Startup folder.
) else (
    (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.Run chr^(34^) ^& "%VENV_PYTHONW%" ^& chr^(34^) ^& " " ^& chr^(34^) ^& "%DAEMON_SCRIPT%" ^& chr^(34^), 0, False
    ) > "%STARTUP_VBS%"
    echo   - Python script daemon registered in Startup folder.
)

:: Check and add Flameshot to startup if installed
set "FLAMESHOT_EXE=C:\Program Files\Flameshot\bin\flameshot.exe"
if exist "%FLAMESHOT_EXE%" (
    powershell -NoProfile -Command "$sh = New-Object -ComObject WScript.Shell; $sc = $sh.CreateShortcut(\"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Flameshot.lnk\"); $sc.TargetPath = 'C:\Program Files\Flameshot\bin\flameshot.exe'; $sc.WorkingDirectory = 'C:\Program Files\Flameshot\bin'; $sc.Save()" >nul 2>&1
    echo   - Flameshot registered for background startup.
)

echo [4/4] Starting Clipboard Daemon and Services...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*clipboard-daemon*' -or $_.CommandLine -like '*clipboard_daemon*' -or $_.CommandLine -like '*clipboard-daemon*' -or $_.CommandLine -like '*clipboard_popup*' -or $_.CommandLine -like '*clipboard-popup*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
powershell -NoProfile -Command "Start-Sleep -Milliseconds 600" >nul 2>&1

if exist "%BIN_EXE%" (
    powershell -NoProfile -Command "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = '%BIN_EXE%'; CurrentDirectory = '%BASE_DIR%\bin' }" >nul 2>&1
) else (
    start "" "%VENV_PYTHONW%" "%DAEMON_SCRIPT%"
)

if exist "%FLAMESHOT_EXE%" (
    powershell -NoProfile -Command "if (-not (Get-Process flameshot -ErrorAction SilentlyContinue)) { Start-Process '%FLAMESHOT_EXE%' }" >nul 2>&1
)
echo   - Daemon and Flameshot are now active and running in background!

echo.
echo =======================================================
echo  [OK] Windows Clipboard Enhancement is Ready!
echo.
echo  - Press Win+V (or Alt+V) anywhere to open AMOLED popup
echo  - Press PrtScn to trigger Flameshot screenshot GUI
echo  - Auto-captures screenshots with thumbnails & app tags
echo  - Multi-paste: click (o) or press Tab, then Enter
echo  - Pinned items (*) survive reboot and Clear all
echo =======================================================
echo.
if "%~1"=="" (
    echo Press any key to continue . . .
    powershell -NoProfile -Command "Start-Sleep -Seconds 3" >nul 2>&1
)
