@echo off
:: feishu-deck-h5  ·  one-click text-apply launcher (Windows)
:: Double-click this file in Explorer to apply edits from texts.md back
:: into index.html.

cd /d "%~dp0"

echo ================================================================
echo   feishu-deck-h5  .  apply texts.md - index.html
echo ================================================================
echo.

:: Try py launcher first (recommended on Windows), then python, then python3
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" where python3 >nul 2>nul && set PY=python3

if "%PY%"=="" (
    echo ERROR  Python 3 not found on this PC.
    echo.
    echo Fix: install Python 3 from https://python.org/downloads/
    echo During install, tick "Add Python to PATH".
    echo Then double-click this file again.
    echo.
    pause
    exit /b 1
)

%PY% apply-texts.py
echo.
echo Tip: open index.html in your browser and refresh to see changes.
echo.
pause
