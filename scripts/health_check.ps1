# Panel (8765) ve Bot Chrome CDP (9333) saglik kontrolu.
# Port acik ama HTTP/CDP olu ise process oldurup yeniden baslatir.
# Gorev Zamanlayicisi: .\scripts\install_health_task.ps1

$ErrorActionPreference = "Continue"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

$logDir = Join-Path $projRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "health.log"

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

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

function Test-PanelHttpHealthy {
    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 8
        $sw.Stop()
        if ($r.StatusCode -ne 200) { return $false }
        if ($sw.ElapsedMilliseconds -gt 7000) { return $false }
        $j = $r.Content | ConvertFrom-Json
        if ($null -eq $j.ok) { return $true }
        return [bool]$j.ok
    } catch {
        return $false
    }
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

function Stop-DashboardProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like '*dashboard.py*') } |
        ForEach-Object {
            Write-Log "Olu panel process olduruluyor: PID=$($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            if ($_ -and $_ -gt 0) {
                Write-Log "8765 port process olduruluyor: PID=$_"
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            }
        }
    Start-Sleep -Seconds 2
}

function Ensure-SchedulerRunning {
    try {
        $st = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/status" -TimeoutSec 8
        if (-not $st.scheduler_running) {
            Write-Log "Zamanlayici kapali -> /api/start"
            Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8765/api/start" -TimeoutSec 8 | Out-Null
        }
    } catch {}
}

$panelPort = Test-PortOpen 8765
$panelHttp = if ($panelPort) { Test-PanelHttpHealthy } else { $false }
$cdpPortOpen = Test-PortOpen 9333
$cdpHealthy = if ($cdpPortOpen) { Test-CdpHealthy } else { $false }

# Port acik ama HTTP olu (10048 / SYN_SENT tipi hayalet)
if ($panelPort -and -not $panelHttp) {
    Write-Log "8765 port acik ama /api/health yanit vermiyor -> panel yeniden"
    Stop-DashboardProcesses
    & "$PSScriptRoot\start_all_bot.ps1" | Out-Null
    Start-Sleep -Seconds 3
    $panelHttp = Test-PanelHttpHealthy
    $cdpHealthy = Test-CdpHealthy
}

if (-not $panelHttp) {
    Write-Log "8765 HTTP kapali -> start_all_bot.ps1"
    & "$PSScriptRoot\start_all_bot.ps1" | Out-Null
    Start-Sleep -Seconds 3
    $panelHttp = Test-PanelHttpHealthy
    $cdpHealthy = Test-CdpHealthy
}

if (-not $cdpHealthy) {
    $reason = if (-not (Test-PortOpen 9333)) { "9333 kapali" } else { "9333 acik ama CDP yanit vermiyor (donmus?)" }
    Write-Log "$reason -> start_bot_chrome.ps1 -ForceRestart"
    & "$PSScriptRoot\start_bot_chrome.ps1" -ForceRestart *>> $logFile
    Start-Sleep -Seconds 2
    $cdpHealthy = Test-CdpHealthy
}

if ($panelHttp) {
    Ensure-SchedulerRunning
    $py = Join-Path $projRoot ".venv\Scripts\python.exe"
    if (Test-Path $py) {
        try {
            $closed = & $py -c "from engine import prune_bot_cdp_tabs; print(prune_bot_cdp_tabs())" 2>$null
            if ($closed -match '^\d+$' -and [int]$closed -gt 0) {
                Write-Log "Chrome: $closed fazla sekme kapatildi."
            }
        } catch {}
    }
}

if ($panelHttp -and $cdpHealthy) {
    exit 0
}

Write-Log "Health bitis: panelHttp=$panelHttp cdpHealthy=$cdpHealthy"
exit 1
