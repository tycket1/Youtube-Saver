@echo off
REM Builds a single "YT Saver.exe" you can keep anywhere or copy to other PCs.
REM Needs Python only for this one-time build; the finished .exe does not.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed.
  echo Install it from https://www.python.org/downloads/  ^(check "Add python.exe to PATH"^)
  echo then run this file again.
  pause
  exit /b 1
)

echo [1/4] Creating a private build environment...
py -3 -m venv .buildenv || goto :fail
set PY=.buildenv\Scripts\python.exe

echo [2/4] Installing yt-dlp, ffmpeg, deno and PyInstaller from PyPI...
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -U "yt-dlp[default]" imageio-ffmpeg deno certifi pyinstaller || goto :fail

echo [3/4] Gathering ffmpeg and deno...
"%PY%" prep_build.py || goto :fail

echo [4/4] Building YT Saver.exe (takes a few minutes)...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "YT Saver" ^
  --add-binary "build_bin\ffmpeg.exe;bin" ^
  --add-binary "build_bin\deno.exe;bin" ^
  --collect-all yt_dlp ^
  --collect-all yt_dlp_ejs ^
  --collect-data certifi ^
  yt_saver.py || goto :fail

copy /y "dist\YT Saver.exe" "YT Saver.exe" >nul
echo.
echo Done!  "YT Saver.exe" is in this folder. You can delete .buildenv, build and dist.
pause
exit /b 0

:fail
echo.
echo Build failed - see the messages above.
pause
exit /b 1
