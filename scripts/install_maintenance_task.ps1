# Gorev Zamanlayicisi: her gun 04:15 Bot Chrome ForceRestart + panel kontrolu
# Kullanim: cd C:\autopublishernews ; .\scripts\install_maintenance_task.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$maintScript = Join-Path $PSScriptRoot "maintenance.ps1"
if (-not (Test-Path $maintScript)) {
    Write-Error "Bulunamadi: $maintScript"
}

$taskName = "XNewsBotMaintenance"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Eski gorev silindi."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$maintScript`"" `
    -WorkingDirectory $projRoot

$trigger = New-ScheduledTaskTrigger -Daily -At "04:15"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "RSS + X bot: gunluk Chrome ForceRestart ve panel saglik kontrolu" | Out-Null

$check = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
Write-Host ""
Write-Host "Gorev olusturuldu: $taskName (durum: $($check.State))"
Write-Host "Zaman: her gun 04:15"
Write-Host "Script: $maintScript"
Write-Host "Log: $projRoot\logs\maintenance.log"
Write-Host ""
Write-Host "Test: Start-ScheduledTask -TaskName '$taskName'"
