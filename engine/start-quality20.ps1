param(
    [string]$Batch = 'pilot20_20261013_stable_v2',
    [int]$Port = 8502
)
$ErrorActionPreference = 'Stop'
$workspaceDirectory = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($Batch -notmatch '^[A-Za-z0-9_-]+$' -or $Port -lt 1024 -or $Port -gt 65535) {
    throw '批次名或端口无效。'
}
$batchDirectory = Join-Path $workspaceDirectory "runtime\quality20\$Batch"
if (-not (Test-Path -LiteralPath (Join-Path $batchDirectory 'trial_contract.json'))) {
    throw '缺少已冻结批次。先运行 run_quality20.py --stage issue。'
}
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw '缺少 Controller 环境 engine/.venv。'
}
$env:HIR_ROOT = Join-Path $batchDirectory 'workflow'
$env:PYTHONUTF8 = '1'
& $pythonExecutable -m streamlit run (Join-Path $PSScriptRoot 'src\hir_manual\ui.py') --server.address 127.0.0.1 --server.port $Port --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
