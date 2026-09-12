@echo off
setlocal
cd /d "%~dp0"
if exist "YuE2 Studio.exe" (
  start "" "YuE2 Studio.exe"
  exit /b 0
)
echo Run Setup YuE2 Studio.bat first.
pause
exit /b 1
