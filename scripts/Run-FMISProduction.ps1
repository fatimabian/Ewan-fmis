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

if ($env:DJANGO_DEBUG -ne "False") {
    throw "DJANGO_DEBUG must be False before FMIS can start in production mode."
}
if ($env:DB_ENGINE -ne "mysql") {
    throw "DB_ENGINE must be mysql before FMIS can start in production mode."
}
if (-not $env:DJANGO_SECRET_KEY -or $env:DJANGO_SECRET_KEY.Length -lt 50) {
    throw "DJANGO_SECRET_KEY must contain a protected random value of at least 50 characters."
}
if (-not $env:EMAIL_HOST) {
    throw "EMAIL_HOST must be configured for account activation and recovery."
}

& python -m waitress `
    --listen=$ListenAddress `
    --threads=$Threads `
    --connection-limit=$ConnectionLimit `
    --backlog=$Backlog `
    config.wsgi:application
