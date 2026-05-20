# Yerel/klon: agir klasorleri siler (.env, panel_config, kod korunur).
# Kullanim: cd <proje> ; .\scripts\cleanup_local_light.ps1 [-WhatIf]

param([switch]$WhatIf)

$ErrorActionPreference = "Continue"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

$targets = @(
    @{ Path = Join-Path $projRoot ".venv"; Desc = "Python venv" }
    @{ Path = Join-Path $projRoot "x_profile"; Desc = "Chrome profil" }
    @{ Path = Join-Path $projRoot "data"; Desc = "DATA_DIR verisi" }
    @{ Path = Join-Path $projRoot "logs"; Desc = "Log dosyalari" }
    @{ Path = Join-Path $projRoot "chrome_cdp_profile"; Desc = "CDP profil" }
    @{ Path = Join-Path $projRoot "posted.sqlite3"; Desc = "SQLite (kok)" }
    @{ Path = Join-Path $projRoot "publish_queue.txt"; Desc = "Eski kuyruk dosyasi" }
)

Write-Host "Proje: $projRoot"
Write-Host "KORUNAN: .env, .env.example, panel_config.json, kod, scripts"
Write-Host ""

foreach ($t in $targets) {
    $p = $t.Path
    if (-not (Test-Path $p)) { continue }
    Write-Host ($t.Desc + ": " + $p)
    if ($WhatIf) {
        Write-Host "  [WhatIf] silinirdi"
    }
    else {
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $p) { Write-Warning "  Silinemedi: $p" } else { Write-Host "  silindi." }
    }
}

Get-ChildItem -Path $projRoot -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
    ForEach-Object {
        Write-Host "__pycache__: $($_.FullName)"
        if (-not $WhatIf) { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    }

Write-Host ""
if ($WhatIf) { Write-Host "Gercek silme icin -WhatIf kaldirin." }
else { Write-Host "Bitti. Gerekirse: python -m venv .venv ; pip install -r requirements.txt" }
