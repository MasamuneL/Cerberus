# Compatible con Windows PowerShell 5.1 y PowerShell 7.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'tools/setup/start.ps1') @args
exit $LASTEXITCODE
