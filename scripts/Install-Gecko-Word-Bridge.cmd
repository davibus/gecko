@echo off
setlocal
cd /d "%~dp0.."

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_word_validation_bridge.ps1"
set "GECKO_EXIT=%ERRORLEVEL%"
if "%GECKO_EXIT%"=="0" echo Gecko Word validation bridge is installed, hidden, and self-healing.
if not "%GECKO_EXIT%"=="0" echo Gecko Word validation bridge installation failed. Review the diagnostics above.
exit /b %GECKO_EXIT%
