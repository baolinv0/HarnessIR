$ErrorActionPreference = 'Stop'
$engineDirectory = $PSScriptRoot
$pythonExecutable = Join-Path $engineDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        & $bundledPython -m venv --system-site-packages (Join-Path $engineDirectory '.venv')
    } else {
        py -3.11 -m venv (Join-Path $engineDirectory '.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 3.11+ 环境失败。' }
}
& $pythonExecutable -m pip install -c (Join-Path $engineDirectory 'requirements.lock.txt') -e ($engineDirectory + '[test]')
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }
Write-Output '安装完成。运行 engine/start.ps1 启动本地向导。'
