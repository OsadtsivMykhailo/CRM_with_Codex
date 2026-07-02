$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsDirectory = Join-Path $projectRoot '.tools'
$archivePath = Join-Path $toolsDirectory 'mailpit.zip'
$extractPath = Join-Path $toolsDirectory 'mailpit-download'

New-Item -ItemType Directory -Force $toolsDirectory | Out-Null
$release = Invoke-RestMethod 'https://api.github.com/repos/axllent/mailpit/releases/latest'
$asset = $release.assets | Where-Object { $_.name -eq 'mailpit-windows-amd64.zip' } | Select-Object -First 1
if (-not $asset) { throw 'Mailpit Windows amd64 archive was not found in the latest release.' }

Invoke-WebRequest $asset.browser_download_url -OutFile $archivePath
if (Test-Path $extractPath) { Remove-Item -LiteralPath $extractPath -Recurse -Force }
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath -Force
$executable = Get-ChildItem -LiteralPath $extractPath -Filter 'mailpit.exe' -Recurse | Select-Object -First 1
if (-not $executable) { throw 'mailpit.exe was not found in the downloaded archive.' }
Copy-Item -LiteralPath $executable.FullName -Destination (Join-Path $toolsDirectory 'mailpit.exe') -Force
Remove-Item -LiteralPath $archivePath -Force
Remove-Item -LiteralPath $extractPath -Recurse -Force
Write-Host "Mailpit installed: $(Join-Path $toolsDirectory 'mailpit.exe')"
