$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$NodeExe = (Get-Command node -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $PythonExe)) { throw '缺少 .venv。请先创建项目虚拟环境并安装 requirements.txt。' }
if (-not (Test-Path -LiteralPath $NodeExe)) { throw '缺少构建所需的 Node.js 运行时。' }
Push-Location $ProjectRoot
try {
    & $PythonExe scripts/fetch_runtime.py --verify-only
    if ($LASTEXITCODE -ne 0) { throw '请先运行 scripts/fetch_runtime.py 下载并校验运行时。' }
    & $NodeExe 'node_modules\vite\bin\vite.js' build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    & $PythonExe scripts/collect_licenses.py
    if ($LASTEXITCODE -ne 0) { throw '依赖许可收集失败。' }
    & $PythonExe -m PyInstaller --noconfirm --clean 'packaging\VideoSummarizer.spec'
    if ($LASTEXITCODE -ne 0) { throw 'Windows 程序打包失败。' }
    Write-Host '构建完成：dist\VideoSummarizer\VideoSummarizer.exe'
}
finally { Pop-Location }
