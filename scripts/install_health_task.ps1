# Gorev Zamanlayicisi: her 15 dk panel + Chrome port kontrolu (Yonetici PowerShell)
# Kullanim: cd C:\autopublishernews ; .\scripts\install_health_task.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$healthScript = Join-Path $PSScriptRoot "health_check.ps1"
if (-not (Test-Path $healthScript)) {
    Write-Error "Bulunamadi: $healthScript"
}

$taskName = "XNewsBotHealth"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Eski gorev silindi."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$healthScript`"" `
    -WorkingDirectory $projRoot

$startAt = (Get-Date).AddMinutes(2)
$trigger = New-ScheduledTaskTrigger -Once -At $startAt `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

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
    -Description "RSS + X bot: 8765/9333 port sagligi; duserse yeniden baslatir" | Out-Null

Write-Host ""
Write-Host "Gorev olusturuldu: $taskName"
Write-Host "Aralik: her 15 dakika"
Write-Host "Script: $healthScript"
Write-Host "Log: $projRoot\logs\health.log"
Write-Host ""
Write-Host "Test: Start-ScheduledTask -TaskName '$taskName'"
