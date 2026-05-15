# Bot X profili (x_profile) — tek Chrome, CDP port 9333.
# Kullanim:
#   .\scripts\start_bot_chrome.ps1
#   .\scripts\start_bot_chrome.ps1 -ForceRestart

param(
    [string]$Url = "https://x.com/login",
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$profile = Join-Path $projRoot "x_profile"
if (-not (Test-Path $profile)) { New-Item -ItemType Directory -Path $profile | Out-Null }

$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    Write-Error "Google Chrome bulunamadi."
    exit 1
}

$port = if ($env:BOT_CDP_PORT) { $env:BOT_CDP_PORT } else { "9333" }
$cdpBase = "http://127.0.0.1:${port}"
$profileNorm = $profile.Replace("\", "/")

function Test-Cdp {
    try {
        $r = Invoke-WebRequest -Uri "$cdpBase/json/version" -UseBasicParsing -TimeoutSec 4
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Open-CdpTab([string]$TargetUrl) {
    $enc = [uri]::EscapeDataString($TargetUrl)
    foreach ($method in @("Put", "Get")) {
        try {
            Invoke-WebRequest -Uri "$cdpBase/json/new?$enc" -Method $method -UseBasicParsing -TimeoutSec 12 | Out-Null
            return $true
        } catch { }
    }
    return $false
}

function Stop-BotProfileChrome {
    $procs = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$profile*" -or $_.CommandLine -like "*x_profile*") }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($procs) { Start-Sleep -Seconds 2 }
}

if (Test-Cdp) {
    Write-Host "Bot Chrome CDP aktif (port $port)."
    if (Open-CdpTab $Url) {
        Write-Host "Mevcut bot Chrome'da yeni sekme: $Url"
        exit 0
    }
}

$needsRestart = $ForceRestart
if (-not $needsRestart) {
    $stale = Get-CimInstance Win32_Process -Filter "name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$profile*" -or $_.CommandLine -like "*x_profile*") }
    if ($stale -and -not (Test-Cdp)) {
        $needsRestart = $true
    }
}

if ($needsRestart) {
    Write-Host "Eski bot Chrome kapatiliyor (CDP icin yeniden baslatilacak)..."
    Stop-BotProfileChrome
}

Write-Host "Bot Chrome aciliyor: profil=$profile port=$port"
Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$port",
    "--user-data-dir=`"$profile`"",
    "--disable-blink-features=AutomationControlled",
    $Url
)

for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Cdp) {
        Write-Host "Hazir. CDP port $port - panel yeni sekme acar."
        Write-Host "Panel: http://127.0.0.1:8765"
        exit 0
    }
}
Write-Host "Chrome acildi; CDP henuz hazir degil. 5 sn sonra panelden tekrar deneyin."
exit 0
