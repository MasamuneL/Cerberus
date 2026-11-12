# Inicio del paquete sin Python, Node ni Git en Windows.
[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$lock = Join-Path $root '.cerberus-setup.lock'
$locked = $false
$previousLocation = Get-Location

function Invoke-Docker {
    param([string[]]$DockerArgs)
    $result = & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw 'Docker no pudo completar la comprobación. Revisa daemon, contexto y diagnóstico.' }
    return $result
}
function Invoke-DockerBounded {
    param([string[]]$DockerArgs, [int]$Seconds)
    $work = [pscustomobject]@{ Root = $root; DockerArgs = $DockerArgs }
    $job = Start-Job -ArgumentList $work -ScriptBlock {
        param($Work)
        Set-Location -LiteralPath $Work.Root
        $nativeArgs = $Work.DockerArgs
        & docker @nativeArgs
        if ($LASTEXITCODE -ne 0) { throw 'Docker devolvió un error. No se borraron datos ni volúmenes.' }
    }
    try {
        $completed = Wait-Job $job -Timeout $Seconds
        if (-not $completed) { throw 'Se agotó la espera. Revisa el diagnóstico y reintenta sin borrar datos.' }
        Receive-Job $job -ErrorAction Stop | Out-Host
        if ($job.State -ne 'Completed') { throw 'No terminó la operación Docker.' }
    } finally {
        Stop-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
}
function Test-PortFree {
    param([int]$Port)
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start(); return $true } catch { return $false } finally { $listener.Stop() }
}
function Select-FreePort {
    param([int]$Start, [int]$Reserved)
    for ($candidate = $Start; $candidate -lt [Math]::Min($Start + 100, 65536); $candidate++) {
        if ($candidate -ne $Reserved -and (Test-PortFree $candidate)) { return $candidate }
    }
    throw 'No se encontró un puerto libre en 100 intentos.'
}
function Get-PublicValue {
    param([string]$Key, [string]$Default)
    $explicit = [Environment]::GetEnvironmentVariable($Key)
    if ($null -ne $explicit -and $explicit -ne '') { return $explicit }
    if ($fileValues.ContainsKey($Key)) { return $fileValues[$Key] }
    return $Default
}
function Get-LocalResponse {
    param([string]$Url)
    # Evita que un proxy del sistema intercepte las comprobaciones de loopback.
    $request = [Net.HttpWebRequest]::Create($Url)
    $request.Proxy = $null
    $request.Timeout = 15000
    $request.ReadWriteTimeout = 15000
    $request.AllowAutoRedirect = $false
    $response = $request.GetResponse()
    try {
        if ([int]$response.StatusCode -ne 200) { throw 'El servicio público no respondió HTTP 200.' }
        $reader = New-Object IO.StreamReader($response.GetResponseStream())
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $response.Dispose() }
}

try {
    Set-Location -LiteralPath $root
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Instala Docker Desktop con contenedores Linux y vuelve a iniciar.' }
    if (-not (Test-Path -LiteralPath 'release.json' -PathType Leaf)) { throw 'Se requiere el paquete distribuido con release.json. Para desarrollar usa Compose con --build.' }
    try { New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null }
    catch { throw 'Otra operación usa esta instalación (.cerberus-setup.lock). Comprueba que terminó antes de retirar el lock vacío.' }
    $locked = $true
    $envFile = Join-Path $root '.env'
    $lines = @()
    $fileValues = @{}
    if (Test-Path -LiteralPath $envFile) {
        $lines = [IO.File]::ReadAllLines($envFile)
        foreach ($line in $lines) {
            if ($line -match '^(CERBERUS_HTTP_PORT|CERBERUS_KEYCLOAK_HTTP_PORT|COMPOSE_PROJECT_NAME|CERBERUS_APP_ORIGIN)=(.*)$') {
                $key = $Matches[1]; $value = $Matches[2]
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                $fileValues[$key] = $value
            }
        }
    }
    $http = Get-PublicValue 'CERBERUS_HTTP_PORT' '8080'
    $identity = Get-PublicValue 'CERBERUS_KEYCLOAK_HTTP_PORT' '8081'
    $project = Get-PublicValue 'COMPOSE_PROJECT_NAME' 'cerberus'
    $origin = Get-PublicValue 'CERBERUS_APP_ORIGIN' ''
    $autoHttp = -not ($env:CERBERUS_HTTP_PORT -or $fileValues.ContainsKey('CERBERUS_HTTP_PORT'))
    $autoIdentity = -not ($env:CERBERUS_KEYCLOAK_HTTP_PORT -or $fileValues.ContainsKey('CERBERUS_KEYCLOAK_HTTP_PORT'))
    $customOrigin = $origin
    if ($project -cnotmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'COMPOSE_PROJECT_NAME inválido.' }
    foreach ($port in @($http, $identity)) {
        if ($port -notmatch '^[0-9]{1,5}$' -or [int]$port -lt 1 -or [int]$port -gt 65535) { throw 'Los puertos deben ser enteros entre 1 y 65535.' }
    }
    $http = [int]$http; $identity = [int]$identity
    $version = (Invoke-Docker @('compose', 'version', '--short')).Trim().TrimStart('v')
    if ($version -notmatch '^(\d+)\.(\d+)\.' -or [int]$Matches[1] -lt 2 -or ([int]$Matches[1] -eq 2 -and [int]$Matches[2] -lt 30)) { throw 'Se requiere Docker Compose 2.30.0 o posterior.' }
    Write-Host 'Etapa 1/4: comprobar Docker, contexto y plataforma.'
    $info = (Invoke-Docker @('info', '--format', '{{.OSType}}|{{.Architecture}}|{{.NCPU}}|{{.MemTotal}}')).Split('|')
    if ($info[0] -ne 'linux') { throw 'Selecciona contenedores Linux en Docker Desktop.' }
    if ($info[1] -notin @('amd64', 'x86_64', 'arm64', 'aarch64')) { throw 'La arquitectura Docker no permite este backend Linux amd64.' }
    if ($info[1] -in @('arm64', 'aarch64')) { Write-Host 'Se comprobará la emulación Linux amd64.' }
    $endpoint = $env:DOCKER_HOST
    if ($env:DOCKER_CONTEXT) { $endpoint = Invoke-Docker @('context', 'inspect', $env:DOCKER_CONTEXT, '--format', '{{.Endpoints.docker.Host}}') }
    elseif (-not $endpoint) { $endpoint = Invoke-Docker @('context', 'inspect', '--format', '{{.Endpoints.docker.Host}}') }
    if ($endpoint -notmatch '^(unix|npipe)://') { throw 'Selecciona un contexto Docker local: los puertos se publican en loopback del host Docker.' }
    Write-Host "Docker: $($info[2]) CPU; $($info[3]) bytes de RAM total. El disco se medirá dentro de la imagen."
    $env:COMPOSE_PROJECT_NAME = $project
    $composeArgs = @('compose', '--project-directory', $root, '-f', (Join-Path $root 'compose.yaml'), '-p', $project)
    $active = @(Invoke-Docker @('ps', '--filter', "label=com.docker.compose.project=$project", '--format', '{{.ID}}'))
    $active = @($active | Where-Object { $_ })
    foreach ($container in $active) {
        $containerLabels = (Invoke-Docker @('inspect', '--format', '{{json .Config.Labels}}', $container)) | ConvertFrom-Json
        $directory = $containerLabels.'com.docker.compose.project.working_dir'
        if ($directory -ne $root) { throw 'Este proyecto ya está activo en otra carpeta. Usa su instalación original; no se modificó.' }
    }
    if ($active.Count -eq 0) {
        if (-not (Test-PortFree $http)) {
            if ($env:CERBERUS_HTTP_PORT -or $fileValues.ContainsKey('CERBERUS_HTTP_PORT')) { throw 'CERBERUS_HTTP_PORT está ocupado. Elige otro puerto; el servicio ajeno se conserva.' }
            $http = Select-FreePort 8080 $identity
        }
        if ($identity -eq $http -or -not (Test-PortFree $identity)) {
            if ($env:CERBERUS_KEYCLOAK_HTTP_PORT -or $fileValues.ContainsKey('CERBERUS_KEYCLOAK_HTTP_PORT')) { throw 'CERBERUS_KEYCLOAK_HTTP_PORT está ocupado o coincide con HTTP.' }
            $identity = Select-FreePort 8081 $http
        }
    }
    if (-not $origin) { $origin = "http://localhost:$http" }
    if ($origin -notmatch "^http://(localhost|127\.0\.0\.1):$http`$") { throw 'El origen debe ser HTTP de loopback con el puerto seleccionado.' }
    $env:CERBERUS_HTTP_PORT = [string]$http
    $env:CERBERUS_KEYCLOAK_HTTP_PORT = [string]$identity
    $env:CERBERUS_APP_ORIGIN = $origin
    $issuer = "http://localhost:$identity/realms/cerberus"
    # .env puede diferir del último arranque: comprobar el estado real antes de recrear.
    foreach ($container in $active) {
        $containerLabels = (Invoke-Docker @('inspect', '--format', '{{json .Config.Labels}}', $container)) | ConvertFrom-Json
        $service = $containerLabels.'com.docker.compose.service'
        if ($service -in @('frontend', 'keycloak')) {
            $expected = $http
            if ($service -eq 'keycloak') { $expected = $identity }
            $binding = Invoke-Docker @('port', $container, '8080/tcp')
            if ($binding -cne "127.0.0.1:$expected") { throw 'Los puertos difieren de la instancia activa. Detén primero su instalación.' }
        } elseif ($service -eq 'api') {
            try {
                Invoke-Docker @('exec', $container, 'python', '-c', 'import os,sys; assert os.environ.get(''CERBERUS_APP_ORIGIN'')==sys.argv[1] and os.environ.get(''CERBERUS_OIDC_ISSUER_URL'')==sys.argv[2]', $origin, $issuer) | Out-Host
            } catch { throw 'Origen o issuer difiere de la instancia activa. Detén primero su instalación.' }
        }
    }
    $timeout = 600; $pullTimeout = 1800
    if ($env:CERBERUS_START_TIMEOUT_SECONDS) { $timeout = [int]$env:CERBERUS_START_TIMEOUT_SECONDS }
    if ($env:CERBERUS_PULL_TIMEOUT_SECONDS) { $pullTimeout = [int]$env:CERBERUS_PULL_TIMEOUT_SECONDS }
    if ($timeout -lt 1 -or $timeout -gt 99999 -or $pullTimeout -lt 1 -or $pullTimeout -gt 99999) { throw 'Los tiempos de espera deben ser segundos positivos menores de 100000.' }
    function Save-PublicConfiguration {
        $publicLines = @($lines | Where-Object { $_ -notmatch '^(CERBERUS_HTTP_PORT|CERBERUS_KEYCLOAK_HTTP_PORT|COMPOSE_PROJECT_NAME|CERBERUS_APP_ORIGIN)=' })
        $publicLines += @("COMPOSE_PROJECT_NAME=$project", "CERBERUS_HTTP_PORT=$http", "CERBERUS_KEYCLOAK_HTTP_PORT=$identity", "CERBERUS_APP_ORIGIN=$origin")
        $temporary = Join-Path $root ('.env.setup.' + [guid]::NewGuid().ToString('N'))
        try {
            [IO.File]::WriteAllLines($temporary, $publicLines, (New-Object Text.UTF8Encoding($false)))
            if (Test-Path -LiteralPath $envFile) { [IO.File]::Replace($temporary, $envFile, [NullString]::Value) }
            else { [IO.File]::Move($temporary, $envFile) }
        } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force } }
    }
    Save-PublicConfiguration
    Write-Host 'Etapa 2/4: descargar imágenes fijadas a esta versión.'
    $images = @(Invoke-Docker ($composeArgs + @('config', '--images')))
    if ($images.Count -eq 0) { throw 'El paquete no declara imágenes.' }
    $allCached = $true
    foreach ($image in $images) {
        if ($image -cnotmatch '@sha256:[a-f0-9]{64}$') { throw 'Todas las imágenes deben estar fijadas por digest.' }
        try { Invoke-Docker @('image', 'inspect', $image) | Out-Null } catch { $allCached = $false }
    }
    if ($allCached) { Write-Host 'Todas las imágenes por digest están en caché; no se requiere descarga.' }
    else { Invoke-DockerBounded ($composeArgs + @('pull')) $pullTimeout }
    $backend = Invoke-Docker ($composeArgs + @('config', '--images', 'api'))
    if ($backend -notmatch '@sha256:[a-f0-9]{64}$') { throw 'El backend debe estar fijado por digest.' }
    Invoke-Docker @('run', '--rm', '--network', 'none', '--platform', 'linux/amd64', '--entrypoint', 'python', $backend, '-c', 'import shutil; d=shutil.disk_usage(''/''); print(''Disco Docker: %d bytes libres, %d totales'' % (d.free,d.total))') | Out-Host
    $manifest = Get-Content -LiteralPath 'release.json' -Raw | ConvertFrom-Json
    foreach ($component in @('api', 'frontend')) {
        $image = Invoke-Docker ($composeArgs + @('config', '--images', $component))
        $labels = (Invoke-Docker @('image', 'inspect', '--format', '{{json .Config.Labels}}', $image)) | ConvertFrom-Json
        $expected = $manifest.images.frontend
        if ($component -eq 'api') { $expected = $manifest.images.backend }
        if ($manifest.format -ne 1 -or $image -ne $expected -or $labels.'org.opencontainers.image.revision' -ne $manifest.revision -or $labels.'org.opencontainers.image.version' -ne $manifest.version) { throw 'Las imágenes mezclan versiones o no coinciden con release.json.' }
    }
    if ($active.Count -eq 0) {
        for ($attempt = 0; $attempt -lt 2; $attempt++) {
            $changed = $false
            if (-not (Test-PortFree $http)) {
                if (-not $autoHttp -or $customOrigin) { throw 'El puerto HTTP se ocupó durante la descarga. Elige otro puerto explícito.' }
                $http = Select-FreePort ($http + 1) $identity; $changed = $true
            }
            if (-not (Test-PortFree $identity)) {
                if (-not $autoIdentity) { throw 'El puerto de identidad se ocupó durante la descarga. Elige otro puerto explícito.' }
                $identity = Select-FreePort ($identity + 1) $http; $changed = $true
            }
            if (-not $changed) { break }
            $origin = $customOrigin
            if (-not $origin) { $origin = "http://localhost:$http" }
            $issuer = "http://localhost:$identity/realms/cerberus"
            $env:CERBERUS_HTTP_PORT = [string]$http
            $env:CERBERUS_KEYCLOAK_HTTP_PORT = [string]$identity
            $env:CERBERUS_APP_ORIGIN = $origin
            Save-PublicConfiguration
        }
    }
    Write-Host "Etapa 3/4: preparar datos, identidad y aplicación; espera máxima $timeout s."
    Invoke-DockerBounded ($composeArgs + @('up', '-d', '--pull', 'never', '--wait', '--wait-timeout', [string]$timeout)) ($timeout + 30)
    Write-Host 'Etapa 4/4: comprobar nginx, API y proveedor OIDC.'
    if ((Get-LocalResponse "$origin/healthz").Trim() -ne 'ok') { throw 'La respuesta HTTP corresponde a otro servicio.' }
    $health = Get-LocalResponse "$origin/api/health" | ConvertFrom-Json
    $auth = Get-LocalResponse "$origin/api/auth/config" | ConvertFrom-Json
    $discovery = Get-LocalResponse "$issuer/.well-known/openid-configuration" | ConvertFrom-Json
    if ($health.status -ne 'ok' -or $auth.mode -ne 'oidc' -or $discovery.issuer -cne $issuer) { throw 'La API o el issuer público no corresponde a esta instalación.' }
    Invoke-Docker ($composeArgs + @('exec', '-T', 'api', 'python', '-c', 'import os,sys; assert os.environ[''CERBERUS_APP_ORIGIN'']==sys.argv[1] and os.environ[''CERBERUS_OIDC_ISSUER_URL'']==sys.argv[2]', $origin, $issuer)) | Out-Host
    $request = [Net.HttpWebRequest]::Create("$origin/api/auth/login")
    $request.Proxy = $null; $request.Timeout = 15000; $request.AllowAutoRedirect = $false
    $response = $request.GetResponse()
    try {
        if ([int]$response.StatusCode -ne 302) { throw 'El login público no devuelve una redirección OIDC.' }
        $location = [uri]$response.Headers['Location']
        $expectedCallback = [uri]::EscapeDataString("$origin/api/auth/callback")
        if ($location.GetLeftPart([UriPartial]::Path) -cne "$issuer/protocol/openid-connect/auth" -or
            $location.Query -cnotmatch ('(^|[?&])redirect_uri=' + [regex]::Escape($expectedCallback) + '(&|$)') -or
            $location.Query -cnotmatch '(^|[?&])client_id=cerberus-web(&|$)') { throw 'El login público usa otro proveedor u otro callback.' }
    } finally { $response.Dispose() }
    Write-Host "Cerberus listo: $origin`nCuenta local: demo / demo"
    if (-not $NoBrowser -and $env:CERBERUS_NO_BROWSER -ne '1') {
        try { Start-Process $origin } catch { Write-Host 'Abre manualmente la URL anterior en tu navegador.' }
    }
    exit 0
} catch {
    [Console]::Error.WriteLine(("Error: " + $_.Exception.Message))
    Write-Host 'Repite el inicio después de corregir el problema. Los datos y volúmenes se conservan.'
    $diagnostic = Join-Path $root 'tools/setup/diagnose.ps1'
    if ($locked -and (Test-Path -LiteralPath $diagnostic)) { & $diagnostic }
    exit 1
} finally {
    if ($locked) { Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue }
    Set-Location -LiteralPath $previousLocation.Path
}
