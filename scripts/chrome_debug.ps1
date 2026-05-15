# Mevcut Chrome + CDP: bot yalnizca YENI SEKME acar (ayri profil penceresi acmaz).
# CDP yoksa: Chrome'u bir kez kapatip bu betigi calistirin (normal profiliniz + port 9222).

$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    Write-Error "Google Chrome bulunamadi."
    exit 1
}

$url = if ($args.Count -gt 0) { $args[0] } else { "https://x.com/login" }
$port = if ($env:CHROME_DEBUG_PORT) { $env:CHROME_DEBUG_PORT } else { "9222" }
$cdpBase = "http://127.0.0.1:${port}"
$cdpOk = $false
try {
    $r = Invoke-WebRequest -Uri "$cdpBase/json/version" -UseBasicParsing -TimeoutSec 4
    $cdpOk = $r.StatusCode -eq 200
} catch { }

function Open-TabInExistingCdpChrome {
    param([string]$TargetUrl)
    $enc = [uri]::EscapeDataString($TargetUrl)
    foreach ($method in @("Put", "Get")) {
        try {
            Invoke-WebRequest -Uri "$cdpBase/json/new?$enc" -Method $method -UseBasicParsing -TimeoutSec 12 | Out-Null
            return $true
        } catch { }
    }
    return $false
}

$chromeRunning = $null -ne (Get-Process chrome -ErrorAction SilentlyContinue | Select-Object -First 1)
$userData = "${env:LOCALAPPDATA}\Google\Chrome\User Data"

if ($cdpOk) {
    Write-Host "CDP aktif (port $port) - mevcut Chrome oturumunda yeni sekme aciliyor."
    if (Open-TabInExistingCdpChrome -TargetUrl $url) {
        Write-Host "Sekme acildi: $url"
        Write-Host "Bot isler bitince sekmeleri kapatir; ayri Chrome penceresi acmaz."
        exit 0
    }
    Write-Host "CDP sekme acilamadi; chrome.exe ile deneniyor..."
    Start-Process -FilePath $chrome -ArgumentList $url
    exit 0
}

if ($chromeRunning) {
    Write-Host ""
    Write-Host "Chrome acik ama CDP (debug portu) KAPALI."
    Write-Host "Bot mevcut pencerede otomasyon icin CDP gerekir."
    Write-Host ""
    Write-Host "Bir kez yapin:"
    Write-Host "  1) Tum Chrome pencerelerini kapatin (Gorev Yoneticisinde chrome.exe kalmasin)"
    Write-Host "  2) Bu betigi tekrar calistirin"
    Write-Host "     -> Ayni profiliniz (User Data) + --remote-debugging-port=$port ile acilir"
    Write-Host "  3) X giris yapin; sonra panelden devam edin"
    Write-Host ""
    Write-Host "Simdilik sadece yeni sekme (CDP olmadan): $url"
    Start-Process -FilePath $chrome -ArgumentList $url
    exit 1
}

Write-Host "Chrome kapali; normal profilinizle debug modunda aciliyor (port $port)..."
Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$port",
    "--user-data-dir=`"$userData`"",
    $url
)
Write-Host "Hazir. Panel: http://127.0.0.1:8765"
Write-Host "Sonraki calistirmalarda Chrome acikken bot yalnizca yeni sekme acar."
