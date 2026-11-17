# Native Windows entry point. Run setup_gateway.ps1 once before using it.
$ErrorActionPreference = "Stop"
$AppRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$GatewayPython = Join-Path $AppRoot ".venv-edge/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $GatewayPython -PathType Leaf)) {
    throw "Gateway environment not found. Run scripts/edge/setup_gateway.ps1 first."
}
Write-Host "Gateway Python: $GatewayPython"
Write-Host "Gateway log: $(Join-Path $AppRoot 'logs/edge_gateway.log')"
Write-Host "Starting gateway. Keep the SSH tunnel open; press Ctrl+C to stop."
& $GatewayPython (Join-Path $PSScriptRoot "launch_gateway.py") @args
exit $LASTEXITCODE
