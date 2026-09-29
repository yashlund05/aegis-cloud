# PowerShell script to execute complete test suite across Python and Go
Write-Host "=== Running Aegis Full Test Suite ===" -ForegroundColor Cyan

Write-Host "`n--- Python Unit Tests (Phases 1-5) ---" -ForegroundColor Yellow
python -m pytest tests/unit/ -v --tb=short
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python unit tests failed!"
    exit 1
}

Write-Host "`n--- Go Scheduler Plugin Tests (Phase 6) ---" -ForegroundColor Yellow
$goBin = "C:\Program Files\Go\bin\go.exe"
if (Get-Command go -ErrorAction SilentlyContinue) {
    $goBin = "go"
}

Push-Location scheduler/aegis-scheduler
& $goBin test ./pkg/plugins/aegis -v
$goRes = $LASTEXITCODE
Pop-Location

if ($goRes -ne 0) {
    Write-Error "Go scheduler tests failed!"
    exit 1
}

Write-Host "`n=== All Test Suites (Python + Go) Passed Cleanly! ===" -ForegroundColor Green
