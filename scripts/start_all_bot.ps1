# Oturum acilisinda veya Gorev Zamanlayicisi: Bot Chrome + panel
# Kullanim: .\scripts\start_all_bot.ps1

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
Start-Sleep -Seconds 8

# Panel zaten aciksa atla
$panelUp = $false
try {
    $panelUp = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8765 -WarningAction SilentlyContinue).TcpTestSucceeded
} catch {}
if ($panelUp) {
    Write-Log "Panel zaten calisiyor (8765)."
} else {
    $py = Join-Path $projRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Log "HATA: venv yok: $py"
        exit 1
    }
    $panelLog = Join-Path $logDir "dashboard.log"
    Start-Process -FilePath $py -ArgumentList "dashboard.py" -WorkingDirectory $projRoot `
        -WindowStyle Minimized -RedirectStandardOutput $panelLog -RedirectStandardError $panelLog
    Write-Log "Panel baslatildi -> http://127.0.0.1:8765"
}

# Bot Chrome (CDP 9333)
$cdpUp = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:9333/json/version" -UseBasicParsing -TimeoutSec 4
    $cdpUp = $r.StatusCode -eq 200
} catch {}

if ($cdpUp) {
    Write-Log "Bot Chrome CDP zaten aktif (9333)."
} else {
    try {
        & "$PSScriptRoot\start_bot_chrome.ps1" *>> $logFile
        Write-Log "start_bot_chrome.ps1 calistirildi."
    } catch {
        Write-Log "HATA start_bot_chrome: $_"
    }
}

Write-Log "Otomatik baslatma bitti. Log: $logFile"
