@echo off
rem Native Windows configuration and Gateway check; does not start a service.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Gecko-OpenClaw-Connection.ps1" -Action Check
set "geckoResult=%ERRORLEVEL%"
pause
exit /b %geckoResult%
