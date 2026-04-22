@echo off
REM Launch the Power-Cadence Constraints GUI
cd /d "%~dp0"
python -c "from constraints.gui import main; main()"
pause
