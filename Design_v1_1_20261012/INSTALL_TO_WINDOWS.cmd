@echo off
powershell.exe -NoProfile -File "%~dp0scripts\install_design.ps1"
if errorlevel 1 (
  echo Installation stopped. See the message above.
  pause
  exit /b 1
)
pause
