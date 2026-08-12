param(
    [string]$PythonPath = "C:\Users\arnig\AppData\Local\Python\pythoncore-3.14-64\python.exe",
    [string]$ProjectPath = "C:\Users\arnig\OneDrive\Documents\GitHub\Ewan-fmis",
    [string]$DailyTime = "02:00"
)

$ErrorActionPreference = "Stop"
$managePath = Join-Path $ProjectPath "manage.py"
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python was not found at the configured path."
}
if (-not (Test-Path -LiteralPath $managePath -PathType Leaf)) {
    throw "FMIS manage.py was not found at the configured project path."
}

$credential = Get-Credential -Message "Enter the protected Windows service account that will run FMIS backups."
$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument ('"{0}" backup_fmis' -f $managePath) `
    -WorkingDirectory $ProjectPath
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName "FMIS Daily Encrypted Backup" `
    -Description "Creates, encrypts, verifies, and uploads the FMIS recovery archive." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $credential.UserName `
    -Password $credential.GetNetworkCredential().Password `
    -RunLevel Highest `
    -Force

Write-Host "FMIS daily backup task installed for $DailyTime."
Write-Host "After its first successful run, set FMIS_BACKUP_SCHEDULER_CONFIGURED=True in the protected environment."
