@echo off
setlocal
cd /d "%~dp0"

echo Setting up the private Stable Audio 3 Small SFX CPU runtime...
if not exist "python\sfx_runtime\Scripts\python.exe" py -3.11 -m venv "python\sfx_runtime"
if errorlevel 1 goto :failed
"python\sfx_runtime\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"python\sfx_runtime\Scripts\python.exe" -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :failed
"python\sfx_runtime\Scripts\python.exe" -m pip install "git+https://github.com/Stability-AI/stable-audio-3.git@a0b57f5483c4588f827f3552b7d5c6ca2a9687be"
if errorlevel 1 goto :failed

echo.
echo Sound-effects runtime ready. YuE2 remains on the GPU while sound effects run on the CPU.
pause
exit /b 0

:failed
echo.
echo Sound-effects setup failed. Review the error above.
pause
exit /b 1
