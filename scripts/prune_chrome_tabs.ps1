# Fazla X/Chrome sekmelerini kapat (bellek temizligi)
# Kullanim: cd C:\autopublishernews ; .\scripts\prune_chrome_tabs.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$py = Join-Path $projRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "venv yok: $py"
}

Set-Location $projRoot
$closed = & $py -c "from engine import prune_bot_cdp_tabs; print(prune_bot_cdp_tabs(log=print))"
Write-Host ""
Write-Host "Kapatilan sekme: $closed"
