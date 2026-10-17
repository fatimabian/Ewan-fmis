param(
    [string]$ListenAddress = "127.0.0.1:8080",
    [ValidateRange(4, 128)]
    [int]$Threads = 32,
    [ValidateRange(100, 5000)]
    [int]$ConnectionLimit = 500,
    [ValidateRange(64, 4096)]
    [int]$Backlog = 512
)

$ErrorActionPreference = "Stop"

function Invoke-FMISCommand {
    param([string[]]$Arguments)
    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "FMIS production validation failed: python $($Arguments -join ' ')"
    }
}

Invoke-FMISCommand @("manage.py", "check", "--deploy")
Invoke-FMISCommand @("manage.py", "migrate", "--check")
Invoke-FMISCommand @("manage.py", "check_fmis_readiness")

& python -m waitress `
    --listen=$ListenAddress `
    --threads=$Threads `
    --connection-limit=$ConnectionLimit `
    --backlog=$Backlog `
    config.wsgi:application
if ($LASTEXITCODE -ne 0) {
    throw "The FMIS Waitress process stopped with exit code $LASTEXITCODE."
}
