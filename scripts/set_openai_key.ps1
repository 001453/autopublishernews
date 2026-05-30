# OPENAI_API_KEY guvenli ekleme / guncelleme
# Kullanim: cd C:\autopublishernews ; .\scripts\set_openai_key.ps1
#           cd C:\autopublishernews ; .\scripts\set_openai_key.ps1 -Key "sk-proj-..."

param(
    [string]$Key
)

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projRoot ".env"

if (-not $Key) {
    Write-Host "OpenAI API anahtarini yapistirin (sk-proj-... veya sk-...):"
    $Key = Read-Host
}

if ($null -eq $Key) { $Key = "" }
$Key = $Key.Trim().Trim('"').Trim("'")
if (-not $Key) {
    Write-Error "Anahtar bos."
}
if ($Key.Length -lt 20) {
    Write-Error "Anahtar cok kisa - tam anahtari yapistirdiginizdan emin olun."
}

if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $projRoot ".env.example") $envPath -ErrorAction SilentlyContinue
}

$lines = @()
if (Test-Path $envPath) {
    $bytes = [System.IO.File]::ReadAllBytes($envPath)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $text = [System.Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    else {
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    $lines = @($text -split "`r?`n")
}

$out = New-Object System.Collections.Generic.List[string]
$keyWritten = $false
foreach ($raw in $lines) {
    $line = $raw
    if ($line -match '^\s*(?:export\s+)?OPENAI_API_KEY\s*=') {
        if (-not $keyWritten) {
            $out.Add("OPENAI_API_KEY=$Key")
            $keyWritten = $true
        }
        continue
    }
    if ($line -match '^\s*(?:export\s+)?OPENAI_(KEY|SECRET|TOKEN)\s*=') {
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
Write-Host "OPENAI_API_KEY kaydedildi: $envPath"
Write-Host "Dogrulama icin: .\scripts\diagnose_env.ps1"
