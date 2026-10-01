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

# Interpreter for test-db.py and pytest. Default is `python` from PATH; override
# with TEST_PYTHON to make the run reproducible when PATH points at a different
# Python than the one with the dependencies (as of 2026-10-01: PATH has system
# Python 3.12 with the deps, while backend/.venv is an empty 3.14 - see B-0006).
$PythonExe = if ($env:TEST_PYTHON) { $env:TEST_PYTHON } else { "python" }
$pythonOk = $true
try { & $PythonExe -c "import sys" *> $null } catch { $pythonOk = $false }
if ($pythonOk -and ($null -ne $LASTEXITCODE) -and $LASTEXITCODE -ne 0) { $pythonOk = $false }
if (-not $pythonOk) {
    throw "TEST_PYTHON='$PythonExe' is not a runnable interpreter (set TEST_PYTHON or fix PATH)"
}

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

# Worker scheduling: one whole module per worker.
# Measurements (3+3 interleaved runs, workers=4, per-module schema isolation):
#   --dist load (default): 370.7 / 372.2 / 367.7s
#   --dist loadfile      : 259.4 / 256.6 / 256.3s   (-31%)
# Same results (1945 passed). Why: the module schema is created per worker, so
# under `load` the tests of one module scatter across workers and setup is
# duplicated (setup sum 327s -> 287s); the heavy tail also packs better.
# An explicit --dist from the caller wins over this default.
# NOTE: keep this file ASCII-only - Windows PowerShell reads it as UTF-8 without
# BOM, so non-ASCII string literals come out garbled in redirected output.
$DistArgs = @()
if (-not ($PytestArgs -contains "--dist")) { $DistArgs = @("--dist", "loadfile") }

if ($FullRun) { Write-Host "Mode   : FULL / SERIAL" }
else {
    if ($NumWorkers) { Write-Host "Mode   : FAST / XDIST (workers=$NumWorkers)" }
    else             { Write-Host "Mode   : FAST / XDIST (auto)" }
    if ($DistArgs.Count -gt 0) { Write-Host "Dist   : $($DistArgs[1]) (whole module per worker)" }
}
if ($KeepDb) { Write-Host "DB     : keep after run (--keep-db)" }
Write-Host "Python : $PythonExe"
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
    & $PythonExe scripts/test-db.py create $TestDbName
    if ($LASTEXITCODE -ne 0) { throw "Failed to create test database: $TestDbName" }
    $DatabaseCreated = $true

    Write-Host "[4/6] Verifying database..."
    & $PythonExe scripts/test-db.py verify $TestDbName
    if ($LASTEXITCODE -ne 0) { throw "Database verify failed for $TestDbName" }

    Push-Location backend
    try {
        $LogDir = Join-Path (Split-Path -Parent $PSScriptRoot) "logs"
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
        $LogFile = Join-Path $LogDir "pytest-$TestRunId.log"
        Write-Host ""
        Write-Host "[5/6] Running pytest..."
        Write-Host "TEST_DATABASE_URL=$TestDatabaseUrl"
        Write-Host "Log    : $LogFile"
        Write-Host ""
        # Output is streamed (Tee) instead of captured: a six-minute run must
        # show progress, and a hang must be visible where it happens. The log
        # file keeps the same text for the xdist crash check below.
        if ($FullRun) {
            & $PythonExe -m pytest @PytestArgs 2>&1 | Tee-Object -FilePath $LogFile
        } else {
            if ($NumWorkers) {
                & $PythonExe -m pytest -n $NumWorkers @DistArgs @PytestArgs 2>&1 | Tee-Object -FilePath $LogFile
            } else {
                & $PythonExe -m pytest -n auto @DistArgs @PytestArgs 2>&1 | Tee-Object -FilePath $LogFile
            }
        }
        $ExitCode = $LASTEXITCODE
        # pytest-xdist may report a worker crash as a successful (0) exit when the
        # suite never actually ran. Detect that and force failure.
        $PytestOutput = Get-Content -LiteralPath $LogFile -ErrorAction SilentlyContinue
        if ($ExitCode -eq 0 -and ($PytestOutput -match 'node down|maximum crashed workers')) {
            Write-Warning "pytest-xdist workers crashed; forcing failure"
            $ExitCode = 2
        }
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
            & $PythonExe scripts/test-db.py drop $TestDbName
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
