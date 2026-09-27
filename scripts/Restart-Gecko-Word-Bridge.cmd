@echo off
setlocal
cd /d "%~dp0.."

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_word_validation_bridge.ps1"
exit /b %ERRORLEVEL%
