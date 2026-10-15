$ErrorActionPreference = 'Stop'
$engineDirectory = $PSScriptRoot
$pythonExecutable = Join-Path $engineDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw '缺少 engine/.venv。请先运行 engine/setup.ps1。'
}
$env:HIR_ROOT = Split-Path -Parent $engineDirectory
$env:PYTHONUTF8 = '1'
& $pythonExecutable -m streamlit run (Join-Path $engineDirectory 'src\hir_manual\ui.py') --server.address 127.0.0.1 --server.port 8501 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
