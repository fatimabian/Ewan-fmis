param(
    [string]$ListenAddress = "127.0.0.1:8080",
    [int]$Threads = 8
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
    config.wsgi:application
