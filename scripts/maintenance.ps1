# Gunluk bakim: Bot Chrome ForceRestart + panel HTTP kontrolu.
# Gorev: .\scripts\install_maintenance_task.ps1

$ErrorActionPreference = "Continue"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

$logDir = Join-Path $projRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "maintenance.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "Gunluk bakim basladi."

# Chrome'u temiz ForceRestart (donma birikimini kirar)
try {
    & "$PSScriptRoot\start_bot_chrome.ps1" -ForceRestart *>> $logFile
    Write-Log "Bot Chrome ForceRestart tamam."
} catch {
    Write-Log "HATA Chrome ForceRestart: $_"
}

Start-Sleep -Seconds 3

# Panel HTTP sagliksizsa tum stack yeniden
$panelOk = $false
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 8
    $panelOk = ($r.StatusCode -eq 200)
} catch {
    $panelOk = $false
}

if (-not $panelOk) {
    Write-Log "Panel HTTP yok -> start_all_bot.ps1 -ForceRestart"
    & "$PSScriptRoot\start_all_bot.ps1" -ForceRestart *>> $logFile
} else {
    Write-Log "Panel HTTP OK."
    try {
        $st = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/status" -TimeoutSec 8
        if (-not $st.scheduler_running) {
            Write-Log "Zamanlayici kapali -> /api/start"
            Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8765/api/start" -TimeoutSec 8 | Out-Null
        }
    } catch {}
}

# Fazla X sekmelerini budamak
$py = Join-Path $projRoot ".venv\Scripts\python.exe"
if (Test-Path $py) {
    try {
        $closed = & $py -c "from engine import prune_bot_cdp_tabs; print(prune_bot_cdp_tabs())" 2>$null
        if ($closed -match '^\d+$' -and [int]$closed -gt 0) {
            Write-Log "Chrome: $closed fazla sekme kapatildi."
        }
    } catch {}
}

Write-Log "Gunluk bakim bitti. Log: $logFile"
