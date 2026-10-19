<#
    START THE SYSTEM (production mode)

    Serves the app with Waitress, a stable WSGI server for Windows.
    Leave this window open while people are using the system.
    To start it automatically at boot, see OPERATIONS-GUIDE.md.

    With EMA_TUNNEL_TOKEN in .env it also starts the Cloudflare Tunnel, so
    the app can be reached from outside the plant, and stops it again with
    the app. No Administrator rights needed. Its log: data\cloudflared.log.
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

# A value from .env (the app reads the same file).
function Get-EnvSetting([string]$name) {
    $file = Join-Path $root ".env"
    if (-not (Test-Path $file)) { return "" }
    foreach ($line in Get-Content $file) {
        if ($line -match "^\s*$name\s*=\s*(.*?)\s*$") { return $Matches[1].Trim('"', "'") }
    }
    return ""
}

function Find-Cloudflared {
    $command = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($path in @(
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:ProgramFiles\cloudflared\cloudflared.exe"
    )) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

# Cloudflare Tunnel: started here, stopped when the app stops.
$tunnel = $null
$tunnelStatus = ""
$tunnelToken = Get-EnvSetting "EMA_TUNNEL_TOKEN"
$publicUrl = Get-EnvSetting "EMA_PUBLIC_URL"
$dataDir = Join-Path $root "data"
$pidFile = Join-Path $dataDir "cloudflared.pid"
$tunnelService = Get-Service -Name cloudflared -ErrorAction SilentlyContinue

if ($tunnelService -and $tunnelService.Status -eq "Running") {
    $tunnelStatus = "running as a Windows service"
} elseif ($tunnelToken) {
    $cloudflared = Find-Cloudflared
    if (-not $cloudflared) {
        $tunnelStatus = "NOT STARTED: cloudflared is not installed (winget install Cloudflare.cloudflared)"
    } else {
        Write-Host ">>> Starting the Cloudflare Tunnel..." -ForegroundColor Cyan
        # One left behind when this window was closed instead of Ctrl + C.
        if (Test-Path $pidFile) {
            $old = Get-Process -Id (Get-Content $pidFile) -ErrorAction SilentlyContinue
            if ($old -and $old.ProcessName -eq "cloudflared") { $old | Stop-Process -Force }
            Remove-Item $pidFile -ErrorAction SilentlyContinue
        }
        New-Item -ItemType Directory -Force $dataDir | Out-Null
        $log = Join-Path $dataDir "cloudflared.log"
        $metrics = "127.0.0.1:20242"
        # The token goes in through the environment, not the command line,
        # so it does not show in the list of running processes.
        $env:TUNNEL_TOKEN = $tunnelToken
        # HTTP/2 over TCP: the plant network drops QUIC (UDP).
        $tunnel = Start-Process -FilePath $cloudflared -PassThru -WindowStyle Hidden `
            -RedirectStandardError $log -RedirectStandardOutput "$log.out" `
            -ArgumentList "tunnel", "--no-autoupdate", "--protocol", "http2", "--metrics", $metrics, "run"
        Remove-Item Env:TUNNEL_TOKEN
        Set-Content $pidFile $tunnel.Id

        $tunnelStatus = "NOT CONNECTED yet: see data\cloudflared.log"
        foreach ($i in 1..20) {
            Start-Sleep -Seconds 1
            if ($tunnel.HasExited) { $tunnelStatus = "STOPPED: see data\cloudflared.log"; break }
            try {
                $ready = Invoke-RestMethod "http://$metrics/ready" -TimeoutSec 2
                if ($ready.readyConnections -gt 0) { $tunnelStatus = "connected"; break }
            } catch { }
        }
    }
}

Write-Host "`n===============================================" -ForegroundColor Green
Write-Host " EQUIPMENT MANAGER IS RUNNING" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host " This machine    : http://localhost:$port"
Write-Host " Other machines  : http://${ip}:$port"
if ($tunnelStatus) {
    $colour = if ($tunnelStatus -like "connected*" -or $tunnelStatus -like "running*") { "Green" } else { "Red" }
    $where = if ($publicUrl) { $publicUrl } else { "Cloudflare Tunnel" }
    Write-Host " Outside plant   : $where ($tunnelStatus)" -ForegroundColor $colour
}
Write-Host ""
Write-Host " Do NOT close this window while people are using the system." -ForegroundColor Yellow
Write-Host " To stop: press Ctrl + C" -ForegroundColor Yellow
Write-Host "===============================================`n" -ForegroundColor Green

$env:DJANGO_SETTINGS_MODULE = "config.settings"
try {
    # Invoked as a module, not the venv's waitress-serve.exe: that launcher has the
    # python.exe path from install time baked in, so it breaks if the project
    # folder is ever moved or copied (e.g. Desktop -> D:\...) after install.
    & $python -m waitress --listen=0.0.0.0:$port --threads=8 config.wsgi:application
} finally {
    if ($tunnel -and -not $tunnel.HasExited) {
        Write-Host ">>> Stopping the Cloudflare Tunnel..." -ForegroundColor Cyan
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
