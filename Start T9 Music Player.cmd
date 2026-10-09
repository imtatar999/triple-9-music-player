@echo off
setlocal
cd /d "%~dp0"
title T9 Music Player

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

python -c "import PySide6, av, sounddevice, mutagen, numpy" >nul 2>nul
if errorlevel 1 (
    echo Installing the packages T9 Music Player needs - this happens only once...
    python -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Installation failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

where pythonw >nul 2>nul
if errorlevel 1 (
    start "" python "T9 Music Player.pyw" %*
) else (
    start "" pythonw "T9 Music Player.pyw" %*
)
