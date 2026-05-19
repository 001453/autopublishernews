# Panel (8765) ve Bot Chrome CDP (9333) kontrolu; kapaliysa yeniden baslatir.
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

$panelUp = Test-PortOpen 8765
$cdpUp = Test-PortOpen 9333

if ($panelUp -and $cdpUp) {
    exit 0
}

if (-not $panelUp) {
    Write-Log "8765 kapali -> start_all_bot.ps1"
    & "$PSScriptRoot\start_all_bot.ps1" | Out-Null
    exit 0
}

if (-not $cdpUp) {
    Write-Log "9333 kapali -> start_bot_chrome.ps1"
    & "$PSScriptRoot\start_bot_chrome.ps1" *>> $logFile
    exit 0
}
