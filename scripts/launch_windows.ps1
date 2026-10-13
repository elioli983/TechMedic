# Development/evaluation launcher. Python owns the server-lifetime lock and keys.
param([switch]$Live)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Please run INSTALL_WINDOWS.bat first.' -ForegroundColor Red
    exit 2
}
Push-Location -LiteralPath $root
try {
    if ($Live) {
        & $python -m techmedic.windows_startup --live
    } else {
        & $python -m techmedic.windows_startup
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
