@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python server.py
  goto done
)
echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
:done
pause
