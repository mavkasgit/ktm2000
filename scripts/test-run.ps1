$ErrorActionPreference = "Stop"

# ============================================================
# Test runner with per-run isolated PostgreSQL database.
#
#   npm run test:pytest                parallel (-n auto)
#   npm run test:pytest:full           serial
#   npm run test:pytest:mon            parallel + testmon
#   npm run test:pytest:lf             parallel + last-failed
#   npm run test:pytest -- --keep-db   leave the run-DB in place (diagnosis)
#   npm run test:pytest -- -k <expr>   extra pytest args pass through
#
# Every invocation gets its own TEST_RUN_ID / TEST_DB_NAME /
# TEST_DATABASE_URL. Multiple agents may run this concurrently:
# each run creates, uses and drops ONLY its own database.
# With --keep-db the database survives the run (and its owner row too), so a
# failure can be inspected; `python scripts/test-db.py drop <db>` removes it
# right away, `npm run test:db:cleanup` — by TTL.
# ============================================================

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
$PostgresHost = if ($env:TEST_DB_HOST)     { $env:TEST_DB_HOST }     else { "localhost" }
$PostgresPort = if ($env:TEST_DB_PORT)     { $env:TEST_DB_PORT }     else { "5441" }
$PostgresUser = if ($env:TEST_DB_USER)     { $env:TEST_DB_USER }     else { "ktm2000_user" }
$PostgresPassword = if ($env:TEST_DB_PASSWORD) { $env:TEST_DB_PASSWORD } else { "ktm2000_pass_test" }
# xdist worker cap for the parallel run. Default: -n auto (= all cores).
# When several agents run tests concurrently, set PYTEST_NUM_WORKERS (e.g. 4),
# otherwise every run grabs all cores and the machine becomes unresponsive.
$NumWorkers = $env:PYTEST_NUM_WORKERS

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
$KeepDb = $args -contains "--keep-db"
$PytestArgs = @($args | Where-Object { $_ -notin @("--full", "--mon", "--lf", "--keep-db") })
if ($Mon) { $PytestArgs += "--testmon" }
if ($Lf) { $PytestArgs += "--lf" }

if ($FullRun) { Write-Host "Mode   : FULL / SERIAL" }
else {
    if ($NumWorkers) { Write-Host "Mode   : FAST / XDIST (workers=$NumWorkers)" }
    else             { Write-Host "Mode   : FAST / XDIST (auto)" }
}
if ($KeepDb) { Write-Host "DB     : keep after run (--keep-db)" }
Write-Host ""

# ------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------
$ExitCode = 1
$DatabaseCreated = $false

try {
    # PostgreSQL is shared infrastructure. Only run up/wait when the container
    # is not healthy yet: under concurrent agents redundant docker compose calls
    # block on the compose lock and make the start look hung.
    $health = docker inspect -f '{{.State.Health.Status}}' ktm2000-postgres-test 2>$null
    if ($LASTEXITCODE -eq 0 -and $health -eq 'healthy') {
        Write-Host "[1/6] PostgreSQL already healthy - skipping up/wait"
    } else {
        Write-Host "[1/6] Starting PostgreSQL..."
        & npm.cmd run test:db:up
        if ($LASTEXITCODE -ne 0) { throw "test:db:up failed (exit $LASTEXITCODE)" }

        Write-Host "[2/6] Waiting for PostgreSQL..."
        & npm.cmd run test:db:wait
        if ($LASTEXITCODE -ne 0) { throw "test:db:wait failed (exit $LASTEXITCODE)" }
    }

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
            $PytestOutput = & python -m pytest @PytestArgs 2>&1
        } else {
            if ($NumWorkers) {
                $PytestOutput = & python -m pytest -n $NumWorkers @PytestArgs 2>&1
            } else {
                $PytestOutput = & python -m pytest -n auto @PytestArgs 2>&1
            }
        }
        $ExitCode = $LASTEXITCODE
        # pytest-xdist may report a worker crash as a successful (0) exit when the
        # suite never actually ran. Detect that and force failure.
        if ($ExitCode -eq 0 -and ($PytestOutput -match 'node down|maximum crashed workers')) {
            Write-Warning "pytest-xdist workers crashed; forcing failure"
            $ExitCode = 2
        }
        $PytestOutput | ForEach-Object { Write-Host $_ }
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
        if ($KeepDb) {
            Write-Host ""
            Write-Host "[6/6] Keeping test database (--keep-db): $TestDbName"
            Write-Host "      DSN  : $TestDatabaseUrl"
            Write-Host "      Drop : python scripts/test-db.py drop $TestDbName"
        }
        else {
            Write-Host ""
            Write-Host "[6/6] Cleaning up database: $TestDbName"
            & python scripts/test-db.py drop $TestDbName
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Failed to cleanup test database: $TestDbName"
            }
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
