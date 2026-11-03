# ==============================================================================
# ChronosMatch Local Startup Script
# Checks environment, verifies Cython matching engine, and launches Web Terminal
# ==============================================================================

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "     CHRONOSMATCH ZERO-COPY HFT TRADING TERMINAL — STARTUP" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python Installation
Write-Host "[1/4] Checking Python environment..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  -> Python detected: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Python is not found in system PATH. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

# 2. Check Required Dependencies
Write-Host "[2/4] Verifying Python dependencies..." -ForegroundColor Yellow
$missingDeps = 0
foreach ($pkg in @("django", "cython", "numpy")) {
    $check = python -c "import $pkg" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [MISSING] $pkg is not installed. Run: python -m pip install -r requirements.txt" -ForegroundColor Red
        $missingDeps++
    } else {
        Write-Host "  -> Package '$pkg' is verified." -ForegroundColor Green
    }
}

if ($missingDeps -gt 0) {
    Write-Host "  [ERROR] Required dependencies are missing. Exiting startup." -ForegroundColor Red
    exit 1
}

# 3. Check and Verify Native Cython Matching Engine
Write-Host "[3/4] Verifying Cython Native Extension..." -ForegroundColor Yellow
$cythonCheck = python -c "from core.cython_engine import order_book; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0 -and $cythonCheck -match "OK") {
    Write-Host "  -> Native Cython Limit Order Book (.pyd) is compiled and verified." -ForegroundColor Green
} else {
    Write-Host "  [NOTICE] Cython extension not loaded or outdated. Attempting compilation..." -ForegroundColor Yellow
    python setup.py build_ext --inplace
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] Cython extension compilation failed. Ensure MSVC Build Tools are installed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  -> Cython extension compiled successfully." -ForegroundColor Green
}

# 4. Launch Django Web Trading Terminal
Write-Host "[4/4] Starting Web Trading Terminal..." -ForegroundColor Yellow
Write-Host ""
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "  ChronosMatch Terminal is now ready!" -ForegroundColor Green
Write-Host "  Open your browser to: http://127.0.0.1:8000/" -ForegroundColor White -BackgroundColor DarkBlue
Write-Host "  Press Ctrl+C in this console to stop the server." -ForegroundColor Gray
Write-Host "=================================================================" -ForegroundColor Green
Write-Host ""

python manage.py runserver 127.0.0.1:8000
