@echo off
setlocal
cd /d "%~dp0"
if not defined PORT set "PORT=5001"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py --host 0.0.0.0 --port %PORT%
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10+ is required. Install it from https://www.python.org/downloads/windows/
    echo Select Add Python to PATH, then reopen this launcher.
    pause
    exit /b 1
  )
  python server.py --host 0.0.0.0 --port %PORT%
)
if errorlevel 1 (
  echo.
  echo Could not start Super Net. Check the error above.
  echo If port %PORT% is already in use, close the old server window or choose another port.
  pause
)
