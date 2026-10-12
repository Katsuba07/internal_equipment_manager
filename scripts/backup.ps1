<#
    BACK UP THE DATA

    Usage:
        .\scripts\backup.ps1
        .\scripts\backup.ps1 -Destination "\\fileserver\Backup\EMA" -Keep 30

    Schedule this nightly with Task Scheduler.
    Step-by-step instructions are in OPERATIONS-GUIDE.md.
#>

param(
    # Folder to write backups to. Defaults to a folder beside the project.
    [string]$Destination = "",
    # How many recent backups to keep.
    [int]$Keep = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Not installed yet. Run .\scripts\install.ps1 first." -ForegroundColor Red
    exit 1
}

# With no -Destination, use EMA_BACKUP_DIR from .env, so the nightly task
# needs no arguments and the folder is set in one place.
if ([string]::IsNullOrWhiteSpace($Destination) -and (Test-Path ".env")) {
    $line = Get-Content ".env" | Where-Object { $_ -match '^\s*EMA_BACKUP_DIR\s*=' } | Select-Object -Last 1
    if ($line) { $Destination = ($line -split "=", 2)[1].Trim().Trim('"') }
}
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path (Split-Path -Parent $root) "EMA-Backup"
    Write-Host "No destination given, using: $Destination" -ForegroundColor Yellow
    Write-Host "Point this at a network share so backups do not sit on the same machine as the original." -ForegroundColor Yellow
    Write-Host ""
}

& $python manage.py backup_db --dest "$Destination" --keep $Keep

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBACKUP FAILED. Check the error above." -ForegroundColor Red
    exit $LASTEXITCODE
}
