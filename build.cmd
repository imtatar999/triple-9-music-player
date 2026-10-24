@echo off
setlocal
cd /d "%~dp0"
title Build T9 Music Player

rem Prefer the Python launcher (py) with 3.11, fall back to python on PATH
set "PYEXE="
where py >nul 2>nul && py -3.11 -c "import sys" >nul 2>nul && set "PYEXE=py -3.11"
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
    echo Python 3.10+ is needed to BUILD the program ^(not to run it^).
    echo Install it from https://www.python.org/downloads/ and run this again.
    pause
    exit /b 1
)

%PYEXE% build.py %*
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (echo Build finished. The installer is in the "dist" folder.) else (echo Build FAILED - see the messages above.)
pause
exit /b %CODE%
