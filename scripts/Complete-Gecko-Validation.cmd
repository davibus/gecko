@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0complete_pending_word_validations.ps1"
set "GECKO_EXIT=%ERRORLEVEL%"
echo.
if "%GECKO_EXIT%"=="0" (
  echo Gecko native Word validation and pending tracker updates completed successfully.
) else (
  echo Gecko validation did not complete. Review the error above.
)
echo.
pause
exit /b %GECKO_EXIT%
