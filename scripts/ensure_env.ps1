# .env: OpenAI 429 icin onerilen anahtarlar (API key degistirilmez).
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

$toSet = @{
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

$lines = @(Get-Content $envPath -Encoding UTF8)
$keys = @{}
$changed = $false

for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $k = $Matches[1]
        $keys[$k] = $true
        if ($k -eq "POLL_INTERVAL_MINUTES" -and $Matches[2].Trim() -eq "15") {
            $lines[$i] = "POLL_INTERVAL_MINUTES=30"
            Write-Host "~ POLL_INTERVAL_MINUTES 15 -> 30"
            $changed = $true
        }
        elseif ($toSet.ContainsKey($k) -and $k -ne "POLL_INTERVAL_MINUTES") {
            $newVal = $toSet[$k]
            if ($Matches[2].Trim() -ne $newVal) {
                $lines[$i] = "$k=$newVal"
                Write-Host "~ $k=$newVal"
                $changed = $true
            }
        }
    }
}

foreach ($k in $toSet.Keys) {
    if (-not $keys.ContainsKey($k)) {
        $lines += "$k=$($toSet[$k])"
        Write-Host "+ $k=$($toSet[$k])"
        $changed = $true
    }
}

$keyLine = $lines | Where-Object { $_ -match '^\s*OPENAI_API_KEY\s*=' } | Select-Object -First 1
if (-not $keyLine) {
    Write-Warning "OPENAI_API_KEY yok - tek satir sk-... ekleyin."
}
else {
    $val = ($keyLine -replace '^\s*OPENAI_API_KEY\s*=\s*', '').Trim()
    if ($val.Length -lt 40) {
        Write-Warning "OPENAI_API_KEY cok kisa - kirik satir olabilir."
    }
    if ($val -match '\s') {
        Write-Warning "OPENAI_API_KEY bosluk iceriyor - tek satir olmali."
    }
}

if ($changed) {
    Set-Content -Path $envPath -Value $lines -Encoding UTF8
    Write-Host "Kaydedildi: $envPath"
}
else {
    Write-Host ".env zaten uygun."
}

Write-Host "Sonra: .\scripts\start_all_bot.ps1"
