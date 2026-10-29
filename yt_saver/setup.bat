@echo off
REM One-time setup for YT Saver. Installs everything into a private folder (.venv)
REM next to this file, so nothing else on your PC is touched.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed.
  echo Install it from https://www.python.org/downloads/  ^(check "Add python.exe to PATH"^)
  echo then run this file again.
  pause
  exit /b 1
)

echo Creating private environment...
py -3 -m venv .venv || goto :fail

echo Installing yt-dlp, ffmpeg and deno (official packages from PyPI)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -U "yt-dlp[default]" imageio-ffmpeg deno certifi customtkinter pillow || goto :fail

echo.
echo Setup complete. Double-click run.bat to start YT Saver.
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
