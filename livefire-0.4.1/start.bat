@echo off
rem liveFire dev-launcher voor Windows.
rem Maakt bij eerste run automatisch een venv aan en installeert dependencies.
rem Daarna: dubbelklikken om de app te starten.

setlocal ENABLEEXTENSIONS
cd /d "%~dp0"

set PYEXE=py
where py >nul 2>nul
if errorlevel 1 set PYEXE=python

if not exist .venv (
    echo --- Eerste keer: venv aanmaken ---
    %PYEXE% -3 -m venv .venv
    if errorlevel 1 (
        echo Venv aanmaken mislukt. Is Python 3.11+ geinstalleerd?
        pause
        exit /b 1
    )
)

if not exist .venv\.deps_installed (
    echo --- Dependencies installeren ---
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
    if errorlevel 1 (
        echo Dependency-installatie mislukt.
        pause
        exit /b 1
    )
    echo. > ".venv\.deps_installed"
)

".venv\Scripts\python.exe" -m livefire
endlocal
