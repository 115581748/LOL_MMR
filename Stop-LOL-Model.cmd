@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_local_app.ps1"
if errorlevel 1 pause
