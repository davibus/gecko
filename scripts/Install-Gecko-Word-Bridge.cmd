@echo off
setlocal
cd /d "%~dp0.."

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_word_validation_bridge.ps1"
set "GECKO_EXIT=%ERRORLEVEL%"
if not "%GECKO_EXIT%"=="0" goto :failure

echo.
echo Gecko Word validation bridge installed successfully.
echo Completing pending native Word validations...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0complete_pending_word_validations.ps1"
set "GECKO_EXIT=%ERRORLEVEL%"
if not "%GECKO_EXIT%"=="0" goto :failure

echo.
echo Gecko native Word validation is ready and the pending queue is clear.
echo.
pause
exit /b 0

:failure
echo.
echo The bridge installation or a pending validation failed. Review the error above.
echo.
pause
exit /b %GECKO_EXIT%
