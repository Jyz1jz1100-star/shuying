$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ProjectRoot
try {
    $env:PYTHONPATH = Join-Path $ProjectRoot 'backend'
    & '.\.venv\Scripts\python.exe' -m videosummarizer.launcher
}
finally { Pop-Location }
