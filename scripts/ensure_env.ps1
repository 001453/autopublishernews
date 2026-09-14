# .env: tekillestir + eksik anahtarlar (OPENAI_API_KEY silinmez, ustte kalir).
# Kullanim: cd C:\autopublishernews ; .\scripts\ensure_env.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projRoot ".env"
$examplePath = Join-Path $projRoot ".env.example"

function Read-EnvTextLines([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) {
        return @()
    }
    $text = $null
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $text = [System.Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $text = [System.Text.Encoding]::BigEndianUnicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    else {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    return $text -split "`r?`n"
}

function Normalize-EnvLine([string]$Line) {
    if ($null -eq $Line) { return "" }
    $line = $Line.TrimEnd("`r").TrimStart([char]0xFEFF)
    $line = $line -replace [char]0xFF1D, '='
    $line = $line -replace [char]0xFE61, '='
    $line = $line -replace [char]0x2019, "'"
    return $line
}

function Normalize-EnvValue([string]$Value) {
    if ($null -eq $Value) { $Value = "" }
    $v = $Value.Trim()
    if ($v.Length -ge 2) {
        $q0 = $v[0]
        $q1 = $v[$v.Length - 1]
        if (($q0 -eq '"' -and $q1 -eq '"') -or ($q0 -eq "'" -and $q1 -eq "'")) {
            $v = $v.Substring(1, $v.Length - 2)
        }
    }
    return $v.Trim()
}

function Set-EnvMapValue([hashtable]$Map, [string]$Key, [string]$Value) {
    if (-not $Map.ContainsKey($Key)) {
        $Map[$Key] = $Value
        return
    }
    if ($Key -eq "OPENAI_API_KEY" -and $Value.Length -gt $Map[$Key].Length) {
        $Map[$Key] = $Value
    }
}

function Parse-EnvMap([string[]]$Lines) {
    $map = @{}
    $pendingKey = $null
    foreach ($raw in $Lines) {
        $line = Normalize-EnvLine $raw
        if ($pendingKey) {
            $extra = $line.Trim()
            if ($extra -and -not ($extra -match '^\s*#') -and -not ($extra -match '^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=')) {
                $map[$pendingKey] = $map[$pendingKey] + $extra
                if ($map[$pendingKey].Length -ge 40) {
                    $pendingKey = $null
                }
                continue
            }
            $pendingKey = $null
        }
        if ($line -match '^\s*#\s*(?:export\s+)?(OPENAI_API_KEY)\s*=\s*(.+)$') {
            Set-EnvMapValue $map $Matches[1] (Normalize-EnvValue $Matches[2])
            continue
        }
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $k = $Matches[1].Trim([char]0xFEFF)
            $v = Normalize-EnvValue $Matches[2]
            Set-EnvMapValue $map $k $v
            if ($k -eq "OPENAI_API_KEY" -and $v.Length -lt 40) {
                $pendingKey = $k
            }
        }
    }
    return $map
}

function Resolve-OpenAiKey([hashtable]$Map) {
    foreach ($alt in @("OPENAI_KEY", "OPENAI_SECRET", "OPENAI_TOKEN")) {
        if ($Map.ContainsKey($alt) -and $Map[$alt]) {
            if (-not $Map.ContainsKey("OPENAI_API_KEY") -or -not $Map["OPENAI_API_KEY"]) {
                $Map["OPENAI_API_KEY"] = $Map[$alt]
            }
        }
    }
}

function Extract-OpenAiKeyFromFile([string]$Path) {
    if (-not (Test-Path $Path)) { return "" }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { return "" }
    $text = $null
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $text = [System.Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    else {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    $flat = ($text -replace "`r", " " -replace "`n", " ")
    if ($flat -match 'OPENAI_API_KEY\s*=\s*(sk-[^\s#"''`]+)') {
        return $Matches[1].Trim().Trim('"').Trim("'")
    }
    $m = [regex]::Match($flat, 'sk-proj-[A-Za-z0-9._-]{20,}')
    if ($m.Success) { return $m.Value }
    $m2 = [regex]::Match($flat, 'sk-[A-Za-z0-9._-]{20,}')
    if ($m2.Success) { return $m2.Value }
    return ""
}

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
    PUBLISH_INTERVAL_MINUTES = "120"
    USE_EXISTING_CHROME      = "0"
    BOT_CDP_PORT             = "9333"
    BOT_MAX_CHROME_TABS      = "2"
    HEADLESS                 = "0"
    BROWSER_CHANNEL          = "chrome"
}

$headerComments = [System.Collections.Generic.List[string]]@()
$map = @{}
$dupCount = 0
$rawLines = @(Read-EnvTextLines $envPath)

foreach ($lineRaw in $rawLines) {
    $line = Normalize-EnvLine $lineRaw
    if ($line -match '^\s*#\s*(?:export\s+)?(OPENAI_API_KEY)\s*=\s*(.+)$') {
        Set-EnvMapValue $map $Matches[1] (Normalize-EnvValue $Matches[2])
    }
    elseif ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $k = $Matches[1].Trim([char]0xFEFF)
        $v = Normalize-EnvValue $Matches[2]
        if ($map.ContainsKey($k)) {
            $dupCount++
            Set-EnvMapValue $map $k $v
        }
        else {
            $map[$k] = $v
        }
    }
    elseif ($line -match '^\s*#' -or $line.Trim() -eq "") {
        if ($map.Count -eq 0) {
            $headerComments.Add($lineRaw)
        }
    }
}

$parsed = Parse-EnvMap $rawLines
foreach ($k in $parsed.Keys) {
    if (-not $map.ContainsKey($k) -or ($k -eq "OPENAI_API_KEY" -and $parsed[$k].Length -gt $map[$k].Length)) {
        $map[$k] = $parsed[$k]
    }
}
Resolve-OpenAiKey $map

$fallbackKey = Extract-OpenAiKeyFromFile $envPath
if ($fallbackKey) {
    if (-not $map.ContainsKey("OPENAI_API_KEY") -or $fallbackKey.Length -gt $map["OPENAI_API_KEY"].Length) {
        $map["OPENAI_API_KEY"] = $fallbackKey
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

if (-not $map.ContainsKey("OPENAI_API_KEY") -or -not ($map["OPENAI_API_KEY"])) {
    Write-Host ""
    Write-Host "HATA: OPENAI_API_KEY .env icinde okunamadi." -ForegroundColor Red
    Write-Host "  Dosya: $envPath"
    Write-Host "  Bulunan anahtarlar: $(if ($map.Keys.Count) { ($map.Keys | Sort-Object) -join ', ' } else { '(hicbiri)' })"
    Write-Host ""
    Write-Host "  Muhtemel nedenler:"
    Write-Host "  - Notepad'de .env.example acik (gercek dosya .env olmali)"
    Write-Host "  - Satir basinda # var (yorum satiri sayilir)"
    Write-Host "  - Anahtar iki satira bolunmus veya bos OPENAI_API_KEY= satiri var"
    Write-Host ""
    Write-Host "  Cozum:"
    Write-Host "  .\scripts\set_openai_key.ps1"
    Write-Host "  veya notepad $envPath -> en uste tek satir:"
    Write-Host "  OPENAI_API_KEY=sk-proj-..."
    Write-Host "Dosya degistirilmedi (anahtar silinmesin diye)."
    exit 1
}

$val = $map["OPENAI_API_KEY"]
if ($val -notmatch '^sk-') {
    Write-Warning "OPENAI_API_KEY sk- ile baslamiyor - anahtar bozuk olabilir."
}
if ($val.Length -gt 220) {
    Write-Warning "OPENAI_API_KEY cok uzun ($($val.Length)) - .\scripts\set_openai_key.ps1 ile tekrar girin."
}
if ($val -match '\s') {
    Write-Warning "OPENAI_API_KEY bosluk iceriyor - tek satir olmali."
}

$out = [System.Collections.Generic.List[string]]@()
if ($headerComments.Count -gt 0) {
    foreach ($c in $headerComments) { $out.Add($c) }
    $out.Add("")
}

$out.Add("OPENAI_API_KEY=$($map['OPENAI_API_KEY'])")

$keyOrder = @(
    "OPENAI_MODEL", "OPENAI_COOLDOWN_SECONDS", "RSS_PREVIEW_AI_MAX",
    "AUTO_START_SCHEDULER", "POLL_INTERVAL_MINUTES", "PUBLISH_INTERVAL_MINUTES",
    "USE_EXISTING_CHROME", "BOT_CDP_PORT", "BOT_MAX_CHROME_TABS", "HEADLESS", "BROWSER_CHANNEL",
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

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($envPath, [string[]]$out, $utf8NoBom)
if ($dupCount -gt 0) {
    Write-Host "Tekillestirildi: $dupCount yinelenen satir birlestirildi."
}
Write-Host "Kaydedildi: $envPath"
Write-Host "Sonra: .\scripts\start_all_bot.ps1"
