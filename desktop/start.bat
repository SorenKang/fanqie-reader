@echo off
rem Launch the reader without a console window.
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 (
    echo Python not found.
    echo Install Python 3.9+ from https://www.python.org/downloads/
    echo and remember to check "Add Python to PATH".
    pause
    exit /b 1
)

start "" pythonw "reader.py"
