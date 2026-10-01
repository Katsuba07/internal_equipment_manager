<#
    START THE SYSTEM (production mode)

    Serves the app with Waitress, a stable WSGI server for Windows.
    Leave this window open while people are using the system.
    To start it automatically at boot, see OPERATIONS-GUIDE.md.
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "`n Not installed yet. Run .\scripts\install.ps1 first.`n" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$port = if ($env:EMA_PORT) { $env:EMA_PORT } else { "8000" }

# Apply any pending schema changes from an update before serving.
Write-Host ">>> Checking the database..." -ForegroundColor Cyan
& $python manage.py migrate --noinput

# Production mode serves compiled static files from staticfiles/, a separate
# copy from static/ — without this, an updated .css/.js after a code change
# keeps serving the old version even after restarting the server.
Write-Host ">>> Syncing static files..." -ForegroundColor Cyan
& $python manage.py collectstatic --noinput | Out-Null

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
       Select-Object -First 1).IPAddress

Write-Host "`n===============================================" -ForegroundColor Green
Write-Host " EQUIPMENT MANAGER IS RUNNING" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host " This machine    : http://localhost:$port"
Write-Host " Other machines  : http://${ip}:$port"
Write-Host ""
Write-Host " Do NOT close this window while people are using the system." -ForegroundColor Yellow
Write-Host " To stop: press Ctrl + C" -ForegroundColor Yellow
Write-Host "===============================================`n" -ForegroundColor Green

$env:DJANGO_SETTINGS_MODULE = "config.settings"
# Invoked as a module, not the venv's waitress-serve.exe: that launcher has the
# python.exe path from install time baked in, so it breaks if the project
# folder is ever moved or copied (e.g. Desktop -> D:\...) after install.
& $python -m waitress --listen=0.0.0.0:$port --threads=8 config.wsgi:application
