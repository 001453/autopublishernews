# Ilk kurulum: venv + pip + playwright (Chrome ayri kurulmali)
# Kullanim: cd C:\autopublishernews ; .\scripts\setup_windows_vps.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

Write-Host "Proje: $projRoot"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python bulunamadi. https://www.python.org/downloads/ - PATH'e ekleyin."
}

$py = (Get-Command python).Source
Write-Host "Python: $py"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Sanal ortam olusturuluyor..."
    python -m venv .venv
}

$venvPy = Join-Path $projRoot ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt
& $venvPy -m playwright install chrome

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env" -ErrorAction SilentlyContinue
    Write-Host "UYARI: .env yok - PC'nizden kopyalayin ve OPENAI_API_KEY girin."
}

Write-Host ""
Write-Host "Kurulum tamam. Siradaki adimlar:"
Write-Host "  1. .env ve panel_config.json kopyala"
Write-Host "  2. .\scripts\start_bot_chrome.ps1"
Write-Host "  3. .\.venv\Scripts\python.exe dashboard.py"
Write-Host "  4. http://127.0.0.1:8765"
