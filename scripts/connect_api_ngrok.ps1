param([string]$InstallDir = "$env:LOCALAPPDATA\ShuyingService")
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $InstallDir 'ngrok.yml'
if (!(Test-Path (Join-Path $InstallDir 'service-runtime.json'))) { throw 'Install the API service first.' }
if (Test-Path $configPath) { throw 'ngrok.yml already exists. Edit the existing configuration locally.' }
Write-Host 'Copy your personal authtoken from the ngrok dashboard, paste below, then press Enter.'
Write-Host 'The token is hidden and saved only in the restricted service directory.'
$secureToken = Read-Host 'ngrok authtoken' -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer).Trim()
    if ($plainToken -notmatch '^[A-Za-z0-9_-]{30,200}$') { throw 'Invalid token format. Copy only the token, not the command.' }
    $configuration = @{ version = '3'; agent = @{ authtoken = $plainToken; web_addr = '127.0.0.1:4040'; remote_management = $false } }
    $json = $configuration | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($configPath, $json, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Saved. Updating and restarting the API supervisor...'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    $plainToken = $null
    $json = $null
    $configuration = $null
    $secureToken.Dispose()
}
$stopPath = Join-Path $InstallDir 'STOP'
New-Item -ItemType File -Path $stopPath -Force | Out-Null
$runtime = Get-Content -LiteralPath (Join-Path $InstallDir 'service-runtime.json') -Raw | ConvertFrom-Json
$deadline = (Get-Date).AddSeconds(35)
do {
    Start-Sleep -Seconds 1
    $listener = Get-NetTCPConnection -LocalPort $runtime.port -State Listen -ErrorAction SilentlyContinue
} while ($listener -and (Get-Date) -lt $deadline)
if ($listener) { throw 'API has not stopped; STOP file retained. Contact the operator.' }
Start-Sleep -Seconds 3
$repoRoot = Split-Path $PSScriptRoot -Parent
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'service_supervisor.py') -Destination $InstallDir -Force
Copy-Item -Path (Join-Path $repoRoot 'backend\videosummarizer\*.py') -Destination (Join-Path $InstallDir 'app\backend\videosummarizer') -Force
Remove-Item -LiteralPath $stopPath
$pythonw = Join-Path (Split-Path $runtime.python) 'pythonw.exe'
Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $InstallDir 'service_supervisor.py') + '" "' + (Join-Path $InstallDir 'service-runtime.json') + '"') -WindowStyle Hidden
Write-Host 'Saved and started. You can close this window.'
