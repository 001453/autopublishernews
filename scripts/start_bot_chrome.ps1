# Bot X profili — tek Chrome penceresi + CDP (varsayilan port 9333).
# Kullanim: .\scripts\start_bot_chrome.ps1
#           .\scripts\start_bot_chrome.ps1 -ForceRestart
#           .\scripts\start_bot_chrome.ps1 -Url "https://x.com/login"

param(
    [string]$Url = "https://x.com/login",
    [switch]$ForceRestart
)

$ErrorActionPreference = "Continue"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

$port = if ($env:BOT_CDP_PORT) { $env:BOT_CDP_PORT.Trim() } else { "9333" }
$cdpBase = "http://127.0.0.1:$port"

$profile = $env:X_PROFILE_DIR
if (-not $profile) {
    $profile = Join-Path $projRoot "x_profile"
}
$profile = $profile.Trim()
if (-not (Test-Path $profile)) {
    New-Item -ItemType Directory -Path $profile -Force | Out-Null
}

$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    Write-Error "Google Chrome bulunamadi."
    exit 1
}

function Test-CdpReady {
    try {
        $r = Invoke-WebRequest -Uri "$cdpBase/json/version" -UseBasicParsing -TimeoutSec 6
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
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
    $profileKey = $profile.TrimEnd('\')
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $cmd = $_.CommandLine
            $cmd -and ($cmd -like "*$profileKey*") -and ($cmd -like "*remote-debugging-port=$port*")
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

$stale = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $cmd = $_.CommandLine
        $cmd -and ($cmd -like "*$($profile.TrimEnd('\'))*") -and ($cmd -like "*remote-debugging-port=$port*")
    } |
    Select-Object -First 1

# -ForceRestart: port acik olsa bile donmus Chrome'u kapat (Playwright timeout dongusunu kirar).
if ($ForceRestart -and ((Test-CdpReady) -or $stale)) {
    Write-Host "Bot Chrome yeniden baslatiliyor (-ForceRestart)..."
    Stop-BotProfileChrome
} elseif (Test-CdpReady) {
    Write-Host "Bot Chrome CDP aktif (port $port)."
    if ($Url -and $Url -ne "https://x.com/login") {
        if (Open-CdpTab -TargetUrl $Url) {
            Write-Host "Yeni sekme: $Url"
        }
    } else {
        Write-Host "Mevcut sekmeler korunuyor (gereksiz login sekmesi acilmadi)."
    }
    exit 0
} elseif ($stale) {
    Write-Host "x_profile Chrome acik ama CDP kapali. Tekrar: .\scripts\start_bot_chrome.ps1 -ForceRestart"
    exit 1
}

Write-Host "Bot Chrome aciliyor: profil=$profile port=$port"
Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$port",
    "--user-data-dir=`"$profile`"",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    $Url
) | Out-Null

foreach ($i in 1..30) {
    Start-Sleep -Seconds 1
    if (Test-CdpReady) {
        Write-Host "Hazir. CDP port $port"
        exit 0
    }
}
Write-Host "Chrome basladi; CDP gecikebilir. Panelden tekrar deneyin."
exit 0
