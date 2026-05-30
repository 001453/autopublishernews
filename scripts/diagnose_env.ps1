# .env okuma teshisi (OPENAI_API_KEY neden gorunmuyor?)
# Kullanim: cd C:\autopublishernews ; .\scripts\diagnose_env.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projRoot ".env"
$examplePath = Join-Path $projRoot ".env.example"

function Read-EnvTextLines([string]$Path) {
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
    return $text -split "`r?`n"
}

function Mask-Secret([string]$Line) {
    if (-not $Line) { return $Line }
    return [regex]::Replace($Line, 'sk-[A-Za-z0-9._-]{8,}', 'sk-****')
}

if (-not (Test-Path $envPath)) {
    Write-Host "HATA: .env yok: $envPath" -ForegroundColor Red
    exit 1
}

$bytes = [System.IO.File]::ReadAllBytes($envPath)
$head = ($bytes | Select-Object -First 4 | ForEach-Object { "{0:X2}" -f $_ }) -join " "
Write-Host "Dosya: $envPath"
Write-Host "Boyut: $($bytes.Length) byte"
Write-Host "Ilk baytlar: $head"

if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
    Write-Host "Kodlama: UTF-16 LE (Notepad Unicode)" -ForegroundColor Yellow
}
elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Host "Kodlama: UTF-8 BOM"
}
else {
    Write-Host "Kodlama: muhtemelen UTF-8"
}

Write-Host ""
Write-Host "OPENAI iceren satirlar (.env):"
$lines = Read-EnvTextLines $envPath
$foundOpenAi = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match 'OPENAI|openai|sk-proj|sk-') {
        $foundOpenAi = $true
        $n = $i + 1
        $tag = ""
        if ($line -match '^\s*#') { $tag = "[YORUM] " }
        elseif ($line -match '^\s*OPENAI_API_KEY\s*=\s*$') { $tag = "[BOS DEGER] " }
        elseif ($line -notmatch 'OPENAI_API_KEY\s*=') { $tag = "[FORMAT DISI] " }
        Write-Host "  satir $n : $tag$(Mask-Secret $line)"
    }
}
if (-not $foundOpenAi) {
    Write-Host "  (hic yok - .env dosyasinda OPENAI satiri yok)" -ForegroundColor Yellow
    Write-Host "  Notepad'de gordugunuz dosya .env.example olabilir: $examplePath" -ForegroundColor Yellow
}

Write-Host ""
& "$PSScriptRoot\ensure_env.ps1"
