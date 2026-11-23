@echo off
if exist "%~dp0bin\clipboard-popup.exe" (
    start "" "%~dp0bin\clipboard-popup.exe"
) else (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0clipboard\clipboard_popup.pyw"
)
