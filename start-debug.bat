@echo off
rem Debug-versie: venster blijft open zodat je tracebacks ziet.

setlocal ENABLEEXTENSIONS
cd /d "%~dp0"

echo ===== liveFire debug launcher =====
echo Werkmap: %CD%
echo.

set PYEXE=py
where py >nul 2>nul
if errorlevel 1 set PYEXE=python

echo --- Python versie ---
%PYEXE% --version

if not exist .venv (
    echo --- Venv aanmaken ---
    %PYEXE% -3 -m venv .venv
)

if not exist .venv\.deps_installed (
    echo --- Pip upgrade ---
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    echo.
    echo --- Dependencies installeren ---
    ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
    if %errorlevel%==0 (
        echo. > ".venv\.deps_installed"
    ) else (
        echo Install faalde met exit %errorlevel%
    )
)

echo.
echo --- liveFire starten ---
".venv\Scripts\python.exe" -m livefire
echo.
echo liveFire afgesloten, exit code: %errorlevel%
echo.
pause
endlocal
