@echo off
setlocal
cd /d "%~dp0"

echo.
echo  YuE2 Studio 0.4.0 - source build setup
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 was not found. Install it from python.org, enable the Python launcher,
  echo then run this file again.
  goto :failed
)
py -3.11 -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 was not found. Install Python 3.11 from python.org and try again.
  goto :failed
)
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js and npm are required. Install the current Node.js LTS release and try again.
  goto :failed
)
where cargo >nul 2>nul
if errorlevel 1 (
  echo Rust is required to build the desktop executable. Install rustup from rustup.rs and try again.
  goto :failed
)

echo Creating local data folders...
for %%D in ("outputs\library" "outputs\settings" "outputs\logs" "outputs\downloads" "models") do (
  if not exist %%D mkdir %%D
)

echo Creating the local backend environment...
if not exist "python\venv\Scripts\python.exe" py -3.11 -m venv "python\venv"
if errorlevel 1 goto :failed
"python\venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "python\requirements.txt"
if errorlevel 1 goto :failed

echo Installing JavaScript dependencies...
call npm ci
if errorlevel 1 goto :failed
echo Building the Windows desktop executable...
call npm run tauri build -- --no-bundle
if errorlevel 1 goto :failed
copy /y "src-tauri\target\release\yue2-studio.exe" "YuE2 Studio.exe" >nul
if errorlevel 1 goto :failed

echo.
echo Setup complete. Launch YuE2 Studio.exe, open Models, and choose the features
echo you want to install. Model files are deliberately not downloaded by this setup.
pause
exit /b 0
:failed
echo.
echo Setup failed. Review the message above. Building on Windows also requires the
echo Visual Studio 2022 Build Tools with the Desktop development with C++ workload.
pause
exit /b 1
