param(
    [string]$ProjectPath = "",
    [string]$OutputPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not $ProjectPath) {
    $ProjectPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $ProjectPath ".env.production"
}

$sourcePath = Join-Path $ProjectPath ".env"
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "The local .env file was not found. Configure and test SMTP before preparing production."
}
if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "The production environment file already exists. Use -Force only when intentionally rotating its secrets."
}

$localEnvironment = @{}
foreach ($line in Get-Content -LiteralPath $sourcePath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
        continue
    }
    $parts = $trimmed.Split("=", 2)
    $localEnvironment[$parts[0].Trim()] = $parts[1].Trim()
}

$requiredEmailKeys = @(
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
    "EMAIL_TIMEOUT",
    "DEFAULT_FROM_EMAIL"
)
foreach ($key in $requiredEmailKeys) {
    if (-not $localEnvironment.ContainsKey($key) -or -not $localEnvironment[$key]) {
        throw "The tested local email setting $key is missing."
    }
}

function New-UrlSafeSecret([int]$ByteCount, [bool]$KeepPadding) {
    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    $encoded = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
    if (-not $KeepPadding) {
        $encoded = $encoded.TrimEnd("=")
    }
    return $encoded
}

$djangoSecret = New-UrlSafeSecret 64 $false
$backupSecret = New-UrlSafeSecret 32 $true

$lines = @(
    "# FMIS production environment - contains secrets; never commit or send through chat.",
    "# Replace every CHANGE_ME value after the hosting service and domain are selected.",
    "DJANGO_DEBUG=False",
    "DJANGO_SECRET_KEY=$djangoSecret",
    "DJANGO_ALLOWED_HOSTS=CHANGE_ME_PRODUCTION_HOSTNAME",
    "DJANGO_CSRF_TRUSTED_ORIGINS=https://CHANGE_ME_PRODUCTION_HOSTNAME",
    "DJANGO_BEHIND_HTTPS_PROXY=True",
    "DJANGO_SECURE_SSL_REDIRECT=True",
    "DJANGO_HSTS_SECONDS=31536000",
    "",
    "DB_ENGINE=mysql",
    "MYSQL_DATABASE=CHANGE_ME_PRODUCTION_DATABASE",
    "MYSQL_USER=CHANGE_ME_LEAST_PRIVILEGE_DATABASE_USER",
    "MYSQL_PASSWORD=CHANGE_ME_STRONG_DATABASE_PASSWORD",
    "MYSQL_HOST=CHANGE_ME_DATABASE_HOST",
    "MYSQL_PORT=3306",
    "DB_CONN_MAX_AGE=60",
    "MYSQL_ALLOW_LEGACY_MARIADB=False",
    "",
    "EMAIL_HOST=$($localEnvironment['EMAIL_HOST'])",
    "EMAIL_PORT=$($localEnvironment['EMAIL_PORT'])",
    "EMAIL_HOST_USER=$($localEnvironment['EMAIL_HOST_USER'])",
    "EMAIL_HOST_PASSWORD=$($localEnvironment['EMAIL_HOST_PASSWORD'])",
    "EMAIL_USE_TLS=$($localEnvironment['EMAIL_USE_TLS'])",
    "EMAIL_USE_SSL=$($localEnvironment['EMAIL_USE_SSL'])",
    "EMAIL_TIMEOUT=$($localEnvironment['EMAIL_TIMEOUT'])",
    "DEFAULT_FROM_EMAIL=$($localEnvironment['DEFAULT_FROM_EMAIL'])",
    "",
    "PUBLIC_PAGE_CACHE_SECONDS=300",
    "REMEMBER_LOGIN_DAYS=7",
    "FMIS_RELEASE_VERSION=CHANGE_ME_RELEASE_TAG",
    "FMIS_FIELD_BASE_URL=https://CHANGE_ME_PRODUCTION_HOSTNAME",
    "FMIS_PREWARM_ON_START=True",
    "FMIS_LOG_ROOT=C:/FMIS/logs",
    "FMIS_LOG_LEVEL=INFO",
    "FMIS_MIN_FREE_DISK_GB=5",
    "",
    "FMIS_BACKUP_ROOT=C:/FMIS/backups",
    "FMIS_BACKUP_ENCRYPTION_KEY=$backupSecret",
    "BACKUP_AZURE_CONTAINER_URL=CHANGE_ME_PRIVATE_HTTPS_CONTAINER_SAS_URL",
    "MARIADB_DUMP_PATH=C:/Program Files/MariaDB 10.11/bin/mariadb-dump.exe",
    "FMIS_BACKUP_SCHEDULER_CONFIGURED=False"
)

[System.IO.File]::WriteAllLines(
    $OutputPath,
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Output "Prepared a Git-ignored FMIS production environment with new application and backup secrets."
Write-Output "Complete the CHANGE_ME values on the production server before using this file."
