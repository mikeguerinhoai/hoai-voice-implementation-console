# HOAi Implementation Console — Windows Task Scheduler Setup
# Run as Administrator: powershell -ExecutionPolicy Bypass -File implementation-console\setup-scheduler.ps1

$WorkDir = "C:\Users\MikeGuerin"
$NpmPath = (Get-Command npm).Source

# ── Task 1: Morning Run (8:00 AM ET) ────────────────────────────────────────
$MorningAction = New-ScheduledTaskAction `
    -Execute $NpmPath `
    -Argument "run implementation" `
    -WorkingDirectory $WorkDir

$MorningTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00"

$MorningSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName "HOAi_Implementation_Morning" `
    -Description "HOAi Implementation Console — Morning pipeline: fetch Notion, evaluate triggers, generate deliverables, write-back, post briefing to Teams" `
    -Action $MorningAction `
    -Trigger $MorningTrigger `
    -Settings $MorningSettings `
    -Force

Write-Host "✓ Registered: HOAi_Implementation_Morning (Monday 8:00 AM)"

# ── Task 2: Evening Run (7:00 PM ET) ────────────────────────────────────────
$EveningAction = New-ScheduledTaskAction `
    -Execute $NpmPath `
    -Argument "run implementation:analyze" `
    -WorkingDirectory $WorkDir

$EveningTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At "19:00"

$EveningSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName "HOAi_Implementation_Evening" `
    -Description "HOAi Implementation Console — Evening analysis: run testing analyses due today, post results to Teams + Notion" `
    -Action $EveningAction `
    -Trigger $EveningTrigger `
    -Settings $EveningSettings `
    -Force

Write-Host "✓ Registered: HOAi_Implementation_Evening (Thursday 7:00 PM)"
Write-Host ""
Write-Host "Verify with: Get-ScheduledTask | Where-Object {`$_.TaskName -like 'HOAi_Implementation*'}"
