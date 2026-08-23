@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_local_app.ps1"
if errorlevel 1 pause
