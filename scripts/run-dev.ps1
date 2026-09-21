<#
    DEVELOPMENT MODE

    Use this to try out changes on your own machine.
    Do NOT use it for real users: it is slower and shows technical error
    details on screen. Use run-server.ps1 for that.
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Not installed yet. Run .\scripts\install.ps1 first." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$env:EMA_DEBUG = "True"
Write-Host "`nDevelopment mode - open http://localhost:8000`n" -ForegroundColor Cyan
& $python manage.py runserver 0.0.0.0:8000
