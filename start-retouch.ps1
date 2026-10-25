param([int]$Port = 8766, [string]$Python = "", [string]$Runs = "")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not $Python) {
    $taskVenvPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
    if (Test-Path -LiteralPath $taskVenvPython) { $Python = $taskVenvPython }
    else { $Python = "python" }
}
if (-not $Runs) { $Runs = Join-Path $PSScriptRoot "runs/retouch" }
$env:PYTHONPATH = Join-Path $PSScriptRoot "engine/src"
$env:PYTHONUTF8 = "1"
& $Python -m hre.retouch --serve --port $Port --runs $Runs
exit $LASTEXITCODE
