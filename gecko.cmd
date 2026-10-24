@echo off
if /I "%~1"=="job" (
  "%~dp0.tools\dashboard-python\Scripts\python.exe" "%~dp0scripts\gecko.py" %*
  exit /b
)
if "%~1"=="" (
  powershell.exe -NoProfile -File "%~dp0scripts\Start-Gecko.ps1"
  exit /b
)
if /I "%~1"=="--status" (
  powershell.exe -NoProfile -File "%~dp0scripts\Start-Gecko.ps1" -Status
  exit /b
)
if /I "%~1"=="-Status" (
  powershell.exe -NoProfile -File "%~dp0scripts\Start-Gecko.ps1" -Status
  exit /b
)
"%~dp0.tools\dashboard-python\Scripts\python.exe" "%~dp0scripts\gecko.py" %*
exit /b
