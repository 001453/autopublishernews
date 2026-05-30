# OPENAI_API_KEY guvenli ekleme / guncelleme
# Kullanim: cd C:\autopublishernews ; .\scripts\set_openai_key.ps1
#           cd C:\autopublishernews ; .\scripts\set_openai_key.ps1 -Key "sk-proj-..."
#           cd C:\autopublishernews ; .\scripts\set_openai_key.ps1 -FromClipboard

param(
    [string]$Key,
    [switch]$FromClipboard
)

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projRoot ".env"

function Extract-OpenAiApiKey([string]$Input) {
    if ($null -eq $Input) { return "" }
    $t = ($Input -replace "`r", " " -replace "`n", " ").Trim()
    if ($t -match 'OPENAI_API_KEY\s*=\s*(.+)') {
        $t = $Matches[1].Trim().Trim('"').Trim("'")
    }
    $m = [regex]::Match($t, 'sk-proj-[A-Za-z0-9._-]{20,}')
    if ($m.Success) { return $m.Value }
    $m2 = [regex]::Match($t, 'sk-[A-Za-z0-9._-]{20,}')
    if ($m2.Success) { return $m2.Value }
    return ""
}

function Read-EnvLines([string]$Path) {
    if (-not (Test-Path $Path)) { return @() }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -eq 0) { return @() }
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
    return @($text -split "`r?`n")
}

if (-not $Key -and $FromClipboard) {
    $Key = Get-Clipboard -ErrorAction SilentlyContinue
    if ($Key) { Write-Host "Panodan okundu." }
}

if (-not $Key) {
    Write-Host ""
    Write-Host "=== OPENAI API ANAHTARI ===" -ForegroundColor Cyan
    Write-Host "SADECE sk-proj-... veya sk-... anahtarini yapistirin."
    Write-Host "Tum .env dosyasini degil, tek satir anahtari kopyalayin."
    Write-Host ""
    $Key = Read-Host "Anahtar"
}

$Key = Extract-OpenAiApiKey $Key
if (-not $Key) {
    Write-Host ""
    Write-Host "HATA: gecerli OpenAI anahtari bulunamadi." -ForegroundColor Red
    Write-Host "Ornek: sk-proj-AbCdEf1234567890..."
    Write-Host "PC .env dosyasindan sadece sk-proj- ile baslayan kismi kopyalayin."
    exit 1
}
if ($Key.Length -gt 220) {
    Write-Host "HATA: Anahtar cok uzun ($($Key.Length) karakter)." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $projRoot ".env.example") $envPath -ErrorAction SilentlyContinue
}

$lines = Read-EnvLines $envPath
$out = New-Object System.Collections.Generic.List[string]
$keyWritten = $false

foreach ($raw in $lines) {
    $line = $raw
    if ($line -match '^\s*(?:export\s+)?OPENAI_(API_KEY|KEY|SECRET|TOKEN)\s*=') {
        if (-not $keyWritten) {
            $out.Add("OPENAI_API_KEY=$Key")
            $keyWritten = $true
        }
        continue
    }
    $out.Add($line)
}

if (-not $keyWritten) {
    if ($out.Count -gt 0 -and $out[0] -match '^\s*#') {
        $out.Insert(1, "OPENAI_API_KEY=$Key")
    }
    else {
        $out.Insert(0, "OPENAI_API_KEY=$Key")
    }
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($envPath, [string[]]$out, $utf8NoBom)

$verifyText = [System.IO.File]::ReadAllText($envPath, $utf8NoBom)
$verifyKey = Extract-OpenAiApiKey $verifyText
if ($verifyKey -ne $Key) {
    Write-Host "HATA: Dosyaya yazildi ama dogrulanamadi: $envPath" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "OK: OPENAI_API_KEY kaydedildi -> $envPath" -ForegroundColor Green
Write-Host "Anahtar uzunlugu: $($Key.Length) karakter (sk-proj-...)"
Write-Host ""
Write-Host "Simdi: .\scripts\update_vps.ps1 -SkipGit" -ForegroundColor Cyan
