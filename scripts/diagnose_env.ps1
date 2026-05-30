# .env okuma teshisi (OPENAI_API_KEY neden gorunmuyor?)
# Kullanim: cd C:\autopublishernews ; .\scripts\diagnose_env.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $projRoot ".env"

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
    Write-Host "Kodlama: UTF-16 LE (Notepad Unicode) - eski script bunu okuyamazdi" -ForegroundColor Yellow
}
elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Host "Kodlama: UTF-8 BOM"
}
else {
    Write-Host "Kodlama: muhtemelen UTF-8"
}

& "$PSScriptRoot\ensure_env.ps1"
