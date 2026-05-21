# Panel (8765) ve Bot Chrome CDP (9333) kontrolu; kapali veya donmus CDP ise yeniden baslatir.
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

$panelUp = Test-PortOpen 8765
$cdpPortOpen = Test-PortOpen 9333
$cdpHealthy = if ($cdpPortOpen) { Test-CdpHealthy } else { $false }

if ($panelUp -and $cdpHealthy) {
    exit 0
}

if (-not $panelUp) {
    Write-Log "8765 kapali -> start_all_bot.ps1"
    & "$PSScriptRoot\start_all_bot.ps1" | Out-Null
    exit 0
}

if (-not $cdpPortOpen -or -not $cdpHealthy) {
    $reason = if (-not $cdpPortOpen) { "9333 kapali" } else { "9333 acik ama CDP yanit vermiyor (donmus?)" }
    Write-Log "$reason -> start_bot_chrome.ps1 -ForceRestart"
    & "$PSScriptRoot\start_bot_chrome.ps1" -ForceRestart *>> $logFile
    exit 0
}
