@echo off
rem Explicit interactive Windows sign-in only; never run automatically on failure.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Gecko-OpenClaw-Connection.ps1" -Action Login
set "geckoResult=%ERRORLEVEL%"
pause
exit /b %geckoResult%
