@echo off
setlocal
cd /d "%~dp0"

echo Installing YuE2 lyric synchronization...
if not exist "python\lyrics_runtime\Scripts\python.exe" py -3.11 -m venv "python\lyrics_runtime"
if errorlevel 1 goto :failed

"python\lyrics_runtime\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"python\lyrics_runtime\Scripts\python.exe" -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto :failed
"python\lyrics_runtime\Scripts\python.exe" -m pip install whisperx==3.8.4 torchcodec==0.7.0
if errorlevel 1 goto :failed

if not exist "models\lyrics" mkdir "models\lyrics"
echo.
echo Lyric synchronization is ready.
echo Language alignment models are kept under models\lyrics and download on first use.
pause
exit /b 0

:failed
echo.
echo Lyric synchronization setup failed. Review the error above.
pause
exit /b 1
