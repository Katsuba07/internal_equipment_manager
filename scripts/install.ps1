<#
    FIRST-TIME SETUP — Equipment Management Application

    Run once on the machine that will act as the server.
    Right-click this file > Run with PowerShell
    (or, from the project folder: .\scripts\install.ps1)
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step($text) { Write-Host "`n>>> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    [OK] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "    [!]  $text" -ForegroundColor Yellow }

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host " EQUIPMENT MANAGER - SETUP" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan

# --- 1. Python ---
Write-Step "Checking Python"
try {
    $pythonVersion = & python --version 2>&1
} catch {
    Write-Host @"

    PYTHON NOT FOUND.

    Install Python 3.12 or newer from https://www.python.org/downloads/
    During setup, TICK "Add python.exe to PATH" on the first screen.
    Then close this window and run this script again.

"@ -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
Write-Ok $pythonVersion

# --- 2. Virtual environment ---
Write-Step "Preparing the project's Python environment"
if (Test-Path ".venv") {
    Write-Ok ".venv already exists"
} else {
    & python -m venv .venv
    Write-Ok "Created .venv"
}
$python = Join-Path $root ".venv\Scripts\python.exe"

# --- 3. Dependencies ---
Write-Step "Installing dependencies (this can take a few minutes)"
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r requirements.txt --quiet
Write-Ok "Dependencies installed"

# --- 4. Configuration ---
Write-Step "Creating the configuration file"
if (Test-Path ".env") {
    Write-Ok ".env already exists - keeping current settings"
} else {
    $secretKey = & $python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
    @"
EMA_SECRET_KEY=$secretKey
EMA_DEBUG=False
EMA_ALLOWED_HOSTS=*
EMA_TIME_ZONE=Asia/Ho_Chi_Minh
EMA_MAX_UPLOAD_MB=20
"@ | Set-Content -Path ".env" -Encoding UTF8
    Write-Ok "Created .env with a unique secret key"
}

# --- 5. Database ---
Write-Step "Setting up the database"
& $python manage.py migrate --noinput
Write-Ok "Database ready"

# --- 6. Static files ---
Write-Step "Preparing interface files"
& $python manage.py collectstatic --noinput --clear | Out-Null
Write-Ok "Interface files ready"

# --- 7. Administrator account ---
Write-Step "Administrator account"
$userCount = & $python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup();from core.models import User;print(User.objects.count())"
if ([int]$userCount -gt 0) {
    Write-Ok "$userCount account(s) already exist - skipping"
} else {
    Write-Host @"
    Create the first administrator account now.
    Note: while typing the password, NOTHING appears on screen. That is normal.
"@ -ForegroundColor Yellow
    & $python manage.py createsuperuser
    Write-Host @"

    That account is a superuser. Sign in, open Admin site > Users,
    edit this account and set Role = 'Administrator'.
"@ -ForegroundColor Yellow
}

# --- 8. Firewall ---
Write-Step "Opening port 8000 for the local network"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    $ruleName = "Equipment Manager (EMA) - port 8000"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
            -LocalPort 8000 -Action Allow -Profile Private,Domain | Out-Null
        Write-Ok "Port 8000 opened for private and domain networks"
    } else {
        Write-Ok "Port 8000 was already open"
    }
} else {
    Write-Warn "Firewall rule not added - run this script as Administrator to add it."
    Write-Warn "Until then, other machines cannot reach the server."
}

# --- Done ---
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
       Select-Object -First 1).IPAddress

Write-Host "`n===============================================" -ForegroundColor Green
Write-Host " SETUP COMPLETE" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host @"

 Next step - start the system:
     .\scripts\run-server.ps1

 Once running:
   - On this machine       : http://localhost:8000
   - From other machines   : http://${ip}:8000

 To start it automatically at boot, see "Run as a Windows service"
 in OPERATIONS-GUIDE.md.

"@ -ForegroundColor White

Read-Host "Press Enter to close"
