<#
    REACH THE APP FROM OUTSIDE THE PLANT (Cloudflare Tunnel)

    Usage (once, on the server PC, in PowerShell opened "as Administrator"):
        .\scripts\install-tunnel.ps1 -Token <token copied from Cloudflare>

    cloudflared connects OUT to Cloudflare, so nothing has to be opened on the
    plant's firewall. Cloudflare then serves the app at https://ema.<your domain>.
    It is installed as a Windows service: it starts with the PC.

    Before running it, in the Cloudflare dashboard:
      Zero Trust > Networks > Tunnels > Create a tunnel (Cloudflared), name it,
      and copy the token from the install command it shows.
    After running it:
      the tunnel's Public Hostname: ema.<your domain>  ->  HTTP  localhost:8000,
      then set EMA_PUBLIC_URL=https://ema.<your domain> in .env and run update.ps1.
    Step-by-step instructions are in README.md, "Reaching the app from outside the plant".

    To remove it again:  cloudflared service uninstall
#>

param(
    # The tunnel token from the Cloudflare dashboard (a long string starting with "ey").
    [Parameter(Mandatory = $true)]
    [string]$Token
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "Run this in PowerShell opened as Administrator (right-click > Run as administrator)." -ForegroundColor Red
    exit 1
}

# Find cloudflared, or install it.
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

$cloudflared = Find-Cloudflared
if (-not $cloudflared) {
    Write-Host "Installing cloudflared..." -ForegroundColor Cyan
    winget install --id Cloudflare.cloudflared --exact --silent --accept-source-agreements --accept-package-agreements
    $cloudflared = Find-Cloudflared
    if (-not $cloudflared) {
        Write-Host "cloudflared could not be installed. Download it from" -ForegroundColor Red
        Write-Host "https://github.com/cloudflare/cloudflared/releases (cloudflared-windows-amd64.msi), install it, and run this again." -ForegroundColor Red
        exit 1
    }
}
Write-Host "cloudflared: $cloudflared"

# A service installed before (another token) is replaced.
if (Get-Service -Name cloudflared -ErrorAction SilentlyContinue) {
    Write-Host "Replacing the tunnel service installed before..." -ForegroundColor Yellow
    & $cloudflared service uninstall | Out-Null
    Start-Sleep -Seconds 2
}

& $cloudflared service install $Token

# The plant network drops QUIC (UDP), which leaves the tunnel with no
# connection: use HTTP/2 over TCP instead.
Stop-Service -Name cloudflared -Force -ErrorAction SilentlyContinue
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared" `
    -Name Environment -Type MultiString -Value @("TUNNEL_TRANSPORT_PROTOCOL=http2")
Start-Service -Name cloudflared
Start-Sleep -Seconds 5

$service = Get-Service -Name cloudflared -ErrorAction SilentlyContinue
if ($service -and $service.Status -eq "Running") {
    Set-Service -Name cloudflared -StartupType Automatic
    Write-Host ""
    Write-Host "The tunnel is running and starts with the PC." -ForegroundColor Green
    Write-Host "In Cloudflare, the tunnel should now show as HEALTHY. Next:"
    Write-Host "  1. Public Hostname: ema.<your domain>  ->  HTTP  localhost:8000"
    Write-Host "  2. In .env: EMA_PUBLIC_URL=https://ema.<your domain>, then .\scripts\update.ps1"
} else {
    Write-Host "The service did not start. Check the token, and that the PC can reach the internet on port 443." -ForegroundColor Red
    exit 1
}
