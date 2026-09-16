param([string]$InstallDir = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ShuyingService'))
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $InstallDir 'ngrok.yml'
if (!(Test-Path -LiteralPath (Join-Path $InstallDir 'service-runtime.json'))) {
    Write-Host "No installation visible in this Windows session. Installing into $InstallDir ..."
    & (Join-Path $PSScriptRoot 'install_api_service.ps1') -InstallDirectory $InstallDir -NoStart
    if (!(Test-Path -LiteralPath (Join-Path $InstallDir 'service-runtime.json'))) {
        throw 'Installation did not create a service configuration. Token entry has not started.'
    }
}
$agentPath = Join-Path $InstallDir 'tools\ngrok.exe'
if (!(Test-Path -LiteralPath $agentPath)) {
    Write-Host 'Downloading the official ngrok Windows agent...'
    $toolsDir = Join-Path $InstallDir 'tools'
    New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    $archive = Join-Path $toolsDir 'ngrok.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri 'https://bin.ngrok.com/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $toolsDir -Force
}
$signature = Get-AuthenticodeSignature -LiteralPath $agentPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O="?ngrok, Inc\.') {
    throw 'ngrok signature validation failed. No token has been requested and the agent has not been started.'
}
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
