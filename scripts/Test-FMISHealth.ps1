param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [string]$LogPath = "C:\ProgramData\FMIS\logs\health-monitor.log",
    [ValidateRange(2, 60)]
    [int]$TimeoutSeconds = 15,
    [switch]$AllowHttpForLocalTest
)

$ErrorActionPreference = "Stop"
$baseUri = [Uri]$BaseUrl
if ($baseUri.Scheme -ne "https" -and -not $AllowHttpForLocalTest) {
    throw "Production health monitoring requires an HTTPS BaseUrl."
}
$healthUri = [Uri]::new($baseUri, "/health/")
$logDirectory = Split-Path -Parent $LogPath
if ($logDirectory) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}

$timestamp = (Get-Date).ToUniversalTime().ToString("o")
try {
    $response = Invoke-WebRequest -Uri $healthUri.AbsoluteUri -TimeoutSec $TimeoutSeconds -UseBasicParsing
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -ne 200 -or $payload.status -ne "ok") {
        throw "Unexpected health response."
    }
    Add-Content -LiteralPath $LogPath -Value "$timestamp OK $($response.StatusCode) $($healthUri.AbsoluteUri)"
    exit 0
}
catch {
    $safeMessage = ($_.Exception.Message -replace "[\r\n]+", " ")
    Add-Content -LiteralPath $LogPath -Value "$timestamp FAIL $($healthUri.AbsoluteUri) $safeMessage"
    try {
        if ([System.Diagnostics.EventLog]::SourceExists("FMIS Health Monitor")) {
            Write-EventLog -LogName Application -Source "FMIS Health Monitor" -EntryType Error -EventId 1001 -Message "FMIS health check failed for $($healthUri.AbsoluteUri): $safeMessage"
        }
    }
    catch {
        # The file log remains authoritative when a non-administrator cannot query the event-log registry.
    }
    Write-Error "FMIS health check failed: $safeMessage"
    exit 1
}
