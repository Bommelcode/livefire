# build-exe.ps1 — bouwt een lokale livefire.exe (onedir) via PyInstaller.
#
# Gebruik (vanuit PowerShell in de project-map):
#     .\build-exe.ps1
#
# Resultaat: dist\livefire\livefire.exe (+ alle dependencies ernaast).
# Dit is een dev-build, nog geen installer. Voor de echte installer-build
# komt er t.z.t. een separate Inno Setup configuratie (v1.0).

$ErrorActionPreference = "Stop"

# Zorg dat venv bestaat en PyInstaller erin staat
if (-not (Test-Path ".venv")) {
    Write-Host "Venv aanmaken..."
    py -3 -m venv .venv
}

Write-Host "Dependencies + PyInstaller installeren..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller

# Oude build wissen
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, livefire.spec

Write-Host "PyInstaller bouwt livefire.exe..."
.\.venv\Scripts\pyinstaller.exe `
    --name livefire `
    --windowed `
    --noconfirm `
    --clean `
    --collect-submodules livefire `
    --collect-data sounddevice `
    --collect-data soundfile `
    -p . `
    livefire\__main__.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build faalde." -ForegroundColor Red
    exit 1
}

$exe = ".\dist\livefire\livefire.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "Klaar: $exe" -ForegroundColor Green
    Write-Host "De hele dist\livefire\-map is portable — kopieer die naar een andere PC en livefire.exe werkt zonder Python te installeren."
} else {
    Write-Host "Build voltooid maar exe niet gevonden. Check output hierboven." -ForegroundColor Yellow
}
