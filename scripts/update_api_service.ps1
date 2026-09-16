param([string]$InstallDir = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ShuyingService'))
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $InstallDir 'service-runtime.json'
if (!(Test-Path -LiteralPath $configPath)) { throw 'Run this script in the Windows session where the API was installed.' }
$runtime = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$repoRoot = Split-Path $PSScriptRoot -Parent
$dbPath = Join-Path $InstallDir 'data\jobs.sqlite3'
if (!(Test-Path -LiteralPath $dbPath)) { throw 'Service database not found; no changes made.' }
# Refuse to interrupt active work, including jobs belonging to other client keys.
$checkCode = "import sqlite3,sys; from pathlib import Path; c=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True); n=c.execute('SELECT count(*) FROM jobs WHERE status NOT IN (?,?,?)',('completed','failed','canceled')).fetchone()[0]; sys.exit(2 if n else 0)"
& $runtime.python -c $checkCode $dbPath
if ($LASTEXITCODE -ne 0) { throw 'Jobs may still be active. Wait until they finish before updating.' }
$stopPath = Join-Path $InstallDir 'STOP'
New-Item -ItemType File -Path $stopPath -Force | Out-Null
$deadline = (Get-Date).AddSeconds(35)
do {
    Start-Sleep -Seconds 1
    $listener = Get-NetTCPConnection -LocalPort $runtime.port -State Listen -ErrorAction SilentlyContinue
} while ($listener -and (Get-Date) -lt $deadline)
if ($listener) { throw 'Service did not stop. STOP marker retained; no code replaced.' }
Start-Sleep -Seconds 3
Copy-Item -Path (Join-Path $repoRoot 'backend\videosummarizer\*.py') -Destination (Join-Path $InstallDir 'app\backend\videosummarizer') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'service_supervisor.py') -Destination $InstallDir -Force
Remove-Item -LiteralPath $stopPath
$pythonw = Join-Path (Split-Path $runtime.python) 'pythonw.exe'
Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $InstallDir 'service_supervisor.py') + '" "' + $configPath + '"') -WindowStyle Hidden
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:" + $runtime.port + '/') -TimeoutSec 3
        if ($page.StatusCode -eq 200 -and $page.Content.Contains('/mobile.js')) {
            Write-Host 'Updated. Open your existing HTTPS address without /docs to use the phone page.'
            exit 0
        }
    } catch { }
}
throw 'Update copied, but the new page did not become ready. Check the local service logs.'
