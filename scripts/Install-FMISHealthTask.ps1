param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [string]$ProjectPath = "",
    [ValidateRange(1, 60)]
    [int]$IntervalMinutes = 5
)

$ErrorActionPreference = "Stop"
$baseUri = [Uri]$BaseUrl
if ($baseUri.Scheme -ne "https") {
    throw "The scheduled production monitor requires an HTTPS BaseUrl."
}
if (-not $ProjectPath) {
    $ProjectPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
$healthScript = Join-Path $ProjectPath "scripts\Test-FMISHealth.ps1"
if (-not (Test-Path -LiteralPath $healthScript -PathType Leaf)) {
    throw "The FMIS health-check script was not found."
}

if (-not [System.Diagnostics.EventLog]::SourceExists("FMIS Health Monitor")) {
    New-EventLog -LogName Application -Source "FMIS Health Monitor"
}
$credential = Get-Credential -Message "Enter the restricted Windows account that will run the FMIS health monitor."
$powerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -BaseUrl "{1}"' -f $healthScript, $baseUri.AbsoluteUri
$action = New-ScheduledTaskAction -Execute $powerShellPath -Argument $arguments -WorkingDirectory $ProjectPath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName "FMIS HTTPS Health Monitor" `
    -Description "Checks the external FMIS HTTPS health endpoint and records failures in the Windows Application log." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $credential.UserName `
    -Password $credential.GetNetworkCredential().Password `
    -RunLevel Highest `
    -Force

Write-Host "FMIS health monitor installed for $($baseUri.AbsoluteUri) every $IntervalMinutes minute(s)."
Write-Host "Connect the Windows Application log to the municipality's alerting service before launch."
