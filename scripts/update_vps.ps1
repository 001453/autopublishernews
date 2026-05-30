# GitHub'dan guncelle + bagimliliklar + bot yeniden baslat
# Kullanim: cd C:\autopublishernews ; .\scripts\update_vps.ps1
#           cd C:\autopublishernews ; .\scripts\update_vps.ps1 -SkipGit

param(
    [switch]$SkipGit
)

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

Write-Host "Proje: $projRoot"

if (-not $SkipGit) {
    Write-Host "git pull..."
    git pull origin main
}

$py = Join-Path $projRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv yok, olusturuluyor..."
    python -m venv .venv
}
& $py -m pip install -r requirements.txt -q

Write-Host ".env kontrol..."
& "$PSScriptRoot\ensure_env.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "DURDURULDU: OPENAI_API_KEY .env dosyasinda yok." -ForegroundColor Red
    Write-Host "Once anahtari ekleyin, sonra tekrar calistirin:" -ForegroundColor Yellow
    Write-Host "  .\scripts\set_openai_key.ps1" -ForegroundColor Cyan
    Write-Host "  .\scripts\update_vps.ps1 -SkipGit" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "PC'nizdeki anahtari kopyalayip VPS'te yapistirin (sk-proj-...)" -ForegroundColor Yellow
    exit 1
}
Get-NetTCPConnection -LocalPort 8765,9333 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

Write-Host "Bot baslatiliyor..."
& "$PSScriptRoot\start_all_bot.ps1"

Start-Sleep -Seconds 5
$panel = Test-NetConnection 127.0.0.1 -Port 8765 -WarningAction SilentlyContinue
$cdp = Test-NetConnection 127.0.0.1 -Port 9333 -WarningAction SilentlyContinue
Write-Host ""
Write-Host "Panel 8765: $($panel.TcpTestSucceeded)"
Write-Host "CDP   9333: $($cdp.TcpTestSucceeded)"
Write-Host "Panel: http://127.0.0.1:8765"
Write-Host ""
Write-Host "Saglik gorevi yoksa (Yonetici PS): .\scripts\install_health_task.ps1"
Write-Host "Otomatik baslatma yoksa (Yonetici PS): .\scripts\install_autostart.ps1"
