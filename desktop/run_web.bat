@echo off
REM Launches the Flying 200 desktop web GUI on http://localhost:8080
REM Run from inside the `desktop/` directory: `run_web.bat`

setlocal
set PORT=8080
cd /d "%~dp0\.."

echo.
echo Flying 200 - Desktop Web GUI
echo http://localhost:%PORT%
echo Press Ctrl+C to stop
echo.

start "" "http://localhost:%PORT%"
python -m desktop --web --port %PORT%
