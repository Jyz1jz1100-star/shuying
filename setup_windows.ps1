param([switch]$SkipWhisper)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.12 和 py 启动器。' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败。' }
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败，需要 Node.js 22.13+ 和 pnpm 11。' }
    pnpm build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    if (-not $SkipWhisper) {
        & '.\.venv\Scripts\python.exe' scripts/fetch_runtime.py
        if ($LASTEXITCODE -ne 0) { throw 'Whisper 运行时准备失败。' }
    }
    Write-Host '安装完成，运行 run_dev.ps1 启动。'
} finally { Pop-Location }
