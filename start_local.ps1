# ==============================================================================
# ChronosMatch Local Startup Script (Windows 11 / PowerShell)
# Master Automated Launcher (Phase 8)
# ==============================================================================

[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "     CHRONOSMATCH ZERO-COPY HFT TRADING TERMINAL — STARTUP" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Virtual Environment (if present, activate it)
Write-Host "[1/8] Checking Virtual Environment..." -ForegroundColor Yellow
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    Write-Host "  -> Activating virtual environment (.venv)..." -ForegroundColor Green
    & .\.venv\Scripts\Activate.ps1
} elseif (Test-Path ".\venv\Scripts\Activate.ps1") {
    Write-Host "  -> Activating virtual environment (venv)..." -ForegroundColor Green
    & .\venv\Scripts\Activate.ps1
} else {
    Write-Host "  -> No local venv folder detected; utilizing system Python environment." -ForegroundColor Gray
}

# 2. Check Python Installation
Write-Host "[2/8] Checking Python environment..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw $pythonVersion }
    Write-Host "  -> Python detected: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Python is not found in system PATH. Please install Python 3.10+ (64-bit)." -ForegroundColor Red
    exit 1
}

# 3. Check Required Dependencies
Write-Host "[3/8] Verifying Python dependencies..." -ForegroundColor Yellow
$missingDeps = 0
foreach ($pkg in @("django", "cython", "numpy", "pytest")) {
    $check = python -c "import $pkg" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [MISSING] $pkg is not installed. Run: python -m pip install -r requirements.txt" -ForegroundColor Red
        $missingDeps++
    } else {
        Write-Host "  -> Dependency verified: $pkg" -ForegroundColor Green
    }
}

if ($missingDeps -gt 0) {
    Write-Host "  [ERROR] Required packages are missing. Run: python -m pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

# 4. Check and Verify Native Cython Matching Engine
Write-Host "[4/8] Verifying Cython Native Extension..." -ForegroundColor Yellow
$cythonCheck = python -c "from core.order_book import IS_NATIVE_CYTHON; print('CYTHON_OK' if IS_NATIVE_CYTHON else 'FALLBACK')" 2>&1
if ($LASTEXITCODE -eq 0 -and $cythonCheck -match "CYTHON_OK") {
    Write-Host "  -> Native Cython Limit Order Book (.pyd) is compiled and verified (C nogil math active)." -ForegroundColor Green
} else {
    Write-Host "  [NOTICE] Cython extension not compiled. Attempting automatic build..." -ForegroundColor Yellow
    python setup.py build_ext --inplace
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARNING] Cython build failed. The engine will operate in pure-Python fallback mode." -ForegroundColor Yellow
    } else {
        Write-Host "  -> Cython extension compiled and verified successfully." -ForegroundColor Green
    }
}

# 5. Check Django Configuration
Write-Host "[5/8] Checking Django configuration..." -ForegroundColor Yellow
$djangoCheck = python manage.py check 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [ERROR] Django check failed: $djangoCheck" -ForegroundColor Red
    exit 1
}
Write-Host "  -> Django configuration verified (0 errors)." -ForegroundColor Green

# 6. Run Database Migrations
Write-Host "[6/8] Running database migrations..." -ForegroundColor Yellow
$migrateOut = python manage.py migrate --noinput 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [WARNING] Database migration notice: $migrateOut" -ForegroundColor Yellow
} else {
    Write-Host "  -> Database schema is up to date." -ForegroundColor Green
}

# 7. Check for Port Conflicts
Write-Host "[7/8] Checking port availability on $HostAddress`:$Port..." -ForegroundColor Yellow
$existingConn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingConn) {
    $conflictingPid = $existingConn[0].OwningProcess
    Write-Host "  [ERROR] Port $Port is already in use by process PID: $conflictingPid" -ForegroundColor Red
    Write-Host "  To stop the conflicting process, run: Stop-Process -Id $conflictingPid -Force" -ForegroundColor Yellow
    Write-Host "  Or start ChronosMatch on a different port: .\start_local.ps1 -Port 8080" -ForegroundColor Yellow
    exit 1
}
Write-Host "  -> Port $Port is free and available." -ForegroundColor Green

# 8. Launch Django Trading Terminal
$serverUrl = "http://${HostAddress}:${Port}/"
Write-Host "[8/8] Starting ChronosMatch Web Terminal..." -ForegroundColor Yellow
Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "  CHRONOSMATCH TRADING TERMINAL IS READY" -ForegroundColor Green
Write-Host "  Access Website: $serverUrl" -ForegroundColor White -BackgroundColor DarkBlue
Write-Host "  Health API:     ${serverUrl}api/health/" -ForegroundColor Gray
Write-Host "  Market Feed:    ${serverUrl}api/market-data/" -ForegroundColor Gray
Write-Host "  Whale Sweeps:   ${serverUrl}api/sweeps/" -ForegroundColor Gray
Write-Host "-----------------------------------------------------------------" -ForegroundColor Green
Write-Host "  Press Ctrl+C to shut down the server safely." -ForegroundColor Gray
Write-Host "=================================================================" -ForegroundColor Green
Write-Host ""

# Start Django Development Server
python manage.py runserver "${HostAddress}:${Port}"
