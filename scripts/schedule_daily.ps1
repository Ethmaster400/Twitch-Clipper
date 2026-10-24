# Registers a Windows scheduled task that runs Claud every day.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1                   # daily at 09:00
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1 -At 18:30         # daily at 18:30
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1 -At 10:00,19:00   # twice a day
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_daily.ps1 -Remove           # stop scheduling
#
# Output of each run is appended to data\claud.log.
param(
    [string[]]$At = @("09:00"),
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$TaskName = "Claud daily clips"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed the scheduled task: $TaskName"
    exit 0
}

$Root = Split-Path -Parent $PSScriptRoot
$Bat = Join-Path $Root "scripts\run_claud.bat"
if (-not (Test-Path (Join-Path $Root ".venv\Scripts\claud.exe"))) {
    throw "Claud is not installed in $Root\.venv - run the setup steps first."
}

$Action = New-ScheduledTaskAction -Execute $Bat -WorkingDirectory $Root
$Triggers = @($At | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
# Run late if the PC was off or asleep at the scheduled time; stop a run stuck for over 3 hours.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Description "Finds new Twitch clips, renders them and uploads or saves them (Claud)." -Force | Out-Null

$Times = $At -join ", "
Write-Host "Scheduled: $TaskName, daily at $Times"
Write-Host "It runs while you are logged in to Windows. Output goes to $Root\data\claud.log"
Write-Host "To test it right now: Start-ScheduledTask -TaskName `"$TaskName`""
