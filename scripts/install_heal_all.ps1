# Kalici rahatlama: oturum acilis + 15 dk health + gunluk bakim
# Kullanim (Yonetici PowerShell):
#   cd C:\autopublishernews
#   .\scripts\install_heal_all.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projRoot

Write-Host "=== XNewsBot kalici heal kurulumu ==="
Write-Host ""

& "$PSScriptRoot\install_autostart.ps1"
Write-Host ""
& "$PSScriptRoot\install_health_task.ps1"
Write-Host ""
& "$PSScriptRoot\install_maintenance_task.ps1"
Write-Host ""

# Hemen bir health gecisi
Write-Host "Ilk health kontrolu calistiriliyor..."
& "$PSScriptRoot\health_check.ps1"
Write-Host ""

Write-Host "Kurulum bitti. Gorevler:"
Get-ScheduledTask -TaskName "XNewsBot","XNewsBotHealth","XNewsBotMaintenance" -ErrorAction SilentlyContinue |
    Select-Object TaskName, State |
    Format-Table -AutoSize

Write-Host "Loglar: $projRoot\logs\health.log , maintenance.log , autostart.log"
Write-Host "RDP'den cikarken Disconnect kullanin (Log off degil)."
