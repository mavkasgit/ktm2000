$ErrorActionPreference = "Stop"

# ============================================================
# Test runner with per-run isolated PostgreSQL database.
#
#   npm run test:pytest                parallel (-n auto)
#   npm run test:pytest:full           serial
#   npm run test:pytest:mon            parallel + testmon
#   npm run test:pytest:lf             parallel + last-failed
#   npm run test:pytest -- -k <expr>   extra pytest args pass through
#
# Every invocation gets its own TEST_RUN_ID / TEST_DB_NAME /
# TEST_DATABASE_URL. Multiple agents may run this concurrently:
# each run creates, uses and drops ONLY its own database.
# ============================================================

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
$PostgresHost = if ($env:TEST_DB_HOST)     { $env:TEST_DB_HOST }     else { "localhost" }
$PostgresPort = if ($env:TEST_DB_PORT)     { $env:TEST_DB_PORT }     else { "5441" }
$PostgresUser = if ($env:TEST_DB_USER)     { $env:TEST_DB_USER }     else { "ktm2000_user" }
$PostgresPassword = if ($env:TEST_DB_PASSWORD) { $env:TEST_DB_PASSWORD } else { "ktm2000_pass_test" }

# ------------------------------------------------------------
# Unique run identity
# ------------------------------------------------------------
$TestRunId = [guid]::NewGuid().ToString("N").ToLower().Substring(0, 12)
$TestDbName = "ktm2000_test_$TestRunId"
$TestDatabaseUrl = "postgresql+asyncpg://$PostgresUser`:$PostgresPassword@$PostgresHost`:$PostgresPort/$TestDbName"

$env:TEST_RUN_ID = $TestRunId
$env:TEST_DB_NAME = $TestDbName
$env:TEST_DATABASE_URL = $TestDatabaseUrl

Write-Host ""
Write-Host "============================================================"
Write-Host " TEST RUN"
Write-Host "============================================================"
Write-Host " Run ID : $TestRunId"
Write-Host " DB     : $TestDbName"
Write-Host "============================================================"
Write-Host ""

# ------------------------------------------------------------
# Mode flags
# ------------------------------------------------------------
$FullRun = $args -contains "--full"
$Mon = $args -contains "--mon"
$Lf = $args -contains "--lf"
$PytestArgs = @($args | Where-Object { $_ -notin @("--full", "--mon", "--lf") })
if ($Mon) { $PytestArgs += "--testmon" }
if ($Lf) { $PytestArgs += "--lf" }

if ($FullRun) { Write-Host "Mode   : FULL / SERIAL" }
else          { Write-Host "Mode   : FAST / XDIST" }
Write-Host ""

# ------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------
$ExitCode = 1
$DatabaseCreated = $false

try {
    Write-Host "[1/6] Starting PostgreSQL..."
    & npm.cmd run test:db:up
    if ($LASTEXITCODE -ne 0) { throw "test:db:up failed (exit $LASTEXITCODE)" }

    Write-Host "[2/6] Waiting for PostgreSQL..."
    & npm.cmd run test:db:wait
    if ($LASTEXITCODE -ne 0) { throw "test:db:wait failed (exit $LASTEXITCODE)" }

    Write-Host "[3/6] Creating isolated database..."
    & python scripts/test-db.py create $TestDbName
    if ($LASTEXITCODE -ne 0) { throw "Failed to create test database: $TestDbName" }
    $DatabaseCreated = $true

    Write-Host "[4/6] Verifying database..."
    & python scripts/test-db.py verify $TestDbName
    if ($LASTEXITCODE -ne 0) { throw "Database verify failed for $TestDbName" }

    Push-Location backend
    try {
        Write-Host ""
        Write-Host "[5/6] Running pytest..."
        Write-Host "TEST_DATABASE_URL=$TestDatabaseUrl"
        Write-Host ""
        if ($FullRun) {
            & python -m pytest @PytestArgs
        } else {
            & python -m pytest -n auto @PytestArgs
        }
        $ExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Host ""
    Write-Error $_
    $ExitCode = 1
}
finally {
    if ($DatabaseCreated) {
        Write-Host ""
        Write-Host "[6/6] Cleaning up database: $TestDbName"
        & python scripts/test-db.py drop $TestDbName
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed to cleanup test database: $TestDbName"
        }
    }
}

Write-Host ""
if ($ExitCode -eq 0) {
    Write-Host "============================================================"
    Write-Host " TESTS PASSED"
    Write-Host "============================================================"
}
else {
    Write-Host "============================================================"
    Write-Host " TESTS FAILED"
    Write-Host " Exit code: $ExitCode"
    Write-Host "============================================================"
}

exit $ExitCode
