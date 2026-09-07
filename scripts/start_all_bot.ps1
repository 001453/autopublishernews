# Oturum acilisinda veya Gorev Zamanlayicisi: Bot Chrome + panel
# Kullanim: .\scripts\start_all_bot.ps1
#           .\scripts\start_all_bot.ps1 -ForceRestart

param(
    [switch]$ForceRestart
)

$ErrorActionPreference = "Continue"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

$logDir = Join-Path $projRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "autostart.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "Otomatik baslatma basladi."
Start-Sleep -Seconds 2

function Test-PortOpen([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(2000, $false)
        if ($ok -and $c.Connected) { $c.Close(); return $true }
        $c.Close()
    } catch {}
    return $false
}

function Test-CdpHealthy {
    param([string]$BaseUrl = "http://127.0.0.1:9333")
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $r = Invoke-WebRequest -Uri "$BaseUrl/json/version" -UseBasicParsing -TimeoutSec 10
        $sw.Stop()
        if ($r.StatusCode -ne 200) { return $false }
        if ($sw.ElapsedMilliseconds -gt 8000) { return $false }
        return $true
    } catch {
        return $false
    }
}

if ($ForceRestart) {
    Write-Log "ForceRestart: 8765 ve 9333 kapatiliyor."
    Get-NetTCPConnection -LocalPort 8765, 9333 -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

# Panel zaten aciksa atla (ForceRestart sonrasi kapali olmali)
$panelUp = Test-PortOpen 8765
if ($panelUp) {
    Write-Log "Panel zaten calisiyor (8765)."
} else {
    $py = Join-Path $projRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Log "HATA: venv yok: $py"
        exit 1
    }
    $panelOut = Join-Path $logDir "dashboard.log"
    $panelErr = Join-Path $logDir "dashboard.err.log"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    Start-Process -FilePath $py -ArgumentList "dashboard.py" -WorkingDirectory $projRoot `
        -WindowStyle Minimized -RedirectStandardOutput $panelOut -RedirectStandardError $panelErr
    $panelReady = $false
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 2
        if (Test-PortOpen 8765) {
            $panelReady = $true
            break
        }
    }
    if ($panelReady) {
        Write-Log "Panel baslatildi -> http://127.0.0.1:8765"
    } else {
        Write-Log "HATA: Panel 8765 acilmadi. logs\dashboard.log ve dashboard.err.log kontrol edin."
    }
}

# Bot Chrome (CDP 9333) - port acik ama donmus CDP icin de kontrol
$cdpPortOpen = Test-PortOpen 9333
$cdpHealthy = if ($cdpPortOpen) { Test-CdpHealthy } else { $false }

if ($cdpHealthy -and -not $ForceRestart) {
    Write-Log "Bot Chrome CDP saglikli (9333)."
} elseif ($cdpPortOpen -or $ForceRestart) {
    if ($ForceRestart) {
        Write-Log "ForceRestart: Bot Chrome yeniden baslatiliyor."
    } else {
        Write-Log "9333 acik ama CDP yanit vermiyor (donmus?) -> ForceRestart"
    }
    try {
        & "$PSScriptRoot\start_bot_chrome.ps1" -ForceRestart *>> $logFile
        Write-Log "start_bot_chrome.ps1 -ForceRestart calistirildi."
    } catch {
        Write-Log "HATA start_bot_chrome: $_"
    }
} else {
    try {
        & "$PSScriptRoot\start_bot_chrome.ps1" *>> $logFile
        Write-Log "start_bot_chrome.ps1 calistirildi."
    } catch {
        Write-Log "HATA start_bot_chrome: $_"
    }
}

Write-Log "Otomatik baslatma bitti. Log: $logFile"
