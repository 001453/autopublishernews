# .env: tekillestir + eksik anahtarlar (OPENAI_API_KEY silinmez, ustte kalir).
# Kullanim: cd C:\autopublishernews ; .\scripts\ensure_env.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projRoot ".env"
$examplePath = Join-Path $projRoot ".env.example"

if (-not (Test-Path $envPath)) {
    if (Test-Path $examplePath) {
        Copy-Item $examplePath $envPath
        Write-Host "Olusturuldu: .env - OPENAI_API_KEY doldurun."
    }
    else {
        Write-Error ".env yok."
    }
}

$desired = [ordered]@{
    OPENAI_MODEL             = "gpt-4o-mini"
    OPENAI_COOLDOWN_SECONDS  = "300"
    RSS_PREVIEW_AI_MAX       = "1"
    AUTO_START_SCHEDULER     = "1"
    POLL_INTERVAL_MINUTES    = "30"
    PUBLISH_INTERVAL_MINUTES = "115"
    USE_EXISTING_CHROME      = "0"
    BOT_CDP_PORT             = "9333"
    HEADLESS                 = "0"
    BROWSER_CHANNEL          = "chrome"
}

$headerComments = [System.Collections.Generic.List[string]]@()
$map = @{}
$dupCount = 0
$rawLines = @(Get-Content $envPath -Encoding UTF8)

foreach ($line in $rawLines) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $k = $Matches[1]
        $v = $Matches[2].Trim()
        if ($map.ContainsKey($k)) {
            $dupCount++
            continue
        }
        $map[$k] = $v
    }
    elseif ($line -match '^\s*#' -or $line.Trim() -eq "") {
        if ($map.Count -eq 0) {
            $headerComments.Add($line)
        }
    }
}

if ($map.ContainsKey("POLL_INTERVAL_MINUTES") -and $map["POLL_INTERVAL_MINUTES"] -eq "15") {
    $map["POLL_INTERVAL_MINUTES"] = "30"
}

foreach ($k in $desired.Keys) {
    if (-not $map.ContainsKey($k)) {
        $map[$k] = $desired[$k]
        Write-Host "+ $k=$($desired[$k])"
    }
    elseif ($k -ne "OPENAI_API_KEY" -and $map[$k] -ne $desired[$k]) {
        $map[$k] = $desired[$k]
        Write-Host "~ $k=$($desired[$k])"
    }
}

if (-not $map.ContainsKey("OPENAI_API_KEY")) {
    Write-Host ""
    Write-Host "HATA: OPENAI_API_KEY .env icinde yok." -ForegroundColor Red
    Write-Host "  notepad $envPath"
    Write-Host "  En uste tek satir: OPENAI_API_KEY=sk-proj-..."
    Write-Host "Dosya degistirilmedi (anahtar silinmesin diye)."
    exit 1
}

$val = $map["OPENAI_API_KEY"]
if ($val.Length -lt 40) {
    Write-Warning "OPENAI_API_KEY cok kisa ($($val.Length) karakter) - kirik satir olabilir."
}
if ($val -match '\s') {
    Write-Warning "OPENAI_API_KEY bosluk iceriyor - tek satir olmali."
}

$out = [System.Collections.Generic.List[string]]@()
if ($headerComments.Count -gt 0) {
    foreach ($c in $headerComments) { $out.Add($c) }
    $out.Add("")
}

if ($map.ContainsKey("OPENAI_API_KEY")) {
    $out.Add("OPENAI_API_KEY=$($map['OPENAI_API_KEY'])")
}

$keyOrder = @(
    "OPENAI_MODEL", "OPENAI_COOLDOWN_SECONDS", "RSS_PREVIEW_AI_MAX",
    "AUTO_START_SCHEDULER", "POLL_INTERVAL_MINUTES", "PUBLISH_INTERVAL_MINUTES",
    "USE_EXISTING_CHROME", "BOT_CDP_PORT", "HEADLESS", "BROWSER_CHANNEL",
    "DISCORD_WEBHOOK_URL"
)
foreach ($k in $keyOrder) {
    if ($map.ContainsKey($k) -and $k -ne "OPENAI_API_KEY") {
        $out.Add("$k=$($map[$k])")
    }
}

$written = @{}
foreach ($k in $keyOrder) { $written[$k] = $true }
$written["OPENAI_API_KEY"] = $true
foreach ($k in $map.Keys) {
    if (-not $written.ContainsKey($k)) {
        $out.Add("$k=$($map[$k])")
    }
}

Set-Content -Path $envPath -Value $out -Encoding UTF8
if ($dupCount -gt 0) {
    Write-Host "Tekillestirildi: $dupCount yinelenen satir silindi."
}
Write-Host "Kaydedildi: $envPath"
Write-Host "Sonra: .\scripts\start_all_bot.ps1"
