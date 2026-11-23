@echo off
if exist "%~dp0bin\clipvault-popup.exe" (
    start "" "%~dp0bin\clipvault-popup.exe"
) else (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0clipboard\clipboard_popup.pyw"
)
