param(
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'ShuyingService'),
    [int]$Port = 8766,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $repoRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup_windows.ps1 first.' }
$installRoot = [IO.Path]::GetFullPath($InstallDirectory)
if (Test-Path -LiteralPath (Join-Path $installRoot 'service-runtime.json')) {
    throw 'Service installation already exists. Stop and review the installation before updating it.'
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw 'API port is already in use.' }
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $installRoot /inheritance:r /grant:r "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict service directory permissions.' }
$appRoot = Join-Path $installRoot 'app'
New-Item -ItemType Directory -Force -Path (Join-Path $appRoot 'backend') | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'backend\videosummarizer') -Destination (Join-Path $appRoot 'backend') -Recurse
$runtime = Join-Path $repoRoot 'vendor\whispercpp\runtime'
if (Test-Path -LiteralPath $runtime) {
    New-Item -ItemType Directory -Force -Path (Join-Path $appRoot 'vendor\whispercpp') | Out-Null
    Copy-Item -LiteralPath $runtime -Destination (Join-Path $appRoot 'vendor\whispercpp') -Recurse
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'service_supervisor.py') -Destination $installRoot
$dataDir = Join-Path $installRoot 'data'
$env:PYTHONPATH = Join-Path $appRoot 'backend'
& $python -m videosummarizer.service_host create-key --data-dir $dataDir --output (Join-Path $installRoot 'client-key.json')
if ($LASTEXITCODE -ne 0) { throw 'API key initialization failed.' }
@{ python=$python; port=$Port; origins=@() } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installRoot 'service-runtime.json') -Encoding utf8
$startup = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup 'Shuying API.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.TargetPath -ne $pythonw) {
    throw 'A startup shortcut for another installation exists; it has not been replaced.'
}
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + (Join-Path $installRoot 'service_supervisor.py') + '" "' + (Join-Path $installRoot 'service-runtime.json') + '"'
$shortcut.WorkingDirectory = $installRoot
$shortcut.WindowStyle = 7
$shortcut.Save()
if (-not $NoStart) {
    Start-Process -FilePath $pythonw -ArgumentList $shortcut.Arguments -WorkingDirectory $installRoot -WindowStyle Hidden | Out-Null
}
Write-Output "API supervisor installed for this user's session and future logins: $installRoot"
Write-Output "Local endpoint: http://127.0.0.1:$Port ; API token stored in client-key.json (not printed)."
