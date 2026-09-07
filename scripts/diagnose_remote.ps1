# Uzak masaustu / VPS teshis - tum ciktiyi logs\vps_diagnose.txt dosyasina yazar
# Kullanim (RDP icinde): cd C:\autopublishernews ; .\scripts\diagnose_remote.ps1
# Sonra logs\vps_diagnose.txt icerigini kopyalayip paylasin.
# Not: em-dash kullanma. Windows PowerShell 5.1 UTF-8 dosyayi yanlis okuyup tirnak kirar.

$ErrorActionPreference = "Continue"
$projRoot = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $projRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$outFile = Join-Path $logDir "vps_diagnose.txt"

function Out-Diag([string]$msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $outFile -Value $line -Encoding UTF8
    Write-Host $line
}

if (Test-Path $outFile) { Remove-Item $outFile -Force }

Out-Diag "=== autopublishernews VPS teshis ==="
Out-Diag "Hostname: $env:COMPUTERNAME"
Out-Diag "Kullanici: $env:USERNAME"
Out-Diag "Proje klasoru: $projRoot"

# Disk
Out-Diag ""
Out-Diag "=== DISK ==="
Get-PSDrive -PSProvider FileSystem | ForEach-Object {
    Out-Diag ("{0}: kullanilan {1} GB, bos {2} GB" -f $_.Name, [math]::Round($_.Used/1GB,2), [math]::Round($_.Free/1GB,2))
}

# Proje konumlari
Out-Diag ""
Out-Diag "=== PROJE KONUMLARI ==="
@("C:\autopublishernews", "D:\autopublishernews", $projRoot) | ForEach-Object {
    Out-Diag ("{0} : {1}" -f $_, (Test-Path $_))
}

# Portlar
Out-Diag ""
Out-Diag "=== PORTLAR (8765 panel, 9333 Chrome CDP) ==="
foreach ($port in @(8765, 9333)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        $started = ""
        if ($proc) { $started = $proc.StartTime }
        Out-Diag ("Port {0}: ACIK - PID {1} ({2}) baslangic={3}" -f $port, $conn.OwningProcess, $proc.ProcessName, $started)
    } else {
        Out-Diag ("Port {0}: KAPALI" -f $port)
    }
}

# CDP saglik
Out-Diag ""
Out-Diag "=== CDP SAGLIK ==="
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:9333/json/version" -UseBasicParsing -TimeoutSec 8
    Out-Diag ("CDP yanit: HTTP {0}" -f $r.StatusCode)
} catch {
    Out-Diag ("CDP hata: {0}" -f $_.Exception.Message)
}

# Panel HTTP
Out-Diag ""
Out-Diag "=== PANEL HTTP ==="
try {
    $pr = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/status" -UseBasicParsing -TimeoutSec 8
    Out-Diag ("Panel /api/status: HTTP {0} boy={1}" -f $pr.StatusCode, $pr.RawContentLength)
    $body = $pr.Content
    if ($body.Length -gt 800) { $body = $body.Substring(0, 800) }
    Out-Diag ("Panel status: {0}" -f $body)
} catch {
    Out-Diag ("Panel HTTP hata: {0}" -f $_.Exception.Message)
}

# venv / python
Out-Diag ""
Out-Diag "=== PYTHON ==="
$py = Join-Path $projRoot ".venv\Scripts\python.exe"
Out-Diag ("venv: {0}" -f (Test-Path $py))
if (Test-Path $py) {
    try { Out-Diag (& $py --version 2>&1) } catch { Out-Diag "python --version hata" }
}
try { Out-Diag ("sistem python: $(python --version 2>&1)") } catch { Out-Diag "sistem python yok" }

# Chrome
Out-Diag ""
Out-Diag "=== CHROME ==="
$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }
Out-Diag ("Chrome: {0}" -f (Test-Path $chrome))

# Veri dosyalari
Out-Diag ""
Out-Diag "=== VERI ==="
foreach ($rel in @("posted.sqlite3", "panel_config.json", ".env")) {
    $fp = Join-Path $projRoot $rel
    if (Test-Path $fp) {
        $it = Get-Item $fp
        Out-Diag ("{0}: {1} byte, yazim={2}" -f $rel, $it.Length, $it.LastWriteTime)
    } else {
        Out-Diag ("{0}: YOK" -f $rel)
    }
}

# .env (gizli anahtarlar maskelenir)
Out-Diag ""
Out-Diag "=== .env ==="
$envPath = Join-Path $projRoot ".env"
if (Test-Path $envPath) {
    Out-Diag (".env var, boyut: $((Get-Item $envPath).Length) byte")
    Get-Content $envPath -ErrorAction SilentlyContinue | ForEach-Object {
        $line = $_
        if ($line -match 'sk-[A-Za-z0-9._-]{8,}') { $line = $line -replace 'sk-[A-Za-z0-9._-]{8,}', 'sk-****' }
        if ($line -match 'OPENAI|BOT_CDP|X_PROFILE|DATA_DIR|AUTO_START|PANEL_HOST|USE_EXISTING') {
            Out-Diag "  $line"
        }
    }
} else {
    Out-Diag ".env YOK!"
}

# Gorev zamanlayici
Out-Diag ""
Out-Diag "=== GOREV ZAMANLAYICISI ==="
foreach ($tn in @("XNewsBot", "XNewsBotHealth")) {
    $t = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
    if ($t) {
        $info = Get-ScheduledTaskInfo $t
        Out-Diag ("{0}: durum={1}, son calisma={2}, sonuc={3}" -f $tn, $t.State, $info.LastRunTime, $info.LastTaskResult)
    } else {
        Out-Diag ("{0}: KURULU DEGIL" -f $tn)
    }
}

# Loglar
Out-Diag ""
Out-Diag "=== SON LOGLAR ==="
foreach ($lf in @("autostart.log", "health.log", "dashboard.log", "dashboard.err.log")) {
    $fp = Join-Path $logDir $lf
    Out-Diag "--- $lf ---"
    if (Test-Path $fp) {
        Get-Content $fp -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Out-Diag "  $_" }
    } else {
        Out-Diag "  (dosya yok)"
    }
}

Out-Diag ""
Out-Diag "=== BITTI ==="
Out-Diag "Dosya: $outFile"
Write-Host ""
Write-Host "Tamam. Bu dosyayi kopyalayip paylasin: $outFile" -ForegroundColor Cyan
