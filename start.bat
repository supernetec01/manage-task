@echo off
setlocal
cd /d "%~dp0"
if not defined PORT set "PORT=5001"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py --host 0.0.0.0 --port %PORT%
) else (
  python server.py --host 0.0.0.0 --port %PORT%
)
if errorlevel 1 (
  echo.
  echo Could not start Super Net. Check the error above.
  echo Python 3 is required. Keep this window open while using the website.
  pause
)
