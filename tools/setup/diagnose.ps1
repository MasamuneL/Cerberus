# Diagnóstico local sin logs ni errores originales. No descarga imágenes.
$ErrorActionPreference = 'Stop'
$dockerReady = $false

function Write-PartialReport {
    $dockerCheck = if ($dockerReady) {
        @{code='DOCKER_READY'; service='docker'; status='ok'; action='Docker accesible en el contexto elegido.'}
    } else {
        @{code='DOCKER_UNAVAILABLE'; service='docker'; status='error'; action='Inicia Docker y comprueba el contexto elegido; los servicios no se comprobaron.'}
    }
    @{format=1; checks=@(
        $dockerCheck,
        @{code='DIAGNOSTIC_UNAVAILABLE'; service='report'; status='pending'; action='Conserva la instalación; el diagnóstico completo necesita la imagen backend local.'}
    )} | ConvertTo-Json -Depth 5 -Compress
}

try {
    $installation = if ($env:CERBERUS_INSTALL_DIR) { $env:CERBERUS_INSTALL_DIR } else { Join-Path $PSScriptRoot '../..' }
    Set-Location -LiteralPath $installation
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'unavailable' }
    & docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'unavailable' }
    $dockerReady = $true
    & docker compose version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'unavailable' }
    $ports = @{http=$env:CERBERUS_HTTP_PORT; identity=$env:CERBERUS_KEYCLOAK_HTTP_PORT}
    if (Test-Path -LiteralPath '.env') {
        foreach ($rawLine in Get-Content -LiteralPath '.env') {
            $line = $rawLine -replace "='([^']*)'$", '=$1'
            if ($line -match '^CERBERUS_HTTP_PORT=(\d+)$' -and -not $ports.http) { $ports.http = $Matches[1] }
            if ($line -match '^CERBERUS_KEYCLOAK_HTTP_PORT=(\d+)$' -and -not $ports.identity) { $ports.identity = $Matches[1] }
        }
    }
    if (-not $ports.http) { $ports.http = '8080' }
    if (-not $ports.identity) { $ports.identity = '8081' }
    $sampleMode = if ($env:CERBERUS_SAMPLE_MODE -eq 'none') { 'none' } else { 'auto' }
    if (-not $env:CERBERUS_SAMPLE_MODE -and (Test-Path -LiteralPath '.env')) {
        if ((Get-Content -LiteralPath '.env') -match "^CERBERUS_SAMPLE_MODE='?none'?$") { $sampleMode = 'none' }
    }
    $services = @()
    foreach ($service in @('setup-secrets','setup-sample','redis','auth-db','keycloak','setup-identity','api','worker','frontend')) {
        $container = & docker compose ps -aq $service 2>$null
        if ($LASTEXITCODE -ne 0 -or $container -notmatch '^[a-f0-9]{12,64}$') { continue }
        $template = '{"service":"' + $service + '","state":{{json .State.Status}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}},"exit_code":{{json .State.ExitCode}},"oom_killed":{{json .State.OOMKilled}},"image":{{json .Config.Image}}}'
        $record = & docker inspect --format $template $container 2>$null
        if ($LASTEXITCODE -eq 0) { $services += ($record | ConvertFrom-Json) }
    }
    $portStates = @{}
    foreach ($key in @('http','identity')) {
        $port = 0
        if (-not [int]::TryParse([string]$ports[$key], [ref]$port) -or $port -lt 1 -or $port -gt 65535) { throw 'port' }
        $service = if ($key -eq 'http') { 'frontend' } else { 'keycloak' }
        $published = & docker compose port $service 8080 2>$null
        if ($LASTEXITCODE -eq 0 -and $published -eq "127.0.0.1:$port") { $portStates[$key] = 'expected'; continue }
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $task = $client.ConnectAsync('127.0.0.1', $port)
            $portStates[$key] = if ($task.Wait(500) -and $client.Connected) { 'busy' } else { 'unknown' }
        } catch { $portStates[$key] = 'free' } finally { $client.Dispose() }
    }
    $release = @{}
    $sample = $null
    if (Test-Path -LiteralPath 'release.json') { $release = Get-Content -Raw -LiteralPath 'release.json' | ConvertFrom-Json }
    if (Test-Path -LiteralPath 'tools/release/sample-manifest.json') { $sample = Get-Content -Raw -LiteralPath 'tools/release/sample-manifest.json' | ConvertFrom-Json }
    $snapshot = @{docker=@{status='ready'}; services=@($services); ports=$portStates; http_port=[int]$ports.http; identity_port=[int]$ports.identity; release=$release; sample_manifest=$sample; sample_mode=$sampleMode} | ConvertTo-Json -Depth 12 -Compress
    $result = $snapshot | & docker compose exec -T api python -m cerberus_api.diagnostics --snapshot-stdin 2>$null
    $resultCode = $LASTEXITCODE
    if (-not $result) {
        $result = $snapshot | & docker compose run --rm --no-deps --pull never --entrypoint python -T api -m cerberus_api.diagnostics --snapshot-stdin 2>$null
        $resultCode = $LASTEXITCODE
    }
    # El módulo solo produce JSON por lista permitida; no reenviar otro stdout del CLI.
    if (-not $result -or -not ([string]$result).StartsWith('{"format": 1, "checks": [')) { throw 'report' }
    Write-Output $result
    exit $resultCode
} catch {
    Write-PartialReport
    exit 1
}
