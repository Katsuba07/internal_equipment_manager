<#
    UPDATE THE SYSTEM

    Run on the server after a new version has been pushed to GitHub:
    fetches the code, installs anything new it needs, and starts the
    system again. The data (the data\ folder) and .env are never touched.

    People are cut off for about a minute - pick a quiet moment.
    Usage: right-click > Run with PowerShell, or .\scripts\update.ps1
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Stop-WithMessage($text) {
    Write-Host "`n $text`n" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Stop-WithMessage "Not installed yet. Run .\scripts\install.ps1 first." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Stop-WithMessage "Git is not installed. Get it from https://git-scm.com/download/win and run this again."
}

# --- 1. Fetch the new code ---
# Code is only ever changed on the development PC. An edit made here would be
# silently mixed into the update, so stop and let a person decide.
Write-Host ">>> Fetching the new version..." -ForegroundColor Cyan
$localEdits = & git status --porcelain --untracked-files=no
if ($localEdits) {
    Write-Host $($localEdits -join "`n")
    Stop-WithMessage "These files were edited on this server. Undo the edits (git restore .) or ask the developer, then run this again."
}
$before = & git rev-parse HEAD
& git pull --ff-only
if ($LASTEXITCODE -ne 0) { Stop-WithMessage "Could not fetch the update (see the message above). Nothing was changed." }
$after = & git rev-parse HEAD

if ($before -eq $after) {
    Write-Host "    Already on the newest version." -ForegroundColor Green
} else {
    Write-Host "    Updated:" -ForegroundColor Green
    & git log --oneline "$before..$after"
}

# --- 2. Anything new the code needs ---
Write-Host ">>> Checking dependencies..." -ForegroundColor Cyan
& $python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Stop-WithMessage "Installing dependencies failed. The system was left as it was running." }

# --- 3. Start the system again ---
$service = Get-Service -Name "EquipmentManager" -ErrorAction SilentlyContinue
if ($service) {
    # Installed as a Windows service (OPERATIONS-GUIDE.md, section 4): the
    # service does not run run-server.ps1, so do its two preparation steps here.
    Write-Host ">>> Updating the database and interface files..." -ForegroundColor Cyan
    & $python manage.py migrate --noinput
    & $python manage.py collectstatic --noinput | Out-Null
    Write-Host ">>> Restarting the service..." -ForegroundColor Cyan
    Restart-Service -Name "EquipmentManager"
    Write-Host "`n Update complete. The system is running again.`n" -ForegroundColor Green
    Read-Host "Press Enter to close"
    exit 0
}

# Running in a window: close the old one, then start the system in this one.
$port = if ($env:EMA_PORT) { $env:EMA_PORT } else { "8000" }
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
             Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $listeners) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -like "python*") {
        Write-Host ">>> Stopping the running system..." -ForegroundColor Cyan
        Stop-Process -Id $processId -Force
    } elseif ($process) {
        Stop-WithMessage "Port $port is in use by '$($process.ProcessName)', not by this system. Close it and run this again."
    }
}

& (Join-Path $PSScriptRoot "run-server.ps1")
