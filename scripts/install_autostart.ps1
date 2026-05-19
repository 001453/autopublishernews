# Gorev Zamanlayicisi: oturum acilinca bot + panel (Yonetici PowerShell)
# Kullanim: cd C:\autopublishernews ; .\scripts\install_autostart.ps1

$ErrorActionPreference = "Stop"
$projRoot = Split-Path $PSScriptRoot -Parent
$startScript = Join-Path $PSScriptRoot "start_all_bot.ps1"
if (-not (Test-Path $startScript)) {
    Write-Error "Bulunamadi: $startScript"
}

$taskName = "XNewsBot"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Eski gorev silindi."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`"" `
    -WorkingDirectory $projRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

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
    -Description "RSS + X bot: Chrome CDP 9333 ve panel 8765" | Out-Null

Write-Host ""
Write-Host "Gorev olusturuldu: $taskName"
Write-Host "Tetikleyici: $($env:USERNAME) oturum acilinca"
Write-Host "Script: $startScript"
Write-Host ""
Write-Host "Test icin: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Log: $projRoot\logs\autostart.log"
Write-Host ""
Write-Host "RDP kapali iken Chrome duserse: .\scripts\install_health_task.ps1 (her 15 dk kontrol)"
